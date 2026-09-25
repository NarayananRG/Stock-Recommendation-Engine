"""Fail-closed endpoint policy for the single Stage 6.1B live source."""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit


SEBI_RSS_SCHEME = "https"
SEBI_RSS_HOST = "www.sebi.gov.in"
SEBI_RSS_PATH = "/sebirss.xml"
SEBI_RSS_URL = f"{SEBI_RSS_SCHEME}://{SEBI_RSS_HOST}{SEBI_RSS_PATH}"
ALLOWED_REDIRECTS = 2


class EndpointPolicyError(ValueError):
    """The requested endpoint is outside the frozen connector allowlist."""


def validate_endpoint(url: str) -> str:
    if not isinstance(url, str) or not url:
        raise EndpointPolicyError("ENDPOINT_REQUIRED")
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != SEBI_RSS_SCHEME:
        raise EndpointPolicyError("HTTPS_REQUIRED")
    if parsed.username is not None or parsed.password is not None:
        raise EndpointPolicyError("ENDPOINT_USERINFO_PROHIBITED")
    try:
        port = parsed.port
    except ValueError as exc:
        raise EndpointPolicyError("ENDPOINT_PORT_PROHIBITED") from exc
    if port not in (None, 443):
        raise EndpointPolicyError("ENDPOINT_PORT_PROHIBITED")
    if (parsed.hostname or "").casefold() != SEBI_RSS_HOST:
        raise EndpointPolicyError("ENDPOINT_HOST_PROHIBITED")
    if parsed.path != SEBI_RSS_PATH:
        raise EndpointPolicyError("ENDPOINT_PATH_PROHIBITED")
    if parsed.query or parsed.fragment:
        raise EndpointPolicyError("ENDPOINT_SUFFIX_PROHIBITED")
    return SEBI_RSS_URL


def validate_redirect(current_url: str, location: str) -> str:
    validate_endpoint(current_url)
    if not isinstance(location, str) or not location.strip():
        raise EndpointPolicyError("REDIRECT_LOCATION_INVALID")
    return validate_endpoint(urljoin(current_url, location.strip()))
