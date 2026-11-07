"""Public job retrieval through Zyte, plus the legacy DNS-pinned HTTP fetcher."""
from contextlib import closing
import asyncio
import ipaddress
import queue
import threading
import json
import logging
import re
import socket
import time
from urllib.parse import urlsplit, urljoin

import httpx
from bs4 import BeautifulSoup

from .errors import BackendError

MAX_PAGE = 5 * 1024 * 1024
MAX_ZYTE_RESPONSE = 20 * 1024 * 1024
ZYTE_TIMEOUT = 90


async def _zyte_response(url, api_key, timeout, transport):
    return await zyte_request({'url': url, 'browserHtml': True}, api_key, timeout, transport)


async def zyte_request(payload, api_key, timeout, transport=None, endpoint='extract'):
    # An overall timeout also bounds slow responses that keep sending small chunks.
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, transport=transport) as client:
            async with client.stream('POST', 'https://api.zyte.com/v1/' + endpoint,
                                     auth=httpx.BasicAuth(api_key, ''), timeout=timeout,
                                     json=payload) as response:
                if response.status_code in (401, 403):
                    raise BackendError('zyte_auth_failed', 'Zyte rejected authentication or account access. Check JAB_ZYTE_API_KEY and account status, or paste the full JD.', 502)
                if response.status_code == 429:
                    raise BackendError('zyte_rate_limited', 'Zyte rate limit reached. Retry later or paste the full JD.', 502, True)
                if response.status_code != 200:
                    raise BackendError('zyte_provider_error', f'Zyte returned HTTP {response.status_code}. Check account access and quota, or paste the full JD.', 502, response.status_code >= 500)
                chunks, length = [], 0
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    length += len(chunk)
                    if length > MAX_ZYTE_RESPONSE:
                        raise BackendError('zyte_response_too_large', 'Zyte response exceeds 20 MiB. Paste the full JD.', 502)
                    chunks.append(chunk)
                return b''.join(chunks)


def fetch_job_zyte(url, api_key, transport=None):
    """Retrieve rendered HTML unchanged for AI cleanup and extraction."""
    return fetch_page_zyte(url, api_key, transport)['browserHtml']


def fetch_page_zyte(url, api_key, transport=None, *, timeout=None):
    """Shared rendered-page retrieval; callers decide how to use the HTML."""
    if not api_key.strip():
        raise BackendError('zyte_not_configured', 'Set JAB_ZYTE_API_KEY in .env and restart to import job URLs, or paste the full JD.', 503)
    started = time.monotonic()
    deadline = started + (ZYTE_TIMEOUT if timeout is None else min(timeout, ZYTE_TIMEOUT))
    error_code = None
    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise BackendError('zyte_timeout', 'Job retrieval exceeded 90 seconds. Retry explicitly or paste the full JD.', 502, True)
        return seconds
    try:
        public_target(url, timeout=min(5, remaining()))
        raw = asyncio.run(_zyte_response(url, api_key, remaining(), transport))
        remaining()
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise BackendError('zyte_invalid_response', 'Zyte returned an unreadable response. Retry explicitly or paste the full JD.', 502) from exc
        if not isinstance(data, dict) or not isinstance(data.get('browserHtml'), str) or not isinstance(data.get('url'), str) or type(data.get('statusCode')) is not int:
            raise BackendError('zyte_invalid_response', 'Zyte did not return a rendered job page. Paste the full JD.', 502)
        public_target(data['url'], timeout=min(5, remaining()))
        if data['statusCode'] != 200:
            raise BackendError('job_fetch_failed', f'Job page returned HTTP {data["statusCode"]}. Check that the posting is active or paste the full JD.', 502)
        body = data['browserHtml']
        if len(body.encode('utf-8')) > MAX_PAGE:
            raise BackendError('job_page_too_large', 'Rendered job page exceeds 5 MiB. Paste the full JD.', 502)
        remaining()
        if not body.strip():
            raise BackendError('job_html_unavailable', 'Zyte returned empty HTML. Check the posting or paste the full JD.', 502)
        return data
    except (httpx.TimeoutException, TimeoutError) as exc:
        error_code = 'zyte_timeout'
        raise BackendError(error_code, 'Zyte retrieval timed out. Retry explicitly or paste the full JD.', 502, True) from exc
    except httpx.HTTPError as exc:
        error_code = 'zyte_network_error'
        raise BackendError(error_code, 'Could not contact Zyte. Retry explicitly or paste the full JD.', 502, True) from exc
    except BackendError as exc:
        error_code = exc.code
        raise
    finally:
        logging.getLogger('jab.tasks').info('provider=zyte duration_seconds=%.2f error=%s', time.monotonic() - started, error_code or 'none')


def public_target(url, timeout=5):
    try:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        if port != (443 if parts.scheme == 'https' else 80):
            raise ValueError()
        host = parts.hostname.encode('idna').decode('ascii')
        results = queue.Queue(maxsize=1)
        def resolve():
            try:
                results.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except OSError as exc:
                results.put(exc)
        threading.Thread(target=resolve, daemon=True).start()
        try:
            resolved = results.get(timeout=max(0.01, timeout))
        except queue.Empty as exc:
            raise OSError('DNS lookup timed out') from exc
        if isinstance(resolved, OSError):
            raise resolved
        addresses = {item[4][0] for item in resolved}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError()
    except (ValueError, UnicodeError, OSError) as exc:
        raise BackendError('unsafe_job_url', 'Use a public HTTP/HTTPS job URL on its standard port.') from exc
    return parts, host, port, sorted(addresses)[0]


