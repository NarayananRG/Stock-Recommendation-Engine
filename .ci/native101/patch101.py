from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"{label} contract missing")
    return text.replace(old, new, 1)

official_module = r'''from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

TARGET_UNIVERSE_SIZE = 200
MIN_IDENTITY_COVERAGE = 0.98
MIN_HISTORY_COVERAGE = 0.95


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _key(value: Any) -> str:
    return " ".join(_clean(value).upper().replace("_", " ").split())


def _symbol(value: Any) -> str:
    raw = _clean(value).upper()
    if raw.endswith(".NS") or raw.endswith(".BO"):
        raw = raw[:-3]
    return raw


def _row_value(row: dict[str, Any], aliases: Iterable[str]) -> str:
    normalized = {_key(k): _clean(v) for k, v in row.items()}
    for alias in aliases:
        value = normalized.get(_key(alias), "")
        if value:
            return value
    return ""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _latest_csv(directories: list[Path]) -> Path | None:
    files: list[Path] = []
    for directory in directories:
        if directory.exists():
            files.extend(p for p in directory.glob("*.csv") if p.is_file())
    if not files:
        return None
    return sorted(files, key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)[0]


def _candidate_dirs(root: Path, relative_paths: list[str]) -> list[Path]:
    roots = [root]
    if root.parent != root:
        roots.append(root.parent)
    out: list[Path] = []
    for base in roots:
        for relative in relative_paths:
            path = (base / relative).resolve()
            if path not in out:
                out.append(path)
    return out


def _history_symbol(path: Path) -> str | None:
    name = path.name.upper()
    if name.startswith("INDEX_"):
        return None
    stem = path.stem.upper()
    if stem.endswith(".NS") or stem.endswith(".BO"):
        stem = stem[:-3]
    if stem.startswith("INDEX_") or stem in {"NSEI", "NIFTY", "NIFTY50", "NIFTY_50"}:
        return None
    return stem


class OfficialUniverseCatalog:
    @classmethod
    def inspect(cls, root: Path, history_files: Iterable[Path] = ()) -> dict[str, Any]:
        root = Path(root).expanduser().resolve()
        constituent_file = _latest_csv(
            _candidate_dirs(
                root,
                [
                    "data/official/nifty200",
                    "data/official/nse/nifty200",
                    "data/external_authoritative/nifty_constituents",
                    "NextGen Research/data/external_authoritative/nifty_constituents",
                ],
            )
        )
        master_file = _latest_csv(
            _candidate_dirs(
                root,
                [
                    "data/official/nse/security_master",
                    "data/external_authoritative/nse_security_master",
                    "NextGen Research/data/external_authoritative/nse_security_master",
                ],
            )
        )

        if constituent_file is None:
            return {
                "official_universe_status": "OFFICIAL_UNIVERSE_NOT_CONNECTED",
                "official_universe_mode": "NONE",
                "official_universe_target": TARGET_UNIVERSE_SIZE,
                "official_universe_members": 0,
                "identity_mapped": 0,
                "identity_coverage": 0.0,
                "history_covered_members": 0,
                "history_coverage": 0.0,
                "universe_ready": False,
                "analysis_universe_ready": False,
                "official_universe_source": None,
                "security_master_source": str(master_file) if master_file else None,
                "missing_identity_symbols": [],
                "missing_history_symbols": [],
                "duplicate_symbols": [],
                "duplicate_isins": [],
                "authority": "DATA_FOUNDATION_ONLY_NO_SCORE_CHANGE",
            }

        master_by_symbol: dict[str, dict[str, str]] = {}
        duplicate_master_symbols: set[str] = set()
        if master_file is not None:
            for row in _read_csv(master_file):
                symbol = _symbol(_row_value(row, ["SYMBOL", "SECURITY SYMBOL", "TICKER"]))
                if not symbol:
                    continue
                item = {
                    "symbol": symbol,
                    "isin": _row_value(row, ["ISIN NUMBER", "ISIN CODE", "ISIN"]),
                    "series": _row_value(row, ["SERIES", "SECURITY SERIES"]),
                    "company_name": _row_value(row, ["NAME OF COMPANY", "COMPANY NAME", "COMPANY"]),
                }
                if symbol in master_by_symbol:
                    duplicate_master_symbols.add(symbol)
                else:
                    master_by_symbol[symbol] = item

        members: list[dict[str, str]] = []
        seen_symbols: set[str] = set()
        duplicate_symbols: set[str] = set()
        for row in _read_csv(constituent_file):
            symbol = _symbol(_row_value(row, ["SYMBOL", "SECURITY SYMBOL", "TICKER"]))
            if not symbol:
                continue
            if symbol in seen_symbols:
                duplicate_symbols.add(symbol)
                continue
            seen_symbols.add(symbol)
            master = master_by_symbol.get(symbol, {})
            series = _row_value(row, ["SERIES", "SECURITY SERIES"]) or master.get("series", "")
            if series and series.upper() not in {"EQ", "BE"}:
                continue
            members.append(
                {
                    "symbol": symbol,
                    "isin": _row_value(row, ["ISIN CODE", "ISIN NUMBER", "ISIN"]) or master.get("isin", ""),
                    "series": series or "EQ",
                    "company_name": _row_value(row, ["COMPANY NAME", "NAME OF COMPANY", "COMPANY"]) or master.get("company_name", ""),
                    "industry": _row_value(row, ["INDUSTRY", "SECTOR", "MACRO ECONOMIC SECTOR"]),
                }
            )

        history_symbols = {s for p in history_files if (s := _history_symbol(Path(p)))}
        member_symbols = {item["symbol"] for item in members}
        mapped = [item for item in members if item["isin"]]
        missing_identity = sorted(item["symbol"] for item in members if not item["isin"])
        missing_history = sorted(member_symbols - history_symbols)

        isins = [item["isin"].upper() for item in mapped if item["isin"]]
        isin_counts: dict[str, int] = {}
        for isin in isins:
            isin_counts[isin] = isin_counts.get(isin, 0) + 1
        duplicate_isins = sorted(isin for isin, count in isin_counts.items() if count > 1)
        identity_coverage = (len(mapped) / len(members)) if members else 0.0
        history_covered = len(member_symbols & history_symbols)
        history_coverage = (history_covered / len(members)) if members else 0.0
        count_ok = 190 <= len(members) <= 210
        universe_ready = (
            count_ok
            and identity_coverage >= MIN_IDENTITY_COVERAGE
            and not duplicate_symbols
            and not duplicate_isins
            and not duplicate_master_symbols
        )
        analysis_ready = universe_ready and history_coverage >= MIN_HISTORY_COVERAGE

        if not universe_ready:
            status = "OFFICIAL_NIFTY200_IDENTITY_GAP"
        elif not analysis_ready:
            status = "OFFICIAL_NIFTY200_HISTORY_GAP"
        else:
            status = "OFFICIAL_NIFTY200_READY"

        return {
            "official_universe_status": status,
            "official_universe_mode": "NIFTY_200_OFFICIAL",
            "official_universe_target": TARGET_UNIVERSE_SIZE,
            "official_universe_members": len(members),
            "identity_mapped": len(mapped),
            "identity_coverage": round(identity_coverage, 6),
            "history_covered_members": history_covered,
            "history_coverage": round(history_coverage, 6),
            "universe_ready": universe_ready,
            "analysis_universe_ready": analysis_ready,
            "official_universe_source": str(constituent_file),
            "security_master_source": str(master_file) if master_file else None,
            "missing_identity_symbols": missing_identity[:25],
            "missing_history_symbols": missing_history[:25],
            "duplicate_symbols": sorted(duplicate_symbols)[:25],
            "duplicate_master_symbols": sorted(duplicate_master_symbols)[:25],
            "duplicate_isins": duplicate_isins[:25],
            "members": members,
            "authority": "DATA_FOUNDATION_ONLY_NO_SCORE_CHANGE",
        }

    @classmethod
    def symbols(cls, root: Path, history_files: Iterable[Path] = ()) -> list[str]:
        status = cls.inspect(root, history_files)
        return [item["symbol"] for item in status.get("members", [])]
'''

