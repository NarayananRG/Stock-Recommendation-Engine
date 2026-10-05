"""Explicit public-official downloader; never used by unit tests without a mock."""
from __future__ import annotations

import hashlib
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_DOMAINS = {"www.nseindia.com", "nsearchives.nseindia.com", "betanseapi.nseindia.com",
                   "betansearchives.nseindia.com", "www.niftyindices.com", "niftyindices.com",
                   "www.bseindia.com", "bseindia.com"}


def acquire(url: str, destination: str | Path, *, opener=urllib.request.urlopen,
            timeout: int = 30, minimum_interval_seconds: float = 1.0) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOMAINS:
        raise ValueError("SOURCE_DOMAIN_NOT_ALLOWLISTED")
    request = urllib.request.Request(url, headers={"User-Agent": "Stock-Recommendation-Engine research archival client/1.0"})
    with opener(request, timeout=timeout) as response:
        content = response.read()
    time.sleep(max(0.0, minimum_interval_seconds))
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {"url": url, "path": str(target), "byte_length": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "cookies_used": False,
            "captcha_bypass": False, "authentication_bypass": False}
