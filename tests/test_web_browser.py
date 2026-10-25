"""Native browser fixtures use one explicit test-owned loopback origin only.

That origin is injected into the internal test transport. No public API,
environment allowlist or model input can enable private-network browsing.
"""
import asyncio
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.parse
from unittest import mock

from harness import web_browser as browser
from harness import web_research as web


class BrowserBoundaryTests(unittest.TestCase):
    def test_private_urls_never_start_process_or_browser(self):
        with mock.patch.object(browser.subprocess, 'Popen') as spawn:
            for url in ('http://127.0.0.1/', 'http://169.254.169.254/', 'file:///etc/passwd', 'https://name.local/'):
                self.assertEqual(browser.render(url)['status'], 'blocked')
            spawn.assert_not_called()

    def test_bounded_selectors_and_windows_fail_closed(self):
        with self.assertRaises(ValueError):
            browser.render('https://example.com/', click_selectors=['x'] * 5)
        with self.assertRaises(ValueError):
            browser.render('https://example.com/', click_selectors='button')
        with self.assertRaises(ValueError):
            browser.render('https://example.com/', wait_selector='x' * 301)
        with mock.patch.object(browser.sys, 'platform', 'win32'):
            self.assertEqual(browser.render('https://example.com/')['status'], 'unsupported_platform')

    def test_configured_guard_requires_its_actual_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = Path(directory) / 'guard.py'
            guard.write_text('# fixture guard identity only\n')
            with mock.patch.dict(os.environ, {'PI_WEB_RESEARCH_GUARD': str(guard), 'PI_WEB_RESEARCH_GUARD_SHA256': '0' * 64}):
                self.assertIsNone(browser._guard())
                os.environ['PI_WEB_RESEARCH_GUARD_SHA256'] = hashlib.sha256(guard.read_bytes()).hexdigest()
                self.assertEqual(browser._guard(), guard.resolve())


_NATIVE = bool(importlib.util.find_spec('playwright') and importlib.util.find_spec('httpx')
               and os.environ.get('PLAYWRIGHT_BROWSERS_PATH') and Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).is_dir())
_BODY = b'Owned synthetic public-research fixture evidence. ' * 8
_DOWNLOAD = b'SYNTHETIC_PERMITTED_DOWNLOAD_73\n'


