"""Small bounded HTTPS transport for explicitly approved RSS endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import socket
import ssl
from typing import Callable

from .policy import EndpointPolicy, SEBI_ENDPOINT, SEBI_RSS_URL, validate_endpoint, validate_redirect


DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 15.0
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
    redirects: tuple[dict[str, object], ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ControlledHttpsTransport:
    """One-purpose transport; callers cannot supply an endpoint."""

    def __init__(self, *, endpoint: EndpointPolicy = SEBI_ENDPOINT,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 max_bytes: int = DEFAULT_MAX_BYTES, max_redirects: int | None = None,
                 connection_factory: Callable[..., http.client.HTTPSConnection] = http.client.HTTPSConnection):
        validate_endpoint(endpoint.url, endpoint)
        redirect_limit = endpoint.max_redirects if max_redirects is None else max_redirects
        if timeout_seconds <= 0 or max_bytes <= 0 or redirect_limit < 0:
            raise ValueError("INVALID_TRANSPORT_LIMIT")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = redirect_limit
        self.connection_factory = connection_factory
        self.request_count = 0
        self.redirect_history: list[dict[str, object]] = []
        self.final_url = endpoint.url

    def fetch(self) -> TransportResponse:
        self.redirect_history = []
        self.final_url = self.endpoint.url
        url = validate_endpoint(self.endpoint.url, self.endpoint)
        redirects = 0
        while True:
            validate_endpoint(url, self.endpoint)
            connection = self.connection_factory(self.endpoint.host, 443, timeout=self.timeout_seconds)
            self.request_count += 1
            try:
                connection.request("GET", self.endpoint.path, headers={
                    "User-Agent": self.endpoint.user_agent,
                    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9",
                    "Connection": "close",
                })
                response = connection.getresponse()
                headers = {name.casefold(): value.strip() for name, value in response.getheaders()}
                if response.status in REDIRECT_STATUSES:
                    if redirects >= self.max_redirects:
                        raise TransportFailure("REDIRECT_LIMIT_EXCEEDED")
                    try:
                        next_url = validate_redirect(url, headers.get("location", ""), self.endpoint)
                    except ValueError as exc:
                        raise TransportFailure(str(exc)) from exc
                    self.redirect_history.append({
                        "from_url": url, "status": response.status,
                        "location": headers.get("location", ""), "to_url": next_url,
                    })
                    url = next_url
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
                self.final_url = url
                return TransportResponse(
                    status=response.status,
                    headers=headers,
                    body=bytes(body),
                    retrieved_timestamp_utc=utc_now(),
                    final_url=url,
                    truncated=truncated,
                    redirects=tuple(self.redirect_history),
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
