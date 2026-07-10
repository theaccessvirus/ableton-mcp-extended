"""
Tiny HTTP client for the max-http-bridge running on Ableton's Master track.
Stdlib only (urllib) to avoid adding a dependency.
"""

import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:7500"


def get(path: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 5.0) -> dict:
    url = base_url.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def post(path: str, body: dict | None = None, base_url: str = DEFAULT_BASE_URL,
         timeout: float = 600.0) -> dict:
    url = base_url.rstrip("/") + path
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ping(base_url: str = DEFAULT_BASE_URL, timeout: float = 3.0) -> dict:
    """Returns the /ping response or raises urllib error if unreachable."""
    return get("/ping", base_url=base_url, timeout=timeout)
