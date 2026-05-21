"""Tiny resilient HTTP GET helper shared by the API clients."""
from __future__ import annotations

import time

import requests

DEFAULT_TIMEOUT = 20
DEFAULT_HEADERS = {
    # ESPN's undocumented endpoints reject requests without a browser-like UA.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def get_json(url: str, *, params: dict | None = None, retries: int = 3,
             timeout: int = DEFAULT_TIMEOUT, session: requests.Session | None = None):
    """GET a URL and return parsed JSON, retrying transient failures.

    Returns None on a 404 (treated as "no data") so callers can handle missing
    resources without exception handling at every call site.
    """
    sess = session or requests
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = sess.get(url, params=params, headers=DEFAULT_HEADERS, timeout=timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            if not resp.content:
                return None
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_exc}")
