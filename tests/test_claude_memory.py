"""Verify local-only observer configuration before worker dispatch."""
import json
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
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
                   "CLAUDE_MEM_OPENAI_COMPAT_API_KEYS": "ambient-pool"}
        before = (self.root / "memory/claude-mem/settings.json").read_bytes()
        with patch.object(claude_memory, "environment", return_value=dict(ambient)), \
                patch.object(model_service_handoff, "launch_environment", return_value=
                             model_service_handoff.LaunchEnvironment({name: key}, {})) as resolver:
            result = claude_memory.child_environment(self.root, config, required)
        resolver.assert_called_once_with(self.root, config["owned_model_service"])
        self.assertEqual(result["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"], key)
        self.assertEqual(result["CLAUDE_MEM_OPENAI_COMPAT_API_KEYS"], "")
        self.assertEqual(result["CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER"], "")
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
    def worker_fixture(self, startup_key, current_key, *, foreign=False, resolver_error=None, live=True):
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
        original_read, original_resolve = Path.read_bytes, Path.resolve
        state = {"live": live, "commands": [], "environments": [], "searches": []}
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
        def run(command, **kwargs):
            state["commands"].append(command)
            state["environments"].append(kwargs["env"])
            if command[-1] == "stop":
                state["live"] = False
            return "synthetic hook delivered"
        name = config["owned_model_service"]["environment_variable"]
        launch = model_service_handoff.LaunchEnvironment({name: current_key}, {})
        with patch.object(claude_memory, "load", return_value=(self.root, config)), \
                patch.object(claude_memory.platform, "system", return_value="Linux"), \
                patch.object(claude_memory, "worker_paths", return_value=(self.root / "bun", worker)), \
                patch.object(claude_memory, "environment", return_value={"HOME": str(Path.home())}), \
                patch.object(claude_memory, "urlopen", side_effect=urlopen), \
                patch.object(claude_memory, "run", side_effect=run), \
                patch.object(model_service_handoff, "launch_environment", return_value=launch,
                             side_effect=resolver_error) as resolver, \
                patch.object(Path, "read_bytes", read), patch.object(Path, "resolve", resolve):
            yield state, resolver

    def test_current_worker_key_allows_hook_without_start_or_restart(self):
        key = "a" * 64
        with self.worker_fixture(key, key) as (state, _resolver):
            result = claude_memory.invoke(self.root, "hook", {"sessionId": "fictional-session"}, "observation")
        self.assertEqual([command[-3:] for command in state["commands"]], [["hook", "raw", "observation"]])
        self.assertEqual(state["environments"][0]["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"], key)
        self.assertNotIn(key, json.dumps(result))

    def test_rotated_nonce_blocks_adoption_and_capture_without_replay_or_restart(self):
        for action in ("start", "hook"):
            with self.worker_fixture("a" * 64, "b" * 64) as (state, _resolver):
                with self.assertRaisesRegex(home.HomeError, "credential is stale") as error:
                    claude_memory.invoke(self.root, action, {"sessionId": "fictional-session"},
                                         "observation" if action == "hook" else "ordinary query")
                self.assertEqual(state["commands"], [])
                self.assertNotIn("a" * 64, str(error.exception))
                self.assertNotIn("b" * 64, str(error.exception))

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
        self.assertEqual([command[-1] for command in state["commands"]], ["stop"])

    def test_foreign_worker_cannot_stop_even_when_nonce_is_stale(self):
        with self.worker_fixture("a" * 64, "b" * 64, foreign=True) as (state, resolver):
            with self.assertRaisesRegex(home.HomeError, "another data directory"):
                claude_memory.invoke(self.root, "stop")
        resolver.assert_not_called()
        self.assertEqual(state["commands"], [])


if __name__ == "__main__":
    unittest.main()