module_path = root / "stock_app" / "official_universe.py"
module_path.write_text(official_module, encoding="utf-8")

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = repl(
    s,
    'APP_VERSION = "0.9.10-phase3-foundation"',
    'APP_VERSION = "0.9.11-phase3b-official-data"',
    "Phase 3B app version",
)

anchor = '''    def _inspect_data_repo(self, root: Path) -> dict[str, Any]:
'''
helper = '''    @staticmethod
    def _phase3b_official_universe_status(root: Path, equity_files: list[Path]) -> dict[str, Any]:
        from stock_app.official_universe import OfficialUniverseCatalog

        return OfficialUniverseCatalog.inspect(root, equity_files)

'''
if helper not in s:
    if anchor not in s:
        raise RuntimeError("Phase 3B official universe insertion point missing")
    s = s.replace(anchor, helper + anchor, 1)

old = '''            "provenance": provenance,
            **self._phase3_freshness_contract(latest, data_mode),
'''
new = '''            "provenance": provenance,
            **self._phase3_freshness_contract(latest, data_mode),
            **self._phase3b_official_universe_status(root, equity_files),
'''
s = repl(s, old, new, "Phase 3B repository status")
api.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
fn_start = t.index("function dataSourceLabel(ds){")
candidates = [
    t.find("\nfunction ", fl_start + 1),
    t.find("\nasync function ", fn_start + 1),
]
fn_end = min(pos for pos in candidates if pos > fn_start) if any(pos > fl_start for pos in candidates) else -1
if fn_end < 0:
    raise RuntimeError("Phase 3B data-source label end marker missing")
