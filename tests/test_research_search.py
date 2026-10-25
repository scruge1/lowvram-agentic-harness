"""Transcript-derived cascade failures using synthetic providers; no network."""
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from harness import research_search as search, web_research as web

try:
    import httpx
except ImportError:
    httpx = None


def provider(name, state="ready", credential=None, endpoint=None):
    return {"provider": name, "state": state, "credential": credential, "endpoint": endpoint}


def hit(domain="example.com", title="Python CSV documentation"):
    return {"t": title, "u": "https://" + domain + "/csv", "s": "Python CSV reference"}


def ddg_result():
    return {"hits": [{"title": "Python CSV reference", "url": "https://docs.python.org/csv", "snippet": "Python CSV documentation"}], "status": "ok"}


class CascadeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="research-search-", dir=os.environ.get("RESEARCH_TEST_ROOT"))
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / "owned-home"
        self.home.mkdir()
        (self.home / "state").mkdir()
        (self.home / "home.json").write_text(json.dumps({"schema": "agent-home/v1", "home": str(self.home)}))
        self.coverage = {"provider_budget": 2, "minimum_providers": 2, "minimum_unique_domains": 2,
                         "required_tokens": ["python csv"]}

    def execute(self, selected, policy=None, timeout=10):
        return search.execute("Python CSV reference", timeout, 5, str(self.home), selected, policy)

    def test_actual_quota_failure_shape_switches_to_ddg_then_cools_only_exhausted_provider(self):
        # Historical actual failure: zero pages after a keyed429. Narrow fix:
        # preserve the provider failure, skip missing keys, let DDG answer.
        selected = [provider("searxng", "skipped"), provider("exa", "credential_missing"),
                    provider("brave", credential="synthetic-token"), provider("tavily", "credential_missing"), provider("ddg")]
        with mock.patch.object(search, "_request", return_value=([], "rate_limited")) as request, \
             mock.patch.object(web, "_search_native", return_value=ddg_result()):
            first = self.execute(selected)
        self.assertTrue(first["ok"])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(first["attempts"][2]["status"], "rate_limited")
        state = json.loads(search._path(self.home).read_text())
        self.assertEqual(set(state), {"brave"})
        self.assertNotIn("synthetic-token", json.dumps(first))
        with mock.patch.object(search, "_request") as request, mock.patch.object(web, "_search_native", return_value=ddg_result()):
            second = self.execute(selected)
        request.assert_not_called()
        self.assertEqual(second["attempts"][2]["status"], "cooling_down")
        self.assertTrue(second["ok"])

    def test_disabled_missing_and_retention_hold_make_no_http_request(self):
        selected = [provider("searxng", "endpoint_missing"), provider("exa", "unconfigured"),
                    provider("brave", "retention_hold"), provider("tavily", "credential_missing"), provider("ddg", "skipped")]
        with mock.patch.object(search, "_request") as request, mock.patch.object(web, "_search_native") as ddg:
            result = self.execute(selected)
        request.assert_not_called()
        ddg.assert_not_called()
        self.assertEqual(result["status"], "providers_unavailable")
        self.assertEqual(result["coverage"]["attempted_providers"], 0)

    def test_absent_settings_default_directory_stays_usable_by_real_config_owner(self):
        from harness import research_config
        self.assertFalse((self.home / "state/research").exists())
        research_config.load_settings(self.home)
        with mock.patch.object(web, "_search_native", return_value=ddg_result()):
            self.assertTrue(self.execute([provider("ddg")])["ok"])
        self.assertEqual(research_config.provider_status(self.home)["providers"]["ddg"]["state"], "ready")
        selected_home, selected = search.bindings(self.home)
        self.assertEqual(selected_home, str(self.home))
        self.assertEqual([item["provider"] for item in selected if item["state"] == "ready"], ["ddg"])

    def test_real_config_sensitive_query_abstains_before_any_worker(self):
        from harness import research_config
        research_config.configure_provider(self.home, "exa", "enabled")
        with mock.patch.dict(os.environ, {"EXA_API_KEY": "synthetic-config-token"}), mock.patch.object(web, "_run") as worker:
            result = web.search("synthetic-config-token", home=self.home)
        worker.assert_not_called()
        self.assertEqual(result["status"], "sensitive_query")
        self.assertNotIn("synthetic-config-token", json.dumps(result))

    def test_actual_bounded_worker_handles_all_skipped_configuration_without_network(self):
        from harness import research_config
        if not Path(web.__file__).with_name("research_config.py").is_file():
            self.skipTest("Complete source packet with the separately owned config module is required")
        for name in research_config.ORDER:
            research_config.configure_provider(self.home, name, "skipped")
        result = web.search("synthetic query", home=self.home, timeout=3)
        self.assertEqual(result["status"], "providers_unavailable", result)
        self.assertEqual(result["coverage"]["attempted_providers"], 0)
        self.assertEqual(len(result["attempts"]), 5)
        self.assertEqual(research_config.provider_status(self.home)["providers"]["ddg"]["state"], "skipped")

    def test_brave_unsupported_query_is_skipped_without_spending_request_budget(self):
        selected = [provider("brave", credential="synthetic-token"), provider("ddg")]
        with mock.patch.object(search, "_request") as request, mock.patch.object(web, "_search_native", return_value=ddg_result()):
            result = search.execute("query " * 76, 10, 5, str(self.home), selected)
        request.assert_not_called()
        self.assertEqual(result["attempts"][0]["status"], "query_unsupported")
        self.assertFalse(result["attempts"][0]["attempted"])
        self.assertEqual(result["coverage"]["attempted_providers"], 1)

    def test_missing_keys_do_not_consume_the_two_actual_request_budget(self):
        selected = [provider("searxng", "unconfigured"), provider("exa", "credential_missing"),
                    provider("brave", "retention_hold"), provider("tavily", credential="synthetic-token"), provider("ddg")]
        with mock.patch.object(search, "_request", return_value=([hit()], "ok")), \
             mock.patch.object(web, "_search_native", return_value=ddg_result()):
            result = self.execute(selected, self.coverage)
        self.assertTrue(result["coverage"]["met"])
        self.assertEqual(result["coverage"]["attempted_providers"], 2)
        self.assertEqual(result["coverage"]["contributing_providers"], ["tavily", "ddg"])
        self.assertFalse(result["coverage"]["corroborated"])

    def test_unrelated_results_cannot_satisfy_declared_entity_coverage(self):
        selected = [provider("searxng", endpoint="http://127.0.0.1:8888"), provider("exa", credential="synthetic-token")]
        with mock.patch.object(search, "_request", side_effect=[([hit(title="Pizza delivery") | {"s": "Pizza", "u": "https://pizza.example/"}], "ok"), ([hit()], "ok")]):
            result = self.execute(selected, self.coverage)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "coverage_unmet")
        self.assertEqual(result["coverage"]["contributing_providers"], ["exa"])

    def test_duplicate_urls_keep_original_observations_and_do_not_invent_domain_coverage(self):
        selected = [provider("exa", credential="synthetic-token"), provider("tavily", credential="other-synthetic-token")]
        rows = [[hit() | {"u": "https://www.example.com/csv?utm_source=one"}], [hit()]]
        with mock.patch.object(search, "_request", side_effect=[(item, "ok") for item in rows]):
            result = self.execute(selected, self.coverage)
        self.assertFalse(result["coverage"]["met"])
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(len(result["hits"][0]["observations"]), 2)
        self.assertIn("utm_source", result["hits"][0]["url"])

    def test_provider_failure_and_ambiguous_ddgs_failure_are_not_semantic_empty(self):
        with mock.patch.object(web, "_search_native", side_effect=RuntimeError("No results found. synthetic-token")):
            result = self.execute([provider("ddg")])
        self.assertEqual(result["status"], "search_exhausted")
        self.assertEqual(result["attempts"][0]["status"], "provider_error")
        self.assertNotIn("synthetic-token", json.dumps(result))
        with mock.patch.object(search, "_request", return_value=([], "empty")):
            empty = self.execute([provider("exa", credential="synthetic-token")])
        self.assertEqual(empty["status"], "empty")

    def test_budget_is_not_reset_for_a_fallback_and_timeout_cannot_accept_late_success(self):
        selected = [provider("exa", credential="synthetic-token"), provider("tavily", credential="other-token"), provider("ddg")]
        with mock.patch.object(search, "_request", return_value=([], "provider_error")), mock.patch.object(web, "_search_native") as ddg:
            result = self.execute(selected, self.coverage)
        ddg.assert_not_called()
        self.assertEqual(result["coverage"]["stop_reason"], "provider_budget_exhausted")
        clock = [10.0]
        def late(*_args):
            clock[0] += 4
            return [hit()], "ok"
        with mock.patch.object(search.time, "monotonic", side_effect=lambda: clock[0]), mock.patch.object(search, "_request", side_effect=late):
            result = self.execute(selected, timeout=3)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["hits"], [])

    def test_poisoned_cooldown_is_capped_once_and_unknown_selftest_state_removed(self):
        path = search._path(self.home)
        path.write_text(json.dumps({"brave": {"cooldown_until": 2_800_000_000}, "selftest-A": {"cooldown_until": 9_000_000_000}}))
        with mock.patch.object(search.time, "time", return_value=1000):
            state = search._state(self.home, ["brave", "ddg"], search.time.monotonic() + 2)
        self.assertEqual(state, {"brave": {"cooldown_until": 1000 + search.COOLDOWN_S}})
        with mock.patch.object(search.time, "time", return_value=1200):
            again = search._state(self.home, ["brave", "ddg"], search.time.monotonic() + 2)
        self.assertEqual(again, state)
        self.assertIn("selftest-A", path.with_suffix(".json.bak").read_text())

    def test_corrupt_primary_recovers_bounded_backup_and_redirected_state_refuses(self):
        path = search._path(self.home)
        path.write_bytes(b"{broken")
        path.with_suffix(".json.bak").write_text(json.dumps({"ddg": {"cooldown_until": search.time.time() + 200}}))
        result = search._state(self.home, ["ddg"], search.time.monotonic() + 2)
        self.assertIn("ddg", result)
        self.assertEqual(path.with_suffix(".json.bak").read_bytes(), b"{broken")
        self.assertEqual(json.loads(path.read_text()), result)
        path.write_bytes(b"x" * (search.MAX_STATE_BYTES + 1))
        with self.assertRaises(ValueError):
            self.execute([provider("ddg")])

    def test_echoed_credentials_private_hits_and_invalid_policy_do_not_become_evidence(self):
        rows = [hit() | {"t": "synthetic-token"}, hit() | {"u": "http://127.0.0.1/private"}]
        with mock.patch.object(search, "_request", return_value=(rows, "ok")):
            result = self.execute([provider("exa", credential="synthetic-token")])
        self.assertEqual(result["hits"], [])
        self.assertNotIn("synthetic-token", json.dumps(result))
        with mock.patch.object(search, "_request") as request:
            blocked = search.execute("synthetic-token", 3, 5, str(self.home), [provider("exa", credential="synthetic-token")])
        request.assert_not_called()
        self.assertEqual(blocked["query"], "[redacted]")
        for bad in ({}, {**self.coverage, "minimum_providers": 1}, {**self.coverage, "provider_budget": True}):
            with self.assertRaises(ValueError):
                self.execute([], bad)


