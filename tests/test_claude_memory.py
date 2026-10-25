"""Verify local-only observer configuration before worker dispatch."""
import json
import io
from contextlib import contextmanager, nullcontext, redirect_stdout
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from harness import claude_memory, home, model_service_handoff


class ClaudeMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "home"
        self.config = home.scaffold(self.root, profile="core", base_url="http://127.0.0.1:8080/v1", model="test", offline=True)

    def test_complete_provider_and_private_worker_root(self):
        root, config = claude_memory.settings(self.root, self.config)
        self.assertEqual(root, self.root / "memory/claude-mem")
        self.assertEqual(config["CLAUDE_MEM_PROVIDER"], "openai-compatible")
        self.assertEqual(config["CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER"], "")
        self.assertEqual(config["CLAUDE_MEM_CHROMA_ENABLED"], "false")
        self.assertEqual(config["CLAUDE_MEM_TRANSCRIPTS_ENABLED"], "false")

    def test_incomplete_or_cloud_fallback_configuration_never_dispatches(self):
        file = self.root / "memory/claude-mem/settings.json"
        value = json.loads(file.read_text())
        value["CLAUDE_MEM_OPENAI_COMPAT_MODEL"] = ""
        value["CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER"] = "claude"
        file.write_text(json.dumps(value))
        with patch.object(claude_memory.platform, "system", return_value="Linux"), patch.object(claude_memory, "worker_paths") as workers:
            with self.assertRaises(home.HomeError):
                claude_memory.invoke(self.root, "start")
            workers.assert_not_called()

    def test_sensitive_search_abstains_before_any_worker_or_store_read(self):
        with patch.object(claude_memory.platform, "system", return_value="Linux"), patch.object(claude_memory, "settings") as settings:
            result = claude_memory.invoke(self.root, "search", event="old API key")
            self.assertEqual(result["reason"], "sensitive_query")
            settings.assert_not_called()

    def test_responding_foreign_port_is_not_worker_ownership(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return b'{"pid":123,"version":"13.29.0"}'
        root, _ = claude_memory.settings(self.root, self.config)
        with patch.object(claude_memory, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(home.HomeError, "owned worker identity"):
                claude_memory.health(self.root, root, self.config, self.root / "worker.cjs")

    def owned_config(self):
        binding = {"schema": model_service_handoff.SCHEMA, "home": str(self.root),
                   "storage_root": str(self.root.parent / "service"), "specification_sha256": "1" * 64,
                   "base_url": self.config["base_url"], "model_id": self.config["model"],
                   "context": self.config["context_window"], "max_output": self.config["max_output"],
                   "transport_profile": self.config["model_profile"],
                   "environment_variable": model_service_handoff._variable(str(self.root))}
        return {**self.config, "owned_model_service": binding}

    def test_owned_disk_settings_remain_nonsecret_and_do_not_resolve_a_service(self):
        config = self.owned_config()
        path = self.root / "memory/claude-mem/settings.json"
        for placeholder in ("local", ""):
            value = json.loads(path.read_text())
            value["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"] = placeholder
            path.write_text(json.dumps(value))
            before = path.read_bytes()
            with patch.object(model_service_handoff, "launch_environment") as resolver:
                _, required = claude_memory.settings(self.root, config)
            self.assertEqual(required["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"], placeholder)
            resolver.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
        for invalid in ("a" * 64, "$" + config["owned_model_service"]["environment_variable"], ["local"]):
            value["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"] = invalid
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(home.HomeError, "out of persisted settings"):
                claude_memory.settings(self.root, config)

    def test_effective_owned_key_overrides_placeholder_and_ambient_values_only_in_child(self):
        config = self.owned_config()
        _, required = claude_memory.settings(self.root, config)
        key = "a" * 64
        name = config["owned_model_service"]["environment_variable"]
        ambient = {"HOME": str(Path.home()), name: "old", "CLAUDE_MEM_OPENAI_COMPAT_API_KEY": "ambient",
                   "CLAUDE_MEM_OPENAI_COMPAT_API_KEYS": "ambient-pool",
                   "CLAUDE_MEM_OBSERVER_CONTEXT_WINDOW": "131072", "CLAUDE_MEM_OBSERVER_MAX_OUTPUT_TOKENS": "16000"}
        before = (self.root / "memory/claude-mem/settings.json").read_bytes()
        with patch.object(claude_memory, "environment", return_value=dict(ambient)), \
                patch.object(model_service_handoff, "launch_environment", return_value=
                             model_service_handoff.LaunchEnvironment({name: key}, {})) as resolver:
            result = claude_memory.child_environment(self.root, config, required)
        resolver.assert_called_once_with(self.root, config["owned_model_service"])
        self.assertEqual(result["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"], key)
        self.assertEqual(result["CLAUDE_MEM_OPENAI_COMPAT_API_KEYS"], "")
        self.assertEqual(result["CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER"], "")
        self.assertEqual(result["CLAUDE_MEM_OBSERVER_CONTEXT_WINDOW"], str(config["context_window"]))
        self.assertEqual(result["CLAUDE_MEM_OBSERVER_MAX_OUTPUT_TOKENS"], str(config["max_output"]))
        self.assertEqual(ambient[name], "old")
        self.assertEqual(required["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"], "local")
        self.assertEqual((self.root / "memory/claude-mem/settings.json").read_bytes(), before)

    def test_owned_route_mismatch_fails_before_credential_resolution(self):
        config = self.owned_config()
        _, required = claude_memory.settings(self.root, config)
        for changes in ({"model": "other"}, {"base_url": "http://127.0.0.1:8081/v1"}, {"context_window": 65536}):
            with patch.object(model_service_handoff, "launch_environment") as resolver, \
                    self.assertRaisesRegex(home.HomeError, "route differs"):
                claude_memory.child_environment(self.root, {**config, **changes}, required)
            resolver.assert_not_called()

    def test_non_owned_child_preserves_local_key_without_resolving_owned_service(self):
        _, required = claude_memory.settings(self.root, self.config)
        with patch.object(model_service_handoff, "launch_environment") as resolver:
            env = claude_memory.child_environment(self.root, self.config, required)
        resolver.assert_not_called()
        self.assertEqual(env["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"], "local")

    @contextmanager
    def worker_fixture(self, startup_key, current_key, *, foreign=False, resolver_error=None, live=True, worker_budget=None):
        """Exercise actual identity/auth code with a fictional proc view; no sockets or workers."""
        config = self.owned_config()
        root = self.root / "memory/claude-mem"
        worker = self.root / "worker.cjs"
        worker.write_text("// synthetic worker asset, never executed")
        pid = 314159
        process = Path("/proc") / str(pid)
        (root / "worker.pid").write_text(json.dumps({"pid": pid, "port": config["claude_memory_port"]}))
        observed = {"pid": pid, "version": "13.29.0", "workerPath": str(worker),
                    "ai": {"provider": "openai-compatible"}}
        stat = b"314159 (synthetic worker) S " + b"0 " * 18 + b"12345"
        env = [os.fsencode("CLAUDE_MEM_DATA_DIR=" + str(root)),
               b"CLAUDE_MEM_OPENAI_COMPAT_API_KEY=" + startup_key.encode()]
        budget = claude_memory.observer_budget(config) if worker_budget is None else worker_budget
        env.extend(os.fsencode(key + "=" + value) for key, value in budget.items())
        original_read, original_resolve = Path.read_bytes, Path.resolve
        state = {"live": live, "commands": [], "searches": [], "requests": [], "stops": []}
        def read(path):
            if path == process / "stat":
                return stat
            if path == process / "environ":
                return b"\0".join(env)
            return original_read(path)
        def resolve(path, *args, **kwargs):
            if path == process / "cwd":
                return self.root if foreign else root
            return original_resolve(path, *args, **kwargs)
        class Response:
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return json.dumps(self.value).encode()
        def urlopen(url, **_kwargs):
            if not state["live"]:
                raise URLError("synthetic stopped worker")
            if "/api/search?" in url:
                state["searches"].append(url)
                return Response({"observations": [{"id": 42, "text": "Synthetic retained observation"}]})
            return Response(observed)
        def request(_proof, route, payload=None, **kwargs):
            state["requests"].append((route, payload))
            if "/api/search?" in route:
                state["searches"].append(route)
                return {"observations": [{"id": 42, "text": "Synthetic retained observation"}]}
            if route == "/api/sessions/init":
                return {"sessionDbId": 1, "promptNumber": 1}
            return {"status": "queued"}
        def stop(_proof):
            state["stops"].append(pid)
            state["live"] = False
            return {"status": "stopped"}
        name = config["owned_model_service"]["environment_variable"]
        launch = model_service_handoff.LaunchEnvironment({name: current_key}, {})
        with patch.object(claude_memory, "load", return_value=(self.root, config)), \
                patch.object(claude_memory.platform, "system", return_value="Linux"), \
                patch.object(claude_memory, "worker_paths", return_value=(self.root / "bun", worker)), \
                patch.object(claude_memory, "environment", return_value={"HOME": str(Path.home())}), \
                patch.object(claude_memory, "urlopen", side_effect=urlopen), \
                patch.object(claude_memory, "request", side_effect=request), \
                patch.object(claude_memory, "stop_worker", side_effect=stop), \
                patch.object(claude_memory, "worker_proof", return_value={"pid": pid}), \
                patch.object(claude_memory, "live_pid", return_value=pid if live else None), \
                patch.object(claude_memory, "operation", return_value=nullcontext()), \
                patch.object(model_service_handoff, "launch_environment", return_value=launch,
                             side_effect=resolver_error) as resolver, \
                patch.object(Path, "read_bytes", read), patch.object(Path, "resolve", resolve):
            yield state, resolver

    def test_current_worker_key_allows_hook_without_start_or_restart(self):
        key = "a" * 64
        with self.worker_fixture(key, key) as (state, _resolver):
            result = claude_memory.invoke(self.root, "hook", {"sessionId": "fictional-session", "toolName": "read",
                                                            "toolInput": {"path": "public-example.txt"}}, "observation")
        self.assertEqual(state["commands"], [])
        self.assertEqual(state["requests"], [("/api/sessions/observations", {
            "contentSessionId": "fictional-session", "platformSource": "raw", "cwd": str(self.root),
            "tool_name": "read", "tool_input": {"path": "public-example.txt"}, "tool_response": None})])
        self.assertEqual(result["status"], "hook_delivered")
        self.assertIn("not generated", result["scope"])
        self.assertNotIn(key, json.dumps(result))

    def test_rotated_nonce_blocks_adoption_and_capture_without_replay_or_restart(self):
        for action in ("start", "hook"):
            with self.worker_fixture("a" * 64, "b" * 64) as (state, _resolver):
                with self.assertRaisesRegex(home.HomeError, "credential is stale") as error:
                    claude_memory.invoke(self.root, action, {"sessionId": "fictional-session", "toolName": "read"},
                                         "observation" if action == "hook" else "ordinary query")
                self.assertEqual(state["commands"], [])
                self.assertNotIn("a" * 64, str(error.exception))
                self.assertNotIn("b" * 64, str(error.exception))

    def test_native_parser_bounds_and_persisted_budget_drift_hold_capture(self):
        self.assertEqual(claude_memory.observer_budget({"context_window": 8192, "max_output": 256}), {
            "CLAUDE_MEM_OBSERVER_CONTEXT_WINDOW": "8192", "CLAUDE_MEM_OBSERVER_MAX_OUTPUT_TOKENS": "256"})
        for changes in ({"context_window": 8191}, {"context_window": 2**53}, {"max_output": 128},
                        {"max_output": 1_000_001}, {"max_output": 32768}, {"max_output": True}):
            with self.subTest(changes=changes), self.assertRaisesRegex(home.HomeError, "Observer capture requires"):
                claude_memory.observer_budget({**self.config, **changes})
        path = self.root / "memory/claude-mem/settings.json"
        original = path.read_bytes()
        for key in ("CLAUDE_MEM_OBSERVER_CONTEXT_WINDOW", "CLAUDE_MEM_OBSERVER_MAX_OUTPUT_TOKENS"):
            try:
                changed = json.loads(original)
                changed[key] = "16000"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(setting=key), self.assertRaisesRegex(home.HomeError, "budget settings differ"):
                    claude_memory.settings(self.root, self.config)
                # Stop/status/search can still use exact ownership on a stale
                # budget; settings validation does not resolve a credential.
                claude_memory.settings(self.root, self.config, require_budget=False)
            finally:
                path.write_bytes(original)

    def test_missing_or_stale_worker_budget_blocks_start_and_hook_before_submission(self):
        correct = claude_memory.observer_budget(self.config)
        for budget in ({}, {**correct, "CLAUDE_MEM_OBSERVER_CONTEXT_WINDOW": "131072"},
                       {**correct, "CLAUDE_MEM_OBSERVER_MAX_OUTPUT_TOKENS": "16000"}):
            for action in ("start", "hook"):
                with self.subTest(budget=budget, action=action), self.worker_fixture("a" * 64, "a" * 64, worker_budget=budget) as (state, _):
                    with self.assertRaisesRegex(home.HomeError, "worker budget is stale"):
                        claude_memory.invoke(self.root, action, {"sessionId": "s", "toolName": "read"},
                                             "observation" if action == "hook" else None)
                    self.assertEqual(state["requests"], [])
                    self.assertEqual(state["commands"], [])

    def test_stale_auth_and_budget_preserve_status_search_and_exact_stop(self):
        with self.worker_fixture("a" * 64, "b" * 64, worker_budget={},
                                 resolver_error=AssertionError("Read/stop must not resolve credentials")) as (state, resolver):
            path = self.root / "memory/claude-mem/settings.json"
            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["CLAUDE_MEM_OBSERVER_MAX_OUTPUT_TOKENS"] = "128"
            path.write_text(json.dumps(changed), encoding="utf-8")
            self.assertEqual(claude_memory.invoke(self.root, "status")["status"], "running")
            self.assertEqual(claude_memory.invoke(self.root, "search", event="synthetic retained observation")["results"][0]["id"], 42)
            self.assertEqual(claude_memory.invoke(self.root, "stop")["status"], "stopped")
        resolver.assert_not_called()
        self.assertEqual(state["stops"], [314159])
        self.assertEqual(state["commands"], [])

    def test_owned_status_works_offline_without_claiming_auth_or_capture_ready(self):
        with self.worker_fixture("a" * 64, "b" * 64,
                                 resolver_error=AssertionError("Inspection must not resolve model credentials")) as (state, resolver):
            result = claude_memory.invoke(self.root, "status")
        resolver.assert_not_called()
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["authentication"], "not_checked")
        self.assertFalse(result["capture_ready"])
        self.assertEqual(state["commands"], [])

    def test_existing_owned_keyword_search_works_when_model_is_offline(self):
        with self.worker_fixture("a" * 64, "b" * 64,
                                 resolver_error=AssertionError("Keyword recall must not resolve model credentials")) as (state, resolver):
            result = claude_memory.invoke(self.root, "search", event="synthetic retained observation")
        resolver.assert_not_called()
        self.assertEqual(result["results"], [{"id": 42, "text": "Synthetic retained observation"}])
        self.assertEqual(result["mode"], "sqlite_fts_keyword")
        self.assertEqual(result["authority"], "retrieval_only")
        self.assertEqual(result["authentication"], "not_checked")
        self.assertFalse(result["capture_ready"])
        self.assertEqual(len(state["searches"]), 1)
        self.assertEqual(state["commands"], [])

    def test_stopped_owned_keyword_search_holds_without_starting_an_observer(self):
        with self.worker_fixture("a" * 64, "b" * 64, live=False,
                                 resolver_error=AssertionError("Unavailable recall must not resolve model credentials")) as (state, resolver):
            result = claude_memory.invoke(self.root, "search", event="synthetic retained observation")
        resolver.assert_not_called()
        self.assertEqual(result["status"], "held")
        self.assertEqual(result["reason"], "owned_observer_stopped")
        self.assertEqual(result["results"], [])
        self.assertEqual(state["searches"], [])
        self.assertEqual(state["commands"], [])

    def test_offline_keyword_search_still_rejects_foreign_worker_identity(self):
        with self.worker_fixture("a" * 64, "b" * 64, foreign=True,
                                 resolver_error=AssertionError("Recall must not resolve model credentials")) as (state, resolver):
            with self.assertRaisesRegex(home.HomeError, "another data directory"):
                claude_memory.invoke(self.root, "search", event="synthetic retained observation")
        resolver.assert_not_called()
        self.assertEqual(state["searches"], [])
        self.assertEqual(state["commands"], [])

    def test_exact_stale_worker_can_stop_without_live_model_or_current_nonce(self):
        with self.worker_fixture("a" * 64, "b" * 64,
                                 resolver_error=AssertionError("Stop must not resolve credentials")) as (state, resolver):
            result = claude_memory.invoke(self.root, "stop")
        resolver.assert_not_called()
        self.assertEqual(result, {"status": "stopped"})
        self.assertEqual(state["stops"], [314159])
        self.assertEqual(state["commands"], [])

    def test_foreign_worker_cannot_stop_even_when_nonce_is_stale(self):
        with self.worker_fixture("a" * 64, "b" * 64, foreign=True) as (state, resolver):
            with self.assertRaisesRegex(home.HomeError, "another data directory"):
                claude_memory.invoke(self.root, "stop")
        resolver.assert_not_called()
        self.assertEqual(state["commands"], [])

    def test_invalid_capture_is_refused_before_auth_start_or_worker_access(self):
        for event, payload in (("context", {"sessionId": "s"}), ("user-message", {"sessionId": "s"}),
                               ("observation", {"sessionId": "s"}), ("summarize", {"sessionId": ""}),
                               ("session-init", {"sessionId": "s", "prompt": "a" * (2 * 1024 * 1024)})):
            with self.subTest(event=event), patch.object(claude_memory, "load") as loader:
                with self.assertRaises(home.HomeError):
                    claude_memory.invoke(self.root, "hook", payload, event)
                loader.assert_not_called()

    def test_remaining_native_capture_payloads_preserve_source_and_queue_semantics(self):
        for event, fields, route in (("session-init", {"prompt": "Synthetic ordinary request"}, "/api/sessions/init"),
                                      ("summarize", {}, "/api/sessions/summarize")):
            with self.subTest(event=event), self.worker_fixture("a" * 64, "a" * 64) as (state, _resolver):
                result = claude_memory.invoke(self.root, "hook", {"sessionId": "source-session", **fields}, event)
                self.assertEqual(state["requests"][0][0], route)
                self.assertEqual(state["requests"][0][1]["platformSource"], "raw")
                self.assertEqual(state["requests"][0][1]["contentSessionId"], "source-session")
                self.assertEqual(result["response"], {"sessionDbId": 1, "promptNumber": 1} if event == "session-init" else {"status": "queued"})
                self.assertNotIn("generated", result["status"])
                self.assertEqual(state["commands"], [])

    def test_import_cannot_inherit_cli_autorun_flag(self):
        _, required = claude_memory.settings(self.root, self.config)
        with patch.object(claude_memory, "environment", return_value={"HOME": str(Path.home()), "CLAUDE_MEM_MANAGED": "true"}):
            self.assertNotIn("CLAUDE_MEM_MANAGED", claude_memory.child_environment(self.root, self.config, required))

    def test_connected_http_checks_lifetime_before_sending_body_and_after_response(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"status":"queued"}'
        with patch.object(claude_memory.http.client, "HTTPConnection", return_value=connection) as constructor, \
                patch.object(claude_memory, "recheck") as recheck:
            result = claude_memory.request({"port": 12345}, "/api/sessions/summarize", {"contentSessionId": "s"})
        self.assertEqual(result, {"status": "queued"})
        constructor.assert_called_once_with("127.0.0.1", 12345, timeout=10)
        self.assertEqual(recheck.call_count, 2)
        self.assertEqual(connection.request.call_args.args[:2], ("POST", "/api/sessions/summarize"))
        connection.close.assert_called_once()
        with patch.object(claude_memory.http.client, "HTTPConnection", return_value=connection), \
                patch.object(claude_memory, "recheck", side_effect=home.HomeError("changed")):
            connection.reset_mock()
            with self.assertRaisesRegex(home.HomeError, "changed"):
                claude_memory.request({"port": 12345}, "/api/sessions/init", {"prompt": "No delivery"})
            connection.request.assert_not_called()
            connection.close.assert_called_once()

    def test_unknown_or_failed_http_response_never_reports_capture_success_or_redirects(self):
        for status, raw in ((302, b'{}'), (500, b'{}'), (200, b'{"error":"failed"}'),
                            (200, b'{"stored":false}'), (200, b'[]'), (200, b'x' * (2 * 1024 * 1024 + 1))):
            connection = Mock()
            connection.getresponse.return_value.status = status
            connection.getresponse.return_value.read.return_value = raw
            with self.subTest(status=status, sample=raw[:30]), patch.object(claude_memory.http.client, "HTTPConnection", return_value=connection), \
                    patch.object(claude_memory, "recheck"):
                with self.assertRaises(home.HomeError):
                    claude_memory.request({"port": 12345}, "/api/processing-status")
                self.assertEqual(connection.request.call_count, 1)
                connection.close.assert_called_once()

    def test_drain_waits_for_active_queued_and_parked_work_without_claiming_generation(self):
        observed = {"pid": 12, "ai": {"lastInteraction": None}}
        values = [{"isProcessing": True, "queueDepth": 2, "parkedSessions": 1},
                  {"isProcessing": False, "queueDepth": 0, "parkedSessions": 0}]
        with patch.object(claude_memory, "request", side_effect=values) as request, \
                patch.object(claude_memory, "health", return_value=observed), \
                patch.object(claude_memory.time, "sleep"), patch.object(claude_memory.time, "monotonic", return_value=0):
            result = claude_memory.drain(self.root, self.root, self.config, self.root / "worker", {"pid": 12})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["status"], "drained")
        self.assertEqual(result["generation_acceptance"], "not_established")

    def test_drain_retains_pending_failure_unknown_and_lost_owner(self):
        value = {"isProcessing": True, "queueDepth": 3, "parkedSessions": 1}
        with patch.object(claude_memory, "request", return_value=value), \
                patch.object(claude_memory, "health", return_value={"pid": 12, "ai": {}}), \
                patch.object(claude_memory, "DRAIN_SECONDS", 0):
            result = claude_memory.drain(self.root, self.root, self.config, self.root / "worker", {"pid": 12})
        self.assertEqual((result["status"], result["timed_out"], result["processing"]), ("pending", True, value))
        with patch.object(claude_memory, "request", return_value={"isProcessing": False, "queueDepth": 0, "parkedSessions": 0}), \
                patch.object(claude_memory, "health", return_value={"pid": 12, "ai": {"lastInteraction": {"success": False, "error": "synthetic inference failure"}}}):
            self.assertEqual(claude_memory.drain(self.root, self.root, self.config, self.root / "worker", {"pid": 12})["status"], "failed")
        for response in ({"isProcessing": False}, {"isProcessing": 0, "queueDepth": 0, "parkedSessions": 0}):
            with patch.object(claude_memory, "request", return_value=response), self.assertRaises(home.HomeError):
                claude_memory.drain(self.root, self.root, self.config, self.root / "worker", {"pid": 12})
        with patch.object(claude_memory, "request", return_value=value), patch.object(claude_memory, "health", return_value=None), \
                self.assertRaisesRegex(home.HomeError, "lost liveness"):
            claude_memory.drain(self.root, self.root, self.config, self.root / "worker", {"pid": 12})

    def test_drain_cli_preserves_nonzero_pending_failed_and_unconfirmed_stop(self):
        for action, status, code in (("drain", "pending", 1), ("drain", "failed", 1), ("drain", "drained", 0),
                                     ("stop", "stop_unconfirmed", 1), ("stop", "stopped", 0)):
            output = io.StringIO()
            with self.subTest(action=action, status=status), patch.object(claude_memory, "invoke", return_value={"status": status}), redirect_stdout(output):
                self.assertEqual(claude_memory.main(["--home", str(self.root), action]), code)
                self.assertEqual(json.loads(output.getvalue()), {"status": status})

    def test_startup_requires_pidfd_before_launch_and_rejects_live_unhealthy_owner(self):
        root, env = claude_memory.settings(self.root, self.config)
        with patch.object(claude_memory, "live_pid", return_value=123), patch.object(claude_memory.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(home.HomeError, "remains alive"):
                claude_memory.foreground_start(self.root, root, self.config, self.root / "bun", self.root / "worker", env)
            launch.assert_not_called()
        native = Mock()
        native.require_support.side_effect = OSError("unsupported kernel")
        with patch.object(claude_memory, "live_pid", return_value=None), patch.object(claude_memory.model_service, "_pidfd", return_value=native), \
                patch.object(claude_memory.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(OSError, "unsupported"):
                claude_memory.foreground_start(self.root, root, self.config, self.root / "bun", self.root / "worker", env)
            launch.assert_not_called()

    def test_foreground_export_launch_is_guarded_and_timeout_signals_only_own_pidfd(self):
        root, env = claude_memory.settings(self.root, self.config)
        child = Mock(pid=123)
        child.poll.return_value = None
        native = Mock()
        native.pidfd_open.return_value = 99
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            config = {**self.config, "claude_memory_port": free.getsockname()[1]}
        with patch.object(claude_memory, "live_pid", return_value=None), patch.object(claude_memory.model_service, "_pidfd", return_value=native), \
                patch.object(claude_memory.subprocess, "Popen", return_value=child) as launch, \
                patch.object(claude_memory.home_entry, "guarded_command", side_effect=lambda _home, args: ["guard", *args]) as guarded, \
                patch.object(claude_memory.home_entry, "consumer", return_value=nullcontext()), \
                patch.object(claude_memory.time, "monotonic", side_effect=[0, 46]), patch.object(claude_memory.os, "close") as close:
            with self.assertRaisesRegex(home.HomeError, "startup deadline"):
                claude_memory.foreground_start(self.root, root, config, self.root / "bun", self.root / "worker", env)
        self.assertEqual(guarded.call_args.args[0], self.root)
        self.assertEqual(launch.call_args.args[0], ["guard", str(self.root / "bun"), "--eval", claude_memory.FOREGROUND, str(self.root / "worker")])
        self.assertEqual(launch.call_args.kwargs["cwd"], root)
        self.assertNotIn("--daemon", launch.call_args.args[0])
        native.pidfd_open.assert_called_once_with(123, 0)
        native.pidfd_send_signal.assert_called_once_with(99, claude_memory.signal.SIGTERM)
        close.assert_called_once_with(99)

    @contextmanager
    def inert_listener(self, *, guarded=True):
        """Real standard-library HTTP child, never Bun/Claude-mem or inference."""
        root, _ = claude_memory.settings(self.root, self.config)
        worker = root / "synthetic-worker.cjs"
        worker.write_text("// inert source marker, never executed")
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            config = {**self.config, "claude_memory_port": free.getsockname()[1]}
        script = '''import http.server,json,os,pathlib,sys
worker,root,port=sys.argv[1:]
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  body=json.dumps({'pid':os.getpid(),'version':'13.29.0','workerPath':worker,'ai':{'provider':'openai-compatible'}}).encode()
  self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
server=http.server.HTTPServer(('127.0.0.1',int(port)),Handler)
pathlib.Path(root,'worker.pid').write_text(json.dumps({'pid':os.getpid(),'port':int(port)}))
print('ready',flush=True)
server.serve_forever()
'''
        python = Path(sys.executable).resolve()
        argv = [str(python), "-u", "-c", script, str(worker), str(root), str(config["claude_memory_port"])]
        if guarded:
            argv = claude_memory.home_entry.guarded_command(self.root, argv)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()), "LANG": "C.UTF-8",
               "CLAUDE_MEM_DATA_DIR": str(root), "CLAUDE_MEM_WORKER_PORT": str(config["claude_memory_port"])}
        native = claude_memory.model_service._pidfd()
        native.require_support()
        child = subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        descriptor = native.pidfd_open(child.pid, 0)
        try:
            self.assertEqual(child.stdout.readline(), b"ready\n")
            observed = claude_memory.health(self.root, root, config, worker)
            yield child, root, config, python, worker, observed
        finally:
            if child.poll() is None:
                native.pidfd_send_signal(descriptor, claude_memory.signal.SIGTERM)
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    native.pidfd_send_signal(descriptor, claude_memory.signal.SIGKILL)
                    child.wait(timeout=3)
            os.close(descriptor)
            child.stdout.close()
            child.stderr.close()

    @unittest.skipUnless(sys.platform == "linux", "Actual proc/flock/PIDFD fixture requires Linux")
    def test_real_child_shared_lease_blocks_exchange_until_exact_pidfd_stop(self):
        with self.inert_listener() as (child, root, config, python, worker, observed):
            proof = claude_memory.worker_proof(self.root, root, config, python, worker, observed, require_lease=True)
            guard = claude_memory.home_entry._load_guard(self.root, config["lifecycle_guard_sha256"])
            with self.assertRaises(ValueError):
                with guard.lease(self.root, expected_sha256=config["lifecycle_guard_sha256"], mode="exclusive"):
                    self.fail("Actual child READ lease was not held")
            self.assertEqual(claude_memory.stop_worker(proof), {"status": "stopped"})
            child.wait(timeout=3)
            with guard.lease(self.root, expected_sha256=config["lifecycle_guard_sha256"], mode="exclusive"):
                self.assertIsNone(claude_memory.live_pid(root))

    @unittest.skipUnless(sys.platform == "linux", "Actual proc/flock/PIDFD fixture requires Linux")
    def test_real_legacy_reader_cannot_be_adopted_for_capture_without_lease(self):
        with self.inert_listener(guarded=False) as (child, root, config, python, worker, observed):
            claude_memory.worker_proof(self.root, root, config, python, worker, observed)
            with self.assertRaisesRegex(ValueError, "READ lease"):
                claude_memory.worker_proof(self.root, root, config, python, worker, observed, require_lease=True)
            self.assertIsNone(child.poll())

    @unittest.skipUnless(sys.platform == "linux", "Actual proc/flock/PIDFD fixture requires Linux")
    def test_real_listener_and_start_identity_mismatch_refuses_without_signal(self):
        with self.inert_listener() as (child, root, config, python, worker, observed):
            with self.assertRaisesRegex(home.HomeError, "ownership differs"):
                claude_memory.worker_proof(self.root, root, {**config, "claude_memory_port": config["claude_memory_port"] + 1}, python, worker, observed)
            proof = claude_memory.worker_proof(self.root, root, config, python, worker, observed)
            proof["process"] = {**proof["process"], "start_ticks": "wrong epoch"}
            with self.assertRaisesRegex(home.HomeError, "lifetime/listener changed"):
                claude_memory.stop_worker(proof)
            self.assertIsNone(child.poll())

    @unittest.skipUnless(sys.platform == "linux", "Actual flock fixture requires Linux")
    def test_real_operation_lock_refuses_racing_admission(self):
        root, _ = claude_memory.settings(self.root, self.config)
        with claude_memory.operation(root):
            with self.assertRaises(BlockingIOError):
                with claude_memory.operation(root):
                    self.fail("Concurrent admission was allowed")


if __name__ == "__main__":
    unittest.main()