def readable_html(html):
    """Keep paragraph/list boundaries without splitting inline emphasis into new lines."""
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup(['script', 'style', 'noscript', 'template', 'nav', 'footer', 'header']):
        node.decompose()
    for node in list(soup.find_all(True)):
        if node.attrs is None:
            continue
        style = (node.get('style') or '').replace(' ', '').lower()
        if node.has_attr('hidden') or node.get('aria-hidden') == 'true' or 'display:none' in style or 'visibility:hidden' in style:
            node.decompose()
    for node in soup.find_all(string=True):
        node.replace_with(re.sub(r'\s+', ' ', str(node)))
    for node in soup.find_all('br'):
        node.replace_with('\n')
    for node in soup.find_all('li'):
        node.insert(0, '- ')
        node.insert_before('\n')
    for node in soup.find_all(['p', 'div', 'section', 'article', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'table', 'tr']):
        node.insert_before('\n\n')
        node.insert_after('\n\n')
    text = soup.get_text(' ')
    text = '\n'.join(re.sub(r'[^\S\n]+', ' ', line).strip() for line in text.splitlines())
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def visible_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    postings = []
    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            kind = value.get('@type')
            if kind == 'JobPosting' or isinstance(kind, list) and 'JobPosting' in kind:
                postings.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (ValueError, RecursionError):
            continue
    if postings:
        job = postings[0]
        text = readable_html(str(job.get('description', '')))
        if text.strip():
            # Keep all advertised structured metadata, not only the description.
            return json.dumps({key: value for key, value in job.items() if key != 'description'}, ensure_ascii=False) + '\n' + text
    for node in soup(['script', 'style', 'noscript', 'template', 'nav', 'footer', 'header']):
        node.decompose()
    for node in list(soup.find_all(True)):
        if node.attrs is None:
            continue
        style = (node.get('style') or '').replace(' ', '').lower()
        if node.has_attr('hidden') or node.get('aria-hidden') == 'true' or 'display:none' in style or 'visibility:hidden' in style:
            node.decompose()
    main = soup.find('main') or soup.find('article') or soup
    return readable_html(str(main))


def fetch_job(url, transport=None):
    deadline = time.monotonic() + 20
    for redirect in range(4):
        parts, host, port, address = public_target(url, timeout=min(5, max(0.01, deadline - time.monotonic())))
        ip_host = f'[{address}]' if ':' in address else address
        pinned = f'{parts.scheme}://{ip_host}{parts.path or "/"}' + (f'?{parts.query}' if parts.query else '')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BackendError('job_fetch_timeout', 'Fetching exceeded 20 seconds. Paste the full JD instead.', 502, True)
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=remaining, transport=transport) as client:
                request = client.build_request('GET', pinned, headers={'Host': host, 'User-Agent': 'JabLocal/1.0', 'Accept': 'text/html,application/xhtml+xml,text/plain', 'Accept-Encoding': 'identity'})
                request.extensions['sni_hostname'] = host
                with closing(client.send(request, stream=True)) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if redirect == 3 or not response.headers.get('location'):
                            raise BackendError('job_redirect_limit', 'Too many job-page redirects. Paste the JD instead.', 502)
                        url = urljoin(url, response.headers['location'])
                        continue
                    if response.status_code != 200:
                        raise BackendError('job_fetch_failed', f'Job page returned HTTP {response.status_code}. Paste the JD instead.', 502, True)
                    mime = response.headers.get('content-type', '').split(';')[0].lower()
                    if mime not in ('text/html', 'application/xhtml+xml', 'text/plain'):
                        raise BackendError('job_page_type', 'The URL did not return a readable job page. Paste the JD instead.', 502)
                    chunks, length = [], 0
                    for chunk in response.iter_bytes(chunk_size=16384):
                        length += len(chunk)
                        if length > MAX_PAGE:
                            raise BackendError('job_page_too_large', 'Job page exceeds 5 MiB. Paste the JD instead.', 502)
                        if time.monotonic() > deadline:
                            raise BackendError('job_fetch_timeout', 'Fetching exceeded 20 seconds. Paste the JD instead.', 502, True)
                        chunks.append(chunk)
                    encoding = response.encoding or 'utf-8'
                    body = b''.join(chunks).decode(encoding, errors='replace')
        except httpx.HTTPError as exc:
            raise BackendError('job_fetch_failed', 'Could not retrieve the page. Paste the full JD instead.', 502, True) from exc
        result = body if mime == 'text/plain' else visible_text(body)
        if len(result.strip()) < 50:
            raise BackendError('job_text_unavailable', 'No usable full JD was found. Paste it manually; login and JavaScript pages may be unavailable.', 502)
        return result
    raise BackendError('job_fetch_failed', 'Paste the full JD instead.', 502)
