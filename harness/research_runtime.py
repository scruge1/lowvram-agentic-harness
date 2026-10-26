"""Project-scoped evidence storage for the home-owned research tools.

Only the bounded projection leaves this helper. Full untrusted source records
stay in immutable content-addressed artifacts. Cached reads do not fetch again.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


MODEL_BYTES = 12 * 1024
ARTIFACT_BYTES = 32 * 1024 * 1024
PROJECT_BYTES = 256 * 1024 * 1024
PROJECT_FILES = 2048
ARTIFACT_ID = re.compile(r"sha256:([a-f0-9]{64})\Z")
AUTHORITY = "untrusted_source_evidence"


class ResearchError(ValueError):
    pass


class ResearchDeadline(ResearchError):
    research_status = "deadline"


def check_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise ResearchDeadline("Research productive deadline reached; delivery held; inspect retained bound artifacts")


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ResearchError(message)


def read_json(path, maximum=ARTIFACT_BYTES):
    require(not path.is_symlink() and path.is_file(), "Missing or redirected evidence file")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, "Evidence file exceeds its byte limit")
    return json.loads(raw), raw


class ArtifactStore:
    def __init__(self, state_root, project, quota_bytes=PROJECT_BYTES, maximum=ARTIFACT_BYTES):
        self.project = project
        state_root = Path(state_root).absolute()
        require(state_root.resolve() == state_root, "Research state ancestors must not be redirected")
        self.root = state_root / "research"
        self.directory = self.root / "artifacts"
        self.quota_bytes, self.maximum = quota_bytes, maximum
        for path in (Path(state_root), self.root, self.directory):
            require(not path.is_symlink(), "Research storage must not follow a symlink")
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        require(self.directory.resolve().is_relative_to(Path(state_root).resolve()), "Research storage escaped project state")

    def quota(self, incoming=0):
        entries = list(self.directory.iterdir())
        require(len(entries) < PROJECT_FILES, "Project research artifact-count quota reached")
        require(all(p.is_file() and not p.is_symlink() for p in entries), "Unexpected research storage entry")
        used = sum(p.stat().st_size for p in entries)
        require(incoming <= self.maximum and used + incoming <= self.quota_bytes, "Project research byte quota reached")
        require(shutil.disk_usage(self.directory).free >= incoming + 8 * 1024 * 1024, "Insufficient research storage reserve")

    @contextlib.contextmanager
    def locked(self):
        # Same crash-releasing native file-lock pattern as harness.executor,
        # scoped only to the short artifact/quota transaction, never network I/O.
        lock = self.root / "artifacts.lock"
        require(not lock.is_symlink(), "Research lock must not be a symlink")
        with lock.open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ResearchError("Research artifact store is busy") from error
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def put(self, record, *, deadline=None):
        check_deadline(deadline)
        require(record.get("project") == self.project, "Artifact project binding differs")
        raw = wire(record)
        check_deadline(deadline)
        sha = digest(raw)
        target = self.directory / (sha + ".json")
        with self.locked():
            check_deadline(deadline)
            if target.exists():
                require(read_json(target)[1] == raw, "Immutable artifact byte drift")
                return "sha256:" + sha
            self.quota(len(raw))
            check_deadline(deadline)
            fd, temporary = tempfile.mkstemp(prefix=".artifact-", dir=self.directory)
            candidate = Path(temporary)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                check_deadline(deadline)
                os.link(candidate, target)  # Atomic publication without overwrite.
            finally:
                candidate.unlink(missing_ok=True)
        return "sha256:" + sha

    def get(self, artifact_id):
        match = ARTIFACT_ID.fullmatch(artifact_id) if isinstance(artifact_id, str) else None
        require(match is not None, "Use an exact research artifact ID")
        record, raw = read_json(self.directory / (match[1] + ".json"), self.maximum)
        require(digest(raw) == match[1], "Immutable artifact content hash differs")
        require(record.get("schema") == "project-research-artifact/v1" and record.get("project") == self.project,
                "Artifact does not belong to the selected project")
        return record


def without_bodies(value):
    if isinstance(value, dict):
        return {key: without_bodies(item) for key, item in value.items()
                if key not in {"raw_content_base64", "content_base64", "cleaned_text", "cleaned_text_full", "text", "user_prompt"}}
    if isinstance(value, list):
        return [without_bodies(item) for item in value]
    return value


def text_view(record, view):
    payload, action = record["payload"], record["action"]
    if view == "metadata":
        return wire(without_bodies(record)).decode(), "provenance_metadata"
    if view in ("tables", "links", "headings"):
        require(action == "render", "This artifact has no captured browser metadata")
        return wire(payload.get("document", {}).get(view, [])).decode(), "captured_browser_metadata"
    if view == "downloads":
        return wire(without_bodies(payload.get("downloads", []))).decode(), "download_metadata"
    require(view == "text", "Unsupported cached evidence view")
    if action == "fetch":
        if isinstance(payload.get("text"), str) and isinstance(payload.get("content_scope"), str):
            return payload["text"], payload["content_scope"]
        return payload.get("response", {}).get("cleaned_text_full", "") if payload.get("response") else "", "full_extraction"
    if action == "render":
        return payload.get("document", {}).get("text", ""), "captured_browser_window"
    if action == "mine":
        return wire(payload).decode(), "source_bound_claims_not_consensus"
    if action == "consensus":
        return wire(payload).decode(), "deterministic_scoring_not_truth_or_editorial_independence"
    if action in {"plan", "retrieval_plan"}:
        return wire(payload).decode(), "main_agent_plan_data_not_permission"
    return wire(payload.get("hits", [])).decode(), "search_metadata"


def projection(record, artifact_id, *, view="text", offset=0, limit=8192, cached=False):
    require(type(offset) is int and offset >= 0 and type(limit) is int and 80 <= limit <= 8192, "Invalid cached evidence window")
    text, scope = text_view(record, view)
    require(offset <= len(text), "Evidence offset exceeds the captured field")
    payload = record["payload"]
    base = {"schema": "research-result/v1", "action": "read" if cached else record["action"],
            "ok": True if cached else payload.get("ok") is True, "status": "cached" if cached else payload.get("status", "unknown"),
            "source_status": payload.get("status", "unknown"), "artifact_id": artifact_id, "artifact_sha256": artifact_id[7:],
            "project_id": record["project"]["project_id"], "authority": AUTHORITY, "cached": cached,
            "view": view, "content_scope": scope, "text_sha256": digest(text.encode()), "text_encoding": "utf-8",
            "reason": str(payload.get("reason") or "")[:500], "offset": offset}
    if record["action"] == "render":
        base.update(page_url=str(payload.get("page_url", ""))[:1500], capture_truncated=payload.get("document", {}).get("truncated", True),
                    capture_offset=payload.get("document", {}).get("offset", 0))
    if record["action"] == "fetch" and "selected_kind" in payload:
        base.update(requested_url=str(payload.get("requested_url") or "")[:1500],
                    selected_url=str(payload.get("selected_url") or "")[:1500],
                    selected_kind=payload.get("selected_kind"),
                    requested_source_complete=payload.get("requested_source_complete") is True,
                    attempt_count=len(payload.get("attempts", [])))
        if payload.get("document"):
            base.update(capture_truncated=payload["document"].get("truncated", True),
                        capture_offset=payload["document"].get("offset", 0))
    if record["action"] == "mine":
        base.update(run_identity_sha256=payload["run_identity_sha256"], complete=payload["complete"],
                    attempted_shards=payload["attempted_shards"], analysed_shards=payload["analysed_shards"],
                    expected_shards=payload["expected_shards"], analysed_rate=payload["analysed_rate"],
                    claim_count=len(payload["claims"]), failure_count=len(payload["failure_ledger"]))
    if record["action"] == "consensus":
        base.update(run_identity_sha256=payload["run_identity_sha256"], complete=payload["complete"],
                    coverage_complete=payload["coverage_complete"], consensus_established=False, cluster_count=len(payload["clusters"]),
                    input_claims=payload["input_claims"], input_count=len(payload["inputs"]))
        if "requested_coverage" in payload:
            base.update(requested_count=len(payload["requested_coverage"]["requests"]),
                        research_plan_id=payload["requested_coverage"]["research_plan_id"],
                        retrieval_plan_id=payload["requested_coverage"]["retrieval_plan_id"])
    if record["action"] in {"plan", "retrieval_plan"}:
        base.update(plan_data_only=True)
    if "research_binding" in record:
        base["research_binding"] = record["research_binding"]
    remaining = limit
    while True:
        window = text[offset:offset + remaining].encode()[:remaining].decode("utf-8", errors="ignore")
        result = {**base, "text": window, "window_sha256": digest(window.encode()), "returned_chars": len(window),
                  "next_offset": offset + len(window) if offset + len(window) < len(text) else None}
        if len(wire(result)) <= MODEL_BYTES:
            return result
        remaining //= 2
        require(remaining >= 1, "Evidence projection metadata exceeds its byte limit")


class ResearchRuntime:
    def __init__(self, home):
        require(home.is_absolute(), "Use the bound absolute agent home")
        self.home = home.resolve(strict=True)
        config, _ = read_json(self.home / "home.json", 1024 * 1024)
        require(config.get("schema") == "agent-home/v1" and Path(config.get("home", "")).resolve() == self.home, "Agent home identity differs")
        self.runtime = self.home / "runtime"
        manifest, raw = read_json(self.runtime / "runtime-manifest.json", 2 * 1024 * 1024)
        require(digest(raw) == config.get("runtime_manifest_sha256"), "Agent runtime manifest drift")
        seen, total = set(), 0
        for item in manifest["files"]:
            relative = item["path"]
            file = self.runtime / relative
            require(relative not in seen and not Path(relative).is_absolute() and ".." not in Path(relative).parts,
                    "Invalid runtime source binding")
            seen.add(relative)
            require(not file.is_symlink() and file.resolve(strict=True).is_relative_to(self.runtime), "Runtime source escaped its home")
            data = file.read_bytes()
            total += len(data)
            require(total <= 64 * 1024 * 1024 and len(seen) <= 2000 and digest(data) == item["sha256"], "Agent runtime source drift")
        require(Path(__file__).resolve() == self.runtime / "harness/research_runtime.py", "Use the research helper installed in this home")
        sys.path.insert(0, str(self.runtime))
        native_home = importlib.import_module("harness.home")
        require(Path(native_home.__file__).resolve() == self.runtime / "harness/home.py", "Mixed agent-home source origin")
        self.home, self.config = native_home.load(self.home)
        self.env = native_home.environment(self.home)
        expected_python = native_home.executable(self.home / "envs/research")
        require(os.path.normcase(str(Path(sys.executable).absolute())) == os.path.normcase(str(expected_python.absolute())),
                "Use this home's research Python")
        for name in ("research", "research/tmp"):
            directory = self.home / "cache" / name
            require(not directory.is_symlink() and directory.resolve() == directory, "Research cache must not be redirected")
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.env.update(XDG_CACHE_HOME=str(self.home / "cache/research"), TMPDIR=str(self.home / "cache/research/tmp"),
                        TMP=str(self.home / "cache/research/tmp"), TEMP=str(self.home / "cache/research/tmp"),
                        PLAYWRIGHT_BROWSERS_PATH=str(self.home / "cache/playwright"),
                        PI_WEB_RESEARCH_GUARD=str(self.runtime / "pi-task-worker.py"),
                        PI_WEB_RESEARCH_GUARD_SHA256=digest((self.runtime / "pi-task-worker.py").read_bytes()))
        spec = importlib.util.spec_from_file_location("bound_research_project_identity", self.runtime / "adapters/pi/project-workflow/project_identity.py")
        self.identity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.identity)

    def selection(self, request):
        selected = request.get("selection")
        require(isinstance(selected, dict) and selected.get("boardAdmissionFailed") is not True, "Admit a valid project before research")
        project = selected.get("project")
        require(isinstance(project, dict), "Admit the current project before research")
        root = Path(project.get("root", ""))
        require(root.is_absolute() and root.is_dir() and str(root.resolve()) == str(root), "Selected project root changed")
        previous = os.environ.get("PI_PROJECT_STATE_BASE")
        os.environ["PI_PROJECT_STATE_BASE"] = self.env["PI_PROJECT_STATE_BASE"]
        try:
            identity = self.identity.load_identity(root)
        finally:
            if previous is None:
                os.environ.pop("PI_PROJECT_STATE_BASE", None)
            else:
                os.environ["PI_PROJECT_STATE_BASE"] = previous
        require(identity["project_id"] == project.get("projectId") and identity["board_id"] == project.get("boardId"), "Native project selection differs from current identity")
        task = selected.get("task")
        if task is not None:
            require(isinstance(task, dict) and isinstance(task.get("cardId"), str) and task.get("taskId") == task["cardId"], "Invalid selected card")
            require((Path(identity["state_root"]) / "kanban.db").is_file(), "Selected project's existing board is unavailable")
            result = subprocess.run([self.env["PI_PROJECT_KANBAN_PYTHON"], "-B", self.env["PI_PROJECT_KANBAN_ADAPTER"]],
                                    input=json.dumps({"action": "show", "project_root": str(root), "task_id": task["cardId"]}),
                                    cwd=root, env=self.env, text=True, capture_output=True, timeout=20, check=False)
            require(result.returncode == 0 and len(result.stdout) <= 1024 * 1024, "Cannot validate the selected native card")
            shown = json.loads(result.stdout)
            require(shown.get("ok") is True and shown.get("result", {}).get("task", {}).get("id") == task["cardId"], "Selected native card differs")
        binding = {"project_id": identity["project_id"], "board_id": identity["board_id"], "canonical_root": str(root)}
        return binding, identity, digest((root / ".icm/project.json").read_bytes())

    def execute(self, request):
        if isinstance(request, dict) and request.get("action") == "_progress_validate":
            return self.progress_validation(request)

        if isinstance(request, dict) and request.get("action") in {"plan", "retrieval_plan"}:
            return self.planning(request)
        if isinstance(request, dict) and request.get("action") in {"mine_prepare", "mine_finish"}:
            return self.mining(request)
        if isinstance(request, dict) and request.get("action") == "consensus":
            return self.consensus(request)
        allowed = {"action", "query", "url", "max_results", "timeout", "artifact_id", "view", "offset", "limit",
                   "wait_selector", "click_selectors", "download_selector", "allow_archive", "selection", "session_id",
                   "research_plan_id", "retrieval_plan_id", "angle_id", "request_id"}
        require(isinstance(request, dict) and not set(request) - allowed, "Unexpected research request fields")
        action = request.get("action")
        require(action in {"search", "fetch", "render", "read"}, "Unsupported research action")
        timeout = request.get("timeout", 40 if action == "render" else 60 if action == "fetch" else 30)
        maximum_timeout = 120 if action == "fetch" else 60
        require(type(timeout) in (int, float) and 2 <= timeout <= maximum_timeout,
                f"Research {action} timeout must be 2 through {maximum_timeout} seconds")
        binding, identity, before = self.selection(request)
        state = Path(identity["state_root"])
        require(state.resolve() == state and state.is_relative_to(self.home / "state/projects"), "Project research storage escaped this home")
        store = ArtifactStore(state, binding)
        research_binding = None
        if {"research_plan_id", "retrieval_plan_id", "angle_id", "request_id"} & set(request):
            from harness import research_plan
            require(action in {"search", "fetch", "render"}, "Cached reads do not create request bindings")
            research_binding = research_plan.acquisition_binding(store, request, before)
        if action == "read":
            record = store.get(request.get("artifact_id"))
            return projection(record, request["artifact_id"], view=request.get("view", "text"),
                              offset=request.get("offset", 0), limit=request.get("limit", 8192), cached=True)
        store.quota(ARTIFACT_BYTES)
        os.environ.update(self.env)  # This one-operation owned helper only.
        web = importlib.import_module("harness.web_research")
        if action == "search":
            # Provider choice and credentials come from the installed host home,
            # never from model-supplied request fields or another project.
            payload = web.search(request.get("query"), limit=request.get("max_results", 5), timeout=timeout,
                                 home=self.home)
        elif action == "fetch":
            retrieval = importlib.import_module("harness.research_fetch")
            payload = retrieval.fetch(request.get("url"), timeout=timeout, allow_browser=True,
                                      allow_archive=request.get("allow_archive", False))
        else:
            browser = importlib.import_module("harness.web_browser")
            payload = browser.render(request.get("url"), timeout=timeout, offset=request.get("offset", 0),
                                     wait_selector=request.get("wait_selector"), click_selectors=request.get("click_selectors", []),
                                     download_selector=request.get("download_selector"))
        require(digest((Path(binding["canonical_root"]) / ".icm/project.json").read_bytes()) == before,
                "Project identity changed during research; result was not published")
        record = {"schema": "project-research-artifact/v1", "project": binding, "identity_sha256": before,
                  "session_id": str(request.get("session_id", ""))[:256], "action": action,
                  "observed_at": datetime.now(timezone.utc).isoformat(), "authority": AUTHORITY, "payload": payload}
        if research_binding is not None:
            record["research_binding"] = research_binding
        artifact_id = store.put(record)
        return projection(record, artifact_id, limit=request.get("limit", 8192))

    def progress_validation(self, request):
        """Read-only host validation, never exposed in the model action schema."""
        require(not set(request) - {"action", "selection", "session_id", "delivery"}, "Unexpected progress validation fields")
        delivered = request.get("delivery")
        require(isinstance(delivered, dict), "Missing delivered research result")
        binding, identity, before = self.selection(request)
        record = ArtifactStore(Path(identity["state_root"]), binding).get(delivered.get("artifact_id"))
        require(record.get("session_id") == request.get("session_id") and bool(request.get("session_id")),
                "Research belongs to another native session")
        require(record.get("identity_sha256") == before, "Research project source changed")
        payload, action = record["payload"], record["action"]
        abstain = {"schema": "research-result/v1", "ok": True, "authority": AUTHORITY,
                   "action": "_progress_validate", "credit": False, "status": "no_new_evidence"}
        if (action not in {"search", "fetch", "render"} or delivered.get("action") != action
                or delivered.get("ok") is not True or delivered.get("cached") is not False
                or delivered.get("view") != "text" or delivered.get("authority") != AUTHORITY
                or payload.get("ok") is not True or payload.get("status") not in {"ok", "partial"}):
            return abstain
        text, scope = text_view(record, "text")
        if not isinstance(text, str) or not text.strip():
            return abstain
        offset, count = delivered.get("offset"), delivered.get("returned_chars")
        require(type(offset) is int and type(count) is int and offset >= 0 and 0 < count <= 8192,
                "No delivered evidence window")
        window = text[offset:offset + count]
        require(count == len(window) and bool(window.strip()), "No nonempty delivered source window")
        require(delivered.get("schema") == "research-result/v1"
                and delivered.get("status") == payload.get("status") and delivered.get("content_scope") == scope
                and delivered.get("project_id") == binding["project_id"]
                and delivered.get("artifact_sha256") == delivered["artifact_id"][7:]
                and delivered.get("source_status") == payload.get("status")
                and delivered.get("text_sha256") == digest(text.encode())
                and delivered.get("text") == window and delivered.get("window_sha256") == digest(window.encode()),
                "Delivered research differs from its saved source")
        if action == "search":
            # Rank, provider order, timestamps and duplicate hits are not new
            # evidence. Incomplete hit JSON cannot expose unseen observations.
            if offset != 0 or count != len(text):
                return abstain
            try:
                hits = json.loads(window)
            except ValueError:
                return abstain
            if not isinstance(hits, list) or not 0 < len(hits) <= 100:
                return abstain
            meaningful = set()
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                url = hit.get("canonical_url") or hit.get("url")
                title, snippet = hit.get("title"), hit.get("snippet")
                if isinstance(url, str) and url and isinstance(title, str) and isinstance(snippet, str) and (title.strip() or snippet.strip()):
                    meaningful.add((url, " ".join(title.split()), " ".join(snippet.split())))
            if not meaningful:
                return abstain
            evidence = wire(sorted(meaningful))
        else:
            evidence = " ".join(window.split()).encode()
        require(digest((Path(binding["canonical_root"]) / ".icm/project.json").read_bytes()) == before,
                "Research project source changed during validation")
        return {**abstain, "credit": True, "status": "validated_source_evidence",
                "fingerprint": digest(evidence), "project_id": binding["project_id"],
                "artifact_id": delivered["artifact_id"], "content_scope": scope,
                "coverage": "captured_partial_evidence" if action == "render" or payload.get("status") == "partial" else "stored_source_evidence",
                "authority": AUTHORITY}

    def planning(self, request):
        from harness import research_plan
        fields = {"action", "timeout", "selection", "session_id", "limit"}
        fields |= ({"query", "extraction_schema", "angles", "source_priorities", "recall_bias"} if request["action"] == "plan"
                   else {"research_plan_id", "requests"})
        require(not set(request) - fields, "Unexpected planning fields")
        timeout = request.get("timeout", 30)
        require(type(timeout) in (int, float) and 2 <= timeout <= 60, "Research plan timeout must be 2 through 60 seconds")
        deadline = time.monotonic() + timeout
        binding, identity, before = self.selection(request)
        state = Path(identity["state_root"])
        require(state.resolve() == state and state.is_relative_to(self.home / "state/projects"), "Project planning storage escaped this home")
        store = ArtifactStore(state, binding)
        payload = (research_plan.plan(request) if request["action"] == "plan"
                   else research_plan.retrieval_plan(store, request, before, deadline))
        check_deadline(deadline)
        require(digest((Path(binding["canonical_root"]) / ".icm/project.json").read_bytes()) == before, "Project identity changed during planning")
        record = {"schema": "project-research-artifact/v1", "project": binding, "identity_sha256": before,
                  "session_id": str(request.get("session_id", ""))[:256], "action": request["action"], "authority": AUTHORITY, "payload": payload}
        key = store.put(record, deadline=deadline)
        result = projection(record, key, limit=request.get("limit", 8192))
        check_deadline(deadline)
        return result

    def mining_model(self, value):
        from harness.home import endpoint
        fields = {"provider", "id", "api", "base_url", "context_window", "max_tokens", "reasoning",
                  "compat_sha256", "models_sha256", "headers_sha256", "output_tokens"}
        require(isinstance(value, dict) and set(value) == fields, "Invalid native mining model binding")
        require(value["provider"] == "local" and value["api"] == "openai-completions"
                and value["id"] == self.config.get("model") and value["base_url"] == self.config.get("base_url"),
                "Mining requires the actual configured local home model")
        require(endpoint(value["base_url"]) == value["base_url"], "Mining needs the configured local endpoint")
        models, raw = read_json(self.home / "agent/models.json", 1024 * 1024)
        require(digest(raw) == value["models_sha256"], "Configured mining model bytes changed")
        provider = models.get("providers", {}).get("local", {})
        candidates = [m for m in provider.get("models", []) if m.get("id") == value["id"]]
        require(len(candidates) == 1 and provider.get("baseUrl") == value["base_url"]
                and provider.get("api") == value["api"], "Native provider differs from the mining binding")
        model = candidates[0]
        require(value["context_window"] == model.get("contextWindow") and value["max_tokens"] == model.get("maxTokens")
                and value["reasoning"] == model.get("reasoning", False)
                and value["compat_sha256"] == digest(wire(model.get("compat", {})))
                # Pi1.4 modelFromJson sets native model.headers=undefined.
                # Configured headers resolve separately from the bound JSON.
                and value["headers_sha256"] == digest(wire({}))
                and type(value["output_tokens"]) is int and value["output_tokens"] == min(1000, value["max_tokens"]),
                "Native model capabilities or transport changed")
        return value

    def mining(self, request):
        from harness import research_mining as mining
        common = {"action", "selection", "session_id", "model_binding"}
        prepare_fields = {"query", "extraction_schema", "artifact_ids", "recall_bias", "resume_artifact_id", "mine_timeout_seconds",
                          "research_plan_id", "retrieval_plan_id"}
        finish_fields = {"plan_artifact_id", "responses", "cancelled", "timed_out"}
        preparing = request["action"] == "mine_prepare"
        require(not set(request) - common - (prepare_fields if preparing else finish_fields), "Unexpected mining request fields")
        model = self.mining_model(request.get("model_binding"))
        binding, identity, before = self.selection(request)
        state = Path(identity["state_root"])
        require(state.resolve() == state and state.is_relative_to(self.home / "state/projects"), "Project mining storage escaped this home")
        store = ArtifactStore(state, binding)
        if preparing:
            plan = mining.prepare({**request, "identity_sha256": before}, store, model, text_view, wire, digest)
            resume = request.get("resume_artifact_id")
            if resume is not None:
                prior = store.get(resume)
                require(prior["action"] == "mine" and prior["payload"].get("complete") is True
                        and prior["payload"].get("ok") is True and prior["payload"].get("status") == "ok"
                        and prior["payload"].get("run_identity_sha256") == plan["run_identity_sha256"],
                        "Only a successful unchanged mining result can mark these sources seen")
                return {"schema": "research-mine-plan/v1", "ok": True, "authority": AUTHORITY,
                        "cached_result": projection(prior, resume, cached=True)}
            payload = {"ok": True, "status": "prepared", **plan}
            record = {"schema": "project-research-artifact/v1", "project": binding, "identity_sha256": before,
                      "action": "mine_plan", "authority": AUTHORITY, "payload": payload}
        else:
            record = store.get(request.get("plan_artifact_id"))
            require(record["action"] == "mine_plan" and record.get("identity_sha256") == before, "Mining plan/project identity changed")
            plan = record["payload"]
            spec = plan["spec"]
            rebuilt = mining.prepare({"query": spec["question"], "extraction_schema": spec["extraction_schema"],
                                      "artifact_ids": [s["artifact_id"] for s in spec["sources"]],
                                      "recall_bias": "HIGH" if spec["recall_floor"] == 1 else "MEDIUM",
                                      "mine_timeout_seconds": spec["mine_timeout_seconds"],
                                      **({k: spec["research_binding"][k] for k in ("research_plan_id", "retrieval_plan_id")}
                                         | {"identity_sha256": before} if "research_binding" in spec else {})},
                                     store, model, text_view, wire, digest)
            require(rebuilt["run_identity_sha256"] == plan["run_identity_sha256"], "Mining source/prompt/schema/model identity changed")
            require(type(request.get("cancelled", False)) is bool and type(request.get("timed_out", False)) is bool, "Invalid mining cancellation state")
            payload = mining.finish(rebuilt, request.get("responses"), cancelled=request.get("cancelled", False),
                                    timed_out=request.get("timed_out", False))
            payload["plan_artifact_id"] = request["plan_artifact_id"]
            record = {"schema": "project-research-artifact/v1", "project": binding, "identity_sha256": before,
                      "session_id": str(request.get("session_id", ""))[:256], "action": "mine", "authority": AUTHORITY,
                      "observed_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        require(digest((Path(binding["canonical_root"]) / ".icm/project.json").read_bytes()) == before,
                "Project identity changed during mining; result was not published")
        key = store.put(record)
        if preparing:
            return {"schema": "research-mine-plan/v1", "ok": True, "authority": AUTHORITY,
                    "plan_artifact_id": key, **plan,
                    "sources": [{k: v for k, v in source.items() if k != "text"} for source in plan["sources"]]}
        return projection(record, key)

    def consensus(self, request):
        from harness import research_consensus
        require(not set(request) - {"action", "artifact_ids", "query", "extraction_schema", "timeout", "limit", "selection", "session_id",
                                   "research_plan_id", "retrieval_plan_id", "acquisition_artifact_ids", "fulfillments", "search_fulfillments"},
                "Unexpected consensus request fields")
        timeout = request.get("timeout", 30)
        require(type(timeout) in (int, float) and 2 <= timeout <= 60, "Research consensus timeout must be 2 through 60 seconds")
        deadline = time.monotonic() + timeout
        binding, identity, before = self.selection(request)
        state = Path(identity["state_root"])
        require(state.resolve() == state and state.is_relative_to(self.home / "state/projects"), "Project consensus storage escaped this home")
        store = ArtifactStore(state, binding)
        if {"research_plan_id", "retrieval_plan_id", "acquisition_artifact_ids", "fulfillments", "search_fulfillments"} & set(request):
            from harness import research_plan
            payload = research_plan.requested_score(store, request, before, deadline)
        else:
            payload = research_consensus.score(store, request.get("artifact_ids"), before, query=request.get("query"),
                                               extraction_schema=request.get("extraction_schema"), deadline=deadline)
        check_deadline(deadline)
        require(digest((Path(binding["canonical_root"]) / ".icm/project.json").read_bytes()) == before,
                "Project identity changed during scoring; result was not published")
        record = {"schema": "project-research-artifact/v1", "project": binding, "identity_sha256": before,
                  "session_id": str(request.get("session_id", ""))[:256], "action": "consensus", "authority": AUTHORITY,
                  "payload": payload}
        key = store.put(record, deadline=deadline)
        check_deadline(deadline)
        result = projection(record, key, limit=request.get("limit", 8192))
        check_deadline(deadline)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    args = parser.parse_args()
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        raw = sys.stdin.buffer.read(524289)
        require(len(raw) <= 524288, "Research request exceeds its byte limit")
        result = ResearchRuntime(args.home).execute(json.loads(raw))
        sys.stdout.buffer.write(wire(result) + b"\n")
        return 0
    except (Exception, KeyboardInterrupt) as error:
        result = {"schema": "research-result/v1", "ok": False,
                  "status": "cancelled" if isinstance(error, KeyboardInterrupt) else "deadline" if getattr(error, "research_status", None) == "deadline" else "runtime_error",
                  "reason": str(error)[:1000], "authority": AUTHORITY}
        sys.stdout.buffer.write(wire(result) + b"\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
