"""Bounded research-only client for NSE's documented public Bhavcopy MCP."""
from __future__ import annotations

import json
from urllib.request import Request, urlopen

ENDPOINT = "https://mcp.nseindia.in/bhavcopy/cm/mcp"
PROTOCOL = "2025-03-26"
MAX_MONTHS_PER_CALL = 3
AUTHORITY = "SHADOW_ONLY"


class NseBhavcopyMcpClient:
    """Small standards-based adapter; never used by production or trading code."""

    def __init__(self, opener=urlopen, endpoint: str = ENDPOINT):
        if endpoint != ENDPOINT:
            raise ValueError("OFFICIAL_DOCUMENTED_MCP_ENDPOINT_REQUIRED")
        self.opener = opener
        self.session_id = None

    def _post(self, payload: dict) -> tuple[dict, dict]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "User-Agent": "Stock-Recommendation-Engine research-only official-source adapter"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = Request(ENDPOINT, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with self.opener(request, timeout=30) as response:
            raw = response.read().decode()
            response_headers = dict(response.headers.items())
        if raw.startswith("event:"):
            line = next((x[5:] for x in raw.splitlines() if x.startswith("data:")), None)
            if line is None:
                raise ValueError("MCP_RESPONSE_INVALID")
            raw = line
        return json.loads(raw), response_headers

    def initialize(self) -> dict:
        result, headers = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "stock-recommendation-engine-research", "version": "1.0"}}})
        self.session_id = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
        if not self.session_id or result.get("result", {}).get("serverInfo", {}).get("name") != "nse-bhavcopy-redis-mcp":
            raise ValueError("OFFICIAL_MCP_INITIALIZATION_FAILED")
        return result
    def stock_history(self, *, symbol: str, months: int, end_date: str) -> dict:
        if not self.session_id:
            raise ValueError("MCP_NOT_INITIALIZED")
        if not symbol or symbol != symbol.upper() or not 1 <= months <= MAX_MONTHS_PER_CALL:
            raise ValueError("BOUNDED_MCP_REQUEST_REQUIRED")
        result, _ = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "get_stock_history", "arguments": {"symbol": symbol, "months": months, "endDate": end_date}}})
        return result
