"""Synthetic failure regressions through the real fallback orchestrator.

Transport injection prevents provider/browser/model requests. Native transport
security/ownership checks have their own tests; these tests never bypass them.
"""
from datetime import datetime, timezone
from email.utils import format_datetime
import base64
import copy
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from harness import research_fetch as fetch, web_research as web


def page(text="Evidence. " * 60, *, status="ok", code=200, content_type="text/html", **extra):
    raw = text.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    response = {"final_url": "https://example.com/final", "status_code": code,
                "content_type": content_type, "cleaned_text_full": text, "cleaned_text": text,
                "raw_truncated": False, "text_truncated": False,
                "raw_content_base64": base64.b64encode(raw).decode(), "raw_content_sha256": digest,
                "full_cleaned_text_sha256": digest, "cleaned_text_sha256": digest,
                "content_supported": content_type in {"text/html", "text/plain"},
                "redirect_chain": [{"url": "https://example.com/final", "status_code": code}],
                "response_headers": {}, "challenge_detected": False}
    response.update(extra)
    return {"schema": "web-research/v1", "ok": status in {"ok", "partial"},
            "status": status, "response": response, "attempts": []}


class Clock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def run_fetch(self, fetcher, url="https://example.com/article", **kwargs):
        return fetch.fetch(url, fetcher=fetcher, clock=self.clock, sleeper=self.clock.sleep, **kwargs)

    def test_static_success_retains_exact_native_raw_and_redirect_provenance(self):
        native = page()
        transport = Mock(return_value=native)
        result = self.run_fetch(transport)
        self.assertTrue(result["ok"])
        self.assertEqual(result["content_scope"], "full_extraction")
        self.assertTrue(result["requested_source_complete"])
        self.assertIs(result["selected_native"], native)
        self.assertIs(result["response"], native["response"])
        self.assertEqual(result["selected_attempt"], 0)
        self.assertEqual(result["attempts"][0]["native"]["response"]["raw_content_base64"], native["response"]["raw_content_base64"])
        transport.assert_called_once()

    def native_long_page(self):
        # Real native artifact constructor, no network or optional HTML parser.
        raw = ("Quoted CSV field behavior is source evidence.\n" * 700).encode()
        response = SimpleNamespace(encoding="utf-8", status_code=200, headers={"content-type": "text/plain; charset=utf-8"})
        artifact = web._artifact("https://example.com/article", response, raw, [], 20000)
        return {"schema": "web-research/v1", "ok": True, "status": "partial", "response": artifact, "attempts": []}

    def test_complete_retained_capture_keeps_short_native_view_and_mining_prefix(self):
        from harness import research_mining as mining, research_runtime as runtime
        native = self.native_long_page()
        original = copy.deepcopy(native)
        result = self.run_fetch(Mock(return_value=native))
        self.assertTrue(result["requested_source_complete"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(native, original)
        self.assertIs(result["selected_native"], native)
        self.assertEqual(native["status"], "partial")
        self.assertTrue(native["response"]["text_truncated"])
        self.assertEqual(len(native["response"]["cleaned_text"]), 20000)
        self.assertGreater(len(result["text"]), 20000)
        record = {"action": "fetch", "project": {"project_id": "p_fixture"}, "payload": result}
        key = "sha256:" + hashlib.sha256(runtime.wire(record)).hexdigest()
        projected = runtime.projection(record, key)
        self.assertLessEqual(len(runtime.wire(projected)), runtime.MODEL_BYTES)
        self.assertLessEqual(len(projected["text"]), 8192)
        self.assertIsNotNone(projected["next_offset"])
        store = SimpleNamespace(project=record["project"], get=lambda artifact_id: record)
        plan = mining.prepare({"query": "What is the CSV field behavior?", "extraction_schema": ["behavior"],
                               "artifact_ids": [key]}, store, {"id": "fixture-only-no-inference"},
                              runtime.text_view, runtime.wire, runtime.digest)
        source = plan["sources"][0]
        self.assertEqual(source["input_chars"], mining.PAGE_CHARS)
        self.assertTrue(source["input_truncated"])
        self.assertEqual(source["source_chars"], len(result["text"]))
        self.assertEqual(source["text"], result["text"][:14000])

    def test_unproven_retained_capture_never_becomes_complete(self):
        cases = [
            {"raw_truncated": True}, {"content_supported": False}, {"challenge_detected": True},
            {"status_code": 500}, {"full_cleaned_text_sha256": None},
            {"full_cleaned_text_sha256": "0" * 64}, {"cleaned_text_sha256": "0" * 64},
            {"raw_content_sha256": "0" * 64}, {"raw_content_base64": "invalid!"},
            {"cleaned_text": "not a prefix", "cleaned_text_sha256": hashlib.sha256(b"not a prefix").hexdigest()},
            {"text_truncated": False},
            {"cleaned_text_full": ""}, {"cleaned_text_full": " " * 25000},
        ]
        for changed in cases:
            with self.subTest(changed=list(changed)):
                native = self.native_long_page()
                native["response"].update(changed)
                result = self.run_fetch(Mock(return_value=native))
                self.assertFalse(result["requested_source_complete"])

    def test_missing_hashes_do_not_promote_an_untruncated_legacy_packet(self):
        for field in ("full_cleaned_text_sha256", "cleaned_text_sha256", "raw_content_sha256"):
            with self.subTest(field=field):
                native = page()
                del native["response"][field]
                result = self.run_fetch(Mock(return_value=native))
                self.assertEqual(result["status"], "partial")
                self.assertFalse(result["requested_source_complete"])

    def test_timeout_after_budget_retains_failure_without_more_calls(self):
        def timeout(url, **kwargs):
            self.clock.value += kwargs["timeout"]
            return {"ok": False, "status": "timeout"}
        transport = Mock(side_effect=timeout)
        result = self.run_fetch(transport, timeout=3, allow_archive=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(len(result["attempts"]), 1)
        transport.assert_called_once()

    def test_transient_retry_then_success_preserves_failure_and_remaining_timeout(self):
        native = page()
        transport = Mock(side_effect=[{"ok": False, "status": "network_error"}, native])
        result = self.run_fetch(transport, timeout=5)
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_attempt"], 1)
        self.assertEqual(result["attempts"][0]["native"]["status"], "network_error")
        self.assertEqual(self.clock.sleeps, [0.5])
        self.assertEqual(transport.call_args.kwargs["timeout"], 4.5)

    def test_rate_limit_honors_numeric_retry_after(self):
        rate = page("", status="rate_limited", code=429, response_headers={"retry-after": "2"})
        result = self.run_fetch(Mock(side_effect=[rate, page()]), timeout=5)
        self.assertTrue(result["ok"])
        self.assertEqual(self.clock.sleeps, [2])
        self.assertIs(result["attempts"][0]["native"], rate)

    def test_retry_after_date_and_capped_or_invalid_delays_never_retry_early(self):
        date = format_datetime(datetime.fromtimestamp(1003, timezone.utc), usegmt=True)
        rate = page("", status="rate_limited", code=429, response_headers={"retry-after": date})
        result = self.run_fetch(Mock(side_effect=[rate, page()]), timeout=10, wall_time=lambda: 1000)
        self.assertTrue(result["ok"])
        self.assertEqual(self.clock.sleeps, [3])
        for value in ("300", "bad-date"):
            transport = Mock(return_value=page("", status="rate_limited", code=429, response_headers={"retry-after": value}))
            result = self.run_fetch(transport, timeout=60, allow_archive=True)
            self.assertFalse(result["ok"])
            self.assertEqual(len(result["attempts"]), 1)
            transport.assert_called_once()

    def test_exhausted_5xx_is_explicit_and_does_not_hide_outage_with_archive(self):
        transport = Mock(return_value=page("", status="http_error", code=503))
        result = self.run_fetch(transport, timeout=20, allow_archive=True)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["attempts"]), 3)
        self.assertIn("retries exhausted", result["reason"])
        self.assertTrue(all("web.archive.org" not in call.args[0] for call in transport.call_args_list))

    def test_generic_403_auth_challenge_and_policy_refusal_never_launch_bypass(self):
        failures = [page("", status="blocked", code=403),
                    page("", status="http_error", code=401),
                    page("", status="challenge", challenge_detected=True),
                    {"ok": False, "status": "blocked", "reason": "Unavailable public destination"}]
        for failure in failures:
            transport, browser = Mock(return_value=failure), Mock()
            result = self.run_fetch(transport, timeout=60, allow_archive=True, allow_browser=True, renderer=browser)
            self.assertFalse(result["ok"])
            transport.assert_called_once()
            browser.assert_not_called()

    def test_scholarly_candidates_use_exact_host_and_keep_legacy_id_version(self):
        choices = fetch.candidates("https://arxiv.org/pdf/math/0301234v2.pdf")
        self.assertEqual([p["url"] for p in choices], ["https://ar5iv.org/abs/math/0301234v2",
                         "https://arxiv.org/pdf/math/0301234v2.pdf", "https://arxiv.org/abs/math/0301234v2"])
        for url in ("https://arxiv.org.example.com/pdf/2401.12345", "https://example.com/arxiv.org/pdf/2401.12345"):
            self.assertEqual(fetch.candidates(url), [{"url": url, "kind": "original"}])

    def test_arxiv_403_and_pdf_failure_can_yield_only_an_explicit_abstract(self):
        transport = Mock(side_effect=[page("", status="blocked", code=403),
                                     page("", status="unsupported_content", content_type="application/pdf"), page()])
        result = self.run_fetch(transport, url="https://arxiv.org/pdf/2401.12345v2")
        self.assertTrue(result["ok"])
        self.assertEqual((result["selected_kind"], result["content_scope"], result["status"]), ("abstract", "abstract_only", "partial"))
        self.assertFalse(result["requested_source_complete"])
        self.assertEqual(result["selected_attempt"], 2)
        self.assertEqual(result["attempts"][0]["native"]["response"]["status_code"], 403)

    def test_scholarly_html_is_substitute_evidence_not_original_complete_work(self):
        result = self.run_fetch(Mock(return_value=page()), url="https://arxiv.org/abs/2401.12345")
        self.assertEqual((result["content_scope"], result["status"]), ("scholarly_html", "partial"))
        self.assertFalse(result["requested_source_complete"])

    def test_wayback_requires_opt_in_and_snapshot_is_partial(self):
        missing = page("", status="http_error", code=404)
        transport = Mock(side_effect=[missing, page()])
        result = self.run_fetch(transport, allow_archive=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["content_scope"], "archived_snapshot")
        self.assertFalse(result["requested_source_complete"])
        self.assertEqual(transport.call_args.args[0], "https://web.archive.org/web/2id_/https://example.com/article")
        transport = Mock(return_value=missing)
        result = self.run_fetch(transport)
        transport.assert_called_once()
        self.assertFalse(result["ok"])

    def test_signed_or_query_urls_are_not_disclosed_to_archive(self):
        for url in ("https://example.com/article?token=opaque", "https://example.com/article#section"):
            self.assertEqual(len(fetch.candidates(url, allow_archive=True)), 1)
        with self.assertRaises(ValueError):
            fetch.candidates("http://127.0.0.1/private", allow_archive=True)

    def test_js_empty_and_thin_html_use_only_guarded_render_with_cleanup_reserve(self):
        for text in ("", "Application shell"):
            with self.subTest(text=text):
                self.clock.value = 0
                native = page(text, status="empty_extraction" if not text else "ok")
                browser = Mock(return_value={"ok": True, "status": "ok", "page_url": "https://example.com/rendered",
                                            "document": {"text": "JS content", "truncated": True}})
                result = self.run_fetch(Mock(return_value=native), timeout=60, allow_browser=True, renderer=browser)
                self.assertEqual(browser.call_args.kwargs, {"timeout": 30.0, "max_chars": 20000})
                self.assertEqual(result["selected_attempt"], 1)
                self.assertEqual(result["content_scope"], "captured_browser_window")
                self.assertEqual(result["status"], "partial")
                self.assertFalse(result["requested_source_complete"])
                self.assertIsNone(result["response"])

    def test_browser_is_not_started_without_full_budget_or_for_oversize_source(self):
        for native in (page("", status="empty_extraction"), page("", status="too_large", raw_truncated=True)):
            browser = Mock()
            result = self.run_fetch(Mock(return_value=native), timeout=30, allow_browser=True, renderer=browser)
            browser.assert_not_called()
            self.assertFalse(result["ok"])
        result = self.run_fetch(Mock(return_value=page("short shell")), timeout=30, allow_browser=True, renderer=Mock())
        self.assertEqual((result["content_scope"], result["status"]), ("thin_extraction", "partial"))

    def test_slow_static_shell_reserves_meaningful_browser_work_and_full_settlement(self):
        native = page("Application shell", status="empty_extraction")

        def slow_static(url, **kwargs):
            self.assertEqual(kwargs["timeout"], 19.75)
            self.clock.value += kwargs["timeout"]
            return native

        def render(url, **kwargs):
            self.assertGreaterEqual(kwargs["timeout"], fetch.BROWSER_MINIMUM_WORK)
            self.assertEqual(self.clock() + kwargs["timeout"] + fetch.BROWSER_SETTLEMENT_RESERVE, 60)
            # Use almost all declared work and the full worst-case settlement.
            self.clock.value += kwargs["timeout"] - 1 + fetch.BROWSER_SETTLEMENT_RESERVE
            return {"schema": "web-browser/v1", "ok": True, "status": "partial",
                    "document": {"text": "Synthetic JS evidence", "truncated": True}}

        result = self.run_fetch(slow_static, timeout=60, allow_browser=True, renderer=render)
        self.assertTrue(result["ok"])
        self.assertEqual(result["elapsed_seconds"], 59)
        self.assertTrue(result["budget"]["browser_reserved"])
        self.assertEqual(result["budget"]["static_phase_seconds"], 19.75)
        self.assertEqual([item["mode"] for item in result["attempts"]], ["fetch", "render"])
        self.assertIs(result["attempts"][0]["native"], native)
        self.assertEqual(result["selected_native"]["schema"], "web-browser/v1")

    def test_static_timeout_does_not_consume_reserved_phase_or_trigger_unvalidated_browser(self):
        def timeout(url, **kwargs):
            self.clock.value += kwargs["timeout"]
            return {"ok": False, "status": "timeout"}

        transport, browser = Mock(side_effect=timeout), Mock()
        result = self.run_fetch(transport, timeout=60, allow_browser=True, renderer=browser)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "timeout")
        self.assertIn("Retry deferred", result["reason"])
        self.assertEqual(result["elapsed_seconds"], 19.75)
        self.assertEqual(len(result["attempts"]), 1)
        transport.assert_called_once()
        browser.assert_not_called()

    def test_noncompliant_slow_static_transport_cannot_admit_starved_browser(self):
        def late_shell(url, **kwargs):
            self.clock.value += 26.339  # Retained normal-path failure timing.
            return page("Application shell", status="empty_extraction")

        browser = Mock()
        result = self.run_fetch(late_shell, timeout=60, allow_browser=True, renderer=browser)
        browser.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertIn("minimum render work", result["attempts"][0]["browser_hold"])
        self.assertEqual(result["attempts"][0]["status"], "empty_extraction")

    def test_explicit_larger_budget_preserves_slow_success_without_changing_default(self):
        def slow_static(url, **kwargs):
            self.assertEqual(kwargs["timeout"], 30)
            self.clock.value += 26.339
            return page("Application shell", status="empty_extraction")

        def render(url, **kwargs):
            self.assertEqual(kwargs["timeout"], 40)
            self.clock.value += 40 + fetch.BROWSER_SETTLEMENT_RESERVE
            return {"ok": True, "status": "partial", "document": {"text": "Synthetic JS evidence"}}

        result = self.run_fetch(slow_static, timeout=120, allow_browser=True, renderer=render)
        self.assertTrue(result["ok"])
        self.assertLess(result["elapsed_seconds"], 120)
        self.assertEqual(result["content_scope"], "captured_browser_window")
        self.assertFalse(result["requested_source_complete"])

    def test_insufficient_browser_budget_retains_static_path_and_explicit_hold(self):
        transport, browser = Mock(return_value=page("", status="empty_extraction")), Mock()
        result = self.run_fetch(transport, timeout=39, allow_browser=True, renderer=browser)
        self.assertFalse(result["budget"]["browser_reserved"])
        self.assertEqual(transport.call_args.kwargs["timeout"], 30)
        self.assertIn("minimum render work", result["attempts"][0]["browser_hold"])
        browser.assert_not_called()

    def test_static_only_requests_keep_their_existing_budget(self):
        transport = Mock(return_value=page())
        result = self.run_fetch(transport, timeout=60)
        self.assertTrue(result["ok"])
        self.assertFalse(result["budget"]["browser_reserved"])
        self.assertEqual(transport.call_args.kwargs["timeout"], 30)

    def test_opted_in_archive_uses_remaining_time_without_unused_browser_reserve(self):
        def transport(url, **kwargs):
            if "web.archive.org" not in url:
                self.clock.value += kwargs["timeout"]
                return page("", status="http_error", code=404)
            self.assertEqual(kwargs["timeout"], 30)
            self.clock.value += 25
            return page()

        browser = Mock()
        result = self.run_fetch(transport, timeout=60, allow_archive=True, allow_browser=True, renderer=browser)
        self.assertTrue(result["ok"])
        self.assertEqual(result["content_scope"], "archived_snapshot")
        self.assertEqual(result["elapsed_seconds"], 44.75)
        browser.assert_not_called()

    def test_browser_cleanup_uncertain_or_late_result_never_becomes_success(self):
        initial = Mock(return_value=page("", status="empty_extraction"))
        browser = Mock(return_value={"ok": False, "status": "cleanup_uncertain"})
        result = self.run_fetch(initial, timeout=60, allow_archive=True, allow_browser=True, renderer=browser)
        self.assertEqual(result["status"], "cleanup_uncertain")
        self.assertFalse(result["ok"])

        def late(url, **kwargs):
            self.clock.value += 61
            return {"ok": True, "status": "ok", "document": {"text": "late"}}
        result = self.run_fetch(initial, timeout=60, allow_browser=True, renderer=late)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(len(result["attempts"]), 2)
        self.assertFalse(result["ok"])

    def test_exception_text_is_not_copied_into_attempts(self):
        result = self.run_fetch(Mock(side_effect=RuntimeError("PRIVATE-EXCEPTION-BODY")))
        self.assertNotIn("PRIVATE-EXCEPTION-BODY", str(result))
        self.assertEqual(result["attempts"][0]["native"]["error_type"], "RuntimeError")

    def test_cumulative_native_packets_stop_with_explicit_custody_limit(self):
        native = page("", status="http_error", code=503, raw_content_base64="A" * (9 * 1024 * 1024))
        transport = Mock(return_value=native)
        result = self.run_fetch(transport, timeout=30, max_bytes=8_388_608)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "evidence_limit")
        self.assertLessEqual(len(fetch._wire(result)), fetch.MAX_EVIDENCE_BYTES)
        self.assertEqual(len(result["attempts"]), 3)
        self.assertIs(result["attempts"][0]["native"], native)
        marker = result["attempts"][-1]
        self.assertIsNone(marker["native"])
        self.assertGreater(marker["omitted_native"]["bytes"], 9 * 1024 * 1024)
        self.assertEqual(len(marker["omitted_native"]["sha256"]), 64)
        self.assertEqual(marker["omitted_native"]["raw_content_sha256"], native["response"]["raw_content_sha256"])

    def test_selected_alias_duplicates_count_against_real_store_budget(self):
        native = page(raw_content_base64="A" * (9 * 1024 * 1024))
        result = self.run_fetch(Mock(return_value=native), max_bytes=8_388_608)
        self.assertEqual(result["status"], "evidence_limit")
        self.assertFalse(result["ok"])
        self.assertEqual(result["withheld_selection_attempt"], 0)
        self.assertIs(result["attempts"][0]["native"], native)
        self.assertIsNone(result["selected_native"])
        self.assertIsNone(result["response"])
        self.assertLessEqual(len(fetch._wire(result)), fetch.MAX_EVIDENCE_BYTES)

    def test_smaller_transport_caps_follow_remaining_cumulative_budget(self):
        native = page("", status="http_error", code=503)
        with patch.object(fetch, "MAX_EVIDENCE_BYTES", 65536), patch.object(fetch, "MARKER_HEADROOM", 4096):
            transport = Mock(side_effect=[native, page()])
            result = self.run_fetch(transport)
            self.assertTrue(result["ok"])
            self.assertLess(transport.call_args.kwargs["max_bytes"], transport.call_args_list[0].kwargs["max_bytes"])


if __name__ == "__main__":
    unittest.main()
