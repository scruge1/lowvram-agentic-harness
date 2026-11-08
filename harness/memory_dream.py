"""Local-first Dream review over the installed memory retrieval surfaces.

Claude-mem observations, MemPalace retrieval and ICM remain separate owners.
This module does not create a store, scheduler or trusted memory entry.
"""

from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
import stat
from pathlib import Path
import re
import urllib.request
import urllib.parse
import urllib.error

SCHEMA = "agent-home-dream-evidence/v1"
MAX_INPUT = 98304
MAX_ITEMS = 64
MAX_SOURCE_BYTES = 8 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}\Z")
KEY = re.compile(r"[a-z0-9][a-z0-9._/-]{0,95}\Z")
REF = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
SECRET = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|(?:api[_-]?key|password|access[_-]?token)\s*[:=]\s*[^\s,;]{8,})"
)
PRIVATE_LOCAL_RANGES = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
    )
)


class DreamInputError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise DreamInputError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def observed(value):
    require(isinstance(value, str) and 10 <= len(value) <= 40, "Invalid dated evidence")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DreamInputError("Evidence must have ISO8601 timestamp") from exc
    require(date.tzinfo is not None, "Evidence time must have timezone")
    return date.astimezone(timezone.utc)


def normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[\W_]+", " ", text.lower())).strip()


def project_scope(home, project):
    home, project = Path(home).resolve(strict=True), Path(project).resolve(strict=True)
    marker = project / ".icm" / "project.json"
    require(
        home.is_dir()
        and project.is_dir()
        and marker.is_file()
        and not marker.is_symlink(),
        "Existing admitted home/project required",
    )
    raw = marker.read_bytes()
    require(len(raw) <= 131072, "ICM source too large")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise DreamInputError("Invalid ICM source") from exc
    require(isinstance(value, dict), "Invalid ICM identity")
    pid = value.get("project_id")
    require(
        isinstance(pid, str)
        and pid
        and value.get("board_id") == "project:" + pid
        and value.get("canonical_root") == str(project)
        and value.get("state_root") == str(home / "state" / "projects" / pid),
        "Dream evidence belongs to a different home/project",
    )
    return home, project, pid, sha(raw)


def prove_source(home, project, value):
    path = value.get("source_path")
    if path is None:
        return False, "retrieval_only_unverified_original"
    require(
        isinstance(path, str) and 1 <= len(path) <= 4096 and "\x00" not in path,
        "Invalid memory source path",
    )
    path = Path(path)
    require(path.is_absolute(), "Only absolute current source paths")
    allowed = (project, home / "agent" / "sessions", home / "memory" / "pi-capture")
    require(
        any(path.is_relative_to(prefix) for prefix in allowed),
        "Memory source escapes admitted project/home",
    )
    current = path
    while current != current.parent:
        require(not current.is_symlink(), "Memory source uses a symlink")
        current = current.parent
    original = path.resolve(strict=True)
    require(
        original == path and original.is_file(), "Memory source aliases another path"
    )
    before = original.stat(follow_symlinks=False)
    require(
        stat.S_ISREG(before.st_mode)
        and before.st_nlink == 1
        and 0 < before.st_size <= MAX_SOURCE_BYTES,
        "Memory source must be bounded regular single-link file",
    )
    if hasattr(os, "getuid"):
        require(before.st_uid == os.getuid(), "Memory source belongs to another owner")
    fd = os.open(original, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)

        def fields(st):
            return (
                st.st_dev,
                st.st_ino,
                st.st_size,
                st.st_mtime_ns,
                st.st_ctime_ns,
            )

        require(fields(opened) == fields(before), "Memory source changed during open")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
        require(
            len(raw) == before.st_size and fields(os.fstat(fd)) == fields(opened),
            "Memory source changed during read",
        )
    finally:
        os.close(fd)
    require(
        fields(original.stat(follow_symlinks=False)) == fields(before),
        "Memory source changed after read",
    )
    require(sha(raw) == value["source_sha256"], "Memory source changed")
    quote = value.get("source_quote")
    require(
        isinstance(quote, str)
        and 8 <= len(quote)
        and len(quote.encode()) <= 1600
        and quote.encode() in raw,
        "Cited exact source excerpt unavailable",
    )
    require(not SECRET.search(quote), "Memory excerpt contains credential-like content")
    return True, "current_source_hash_and_exact_excerpt"