@unittest.skipUnless(httpx, "HTTPX native MockTransport dependency")
class NativeProviderTransportTests(unittest.TestCase):
    def run_request(self, name, selected, responder):
        original = httpx.Client
        clients = []
        def client(**kwargs):
            clients.append(kwargs)
            return original(transport=httpx.MockTransport(responder), **kwargs)
        def resolved(url):
            parts = web._public_url(url)
            return parts, parts.hostname, "8.8.8.8"
        with mock.patch.object(httpx, "Client", side_effect=client), mock.patch.object(web, "_resolved_target", side_effect=resolved):
            result = search._request(name, selected, "Python CSV", 5, search.time.monotonic() + 5)
        self.assertFalse(clients[0]["trust_env"])
        self.assertFalse(clients[0]["follow_redirects"])
        return result

    def test_fixed_provider_endpoints_native_headers_and_result_decoding(self):
        for name, host in [("exa", "api.exa.ai"), ("brave", "api.search.brave.com"), ("tavily", "api.tavily.com")]:
            seen = []
            def respond(request):
                seen.append(request)
                row = {"title": "Python CSV", "url": "https://docs.python.org/csv", "text": "reference", "description": "reference", "content": "reference"}
                body = {"web": {"results": [row]}} if name == "brave" else {"results": [row]}
                return httpx.Response(200, json=body)
            result = self.run_request(name, provider(name, credential="synthetic-token", endpoint="https://ignored.invalid"), respond)
            self.assertEqual(result[1], "ok")
            self.assertEqual(seen[0].headers["host"], host)
            self.assertEqual(seen[0].url.host, "8.8.8.8")
            self.assertEqual(seen[0].extensions["sni_hostname"], host)
            if name == "tavily":
                self.assertEqual(seen[0].headers["Authorization"], "Bearer synthetic-token")
                payload = json.loads(seen[0].content)
                self.assertNotIn("api_key", payload)
                self.assertEqual(payload["search_depth"], "basic")
                self.assertIs(payload["include_answer"], False)
                self.assertIs(payload["include_raw_content"], False)
                self.assertIs(payload["auto_parameters"], False)

    def test_redirect_never_forwards_credentials_and_native_response_bound_holds(self):
        seen = []
        def redirect(request):
            seen.append(request)
            return httpx.Response(302, headers={"location": "https://other.example/steal"})
        self.assertEqual(self.run_request("exa", provider("exa", credential="synthetic-token"), redirect), ([], "http_302"))
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.run_request("exa", provider("exa", credential="synthetic-token"),
                                         lambda _r: httpx.Response(429)), ([], "rate_limited"))
        self.assertEqual(self.run_request("exa", provider("exa", credential="synthetic-token"),
                                         lambda _r: httpx.Response(200, content=b"x" * (search.MAX_RESPONSE_BYTES + 1))), ([], "too_large"))

    def test_explicit_owned_searx_endpoint_uses_local_route_without_widening_fetch(self):
        original = httpx.Client
        seen = []
        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={"results": [{"title": "Python CSV", "url": "https://docs.python.org/csv", "content": "reference"}]})
        with mock.patch.object(httpx, "Client", side_effect=lambda **kw: original(transport=httpx.MockTransport(respond), **kw)), \
             mock.patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8888))]):
            result = search._request("searxng", provider("searxng", endpoint="http://127.0.0.1:8888"), "Python CSV", 5, search.time.monotonic() + 5)
        self.assertEqual(result[1], "ok")
        self.assertEqual(seen[0].url.path, "/search")
        self.assertEqual(web.fetch("http://127.0.0.1/")["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
