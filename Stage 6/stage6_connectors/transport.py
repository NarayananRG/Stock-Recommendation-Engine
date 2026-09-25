"""Small bounded HTTPS transport for the fixed SEBI RSS endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import socket
import ssl
from typing import Callable

from .policy import ALLOWED_REDIRECTS, SEBI_RSS_HOST, SEBI_RSS_PATH, SEBI_RSS_URL, validate_endpoint, validate_redirect


DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 15.0
USER_AGENT = "Stock-Recommendation-Engine-Stage6.1B/1.0 (+controlled-SEBI-RSS-research)"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class TransportFailure(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}:{detail}")
        self.code = code


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    retrieved_timestamp_utc: str
    final_url: str = SEBI_RSS_URL
    truncated: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ControlledHttpsTransport:
    """One-purpose transport; callers cannot supply an endpoint."""

    def __init__(self, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 max_bytes: int = DEFAULT_MAX_BYTES, max_redirects: int = ALLOWED_REDIRECTS,
                 connection_factory: Callable[..., http.client.HTTPSConnection] = http.client.HTTPSConnection):
        if timeout_seconds <= 0 or max_bytes <= 0 or max_redirects < 0:
            raise ValueError("INVALID_TRANSPORT_LIMIT")
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.connection_factory = connection_factory
        self.request_count = 0

    def fetch(self) -> TransportResponse:
        url = validate_endpoint(SEBI_RSS_URL)
        redirects = 0
        while True:
            validate_endpoint(url)
            connection = self.connection_factory(SEBI_RSS_HOST, 443, timeout=self.timeout_seconds)
            self.request_count += 1
            try:
                connection.request("GET", SEBI_RSS_PATH, headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9",
                    "Connection": "close",
                })
                response = connection.getresponse()
                headers = {name.casefold(): value.strip() for name, value in response.getheaders()}
                if response.status in REDIRECT_STATUSES:
                    if redirects >= self.max_redirects:
                        raise TransportFailure("REDIRECT_LIMIT_EXCEEDED")
                    try:
                        url = validate_redirect(url, headers.get("location", ""))
                    except ValueError as exc:
                        raise TransportFailure(str(exc)) from exc
                    redirects += 1
                    continue
                body = bytearray()
                while True:
                    chunk = response.read(min(65536, self.max_bytes + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > self.max_bytes:
                        raise TransportFailure("RESPONSE_SIZE_LIMIT_EXCEEDED")
                content_length = headers.get("content-length")
                truncated = False
                if content_length is not None:
                    try:
                        truncated = int(content_length) != len(body)
                    except ValueError:
                        truncated = True
                return TransportResponse(
                    status=response.status,
                    headers=headers,
                    body=bytes(body),
                    retrieved_timestamp_utc=utc_now(),
                    final_url=url,
                    truncated=truncated,
                )
            except TransportFailure:
                raise
            except socket.timeout as exc:
                raise TransportFailure("TIMEOUT") from exc
            except socket.gaierror as exc:
                raise TransportFailure("DNS_FAILURE") from exc
            except ssl.SSLError as exc:
                raise TransportFailure("TLS_FAILURE") from exc
            except (ConnectionError, OSError, http.client.HTTPException) as exc:
                raise TransportFailure("NETWORK_FAILURE", type(exc).__name__) from exc
            finally:
                connection.close()
