"""Public research boundaries and real native HTTPX/BeautifulSoup extraction.

All HTTP traffic uses HTTPX's native in-memory MockTransport. No provider,
browser, model, credentials or private destination is contacted by this suite.
"""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from harness import web_research as web

try:
    import httpx
except ImportError:
    httpx = None
try:
    import bs4
except ImportError:
    bs4 = None


class PublicResearchTests(unittest.TestCase):
    def test_identity_is_lossy_and_never_replaces_retrieval_url(self):
        original = 'https://www.example.com/a%2Fb/?utm_source=fixture&z=2&a=1#section'
        self.assertEqual(web.canonical_url(original), 'https://example.com/a/b?a=1&z=2')
        fake = types.SimpleNamespace(DDGS=mock.Mock())
        fake.DDGS.return_value.text.return_value = [
            {'title': 'Source', 'href': original, 'body': 'Original provider snippet'},
            {'title': 'Duplicate', 'href': 'https://example.com/a/b?a=1&z=2', 'body': 'Other observation'},
            {'title': 'Private', 'href': 'http://127.0.0.1/private', 'body': 'Unavailable'},
        ]
        with mock.patch.dict(sys.modules, {'ddgs': fake}):
            result = web._search_native('fixture query', 3, 5)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['hits']), 1)
        hit = result['hits'][0]
        self.assertEqual(hit['url'], original)
        self.assertEqual(len(hit['observations']), 2)
        self.assertEqual(result['coverage']['independent_providers'], 1)
        self.assertFalse(result['coverage']['corroborated'])
        fake.DDGS.assert_called_once_with(timeout=3)
        fake.DDGS.return_value.text.assert_called_once_with('fixture query', max_results=5, page=1, backend='duckduckgo')

    def test_domain_grouping_is_best_effort_not_corroboration(self):
        self.assertEqual(web.coverage_domain('https://docs.example.co.uk/a'), 'example.co.uk')
        self.assertEqual(web.coverage_domain('https://docs.example.com/a'), 'example.com')

    def test_unknown_and_empty_search_are_explicit(self):
        fake = types.SimpleNamespace(DDGS=mock.Mock())
        with mock.patch.dict(sys.modules, {'ddgs': fake}):
            fake.DDGS.return_value.text.return_value = []
            result = web._search_native('fixture', 3, 5)
            self.assertFalse(result['ok'])
            self.assertEqual(result['status'], 'empty')
            fake.DDGS.return_value.text.return_value = {'unexpected': []}
            self.assertEqual(web._search_native('fixture', 3, 5)['status'], 'invalid_response')

    def test_public_route_rejects_local_credentials_ports_and_control_bytes_before_worker(self):
        urls = [
            'file:///etc/passwd', 'http://localhost/', 'http://127.0.0.1/',
            'http://169.254.169.254/latest/meta-data', 'http://10.0.0.1/',
            'http://100.64.0.1/', 'http://[::1]/', 'http://[::ffff:8.8.8.8]/',
            'http://printer.local/', 'http://service.internal/', 'http://user:pass@example.com/',
            'https://example.com:8443/', 'http://2130706433/', 'https://example.com/\nprivate',
        ]
        with mock.patch.object(web, '_run') as run:
            for url in urls:
                with self.subTest(url=url):
                    self.assertEqual(web.fetch(url)['status'], 'blocked')
            run.assert_not_called()

    def test_invalid_limits_and_queries_do_not_start_worker(self):
        with mock.patch.object(web.subprocess, 'run') as run:
            for options in ({'limit': True}, {'limit': 0}, {'timeout': float('nan')}, {'timeout': 121}):
                with self.assertRaises(ValueError):
                    web.search('fixture', **options)
            for value in ('', ' ' * 3, 'x' * 4097):
                with self.assertRaises(ValueError):
                    web.search(value)
            with self.assertRaises(ValueError):
                web.fetch('https://example.com/', max_bytes=8_000_000)
            run.assert_not_called()

    def test_native_worker_environment_does_not_inherit_keys_or_profiles(self):
        response = {'schema': 'web-search/v1', 'ok': False, 'status': 'empty'}
        completed = subprocess.CompletedProcess([], 0, json.dumps(response), '')
        private = {'BRAVE_API_KEY': 'fixture-secret', 'SERPAPI_KEY': 'fixture-secret',
                   'HTTPS_PROXY': 'http://private.invalid', 'DDGS_PROXY': 'http://private.invalid',
                   'PYTHONPATH': '/private/fixture', 'HOME': '/private/fixture'}
        with mock.patch.dict(os.environ, private), mock.patch.object(web.subprocess, 'run', return_value=completed) as run:
            self.assertEqual(web.search('fixture'), response)
        args, options = run.call_args
        self.assertFalse(options['shell'])
        self.assertEqual(options['timeout'], 30)
        self.assertEqual(args[0][-2:], ['--worker', 'search'])
        self.assertEqual(set(private) & set(options['env']), set())

    def test_total_deadline_cancel_and_invalid_worker_are_typed_failures(self):
        with mock.patch.object(web.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['fixture'], 0.1)):
            self.assertEqual(web.search('fixture', timeout=0.1)['status'], 'timeout')
        with mock.patch.object(web.subprocess, 'run', side_effect=KeyboardInterrupt):
            self.assertEqual(web.search('fixture')['status'], 'cancelled')
        for completed in (subprocess.CompletedProcess([], 1, '', ''),
                          subprocess.CompletedProcess([], 0, '{"ok":true}', ''),
                          subprocess.CompletedProcess([], 0, 'not json', '')):
            with mock.patch.object(web.subprocess, 'run', return_value=completed):
                self.assertFalse(web.search('fixture')['ok'])

    def test_owned_cache_and_temporary_paths_survive_without_shared_home_fallback(self):
        completed = subprocess.CompletedProcess([], 0, '{"schema":"web-search/v1","ok":false,"status":"empty"}', '')
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {'XDG_CACHE_HOME': directory, 'TMPDIR': directory}):
                with mock.patch.object(web.subprocess, 'run', return_value=completed) as run:
                    web.search('fixture')
                self.assertEqual(run.call_args.kwargs['env']['XDG_CACHE_HOME'], directory)
                self.assertEqual(run.call_args.kwargs['env']['TMPDIR'], directory)
            caches = []
            def worker(*args, **kwargs):
                cache = Path(kwargs['env']['XDG_CACHE_HOME'])
                self.assertTrue(cache.is_dir())
                caches.append(cache)
                return completed
            with mock.patch.dict(os.environ, {'XDG_CACHE_HOME': '', 'TMPDIR': directory}):
                with mock.patch.object(web.subprocess, 'run', side_effect=worker):
                    web.search('fixture')
            self.assertTrue(caches)
            self.assertFalse(caches[0].exists())

    def test_dependency_and_native_provider_failures_are_specific(self):
        request = {'value': 'fixture', 'timeout': 3, 'limit': 5}
        with mock.patch.object(web, '_search_native', side_effect=ModuleNotFoundError(name='ddgs')):
            result = web._worker('search', request)
        self.assertEqual((result['status'], result['reason']), ('dependency_missing', 'ddgs'))
        for name, expected in [('RatelimitException', 'rate_limited'), ('TimeoutException', 'timeout')]:
            error = type(name, (Exception,), {})()
            with mock.patch.object(web, '_search_native', side_effect=error):
                self.assertEqual(web._worker('search', request)['status'], expected)

    def test_mixed_public_private_dns_fails_closed(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in ('8.8.8.8', '127.0.0.1')]
        with mock.patch.object(web.socket, 'getaddrinfo', return_value=answers):
            with self.assertRaises(ValueError):
                web._resolved_target('https://example.com/')

    def test_import_needs_no_optional_native_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        script = """import importlib.abc,sys
class NoOptional(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in ('ddgs','httpx','bs4'): raise ImportError(fullname)
sys.meta_path.insert(0,NoOptional())
from harness import web_research
assert web_research.canonical_url('https://www.example.com/')=='https://example.com/'
"""
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(httpx is not None and bs4 is not None, 'Optional httpx/beautifulsoup4 are required for native extraction fixtures')
class NativeExtractionTests(unittest.TestCase):
    def invoke(self, handler, url='https://www.example.com/article?utm_source=fixture', **options):
        native_client = httpx.Client
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        def client(**kwargs):
            self.assertFalse(kwargs['trust_env'])
            self.assertFalse(kwargs['follow_redirects'])
            return native_client(transport=httpx.MockTransport(handler), **kwargs)
        with mock.patch.object(web.socket, 'getaddrinfo', return_value=addresses), mock.patch.object(httpx, 'Client', side_effect=client):
            return web._fetch_native(url, 3, options.get('max_bytes', 4096), options.get('max_chars', 2000), options.get('max_redirects', 3),
                                     options.get('browser_origin'), options.get('browser_referrer'))

    def test_reviewed_response_headers_preserve_policy_without_cookies_auth_or_decoding_headers(self):
        raw = b'<main>' + b'Public policy fixture evidence. ' * 8 + b'</main>'
        headers = {'content-type': 'text/html', 'content-security-policy': "script-src 'none'",
                   'access-control-allow-origin': 'https://example.com', 'referrer-policy': 'no-referrer',
                   'set-cookie': 'private=fixture', 'authorization': 'fixture-token',
                   'content-encoding': 'gzip', 'content-length': str(len(gzip.compress(raw)))}
        result = self.invoke(lambda request: httpx.Response(200, headers=headers, content=gzip.compress(raw)))
        retained = result['response']['response_headers']
        self.assertEqual(retained['content-security-policy'], "script-src 'none'")
        self.assertEqual(retained['access-control-allow-origin'], 'https://example.com')
        self.assertTrue(result['response']['response_headers_complete'])
        self.assertEqual(base64.b64decode(result['response']['raw_content_base64']), raw)
        for name in ('set-cookie', 'authorization', 'content-length', 'content-encoding'):
            self.assertNotIn(name, retained)

    def test_browser_metadata_is_narrow_and_policy_headers_are_never_silently_truncated(self):
        for origin in ('http://127.0.0.1', 'https://example.com/path', 'https://example.com/?query=1', 'https://example.com/\nCookie:bad'):
            with self.assertRaises(ValueError):
                web._browser_metadata(origin, None)
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, headers={'content-type': 'text/plain', 'content-security-policy': 'x' * 8193}, content=b'x' * 100)
        result = self.invoke(handler, browser_origin='https://example.com', browser_referrer='https://example.com/source')
        self.assertEqual(seen[0].headers['origin'], 'https://example.com')
        self.assertEqual(seen[0].headers['referer'], 'https://example.com/source')
        self.assertNotIn('cookie', seen[0].headers)
        self.assertFalse(result['response']['response_headers_complete'])
        self.assertEqual(result['response']['response_headers'], {})

    def test_native_client_pins_public_address_and_preserves_original_source_and_hashes(self):
        text = 'Readable public source evidence. ' * 8
        raw = ('<html><nav>Unrelated navigation</nav><main><h1>Source heading</h1><p>' + text +
               '</p></main><script>untrusted instructions</script></html>').encode()
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, headers={'content-type': 'text/html; charset=utf-8'}, content=raw)
        result = self.invoke(handler)
        self.assertTrue(result['ok'], result)
        artifact = result['response']
        self.assertEqual(requests[0].url.host, '8.8.8.8')
        self.assertEqual(requests[0].headers['host'], 'www.example.com')
        self.assertEqual(requests[0].extensions['sni_hostname'], 'www.example.com')
        self.assertEqual(artifact['final_url'], 'https://www.example.com/article?utm_source=fixture')
        self.assertEqual(base64.b64decode(artifact['raw_content_base64']), raw)
        self.assertEqual(artifact['raw_content_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertIn('Source heading', artifact['cleaned_text'])
        self.assertNotIn('Unrelated navigation', artifact['cleaned_text'])
        self.assertNotIn('untrusted instructions', artifact['cleaned_text'])
        self.assertEqual(artifact['cleaned_text_sha256'], hashlib.sha256(artifact['cleaned_text'].encode()).hexdigest())

    def test_redirect_to_private_destination_is_blocked_before_second_request(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={'location': 'http://169.254.169.254/latest/meta-data'})
        result = self.invoke(handler)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(len(requests), 1)
        self.assertEqual(result['attempts'][0]['status_code'], 302)

    def test_redirect_limit_and_native_error_preserve_prior_attempts(self):
        result = self.invoke(lambda request: httpx.Response(302, headers={'location': '/next'}), max_redirects=1)
        self.assertEqual(result['status'], 'redirect_limit')
        self.assertEqual(len(result['attempts']), 2)
        calls = []
        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(302, headers={'location': '/next'})
            raise httpx.ReadTimeout('synthetic timeout')
        result = self.invoke(handler)
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['attempts'][0]['status_code'], 302)

    def test_blocked_rate_limited_and_server_errors_preserve_exact_body(self):
        for code, status in [(403, 'blocked'), (429, 'rate_limited'), (503, 'http_error')]:
            raw = b'Synthetic public HTTP failure'
            with self.subTest(code=code), mock.patch.object(web, '_clean_html') as clean:
                result = self.invoke(lambda request: httpx.Response(code, headers={'content-type': 'text/html'}, content=raw))
                self.assertEqual(result['status'], status)
                self.assertFalse(result['ok'])
                self.assertEqual(base64.b64decode(result['response']['raw_content_base64']), raw)
                clean.assert_not_called()

    def test_response_byte_limit_and_partial_text_are_explicit(self):
        raw = b'a' * 1200
        result = self.invoke(lambda request: httpx.Response(200, headers={'content-type': 'text/plain'}, content=raw), max_bytes=1024)
        self.assertEqual(result['status'], 'too_large')
        self.assertTrue(result['response']['raw_truncated'])
        self.assertEqual(len(base64.b64decode(result['response']['raw_content_base64'])), 1024)
        result = self.invoke(lambda request: httpx.Response(200, headers={'content-type': 'text/plain'}, content=raw), max_chars=80)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['ok'])
        self.assertTrue(result['response']['text_truncated'])
        self.assertEqual(len(result['response']['cleaned_text']), 80)
        self.assertEqual(result['response']['cleaned_text_full'], raw.decode())
        self.assertEqual(result['response']['cleaned_text_encoding'], 'utf-8')
        self.assertEqual(result['response']['full_cleaned_text_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(result['response']['cleaned_text_sha256'], result['response']['full_cleaned_text_sha256'])

    def test_challenge_thin_and_document_responses_are_not_useful_extraction(self):
        for raw, content_type, status in [
            (b'<html><title>Just a moment</title><main>Checking</main></html>', 'text/html', 'challenge'),
            (b'<html><main>thin</main></html>', 'text/html', 'empty_extraction'),
            (b'%PDF-synthetic fixture', 'application/pdf', 'unsupported_content'),
        ]:
            with self.subTest(status=status):
                result = self.invoke(lambda request: httpx.Response(200, headers={'content-type': content_type}, content=raw))
                self.assertFalse(result['ok'])
                self.assertEqual(result['status'], status)

    def test_ordinary_article_about_captcha_is_not_misclassified_as_challenge(self):
        raw = ('<html><title>Public API documentation</title><main>' + 'A captcha is an interface example. ' * 8 + '</main></html>').encode()
        result = self.invoke(lambda request: httpx.Response(200, headers={'content-type': 'text/html'}, content=raw))
        self.assertTrue(result['ok'], result)


if __name__ == '__main__':
    unittest.main()