class FixtureHandler(BaseHTTPRequestHandler):
    requests = []
    origins = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.requests.append(self.path)
        self.origins.append({'path': self.path, 'origin': self.headers.get('Origin')})
        content_type, status, extra = 'text/html', 200, {}
        if self.path == '/redirect':
            status, extra, raw = 302, {'Location': '/static'}, b''
        elif self.path == '/redirect-script':
            status, extra, raw = 302, {'Location': 'http://169.254.169.254/latest/meta-data'}, b''
        elif self.path == '/app.js':
            content_type = 'application/javascript'
            raw = b"fetch('/data.json').then(r=>r.json()).then(d=>{let e=document.querySelector('#result');e.textContent=d.text;e.dataset.ready='yes';})"
        elif self.path == '/data.json':
            content_type, raw = 'application/json', b'{"text":"SYNTHETIC_RENDERED_JS_73"}'
        elif self.path == '/download.bin':
            content_type, raw = 'application/octet-stream', _DOWNLOAD
        elif self.path == '/js':
            raw = b'<html><main id="result">Waiting</main><script src="/app.js"></script></html>'
        elif self.path == '/slow-image-before-script':
            raw = b'<html><img src="/slow-image.png"><main id="result">Waiting</main><script src="/app.js"></script></html>'
        elif self.path == '/slow-image.png':
            content_type, raw = 'image/png', b'SYNTHETIC_IMAGE_RESOURCE_73'
        elif self.path == '/pages':
            raw = b'<html><main>' + _BODY + b'<table><tr><th>Page</th></tr><tr><td id="cell">One</td></tr></table><button id="next" onclick="document.querySelector(\'#cell\').textContent=\'Two\'">Next</button></main></html>'
        elif self.path == '/download':
            raw = b'<html><main>' + _BODY + b'<span id="download-state">Ready</span><a id="file" href="/download.bin" download="fixture.txt" onclick="document.querySelector(\'#download-state\').textContent=\'NATIVE_DOWNLOAD_CLICKED_73\'">Download fixture</a></main></html>'
        elif self.path == '/unsafe':
            raw = b'<html><main>' + _BODY + b'</main><script>fetch("http://169.254.169.254/latest/meta-data").catch(()=>{});fetch("/writes",{method:"POST"}).catch(()=>{});new WebSocket("ws://127.0.0.1:9/private");</script><script src="/redirect-script"></script></html>'
        elif self.path == '/state':
            raw = b'<html><main id="state">' + _BODY + b'</main><script>document.querySelector("#state").textContent=localStorage.getItem("fixture")||"FRESH_CONTEXT_73";localStorage.setItem("fixture","LEAKED_CONTEXT_73");</script></html>'
        elif self.path == '/js-error':
            raw = b'<html><main>' + _BODY + b'</main><script>throw new Error("SYNTHETIC_JS_FAILURE_73")</script></html>'
        elif self.path == '/visibility':
            raw = b'<html><main>' + _BODY + b'<p>VISIBLE_TEXT_73</p><div style="display:none"><span>HIDDEN_DISPLAY_ANCESTOR_73</span></div><div style="visibility:hidden"><span>HIDDEN_VISIBILITY_ANCESTOR_73</span><span style="visibility:visible">RESTORED_VISIBLE_TEXT_73</span></div><div style="display:contents">VISIBLE_DISPLAY_CONTENTS_73</div></main></html>'
        elif self.path == '/csp':
            extra['Content-Security-Policy'] = "script-src 'none'; connect-src 'none'"
            raw = b'<html><main id="protected">' + _BODY + b'</main><script>document.querySelector("#protected").textContent="CSP_BYPASS"</script></html>'
        elif self.path in ('/cross.json', '/cross-denied.json'):
            content_type, raw = 'application/json', b'{"text":"NATIVE_CORS_ALLOWED_73"}'
            if self.path == '/cross.json' and self.headers.get('Origin') == 'http://127.0.0.1:' + str(self.server.server_port):
                extra['Access-Control-Allow-Origin'] = self.headers['Origin']
                extra['Vary'] = 'Origin'
        elif self.path in ('/cors', '/cors-denied'):
            target = 'http://localhost:' + str(self.server.server_port) + ('/cross.json' if self.path == '/cors' else '/cross-denied.json')
            raw = b'<html><main>' + _BODY + b'<span id="cors">Waiting</span></main><script>' + (
                "fetch(" + repr(target) + ").then(r=>r.json()).then(d=>{let e=document.querySelector('#cors');e.textContent=d.text;e.dataset.ready='yes'}).catch(()=>{let e=document.querySelector('#cors');e.textContent='NATIVE_CORS_DENIED_73';e.dataset.ready='yes'})"
            ).encode() + b'</script></html>'
        else:
            raw = b'<html><head><title>Fixture Research</title></head><main><h1 id="title">Fixture Research</h1>' + _BODY + b'<a href="/pages">Pages</a></main></html>'
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        for name, value in extra.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)


