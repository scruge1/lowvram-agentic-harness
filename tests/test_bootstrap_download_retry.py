"""Actual curl over owned local TLS; no public downloads or runtime installation.

Fixtures shorten curl deadlines and trust a generated local certificate only.
The shell fixture also changes URL/hash and stops before archive extraction.
Those transformations do not qualify a normal fresh installer on a real host.
"""
import hashlib
from pathlib import Path
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

from harness import bootstrap as b


class LocalTLS:
    def __init__(self, cert, key, body, *, stalls=0, retry_after=None):
        self.body, self.stalls = body, stalls
        self.retry_after = retry_after
        self.accepted, self.requests = 0, []
        self.stop = threading.Event()
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(.1)
        self.url = 'https://127.0.0.1:' + str(self.listener.getsockname()[1]) + '/archive'
        self.children = []
        self.thread = threading.Thread(target=self.serve)
        self.thread.start()

    def serve(self):
        while not self.stop.is_set():
            try:
                connection, _peer = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.accepted += 1
            child = threading.Thread(target=self.reply, args=(connection, self.accepted <= self.stalls))
            self.children.append(child)
            child.start()

    def reply(self, connection, stall):
        try:
            with connection:
                if stall:
                    self.stop.wait(.6)  # exceed the fixture's .2s TLS deadline
                    return
                connection.settimeout(2)
                with self.context.wrap_socket(connection, server_side=True) as channel:
                    headers = b''
                    while b'\r\n\r\n' not in headers:
                        block = channel.recv(1024)
                        if not block:
                            return
                        headers += block
                        if len(headers) > 8192:
                            return
                    match = re.search(br'(?im)^Range: bytes=(\d+)-\r?$', headers)
                    offset = int(match[1]) if match else 0
                    self.requests.append(offset)
                    if self.retry_after is not None:
                        channel.sendall(b'HTTP/1.1 503 Service Unavailable\r\n'
                                        + f'Retry-After: {self.retry_after}\r\n'.encode()
                                        + b'Content-Length: 0\r\nConnection: close\r\n\r\n')
                        return
                    if offset >= len(self.body):
                        channel.sendall(b'HTTP/1.1 416 Range Not Satisfiable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                        return
                    payload = self.body[offset:]
                    status = b'206 Partial Content' if offset else b'200 OK'
                    extra = (f'Content-Range: bytes {offset}-{len(self.body)-1}/{len(self.body)}\r\n'.encode()
                             if offset else b'')
                    channel.sendall(b'HTTP/1.1 ' + status + b'\r\n' + extra
                                    + f'Content-Length: {len(payload)}\r\n'.encode()
                                    + b'Connection: close\r\n\r\n' + payload)
        except (OSError, ssl.SSLError):
            pass  # expected when curl rejects the synthetic certificate

    def close(self):
        self.stop.set()
        self.listener.close()
        self.thread.join(timeout=3)
        for child in self.children:
            child.join(timeout=3)
        if self.thread.is_alive() or any(child.is_alive() for child in self.children):
            raise AssertionError('Owned TLS fixture did not settle')


@unittest.skipUnless(sys.platform == 'linux' and Path('/usr/bin/curl').is_file()
                     and Path('/usr/bin/openssl').is_file(), 'Actual Linux curl/OpenSSL local TLS controls')
class NativeDownloadRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory(prefix='bootstrap-tls-cert-')
        cls.addClassCleanup(cls.shared.cleanup)
        root = Path(cls.shared.name).resolve()
        cls.cert, cls.key = root / 'cert.pem', root / 'key.pem'
        subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', cls.key, '-out', cls.cert, '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1', '-days', '1'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='bootstrap-curl-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.body = b'Synthetic archive bytes for local curl controls only.\n'
        self.digest = hashlib.sha256(self.body).hexdigest()
        self.final = self.root / 'native.tar.xz'
        self.partial = self.final.with_name(self.final.name + '.partial')
        self.env = {'HOME': str(self.root), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                    'CURL_CA_BUNDLE': str(self.cert)}

    def server(self, *, stalls=0, body=None, retry_after=None):
        server = LocalTLS(self.cert, self.key, self.body if body is None else body,
                          stalls=stalls, retry_after=retry_after)
        self.addCleanup(server.close)
        return server

    def native(self, argv, *, env, timeout):
        # Transform timing only. Production's URL, HTTPS, resume, size, retry
        # selection and exact promotion code remain the actual download call.
        argv = list(map(str, argv))
        for name, value in (('--connect-timeout', '.2'), ('--max-time', '3'), ('--retry-max-time', '4')):
            argv[argv.index(name) + 1] = value
        self.assertEqual(timeout, 620)
        return b.command(argv, env=env, timeout=8)

    def download(self, server, *, env=None):
        return b.download(server.url, self.final, self.digest, len(self.body),
                          env=self.env if env is None else env, runner=self.native)

    def test_tls_timeout_retries_and_resumes_existing_prefix(self):
        server = self.server(stalls=1)
        self.partial.write_bytes(self.body[:7])
        self.download(server)
        self.assertEqual(server.accepted, 2)
        self.assertEqual(server.requests, [7])
        self.assertEqual(self.final.read_bytes(), self.body)
        self.assertFalse(self.partial.exists())

    def test_exhausted_tls_retries_retain_existing_prefix(self):
        server = self.server(stalls=100)
        self.partial.write_bytes(self.body[:7])
        with self.assertRaises(b.BootstrapError):
            self.download(server)
        self.assertEqual(server.accepted, 3)
        self.assertEqual(server.requests, [])
        self.assertEqual(self.partial.read_bytes(), self.body[:7])
        self.assertFalse(self.final.exists())

    def test_certificate_refusal_is_not_retried(self):
        server = self.server()
        self.partial.write_bytes(self.body[:7])
        env = {key: value for key, value in self.env.items() if key != 'CURL_CA_BUNDLE'}
        with self.assertRaises(b.BootstrapError):
            self.download(server, env=env)
        self.assertEqual(server.accepted, 1)
        self.assertEqual(server.requests, [])
        self.assertEqual(self.partial.read_bytes(), self.body[:7])
        self.assertFalse(self.final.exists())

    def test_retry_after_does_not_expand_native_retry_admission(self):
        server = self.server(retry_after=120)
        self.partial.write_bytes(self.body[:7])
        with self.assertRaises(b.BootstrapError):
            self.download(server)
        self.assertEqual(server.accepted, 1)
        self.assertEqual(self.partial.read_bytes(), self.body[:7])
        self.assertFalse(self.final.exists())

    def test_corrupt_transfer_and_complete_partial_never_promote(self):
        server = self.server(body=b'X' * len(self.body))
        with self.assertRaisesRegex(b.BootstrapError, 'failed partial retained'):
            self.download(server)
        self.assertEqual(server.accepted, 1)
        self.assertEqual(self.partial.read_bytes(), b'X' * len(self.body))
        with self.assertRaisesRegex(b.BootstrapError, 'failed partial retained'):
            self.download(server)  # complete corrupt partial is checked locally
        self.assertEqual(server.accepted, 1)
        self.assertFalse(self.final.exists())

    def test_conflicting_final_and_oversized_partial_do_not_connect(self):
        server = self.server()
        self.final.write_bytes(b'Keep the existing final')
        with self.assertRaisesRegex(b.BootstrapError, 'final download conflicts'):
            self.download(server)
        self.assertEqual(self.final.read_bytes(), b'Keep the existing final')
        self.final.unlink()
        self.partial.write_bytes(self.body + b'oversized')
        with self.assertRaisesRegex(b.BootstrapError, 'Oversized partial'):
            self.download(server)
        self.assertEqual(server.accepted, 0)
        self.assertEqual(self.partial.read_bytes(), self.body + b'oversized')

    def shell_fragment(self, server, *, trust=True, name='shell', prefix=None, final=None):
        if shutil.disk_usage(self.root).free < 8 * 1024**3:
            self.skipTest('The unchanged shell preflight requires8GiB free')
        root = self.root / name
        source = root / 'source'
        (source / 'harness').mkdir(parents=True)
        for name in ('home.py', 'bootstrap.py'):
            (source / 'harness' / name).write_text('# Fixture stops before managed Python\n')
        text = (b.SOURCE / 'install.sh').read_text(encoding='utf-8')
        marker = '\nif [[ ! -e "$runtime_root/bin/uv" ]]; then\n'
        self.assertEqual(text.count(marker), 1)
        text = text.split(marker)[0] + '\nexit 0 # Native UV fragment only, before extraction\n'
        text = re.sub(r'^UV_SHA=.*$', 'UV_SHA=' + self.digest, text, count=1, flags=re.M)
        text = re.sub(r'^UV_URL=.*$', 'UV_URL=' + shlex.quote(server.url), text, count=1, flags=re.M)
        text = text.replace('--connect-timeout 20 --max-time 555', '--connect-timeout .2 --max-time 3')
        text = text.replace('--retry-max-time 45', '--retry-max-time 4')
        if trust:
            text = text.replace('curl -q --fail', 'curl -q --cacert ' + shlex.quote(str(self.cert)) + ' --fail')
        file = source / 'install.sh'
        file.write_text(text, encoding='utf-8')
        home = root / 'agent-home'
        runtime = Path(str(home) + '-runtimes')
        (runtime / 'downloads').mkdir(parents=True)
        (runtime / 'bootstrap-owner').write_text('agent-home-bootstrap/v1:' + str(home) + '\n')
        partial = runtime / 'downloads/uv-0.11.25.tar.gz.partial'
        partial.write_bytes(self.body[:7] if prefix is None else prefix)
        if final is not None:
            partial.with_suffix('').write_bytes(final)
        env = {'HOME': str(root), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        result = subprocess.run(['/bin/bash', file, '--home', home, '--yes'], env=env,
                                capture_output=True, text=True, timeout=10)
        return result, runtime, partial

    def test_actual_shell_uv_fragment_retries_without_starting_factory(self):
        server = self.server(stalls=1)
        result, runtime, partial = self.shell_fragment(server)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(server.accepted, 2)
        self.assertEqual(server.requests, [7])
        self.assertEqual((runtime / 'downloads/uv-0.11.25.tar.gz').read_bytes(), self.body)
        self.assertFalse(partial.exists())
        self.assertFalse((runtime / 'bin/uv').exists())

    def test_actual_shell_uv_fragment_preserves_certificate_failure(self):
        server = self.server()
        result, runtime, partial = self.shell_fragment(server, trust=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(server.accepted, 1)
        self.assertEqual(server.requests, [])
        self.assertEqual(partial.read_bytes(), self.body[:7])
        self.assertFalse((runtime / 'downloads/uv-0.11.25.tar.gz').exists())

    def test_actual_shell_uv_fragment_retains_exhaustion_corruption_and_conflict(self):
        for name in ('exhausted', 'corrupt-prefix', 'conflicting-final'):
            with self.subTest(case=name):
                server = self.server(stalls=100 if name == 'exhausted' else 0)
                prefix = b'X' * 7 if name == 'corrupt-prefix' else self.body[:7]
                final = b'Keep existing final' if name == 'conflicting-final' else None
                result, runtime, partial = self.shell_fragment(server, name=name, prefix=prefix, final=final)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(server.accepted, {'exhausted': 3, 'corrupt-prefix': 1, 'conflicting-final': 0}[name])
                if final is not None:
                    self.assertEqual(partial.with_suffix('').read_bytes(), final)
                    self.assertEqual(partial.read_bytes(), prefix)
                else:
                    self.assertFalse((runtime / 'downloads/uv-0.11.25.tar.gz').exists())
                    expected = prefix + self.body[7:] if name == 'corrupt-prefix' else prefix
                    self.assertEqual(partial.read_bytes(), expected)


if __name__ == '__main__':
    unittest.main()
