"""Run against a built web image: NGINX_TEST_IMAGE=<tag> python3 frontend/test_proxy.py."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import Request, urlopen
import uuid


class ProxyTests(unittest.TestCase):
    image = os.environ.get('NGINX_TEST_IMAGE', 'resume-match-web-compat-check')

    def docker(self, *args, check=True):
        result = subprocess.run(['docker', *args], capture_output=True, text=True)
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result

    def proxy(self, cloud=False):
        suffix = uuid.uuid4().hex[:10]
        network, backend, web = (f'proxy-check-{suffix}-{part}' for part in ('net', 'api', 'web'))
        self.docker('network', 'create', network)
        self.addCleanup(lambda: self.docker('network', 'rm', network, check=False))
        fixture = tempfile.TemporaryDirectory(prefix='.proxy-check-', dir=Path(__file__).resolve().parent)
        self.addCleanup(fixture.cleanup)
        config = Path(fixture.name) / 'backend.conf'
        config.write_text('pid /tmp/mock.pid; error_log /dev/stderr; events {} http { '
                          'client_body_temp_path /tmp/mock_client; proxy_temp_path /tmp/mock_proxy; '
                          'fastcgi_temp_path /tmp/mock_fastcgi; uwsgi_temp_path /tmp/mock_uwsgi; '
                          'scgi_temp_path /tmp/mock_scgi; server { listen 8000; '
                          'location /api/ { return 200 "$http_x_forwarded_proto"; } } }')
        self.docker('run', '-d', '--name', backend, '--network', network,
                    '--network-alias', 'api', '-p', '127.0.0.1::8080',
                    '-v', f'{config}:/tmp/backend.conf:ro', '--entrypoint', 'nginx',
                    self.image, '-c', '/tmp/backend.conf', '-g', 'daemon off;')
        self.addCleanup(lambda: self.docker('rm', '-f', backend, check=False))
        if self.docker('inspect', '--format', '{{.State.Running}}', backend).stdout.strip() != 'true':
            self.fail(self.docker('logs', backend).stderr)
        env = ['-e', 'FRONTEND_API_UPSTREAM=127.0.0.1:8000',
               '-e', 'FRONTEND_TRUST_ALB_PROTO=true'] if cloud else []
        self.addCleanup(lambda: self.docker('rm', '-f', web, check=False))
        self.docker('run', '-d', '--name', web, '--network', f'container:{backend}',
                    *env, self.image)
        port = self.docker('port', backend, '8080').stdout.strip().rsplit(':', 1)[1]
        url = f'http://127.0.0.1:{port}/api/test/'
        for attempt in range(40):
            try:
                with urlopen(url, timeout=1) as response:
                    response.read()
                return url
            except (URLError, ConnectionError):
                time.sleep(.1)
        self.fail('Proxy did not become reachable')

    def request(self, url, scheme):
        with urlopen(Request(url, headers={'X-Forwarded-Proto': scheme}), timeout=3) as response:
            return response.read().decode()

    def test_local_proxy_overwrites_spoofed_forwarded_scheme(self):
        url = self.proxy()
        self.assertEqual(self.request(url, 'https'), 'http')

    def test_cloud_proxy_preserves_only_exact_https_from_trusted_alb(self):
        url = self.proxy(cloud=True)
        self.assertEqual(self.request(url, 'https'), 'https')
        self.assertEqual(self.request(url, 'https,http'), 'http')
        self.assertEqual(self.request(url, 'untrusted'), 'http')

    def test_rejects_invalid_configuration_before_nginx(self):
        cases = [
            ('FRONTEND_API_UPSTREAM=api:8000; include /tmp/evil;',),
            ('FRONTEND_TRUST_ALB_PROTO=yes',),
            ('FRONTEND_TRUST_ALB_PROTO=true',),
        ]
        for case in cases:
            with self.subTest(case=case):
                env = [part for value in case for part in ('-e', value)]
                result = self.docker('run', '--rm', *env, self.image, '-t', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('syntax is ok', result.stderr)


if __name__ == '__main__':
    unittest.main()
