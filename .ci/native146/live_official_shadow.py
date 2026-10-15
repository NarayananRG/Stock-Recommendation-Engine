from __future__ import annotations

import json
import os
import sys
from pathlib import Path


engine = Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0, str(engine))
from modern_ui.api import ModernAppContext  # noqa: E402
from stock_app import official_daily_refresh as refresh  # noqa: E402


expected = ModernAppContext.expected_market_session()["expected_market_session"]
result = {
    "schema": "SRE_OFFICIAL_LIVE_SHADOW_V1",
    "expected_session": expected,
    "automatic_yfinance_fallback": False,
    "mutates_cache": False,
}
try:
    payload, meta = refresh._download_candidates(refresh._bhavcopy_candidates(expected))
    rows, parsed = refresh._parse_bhav(payload, expected)
    result["equity"] = {
        "status": "AVAILABLE",
        "session": parsed.get("equity_session"),
        "rows": len(rows),
        "http_status": meta.get("http_status"),
        "payload_size": meta.get("payload_size"),
        "provider": "NSE_OFFICIAL_CM_UDIFF",
    }
except refresh.OfficialDataNotReady as exc:
    result["equity"] = {"status": "NOT_YET_PUBLISHED", "reason": str(exc)}
except Exception as exc:
    result["equity"] = {"status": "ERROR", "reason": f"{type(exc).__name__}:{exc}"}
    print(json.dumps(result, indent=2))
    raise

try:
    _, session, meta = refresh._fetch_index(expected)
    result["index"] = {
        "status": "AVAILABLE",
        "session": session,
        "http_status": meta.get("http_status"),
        "payload_size": meta.get("payload_size"),
        "provider": "NSE_OFFICIAL_INDEX_REPORT_OR_API",
    }
except refresh.OfficialDataNotReady as exc:
    result["index"] = {"status": "NOT_YET_PUBLISHED", "reason": str(exc)}
except Exception as exc:
    result["index"] = {"status": "ERROR", "reason": f"{type(exc).__name__}:{exc}"}
    print(json.dumps(result, indent=2))
    raise

equity_session = (result.get("equity") or {}).get("session")
index_session = (result.get("index") or {}).get("session")
result["status"] = "READY" if equity_session == expected and index_session == expected else "NOT_YET_PUBLISHED"
print(json.dumps(result, indent=2))
