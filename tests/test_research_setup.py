"""Synthetic local setup controls. No accounts, keys, provider or model calls."""
from contextlib import redirect_stderr, redirect_stdout
import getpass
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings

from harness import research_config as config, research_setup as setup


class ResearchSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / "home"
        self.home.mkdir(mode=0o700)
        (self.home / "state").mkdir(mode=0o700)
        (self.home / "home.json").write_text(json.dumps({"schema": "agent-home/v1", "home": str(self.home)}))
        self.secret = "synthetic-token-UNIQUE-never-output"

    def enable(self, provider="exa", **kwargs):
        return config.configure_provider(self.home, provider, "enabled", **kwargs)

    def test_absent_and_unconfigured_never_adopt_ambient_credentials(self):
        ambient = {"EXA_API_KEY": self.secret, "BRAVE_API_KEY": self.secret,
                   "TAVILY_API_KEY": self.secret, "SEARXNG_URL": "http://127.0.0.1:8888"}
        view = config.provider_status(self.home, ambient)
        self.assertEqual(view["providers"]["ddg"]["state"], "ready")
        for name in config.ORDER[:-1]:
            self.assertEqual(view["providers"][name]["state"], "unconfigured")
        self.assertFalse((self.home / "state/research").exists())

    def test_enabled_store_env_precedence_skip_revisit_and_remove(self):
        self.enable(credential=self.secret)
        self.assertEqual(config.resolve_provider(self.home, "exa", {}).credential, self.secret)
        self.assertEqual(config.resolve_provider(self.home, "exa", {"EXA_API_KEY": "synthetic-override"}).credential, "synthetic-override")
        config.configure_provider(self.home, "exa", "skipped")
        held = config.resolve_provider(self.home, "exa", {"EXA_API_KEY": self.secret})
        self.assertEqual((held.state, held.credential), ("skipped", None))
        self.enable()
        self.assertEqual(config.resolve_provider(self.home, "exa", {}).credential, self.secret)
        config.configure_provider(self.home, "exa", "skipped", remove_credential=True)
        self.enable()
        self.assertEqual(config.resolve_provider(self.home, "exa", {}).state, "credential_missing")

    def test_status_repr_and_cli_never_emit_credentials_or_claim_testing(self):
        self.enable(credential=self.secret)
        result = config.resolve_provider(self.home, "exa", {})
        self.assertNotIn(self.secret, repr(result))
        with self.assertRaises(TypeError):
            json.dumps(result)
        self.assertNotIn(self.secret, json.dumps(config.provider_status(self.home, {})))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = setup.main(["--home", str(self.home), "status"])
        self.assertEqual(code, 0)
        self.assertNotIn(self.secret, out.getvalue() + err.getvalue())
        self.assertFalse(json.loads(out.getvalue())["providers"]["exa"]["tested"])

    def test_brave_retention_covers_all_persistence_and_can_be_revoked(self):
        self.enable("brave", credential=self.secret)
        self.assertEqual(config.resolve_provider(self.home, "brave", {}).state, "retention_hold")
        self.assertTrue(config.provider_status(self.home, {})["providers"]["brave"]["credential_present"])
        self.enable("brave", retention_acknowledged=True)
        ready = config.resolve_provider(self.home, "brave", {})
        self.assertEqual((ready.state, ready.rights_source), ("ready", config.RIGHTS_SOURCE))
        self.enable("brave", retention_acknowledged=False)
        self.assertEqual(config.resolve_provider(self.home, "brave", {}).state, "retention_hold")
        self.assertIn("native session history", config.CATALOG["brave"]["note"])

    def test_endpoint_is_operator_setting_not_request_data(self):
        self.enable("searxng")
        self.assertEqual(config.resolve_provider(self.home, "searxng", {}).state, "endpoint_missing")
        self.enable("searxng", endpoint="http://127.0.0.1:8888/")
        self.assertEqual(config.resolve_provider(self.home, "searxng", {}).endpoint, "http://127.0.0.1:8888")
        for value in ("https://user:password@example.test", "https://example.test/?key=hidden", "file:///tmp/query", "http://example.test:bad"):
            with self.subTest(value=value), self.assertRaises(config.ConfigError):
                self.enable("searxng", endpoint=value)

    def test_wrong_home_binding_and_unexpected_fields_are_refused_without_values(self):
        self.enable(credential=self.secret)
        path = self.home / "state/research/providers.json"
        previous = path.read_bytes()
        for mutate in (lambda value: value.update(home="foreign-home"),
                       lambda value: value["providers"]["exa"].update(secret=self.secret),
                       lambda value: value["providers"]["exa"].update(state=[])):
            value = json.loads(previous)
            mutate(value)
            path.write_text(json.dumps(value))
            with self.assertRaises(config.ConfigError) as caught:
                config.load_settings(self.home)
            self.assertNotIn(self.secret, str(caught.exception))
        path.write_bytes(previous)
        auth = self.home / "state/research/auth.json"
        auth.write_text('{"synthetic-secret-in-bad-json":"' + self.secret)
        with self.assertRaises(config.ConfigError) as caught:
            config.resolve_provider(self.home, "exa", {})
        self.assertNotIn(self.secret, str(caught.exception))

    def test_concurrent_file_change_is_not_overwritten(self):
        self.enable(credential=self.secret)
        path = self.home / "state/research/providers.json"
        before = path.read_bytes()
        real_read = config._read
        calls = 0

        def changed(target):
            nonlocal calls
            calls += 1
            if calls == 2:
                target.write_bytes(before + b" ")
            return real_read(target)

        with patch.object(config, "_read", side_effect=changed), self.assertRaisesRegex(config.ConfigError, "Concurrent"):
            config._replace(path, json.loads(before), before)
        self.assertEqual(path.read_bytes(), before + b" ")
        self.assertEqual(list(path.parent.glob(".settings-*")), [])

    def test_home_identity_drift_prevents_auth_and_config_publication(self):
        self.enable(credential=self.secret)
        root = self.home / "state/research"
        before = {name: (root / name).read_bytes() for name in ("auth.json", "providers.json")}
        real_auth = config._auth

        def drift(home, raw):
            (home / "home.json").write_text(json.dumps({"schema": "agent-home/v1", "home": "foreign"}))
            return real_auth(home, raw)

        with patch.object(config, "_auth", side_effect=drift), self.assertRaises(config.ConfigError):
            self.enable(credential="synthetic-replacement")
        self.assertEqual(before, {name: (root / name).read_bytes() for name in before})

    def test_competing_setup_lock_holds_without_replay(self):
        self.enable(credential=self.secret)
        directory = self.home / "state/research"
        with config._locked(directory), self.assertRaisesRegex(config.ConfigError, "busy"):
            config.configure_provider(self.home, "exa", "skipped")
        self.assertEqual(config.resolve_provider(self.home, "exa", {}).state, "ready")

    def test_owner_permissions_and_redirected_auth_are_refused(self):
        self.enable(credential=self.secret)
        path = self.home / "state/research/auth.json"
        config._owned(path)
        if os.name != "nt":
            path.chmod(0o644)
            with self.assertRaisesRegex(config.ConfigError, "owner-only"):
                config.resolve_provider(self.home, "exa", {})
            path.chmod(0o600)
        alias = path.with_suffix(".alias")
        try:
            alias.symlink_to(path)
        except OSError:
            self.skipTest("Native symbolic links unavailable")
        raw = path.read_bytes()
        path.unlink()
        path.symlink_to(alias)
        with self.assertRaises((config.ConfigError, OSError)):
            config.resolve_provider(self.home, "exa", {})
        self.assertNotIn(self.secret, repr(config.ProviderResolution("exa", "credential_missing")))
        self.assertTrue(raw)

    def test_no_tty_refuses_before_prompt_or_write(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(setup.sys.stdin, "isatty", return_value=False), patch.object(setup.getpass, "getpass") as prompt:
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(setup.main(["--home", str(self.home), "setup"]), 2)
        prompt.assert_not_called()
        self.assertFalse((self.home / "state/research").exists())

    def test_accidental_key_argument_is_not_repeated_in_parser_error(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = setup.main(["--home", str(self.home), "setup", "--api-key", self.secret])
        self.assertEqual(code, 2)
        self.assertNotIn(self.secret, out.getvalue() + err.getvalue())
        self.assertFalse((self.home / "state/research").exists())

    def test_getpass_echo_fallback_aborts_without_saving(self):
        def fallback(*args, **kwargs):
            warnings.warn("echo fallback", getpass.GetPassWarning)
            return self.secret
        with patch.object(setup, "_terminal"), patch.object(setup.getpass, "getpass", side_effect=fallback):
            with self.assertRaisesRegex(config.ConfigError, "no key was saved"):
                setup.masked_key()
        self.assertFalse((self.home / "state/research").exists())

    def test_guided_skip_revisit_and_masked_entry_do_not_echo_key(self):
        output = io.StringIO()
        with patch.object(setup, "_terminal"), patch("builtins.input", return_value="s"), redirect_stdout(output):
            setup.guided(self.home, "tavily")
        self.assertEqual(config.resolve_provider(self.home, "tavily", {}).state, "skipped")
        with patch.object(setup, "_terminal"), patch("builtins.input", return_value="e"), \
                patch.object(setup.getpass, "getpass", return_value=self.secret), redirect_stdout(output):
            setup.guided(self.home, "tavily")
        self.assertEqual(config.resolve_provider(self.home, "tavily", {}).credential, self.secret)
        self.assertNotIn(self.secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