def validate_item(home, project, pid, item):
    allowed = {
        "source_id",
        "source_kind",
        "claim_key",
        "claim_text",
        "source_quote",
        "source_path",
        "source_sha256",
        "observed_at",
        "project_id",
        "verification",
    }
    require(
        isinstance(item, dict) and set(item) <= allowed, "Unknown memory record fields"
    )
    require(item.get("project_id") == pid, "Cross-project memory record denied")
    sid, key, kind, text = (
        item.get("source_id"),
        item.get("claim_key"),
        item.get("source_kind"),
        item.get("claim_text"),
    )
    require(
        isinstance(sid, str) and REF.fullmatch(sid) is not None, "Invalid source ID"
    )
    require(
        isinstance(key, str) and KEY.fullmatch(key) is not None, "Invalid topic key"
    )
    require(
        kind
        in {
            "claude_mem",
            "mempalace",
            "pi_journal",
            "icm",
            "owner_correction",
            "test_receipt",
        },
        "Unknown evidence role",
    )
    require(
        isinstance(text, str)
        and 8 <= len(text) <= 800
        and len(text.encode()) <= 1600
        and not SECRET.search(text),
        "Memory claim invalid/unsafe",
    )
    pin = item.get("source_sha256")
    require(
        isinstance(pin, str) and HASH.fullmatch(pin) is not None,
        "Source SHA256 required",
    )
    stamp = observed(item.get("observed_at"))
    require(
        item.get("verification", "retrieval_only")
        in {"retrieval_only", "source_observed", "verified_receipt", "owner_asserted"},
        "Invalid verifier label",
    )
    proven, quality = prove_source(home, project, item)
    return {
        "id": sid,
        "key": key,
        "text": text,
        "variant": normalize(text),
        "kind": kind,
        "date": stamp,
        "date_text": stamp.isoformat(),
        "source_current": proven,
        "quality": quality,
        "source_sha256": pin,
    }


def preview(home, project, request):
    require(
        isinstance(request, dict)
        and set(request) == {"schema", "project_id", "evidence"}
        and request.get("schema") == SCHEMA,
        "Invalid Dream envelope",
    )
    raw = json.dumps(request, ensure_ascii=False).encode()
    require(len(raw) <= MAX_INPUT, "Dream input exceeds bound")
    home, project, pid, identity = project_scope(home, project)
    require(request["project_id"] == pid, "Dream project differs from current identity")
    data = request["evidence"]
    require(
        isinstance(data, list) and 1 <= len(data) <= MAX_ITEMS,
        "Dream requires 1-64 evidence windows",
    )
    groups = defaultdict(list)
    seen = set()
    for item in data:
        row = validate_item(home, project, pid, item)
        require(row["id"] not in seen, "Duplicate memory source identity")
        seen.add(row["id"])
        groups[row["key"]].append(row)
    require(len(groups) <= 20, "Dream topics exceed bounded review")
    subjects = []
    for key, items in sorted(groups.items()):
        forward = sorted(items, key=lambda x: (x["date"], x["id"]))
        backward = list(reversed(forward))
        variants = defaultdict(list)
        for item in items:
            variants[item["variant"]].append(item["id"])
        conflict = len(variants) > 1
        qualified = sum(row["source_current"] for row in items)
        subjects.append(
            {
                "claim_key": key,
                "status": "CONTRADICTION_REVIEW_REQUIRED"
                if conflict
                else "SOURCE_REVIEW_REQUIRED"
                if qualified != len(items)
                else "SOURCE_PINNED_CANDIDATE",
                "source_count": len(items),
                "variant_count": len(variants),
                "forward_source_ids": [x["id"] for x in forward],
                "backward_source_ids": [x["id"] for x in backward],
                "earliest": forward[0]["date_text"],
                "latest": forward[-1]["date_text"],
                "source_qualified_count": qualified,
                "variant_sources": [sorted(v) for v in variants.values()],
                "newest_not_necessarily_best": True,
                "review": "independent comparative test and original-source verification",
            }
        )
    return {
        "schema": "agent-home-dream-review/v1",
        "authority": "retrieval_only",
        "status": "CANDIDATES_NOT_PROMOTED",
        "project_id": pid,
        "project_identity_sha256": identity,
        "input_sha256": sha(raw),
        "source_count": len(data),
        "forward_backward": subjects,
        "exact_source_count": sum(
            r["source_current"] for g in groups.values() for r in g
        ),
        "allowed_next": [
            "review_against_originals",
            "propose_wiki_links",
            "propose_regression_tests",
        ],
        "forbidden": [
            "mutate_memory",
            "bless_ssot",
            "write_icm",
            "start_worker",
            "modify_model",
            "send_messages",
        ],
        "last_known_best": "UNASSESSED_NOT_INFERRED",
    }


