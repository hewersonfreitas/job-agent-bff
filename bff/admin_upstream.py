"""Server-owned bearer transport to the API's private administration network."""

import httpx

ADMIN_URL = "http://api:8765"


def client(transport=None):
    return httpx.AsyncClient(
        base_url=ADMIN_URL,
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(connect=5, read=30, write=10, pool=5),
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
    )
