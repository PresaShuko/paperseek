"""Shared Community transport policy for source and writing model clients."""
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx


def create_http_client(routes: list[dict]) -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=16)
    mounts = {}
    for route in routes:
        url = urlsplit(route.get("base_url") or "")
        try:
            loopback = url.hostname == "localhost" or ip_address(url.hostname or "").is_loopback
        except ValueError:
            loopback = False
        if loopback:
            mounts[f"{url.scheme}://{url.netloc}"] = httpx.AsyncHTTPTransport(limits=limits)
    return httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=180, write=30, pool=10),
                             limits=limits, mounts=mounts)