def local_url(value):
    require(isinstance(value, str) and len(value) <= 256, "Missing pinned local model")
    parts = urllib.parse.urlsplit(value)
    require(
        parts.scheme in {"http", "https"}
        and parts.hostname
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
        and parts.path in {"", "/", "/v1", "/v1/"},
        "Dream model must use exact configured local OpenAI endpoint",
    )
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError as exc:
        raise DreamInputError("Model endpoint must use an IP literal") from exc
    require(
        any(ip in local_network for local_network in PRIVATE_LOCAL_RANGES),
        "Dream inference forbids public network destinations",
    )
    require(parts.port and 1 <= parts.port <= 65535, "Pinned local model port required")
    return parts.scheme + "://" + parts.netloc + "/v1/chat/completions"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise DreamInputError("Local memory review cannot follow redirects")


def analyze_local(home, project, request, config, *, timeout=12):
    result = preview(home, project, request)
    require(
        isinstance(config, dict)
        and isinstance(config.get("model"), str)
        and 1 <= len(config["model"]) <= 160,
        "Configured local model identity required",
    )
    require(
        type(timeout) in (float, int) and 1 <= timeout <= 30,
        "Bound local inference timeout",
    )
    url = local_url(config.get("base_url"))
    # LLM input is a bounded view. Paths, secrets and original transcript
    # details stay with the existing memory engines.
    rows = [
        {
            key: x[key]
            for key in (
                "source_id",
                "claim_key",
                "source_kind",
                "observed_at",
                "claim_text",
            )
        }
        for x in request["evidence"]
    ]
    content = (
        "Review this *untrusted* memory evidence. Suggest inconsistencies, "
        "revalidation and linked wiki/test candidates, never approval. "
        'Respond with JSON only: {"proposals":[{"claim_key":"...",'
        '"source_ids":["..."],"reason":"...","kind":'
        '"candidate_summary|contradiction|revalidation"}]}. '
        "Cite exact listed source_ids; do not invent facts. Evidence:\n"
        + json.dumps(rows, ensure_ascii=False)
    )
    require(len(content.encode()) <= 16000, "Dream LLM context budget exceeded")
    body = json.dumps(
        {
            "model": config["model"],
            "temperature": 0,
            "max_tokens": 650,
            "stream": False,
            "messages": [{"role": "user", "content": content}],
        },
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        ).open(req, timeout=timeout) as response:
            raw = response.read(100001)
            require(len(raw) <= 100000, "Dream model response exceeds bound")
            answer = json.loads(raw)["choices"][0]["message"]["content"]
        proposal = json.loads(answer)
    except (
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise DreamInputError(
            "Local memory inference failed (" + type(exc).__name__ + ")"
        ) from None
    require(
        isinstance(proposal, dict)
        and set(proposal) == {"proposals"}
        and isinstance(proposal["proposals"], list)
        and len(proposal["proposals"]) <= 12,
        "Local model returned invalid dream proposals",
    )
    ids = {x["source_id"]: x["claim_key"] for x in request["evidence"]}
    for item in proposal["proposals"]:
        require(
            isinstance(item, dict)
            and set(item) == {"claim_key", "source_ids", "reason", "kind"},
            "Untrusted model output contains forbidden fields",
        )
        cited = item["source_ids"]
        require(
            isinstance(cited, list)
            and 1 <= len(cited) <= 16
            and len(cited) == len(set(cited))
            and all(
                isinstance(i, str) and ids.get(i) == item["claim_key"] for i in cited
            ),
            "Dream proposal contains unknown or cross-topic citation",
        )
        require(
            isinstance(item["reason"], str)
            and 8 <= len(item["reason"]) <= 400
            and not SECRET.search(item["reason"]),
            "Dream explanation invalid/unsafe",
        )
        require(
            item["kind"] in {"candidate_summary", "contradiction", "revalidation"},
            "Dream suggestion type invalid",
        )
    result["model_review"] = {
        "status": "UNVERIFIED_LOCAL_MODEL_SUGGESTIONS",
        "model": config["model"],
        "proposals": proposal["proposals"],
        "cannot_promote": True,
    }
    return result


def from_claude_mem_tool_window(
    value, *, project_id, observer_project, claim_key, claim_text, observed_at
):
    """Convert ONE already verified native Claude-mem tool field into review input.

    The existing memory history API owns the HTTP worker connection and
    project/session selection. The field itself is retrieval-only: no stored
    row receives independent owner authority from this conversion.
    """
    require(
        isinstance(value, dict)
        and value.get("schema") == "claude-memory-tool-history/v1"
        and value.get("authority") == "retrieval_only"
        and value.get("source_scope") == "native_stored_tool_field"
        and value.get("status") == "ok"
        and value.get("field_present") is True
        and value.get("platform_source") == "raw",
        "Claude-mem native field result was not verified",
    )
    require(
        isinstance(observer_project, str)
        and 1 <= len(observer_project) <= 512
        and value.get("project") == observer_project,
        "Claude-mem observation belongs to a different native project",
    )
    require(
        type(value.get("id")) is int
        and 1 <= value["id"] <= 2**53 - 1
        and isinstance(value.get("content_session_id"), str)
        and 1 <= len(value["content_session_id"]) <= 512
        and value.get("field") in ("tool_input", "tool_response"),
        "Claude-mem tool field identity invalid",
    )
    text = value.get("text")
    require(
        isinstance(text, str)
        and 8 <= len(text) <= 4096
        and value.get("stored_eof") is True
        and value.get("offset") == 0
        and value.get("window_bytes") == value.get("stored_bytes")
        and value.get("stored_bytes") == len(text.encode("utf-8")),
        "Claude-mem field is a partial or unsafe source window",
    )
    pin = sha(text.encode("utf-8"))
    require(
        value.get("window_sha256") == pin and value.get("stored_sha256") == pin,
        "Claude-mem stored field changed after reading",
    )
    require(
        isinstance(claim_text, str)
        and 8 <= len(claim_text) <= 800
        and claim_text in text
        and not SECRET.search(claim_text),
        "Claim is not present in the cited native tool field",
    )
    require(
        isinstance(claim_key, str) and KEY.fullmatch(claim_key) is not None,
        "Unknown source topic key",
    )
    observed(observed_at)
    return {
        "project_id": project_id,
        "source_id": "cmtool-" + str(value["id"]) + "-" + value["field"],
        "source_kind": "claude_mem",
        "claim_key": claim_key,
        "claim_text": claim_text,
        "observed_at": observed_at,
        "source_sha256": pin,
        "verification": "retrieval_only",
    }


def main(argv=None):
    """Read a bounded JSON evidence envelope from stdin; preview only."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        require(
            0 < len(raw) <= MAX_INPUT,
            "Memory evidence input is unavailable or oversized",
        )
        request = json.loads(raw)
        view = preview(args.home, args.project, request)
    except (OSError, ValueError, TypeError, UnicodeError):
        print(
            json.dumps(
                {
                    "schema": "agent-home-dream-review/v1",
                    "status": "unavailable",
                    "authority": "retrieval_only",
                    "error": "Memory review unavailable; inspect the exact original input and current project identity.",
                }
            )
        )
        return 1
    print(json.dumps(view, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