@unittest.skipUnless(_NATIVE, 'Owned native Playwright/browser cache and httpx required')
class NativeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
        cls.server.daemon_threads = True
        cls.origin = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        self.attempted = []

    def fixture_fetch(self, url, *, timeout, max_bytes, max_chars, max_redirects, browser_origin=None, browser_referrer=None):
        import httpx

        # Explicit owner-only fixture transport. A page cannot expand its origin.
        current, chain = url, []
        for hop in range(max_redirects + 1):
            approved = {urllib.parse.urlsplit(self.origin).netloc, 'localhost:' + str(self.server.server_port)}
            if urllib.parse.urlsplit(current).netloc not in approved:
                raise ValueError('Fixture does not authorize this private destination')
            self.attempted.append(current)
            headers = {}
            for value, name in ((browser_origin, 'Origin'), (browser_referrer, 'Referer')):
                if value is not None:
                    if urllib.parse.urlsplit(value).netloc not in approved:
                        raise ValueError('Fixture does not authorize browser metadata')
                    headers[name] = value
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout) as client:
                response = client.get(current, headers=headers)
            chain.append({'url': current, 'status_code': response.status_code, 'location': response.headers.get('location')})
            if response.status_code == 302:
                if hop == max_redirects:
                    return web._failure('fetch', url, 'redirect_limit')
                current = urllib.parse.urljoin(current, response.headers['location'])
                continue
            artifact = web._artifact(current, response, response.content[:max_bytes], chain, max_chars, len(response.content) > max_bytes)
            return {'schema': 'web-fetch/v1', 'ok': not artifact['raw_truncated'], 'status': 'ok', 'reason': None, 'response': artifact}
        raise AssertionError('Fixture exceeded its declared redirect limit')

    def run_page(self, path, **options):
        request = {'url': self.origin + path, 'timeout': 12, 'max_chars': 12000, 'offset': 0,
                   'wait_selector': None, 'click_selectors': [], 'download_selector': None, **options}
        result = asyncio.run(asyncio.wait_for(browser._browse_native(request, self.fixture_fetch), timeout=request['timeout']))
        self.assertTrue(result['ok'], result)
        return result

    def test_static_page_and_source_evidence_window(self):
        result = self.run_page('/static', max_chars=80)
        self.assertEqual(result['title'], 'Fixture Research')
        self.assertIn('--disable-gpu', result['launch_args'])
        self.assertIn('--disable-webgl', result['launch_args'])
        self.assertEqual(len(result['document']['text']), 80)
        self.assertTrue(result['document']['truncated'])
        self.assertEqual(result['document']['text_sha256'], hashlib.sha256(result['document']['text'].encode()).hexdigest())
        self.assertEqual(result['document']['headings'][0]['text'], 'Fixture Research')
        self.assertIn(self.origin + '/pages', [link['url'] for link in result['document']['links']])
        self.assertEqual(result['sources'][0]['raw_sha256'], hashlib.sha256(base64.b64decode(result['sources'][0]['content_base64'])).hexdigest())

    def test_js_rendering_and_native_locator_wait(self):
        result = self.run_page('/js', wait_selector='#result[data-ready="yes"]')
        self.assertIn('SYNTHETIC_RENDERED_JS_73', result['document']['text'])
        self.assertEqual({urllib.parse.urlsplit(source['url']).path for source in result['sources']}, {'/js', '/app.js', '/data.json'})

    def test_slow_image_before_script_never_fetches_and_javascript_still_renders(self):
        images = []
        def slow_image(url, **options):
            if urllib.parse.urlsplit(url).path == '/slow-image.png':
                images.append(url)
                time.sleep(7)  # Exceeds the six-second operation on the old serial route.
            return self.fixture_fetch(url, **options)
        request = {'url': self.origin + '/slow-image-before-script', 'timeout': 6, 'max_chars': 12000,
                   'offset': 0, 'wait_selector': '#result[data-ready="yes"]', 'click_selectors': [], 'download_selector': None}
        result = asyncio.run(asyncio.wait_for(browser._browse_native(request, slow_image), timeout=request['timeout']))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('SYNTHETIC_RENDERED_JS_73', result['document']['text'])
        self.assertEqual(images, [])
        self.assertTrue(any(item.get('resource_type') == 'image' and item['reason'] == 'nonessential_text_resource'
                            and urllib.parse.urlsplit(item['url']).path == '/slow-image.png' for item in result['blocked_requests']))
        self.assertEqual({urllib.parse.urlsplit(source['url']).path for source in result['sources']},
                         {'/slow-image-before-script', '/app.js', '/data.json'})

    def test_javascript_error_is_visible_partial_not_full_success(self):
        result = self.run_page('/js-error')
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(any('SYNTHETIC_JS_FAILURE_73' in error for error in result['page_errors']))

    def test_native_rendered_text_respects_hidden_ancestors_and_visible_override(self):
        result = self.run_page('/visibility')
        text = result['document']['text']
        self.assertIn('VISIBLE_TEXT_73', text)
        self.assertNotIn('HIDDEN_DISPLAY_ANCESTOR_73', text)
        self.assertNotIn('HIDDEN_VISIBILITY_ANCESTOR_73', text)
        self.assertIn('RESTORED_VISIBLE_TEXT_73', text)
        self.assertIn('VISIBLE_DISPLAY_CONTENTS_73', text)

    def test_original_csp_and_cross_origin_cors_are_enforced_by_native_browser(self):
        result = self.run_page('/csp')
        self.assertNotIn('CSP_BYPASS', result['document']['text'])
        result = self.run_page('/cors', wait_selector='#cors[data-ready="yes"]')
        self.assertIn('NATIVE_CORS_ALLOWED_73', result['document']['text'])
        self.assertTrue(any(item['path'] == '/cross.json' and item['origin'] == self.origin for item in FixtureHandler.origins))
        result = self.run_page('/cors-denied', wait_selector='#cors[data-ready="yes"]')
        self.assertIn('NATIVE_CORS_DENIED_73', result['document']['text'])
        self.assertNotIn('NATIVE_CORS_ALLOWED_73', result['document']['text'])

    def test_native_table_pagination_and_redirect_source(self):
        result = self.run_page('/pages', click_selectors=['#next'])
        self.assertEqual(result['document']['tables'][0]['rows'][1], ['Two'])
        result = self.run_page('/redirect')
        self.assertEqual(result['page_url'], self.origin + '/static')
        self.assertEqual(result['sources'][0]['redirect_chain'][0]['status_code'], 302)

    def test_all_subresources_methods_websockets_and_redirects_are_guarded(self):
        result = self.run_page('/unsafe', wait_selector='main')
        reasons = {item['reason'] for item in result['blocked_requests']}
        self.assertIn('blocked', reasons)
        self.assertIn('read_only_public_http', reasons)
        self.assertIn('redirect_limit', reasons)
        self.assertIn('websocket_unavailable', reasons)
        self.assertNotIn('/writes', FixtureHandler.requests)
        self.assertTrue(all(value.startswith(self.origin + '/') for value in self.attempted))

    def test_native_download_has_exact_bound_source_bytes(self):
        result = self.run_page('/download', download_selector='#file')
        self.assertEqual(len(result['downloads']), 1)
        download = result['downloads'][0]
        self.assertEqual(download['bytes'], len(_DOWNLOAD))
        self.assertEqual(base64.b64decode(download['content_base64']), _DOWNLOAD)
        self.assertEqual(download['sha256'], hashlib.sha256(_DOWNLOAD).hexdigest())
        self.assertEqual(download['transport'], 'host-fetch/browser-blob')
        self.assertNotIn('Research download', result['document']['text'])

    def test_unrouted_native_download_cannot_bypass_host_transport(self):
        before = FixtureHandler.requests.count('/download.bin')
        request = {'url': self.origin + '/download', 'timeout': 6, 'max_chars': 1000, 'offset': 0,
                   'wait_selector': None, 'click_selectors': ['#file'], 'download_selector': None}
        try:
            result = asyncio.run(asyncio.wait_for(browser._browse_native(request, self.fixture_fetch), timeout=6))
        except Exception as error:
            self.assertIn('ERR_PROXY_CONNECTION_FAILED', str(error))
        else:
            self.assertEqual(result['downloads'], [])
            self.assertIn('NATIVE_DOWNLOAD_CLICKED_73', result['document']['text'])
        self.assertEqual(FixtureHandler.requests.count('/download.bin'), before)
        self.assertEqual(self.attempted, [self.origin + '/download'])

    def test_timeout_cleans_context_and_restart_carries_no_storage(self):
        request = {'url': self.origin + '/static', 'timeout': 2, 'max_chars': 1000, 'offset': 0,
                   'wait_selector': '#never-created', 'click_selectors': [], 'download_selector': None}
        started = time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(asyncio.wait_for(browser._browse_native(request, self.fixture_fetch), timeout=2))
        self.assertLess(time.monotonic() - started, 8)
        for _ in range(2):
            result = self.run_page('/state')
            self.assertIn('FRESH_CONTEXT_73', result['document']['text'])
            self.assertNotIn('LEAKED_CONTEXT_73', result['document']['text'])


if __name__ == '__main__':
    unittest.main()
