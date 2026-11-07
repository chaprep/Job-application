import base64
import asyncio
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import Settings
from backend.errors import BackendError
from backend.fetching import fetch_job_zyte


class ZyteTests(unittest.TestCase):
    url = 'https://voucherify.bamboohr.com/careers/82'
    html = '<main>Example is hiring an Engineer to build Python applications and maintain reliable services.</main>'

    def setUp(self):
        def dns(host, port, **kwargs):
            address = '127.0.0.1' if host in ('private.example', '127.0.0.1') else '93.184.216.34'
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]
        self.dns = patch('backend.fetching.socket.getaddrinfo', side_effect=dns)
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def fetch(self, data=None, status=200):
        payload = {'url': self.url, 'statusCode': 200, 'browserHtml': self.html} if data is None else data
        return fetch_job_zyte(self.url, 'secret', httpx.MockTransport(lambda req: httpx.Response(status, json=payload)))

    def test_request_and_rendered_content(self):
        def respond(request):
            self.assertEqual(str(request.url), 'https://api.zyte.com/v1/extract')
            self.assertEqual(request.method, 'POST')
            self.assertEqual(json.loads(request.content), {'url': self.url, 'browserHtml': True})
            self.assertEqual(request.headers['authorization'], 'Basic ' + base64.b64encode(b'secret:').decode())
            self.assertNotIn('secret', str(request.url))
            return httpx.Response(200, json={'url': self.url, 'statusCode': 200, 'browserHtml': self.html.replace('</main>', '<p hidden>HIDDEN</p></main>')})
        text = fetch_job_zyte(self.url, 'secret', httpx.MockTransport(respond))
        self.assertEqual(text, self.html.replace('</main>', '<p hidden>HIDDEN</p></main>'))
        structured = '<script type="application/ld+json">' + json.dumps({'@type': 'JobPosting', 'title': 'Engineer', 'description': self.html}) + '</script>'
        self.assertEqual(structured, self.fetch({'url': self.url, 'statusCode': 200, 'browserHtml': structured}))
        large_html = '<main>' + 'x'*150001 + '</main>'
        self.assertEqual(large_html, self.fetch({'url': self.url, 'statusCode': 200, 'browserHtml': large_html}))

    def test_missing_key_and_unsafe_input_do_not_call_provider(self):
        def unexpected(request):
            self.fail('Provider must not be contacted')
        transport = httpx.MockTransport(unexpected)
        with self.assertRaises(BackendError) as caught:
            fetch_job_zyte(self.url, '', transport)
        self.assertEqual(caught.exception.code, 'zyte_not_configured')
        for url in ('http://127.0.0.1/job', 'https://private.example/job', 'https://user:pass@example.com/job', 'file:///tmp/jd'):
            with self.subTest(url=url), self.assertRaises(BackendError):
                fetch_job_zyte(url, 'secret', transport)
        self.assertNotIn('secret', repr(Settings(zyte_api_key='secret')))

    def test_provider_failures_are_sanitized_and_not_retried(self):
        for status, code in ((401, 'zyte_auth_failed'), (403, 'zyte_auth_failed'), (429, 'zyte_rate_limited'), (500, 'zyte_provider_error'), (402, 'zyte_provider_error')):
            calls = []
            def respond(request):
                calls.append(request)
                return httpx.Response(status, text='secret provider diagnostic')
            with self.subTest(status=status), self.assertRaises(BackendError) as caught:
                fetch_job_zyte(self.url, 'secret', httpx.MockTransport(respond))
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('secret', caught.exception.message)
            self.assertEqual(len(calls), 1)

    def test_invalid_or_unusable_responses(self):
        for payload, code in (([], 'zyte_invalid_response'), ({}, 'zyte_invalid_response'),
                              ({'url': self.url, 'statusCode': 404, 'browserHtml': self.html}, 'job_fetch_failed'),
                              ({'url': 'http://private.example/job', 'statusCode': 200, 'browserHtml': self.html}, 'unsafe_job_url'),
                              ({'url': self.url, 'statusCode': 200, 'browserHtml': '  \n'}, 'job_html_unavailable')):
            with self.subTest(code=code), self.assertRaises(BackendError) as caught:
                self.fetch(payload)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(BackendError) as caught:
            fetch_job_zyte(self.url, 'secret', httpx.MockTransport(lambda req: httpx.Response(200, text='invalid json')))
        self.assertEqual(caught.exception.code, 'zyte_invalid_response')

    def test_size_and_time_limits(self):
        for constant, code in (('MAX_ZYTE_RESPONSE', 'zyte_response_too_large'), ('MAX_PAGE', 'job_page_too_large')):
            with patch('backend.fetching.' + constant, 10), self.assertRaises(BackendError) as caught:
                self.fetch()
            self.assertEqual(caught.exception.code, code)
        with patch('backend.fetching.ZYTE_TIMEOUT', 0), self.assertRaises(BackendError) as caught:
            self.fetch()
        self.assertEqual(caught.exception.code, 'zyte_timeout')
        for exception, code in ((httpx.ReadTimeout('secret'), 'zyte_timeout'), (httpx.ConnectError('secret'), 'zyte_network_error')):
            def respond(request):
                raise exception
            with self.subTest(code=code), self.assertRaises(BackendError) as caught:
                fetch_job_zyte(self.url, 'secret', httpx.MockTransport(respond))
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('secret', caught.exception.message)

    def test_total_deadline_cancels_slow_response(self):
        closed = []
        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    await asyncio.sleep(0.005)
                    yield b' '

            async def aclose(self):
                closed.append(True)

        with patch('backend.fetching.ZYTE_TIMEOUT', 0.03), self.assertRaises(BackendError) as caught:
            fetch_job_zyte(self.url, 'secret', httpx.MockTransport(lambda req: httpx.Response(200, stream=SlowStream())))
        self.assertEqual(caught.exception.code, 'zyte_timeout')
        self.assertTrue(closed)
