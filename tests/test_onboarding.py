"""Actual bounded local metadata discovery, without any inference POST."""
import json
import contextlib
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest import mock

from harness import onboarding
from harness.home import HomeError
from harness import home


class DiscoveryServer(ThreadingHTTPServer):
    daemon_threads = True


class LocalMetadataHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.server.observed.append({"method": "GET", "path": self.path,
                                     "authorization": self.headers.get("Authorization")})
        route = self.server.route
        if route == "redirect":
            self.send_response(302)
            self.send_header("Location", "https://example.org/should-not-be-contacted")
            self.end_headers()
            return
        if route == "unauthorized":
            self.send_response(401)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if route == "html" else "application/json")
        self.end_headers()
        if route == "slow":
            try:
                for _ in range(80):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            return
        bodies = {"models": {"data": [{"id": "test-local-model"}, {"id": "remote:cloud"}]},
                  "empty": {"data": []}, "invalid": {"models": ["not-the-wire-format"]},
                  "bad_id": {"data": [{"id": "invalid\nidentity"}]},
                  "many": {"data": [{"id": str(i)} for i in range(onboarding.MAX_MODELS + 1)]}}
        if route == "oversized":
            body = b" " * (onboarding.MAX_RESPONSE_BYTES + 1)
        elif route == "malformed":
            body = b'{"data": ['
        else:
            body = json.dumps(bodies.get(route, {"page": "not-a-model-list"})).encode()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_POST(self):
        self.server.observed.append({"method": "POST", "path": self.path})
        self.send_error(405)


class OnboardingTests(unittest.TestCase):
    def service(self, route):
        server = DiscoveryServer(("127.0.0.1", 0), LocalMetadataHandler)
        server.route, server.observed = route, []
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.addCleanup(cleanup)
        return f"http://127.0.0.1:{server.server_port}/v1", server

    def test_real_get_no_credentials_proxy_or_inference_and_no_qualification(self):
        url, server = self.service("models")
        with mock.patch.dict(os.environ, {"HARNESS_API_KEY": "must-not-leave-process",
                                          "HTTP_PROXY": "http://127.0.0.1:1",
                                          "http_proxy": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}):
            result = onboarding.probe_service(url, timeout=5)
        self.assertEqual(result["status"], "discovered")
        self.assertEqual(result["authority"], "discovery_only")
        self.assertEqual(result["model_requests"], 0)
        self.assertEqual(server.observed, [{"method": "GET", "path": "/v1/models", "authorization": None}])
        self.assertEqual(result["models"][0]["inference_locality"], "not_verified")
        self.assertTrue(result["models"][1]["remote_name_hint"])
        self.assertEqual(len(result["response_sha256"]), 64)

    def test_redirect_is_not_followed(self):
        url, server = self.service("redirect")
        result = onboarding.probe_service(url, timeout=5)
        self.assertEqual(result["status"], "redirect_refused")
        self.assertEqual(len(server.observed), 1)

    def test_typed_real_http_and_protocol_failures(self):
        for route, status in [("empty", "empty"), ("unauthorized", "http_error"),
                              ("html", "invalid_response"), ("invalid", "invalid_response"),
                              ("bad_id", "invalid_response"), ("malformed", "invalid_response"),
                              ("many", "too_many_models"), ("oversized", "response_too_large")]:
            with self.subTest(route=route):
                url, _server = self.service(route)
                self.assertEqual(onboarding.probe_service(url, timeout=5)["status"], status)

    def test_whole_deadline_stops_slow_drip(self):
        url, _server = self.service("slow")
        started = time.monotonic()
        result = onboarding.probe_service(url, timeout=0.6)
        self.assertEqual(result["status"], "timeout")
        self.assertLess(time.monotonic() - started, 2.5)

    def test_cloud_and_credential_urls_refused_before_worker(self):
        with mock.patch.object(onboarding.subprocess, "run") as worker:
            for url in ["https://example.org/v1", "https://user:secret@127.0.0.1/v1",
                        "http://127.0.0.1/v1?api_key=secret"]:
                with self.subTest(url=url), self.assertRaises(HomeError):
                    onboarding.probe_service(url)
            worker.assert_not_called()

    def test_inventory_observes_selected_volume_without_home_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "Agent home with spaces" / "new"
            hardware = {"gpu": {"available": False}, "ram": {"total_gb": None}}
            with mock.patch.object(onboarding.hardware_probe, "summary", return_value=hardware):
                result = onboarding.inventory(target)
            self.assertFalse(target.exists())
            self.assertEqual(result["hardware"], hardware)
            self.assertEqual(result["changes"], [])
            self.assertEqual(result["qualification"], "inventory_only")
            self.assertGreater(result["storage"]["free_bytes"], 0)

    def test_discovery_deduplicates_and_retains_unqualified_results(self):
        url, server = self.service("models")
        result = onboarding.discover(services=[url, url], timeout=5, total_timeout=6)
        self.assertEqual(len(server.observed), 1)
        self.assertEqual(len(result["services"]), 1)
        self.assertEqual(result["configuration_changes"], [])
        self.assertEqual(result["model_requests"], 0)

    def test_timeout_and_service_limits_refuse_without_network(self):
        for value in [True, float("nan"), float("inf"), -1, 0, 61, "5"]:
            with self.subTest(value=value), self.assertRaises(onboarding.OnboardingError):
                onboarding.discover(timeout=value)
        with self.assertRaises(onboarding.OnboardingError):
            onboarding.discover(services=["http://127.0.0.1/v1"] * 9)

    def test_total_discovery_deadline_does_not_probe_remaining_services(self):
        slow, _server = self.service("slow")
        fast, fast_server = self.service("models")
        result = onboarding.discover(services=[slow, fast], timeout=0.6, total_timeout=0.6)
        self.assertEqual([item["status"] for item in result["services"]], ["timeout", "not_attempted"])
        self.assertEqual(fast_server.observed, [])

    def test_cli_rejects_remote_url_with_plain_error_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "-B", str(Path(onboarding.__file__).resolve()),
                                     "discover", "--base-url", "https://example.org/v1"],
                                    cwd=temporary, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Onboarding:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_existing_home_cli_inspects_before_a_home_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "not-created"
            with mock.patch.object(onboarding.hardware_probe, "summary", return_value={"gpu": {}, "ram": {}}), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                status = home.main(["onboard", "inspect", "--destination", str(destination)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["qualification"], "inventory_only")
            self.assertFalse(destination.exists())

    def test_existing_cli_metadata_discovery_does_not_need_a_home(self):
        url, server = self.service("models")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = home.main(["onboard", "discover", "--base-url", url, "--timeout", "5"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["model_requests"], 0)
        self.assertEqual([entry["method"] for entry in server.observed], ["GET"])

    def test_existing_cli_bad_deadline_has_plain_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as error:
            status = home.main(["onboard", "discover", "--timeout", "nan"])
        self.assertEqual(status, 1)
        self.assertIn("timeout", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())

    def test_direct_source_cli_works_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "-B", str(Path(home.__file__).resolve()),
                                     "onboard", "discover", "--base-url", "https://example.org/v1"],
                                    cwd=temporary, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("local", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