new_fn = """function dataSourceLabel(ds){const a=ds?.active||{},idx=+a.index_files||0,extra=idx?(' · '+idx+' market index'++idx===1?'':'es')):'';const gate=a.freshness_gate||'FAIL',fresh=a.freshness_status||'UNAVAILABLE',freshTag=' · freshness '+gate+'/'+fresh;const u=+a.official_universe_members||0,im=+a.identity_mapped||0,hc=+a.history_covered_members||0,ut=+a.official_universe_target||200,universeTag=u?(' · NIFTY 200 '+u+'/'+ut+' · ISIN '+im+'/'+u+' · history '+hc+'/'+u):'';if(ds?.mode==='REAL_OFFICIAL_DATA')return 'Official NSE OHLCV · '+(a.stock_files||0)+' equities'+extra+' · '+(a.latest_session||'—')+freshTag+universeTag;if(ds?.mode==='REAL_FROZEN_HISTORY')return 'Frozen historical OHLCV · '+(a.stock_files||0)+' equities'+extra+' · '+(a.latest_session||'—')+freshTag+universeTag;return 'No real OHLCV repository connected · freshness FAIL/UNAVAILABLE'+universeTag;}"""
t = t[:fn_start] + new_fn + t[fn_end:]
js.write_text(t, encoding="utf-8")

phase_dir = root / "phase3"
phase_dir.mkdir(parents=True, exist_ok=True)
(phase_dir / "official_market_data_contract_v1.json").write_text(
    """{
  "schema": "SRE_PHASE3B_OFFICIAL_MARKET_DATA_CONTRACT_V1",
  "version": "0.9.11-phase3b-official-data",
  "universe": {
    "name": "NIFTY 200",
    "target_members": 200,
    "minimum_identity_coverage": 0.98,
    "minimum_history_coverage": 0.95,
    "identity_keys": ["symbol", "ISIN"],
    "series": ["EQ", "BE"]
  },
  "source_precedence": [
    "Official NSE/NSE Indices local data",
    "Existing verified official normalized cache",
    "Frozen deterministic history for testing only"
  ],
  "automatic_yfinance_fallback": false,
  "authority": "DATA_FOUNDATION_ONLY_NO_SCORE_CHANGE",
  "promotion_rule": "Universe expansion must not change model or recommendation authority by itself."
}
""",
    encoding="utf-8",
)

assert 'APP_VERSION = "0.9.11-phase3b-official-data"' in api.read_text(encoding="utf-8")
assert "OfficialUniverseCatalog" in module_path.read_text(encoding="utf-8")
assert "NIFTY 200" in js.read_text(encoding="utf-8")
print("0.9.11 Phase 3B official data foundation patch applied")
