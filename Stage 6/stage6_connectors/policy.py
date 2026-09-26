"""Fail-closed endpoint policy for the two approved official RSS sources."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit


SEBI_RSS_SCHEME = "https"
SEBI_RSS_HOST = "www.sebi.gov.in"
SEBI_RSS_PATH = "/sebirss.xml"
SEBI_RSS_URL = f"{SEBI_RSS_SCHEME}://{SEBI_RSS_HOST}{SEBI_RSS_PATH}"
RBI_RSS_SCHEME = "https"
RBI_RSS_HOST = "rbi.org.in"
RBI_RSS_PATH = "/pressreleases_rss.xml"
RBI_RSS_URL = f"{RBI_RSS_SCHEME}://{RBI_RSS_HOST}{RBI_RSS_PATH}"
ALLOWED_REDIRECTS = 2


class EndpointPolicyError(ValueError):
    """The requested endpoint is outside the frozen connector allowlist."""


@dataclass(frozen=True)
class EndpointPolicy:
    source_id: str
    scheme: str
    host: str
    path: str
    user_agent: str
    max_redirects: int = ALLOWED_REDIRECTS

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.host}{self.path}"


SEBI_ENDPOINT = EndpointPolicy(
    source_id="SEBI_OFFICIAL_RSS", scheme=SEBI_RSS_SCHEME, host=SEBI_RSS_HOST, path=SEBI_RSS_PATH,
    user_agent="Stock-Recommendation-Engine-Stage6.1B/1.0 (+controlled-SEBI-RSS-research)",
)
RBI_ENDPOINT = EndpointPolicy(
    source_id="RBI_OFFICIAL_PRESS_RELEASES_RSS", scheme=RBI_RSS_SCHEME, host=RBI_RSS_HOST, path=RBI_RSS_PATH,
    user_agent="Stock-Recommendation-Engine-Stage6.1C/1.0 (+controlled-RBI-RSS-research)",
)
APPROVED_ENDPOINTS = (SEBI_ENDPOINT, RBI_ENDPOINT)


def endpoint_for_source(source_id: str) -> EndpointPolicy:
    matches = [endpoint for endpoint in APPROVED_ENDPOINTS if endpoint.source_id == source_id]
    if len(matches) != 1:
        raise EndpointPolicyError("SOURCE_ENDPOINT_NOT_APPROVED")
    return matches[0]


def _approved(endpoint: EndpointPolicy) -> EndpointPolicy:
    if endpoint not in APPROVED_ENDPOINTS:
        raise EndpointPolicyError("SOURCE_ENDPOINT_NOT_APPROVED")
    return endpoint


def validate_endpoint(url: str, endpoint: EndpointPolicy = SEBI_ENDPOINT) -> str:
    endpoint = _approved(endpoint)
    if not isinstance(url, str) or not url:
        raise EndpointPolicyError("ENDPOINT_REQUIRED")
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != endpoint.scheme:
        raise EndpointPolicyError("HTTPS_REQUIRED")
    if parsed.username is not None or parsed.password is not None:
        raise EndpointPolicyError("ENDPOINT_USERINFO_PROHIBITED")
    try:
        port = parsed.port
    except ValueError as exc:
        raise EndpointPolicyError("ENDPOINT_PORT_PROHIBITED") from exc
    if port not in (None, 443):
        raise EndpointPolicyError("ENDPOINT_PORT_PROHIBITED")
    if (parsed.hostname or "").casefold() != endpoint.host:
        raise EndpointPolicyError("ENDPOINT_HOST_PROHIBITED")
    if parsed.path != endpoint.path:
        raise EndpointPolicyError("ENDPOINT_PATH_PROHIBITED")
    if parsed.query or parsed.fragment:
        raise EndpointPolicyError("ENDPOINT_SUFFIX_PROHIBITED")
    return endpoint.url


def validate_redirect(current_url: str, location: str, endpoint: EndpointPolicy = SEBI_ENDPOINT) -> str:
    validate_endpoint(current_url, endpoint)
    if not isinstance(location, str) or not location.strip():
        raise EndpointPolicyError("REDIRECT_LOCATION_INVALID")
    return validate_endpoint(urljoin(current_url, location.strip()), endpoint)
