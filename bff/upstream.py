"""Server-owned mTLS transport. Never forwards browser headers or retries writes."""

import ssl

import httpx

from bff.config import ATS_URL, Settings, private_file


def tls_context(settings: Settings):
    # Inspect all mounted material, then load directly from operator-controlled files.
    for path in (settings.ca_file, settings.cert_file, settings.key_file):
        private_file(path)
    ctx = ssl.create_default_context(cafile=str(settings.ca_file))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(settings.cert_file), str(settings.key_file))
    return ctx


def client(settings: Settings):
    return httpx.AsyncClient(
        base_url=ATS_URL,
        verify=tls_context(settings),
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(connect=5, read=120, write=30, pool=5),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )
