"""One-command, after-close, no-broker live-paper evidence runner.

Run from any directory with:
    python "Stage 5D/live_paper/run_after_close.py" --config "Stage 5D/live_paper/config.json"
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

STAGE_ROOT = Path(__file__).resolve().parents[1]
REPO = STAGE_ROOT.parent
for _root in (STAGE_ROOT, REPO / "Stage 4A.3"):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from live_paper import SCHEMA_VERSION
from live_paper.admission import admission_status, available_slots
from live_paper.news_normalizer import normalize_article
from live_paper.news_provider import fetch_yfinance_news
from stage5d.allocator import allocate_candidates
from stage5d.ledger import Stage5DLedger, canonical_json, payload_sha256
from stage5d.management_store import Stage5D3Manager
from stage5d.news_ml_overlay import Stage5D4Overlay
from stage5d.source_contract import normalize_source_candidate
from stage5d.stage4a3_shadow_adapter import Stage4A3PredictionNotAvailable, Stage4A3ShadowAdapter
from stage5d.user_profile import ProfileStore

IST = ZoneInfo("Asia/Kolkata")


def require_after_close(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Production clock must be timezone-aware")
    local = now.astimezone(IST)
    if local.weekday() > 4 or local.time() < time(15, 45):
        raise RuntimeError("BEFORE_COMPLETED_NSE_SESSION")
    return local.date().isoformat()


def _utc(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _config(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError("A real Stage 5D.5 config.json is required; copy and edit config.example.json")
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("timezone") != "Asia/Kolkata":
        raise ValueError("timezone must be Asia/Kolkata")
    if config.get("preferred_horizon") not in {"ONE_MONTH", "THREE_MONTHS"}:
        raise ValueError("Only ONE_MONTH and THREE_MONTHS are supported")
    if config.get("news_provider") != "yfinance":
        raise ValueError("Only yfinance news_provider is supported")
    stage4a3_repo = config.get("stage4a3_runtime_repo")
    if stage4a3_repo not in (None, ""):
        stage4a3_repo = Path(str(stage4a3_repo)).expanduser().resolve()
        if not (stage4a3_repo / "Stage 4A.3/prospective/audit/activation_record.json").is_file():
            raise ValueError("stage4a3_runtime_repo must be an already activated Stage 4A.3 repository")
        config["stage4a3_runtime_repo"] = str(stage4a3_repo)
    from decimal import Decimal
    capital = Decimal(str(config["capital_ceiling_inr"]))
    if not capital.is_finite() or capital <= 0:
        raise ValueError("capital_ceiling_inr must be a positive finite amount")
    config["database_path"] = str(Path(config.get("database_path") or "Stage 5D/runtime/live_paper.sqlite3"))
    return config


def _database_path(config: dict, override: str | None) -> Path:
    name = override or config["database_path"]
    path = Path(name)
    return path if path.is_absolute() else REPO / path


def _profile(config: dict, runtime: Path):
    store = ProfileStore(runtime / "profiles")
    try:
        existing = store.load()
    except FileNotFoundError:
        existing = None
    from decimal import Decimal
    if (existing is None or existing.capital_ceiling_inr != Decimal(str(config["capital_ceiling_inr"]))
            or existing.preferred_horizon.value != config["preferred_horizon"]):
        return store.save(config["capital_ceiling_inr"], config["preferred_horizon"])
    return existing


def _assert_integrity(ledger: Stage5DLedger, manager: Stage5D3Manager, overlay: Stage5D4Overlay) -> None:
    for name, result in (("LEDGER", ledger.integrity_check()),
                         ("MANAGEMENT", manager.integrity_check()),
                         ("OVERLAY", overlay.integrity_check())):
        if not result["ok"]:
            raise RuntimeError(f"{name}_INTEGRITY_FAILURE: {result}")


def _initialize_runs(ledger: Stage5DLedger) -> None:
    with ledger.connection:
        ledger.connection.execute("""CREATE TABLE IF NOT EXISTS stage5d5_meta(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version TEXT NOT NULL)""")
        ledger.connection.execute("""CREATE TABLE IF NOT EXISTS stage5d5_live_runs(
            run_id TEXT PRIMARY KEY, market_session_date TEXT NOT NULL UNIQUE,
            run_started_utc TEXT NOT NULL, run_completed_utc TEXT NOT NULL,
            data_provider TEXT NOT NULL, market_data_hash TEXT NOT NULL,
            candidate_input_hash TEXT NOT NULL, candidate_count INTEGER NOT NULL,
            stage4a3_snapshot_id TEXT NOT NULL, allocation_run_id TEXT NOT NULL,
            management_session_run_id TEXT NOT NULL, recommendation_count INTEGER NOT NULL,
            news_status TEXT NOT NULL, canonical_payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL)""")
        existing_runs = ledger.connection.execute("SELECT count(*) FROM stage5d5_live_runs").fetchone()[0]
        row = ledger.connection.execute("SELECT schema_version FROM stage5d5_meta WHERE singleton=1").fetchone()
        if row is None:
            if existing_runs:
                raise RuntimeError("LIVE_RUN_INTEGRITY_FAILURE: missing Stage 5D.5 schema marker")
            ledger.connection.execute("INSERT INTO stage5d5_meta VALUES(1,?)", (SCHEMA_VERSION,))
        elif row[0] != SCHEMA_VERSION:
            raise RuntimeError("LIVE_RUN_INTEGRITY_FAILURE: unsupported Stage 5D.5 schema")


def verify_live_run_integrity(ledger: Stage5DLedger) -> None:
    """Verify every persisted Stage 5D.5 row, including its typed bindings."""
    fields = ("run_id", "market_session_date", "run_started_utc", "run_completed_utc",
              "data_provider", "market_data_hash", "candidate_input_hash", "candidate_count",
              "stage4a3_snapshot_id", "allocation_run_id", "management_session_run_id",
              "recommendation_count", "news_status")
    try:
        marker = ledger.connection.execute("SELECT schema_version FROM stage5d5_meta WHERE singleton=1").fetchone()
        if marker is None or marker[0] != SCHEMA_VERSION:
            raise ValueError("schema marker")
        if ledger.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity")
        if ledger.connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("foreign key integrity")
        previous = None
        seen = set()
        for row in ledger.connection.execute("SELECT * FROM stage5d5_live_runs ORDER BY market_session_date"):
            canonical = row["canonical_payload_json"]
            payload = json.loads(canonical)
            if (not isinstance(payload, dict) or canonical_json(payload) != canonical
                    or payload_sha256(canonical) != row["payload_sha256"]):
                raise ValueError("payload identity")
            for field in fields:
                if payload.get(field) != row[field]:
                    raise ValueError(f"typed binding: {field}")
            session = row["market_session_date"]
            if date.fromisoformat(session).isoformat() != session or session in seen or (previous and session <= previous):
                raise ValueError("ordered unique market sessions")
            seen.add(session)
            previous = session
    except Exception as exc:
        raise RuntimeError("LIVE_RUN_INTEGRITY_FAILURE") from exc


def _existing_run(ledger: Stage5DLedger, session: str):
    row = ledger.connection.execute("SELECT * FROM stage5d5_live_runs WHERE market_session_date=?", (session,)).fetchone()
    if row is None:
        return None
    if payload_sha256(row["canonical_payload_json"]) != row["payload_sha256"]:
        raise RuntimeError("LIVE_RUN_INTEGRITY_FAILURE")
    report = json.loads(row["canonical_payload_json"])
    for key, column in (("run_id", "run_id"), ("market_session_date", "market_session_date"),
                        ("market_data_hash", "market_data_hash"), ("candidate_input_hash", "candidate_input_hash"),
                        ("allocation_run_id", "allocation_run_id"),
                        ("management_session_run_id", "management_session_run_id")):
        if str(report[key]) != str(row[column]):
            raise RuntimeError("LIVE_RUN_TYPED_PAYLOAD_MISMATCH")
    return report


def _collect_news(ticker: str) -> tuple[list[dict], list[str], str]:
    """Keep provider failure separate from quarantine of individual articles."""
    try:
        articles, quarantined = fetch_yfinance_news(ticker)
        events = []
        for article in articles:
            try:
                events.append(normalize_article(article))
            except (ValueError, TypeError, KeyError) as exc:
                quarantined.append(f"NORMALIZATION_REJECTED:{type(exc).__name__}:{exc}")
        if not events:
            return events, quarantined, "NEWS_DATA_UNAVAILABLE"
        return events, quarantined, "AVAILABLE_WITH_QUARANTINE" if quarantined else "AVAILABLE"
    except Exception as exc:
        return [], [f"PROVIDER_FAILURE:{type(exc).__name__}:{exc}"], "NEWS_DATA_UNAVAILABLE"


def _persist_report_file(report: dict, runtime: Path) -> None:
    report_dir = runtime / "reports" / report["market_session_date"]
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / "live_paper_report.json"
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    if report_file.exists():
        if report_file.read_text(encoding="utf-8") != rendered:
            raise RuntimeError("CONFLICTING_SAME_SESSION_REPORT")
        return
    report_file.write_text(rendered, encoding="utf-8")


def _snapshot(session: str, now: datetime, protocol_repo: Path | None = None) -> tuple[Path, dict]:
    from stage4a3.protocol_integrity import verify_runtime_protocol_integrity

    protocol_repo = (protocol_repo or REPO).resolve()
    root = protocol_repo / "Stage 4A.3"
    activation_file = root / "prospective/audit/activation_record.json"
    if not activation_file.is_file():
        raise RuntimeError("PROSPECTIVE_COLLECTION_NOT_ACTIVATED")
    activation = json.loads(activation_file.read_text(encoding="utf-8"))
    verify_runtime_protocol_integrity(protocol_repo, root, activation)
    directory = root / "prospective" / "snapshots" / session[:4] / session
    verification_time = now.astimezone(timezone.utc)
    if not directory.exists():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root)
        subprocess.run([sys.executable, "-m", "stage4a3.prospective_runner", "--repo-root", str(protocol_repo)],
                       cwd=protocol_repo, env=env, check=True)
        verification_time = datetime.now(timezone.utc)
    metadata = json.loads((directory / "snapshot_metadata.json").read_text(encoding="utf-8"))
    created = datetime.fromisoformat(metadata["Snapshot Created UTC"].replace("Z", "+00:00"))
    if created > verification_time:
        raise RuntimeError("FUTURE_CREATED_SNAPSHOT")
    if metadata["Signal Date"] != session:
        raise RuntimeError("SNAPSHOT_MARKET_DATE_MISMATCH")
    adapter = Stage4A3ShadowAdapter(root)
    try:
        adapter.load_verified_prediction(
            {"signal_date": session, "signal_id": "S5D5_NONMATCHING_VERIFICATION_SENTINEL", "ticker": "SENTINEL.NS"},
            _utc(verification_time), directory)
    except Stage4A3PredictionNotAvailable:
        pass
    else:
        raise RuntimeError("SNAPSHOT_SENTINEL_COLLISION")
    return directory, metadata


def resolve_snapshot_input_cache(protocol_repo: Path, snapshot_dir: Path, metadata: dict) -> tuple[Path, dict]:
    """Bind a verified snapshot to its exact complete, read-only market CSV cache."""
    import pandas as pd

    root = protocol_repo / "Stage 4A.3"
    created = datetime.fromisoformat(metadata["Snapshot Created UTC"].replace("Z", "+00:00"))
    if created.tzinfo is None or created.utcoffset() is None:
        raise RuntimeError("SNAPSHOT_INPUT_CACHE_INCOMPLETE: creation timestamp has no timezone")
    cache = root / "prospective/input_cache" / created.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw = cache / "raw_market_data"
    if not raw.is_dir():
        raise RuntimeError("SNAPSHOT_INPUT_CACHE_MISSING")
    snapshot_manifest = json.loads((snapshot_dir / "candidate_input_manifest.json").read_text(encoding="utf-8"))
    universe = pd.read_csv(root / "prospective_universe.csv")
    expected = {"^NSEI", *universe["Ticker"].astype(str).tolist()}
    if set(snapshot_manifest["Per-Ticker Raw Hashes"]) != expected:
        raise RuntimeError("SNAPSHOT_INPUT_CACHE_INCOMPLETE: snapshot ticker set differs from frozen universe")
    # The frozen REFRESH loader first reads these files, then downloads only
    # when a cache frame is missing or empty. Prove that branch is unreachable.
    if not (raw / "yfinance_internal").is_dir():
        raise RuntimeError("SNAPSHOT_INPUT_CACHE_INCOMPLETE: yfinance cache directory missing")
    for ticker in expected:
        filename = ticker.replace("^", "INDEX_").replace("&", "AND") + ".csv"
        path = raw / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"SNAPSHOT_INPUT_CACHE_INCOMPLETE: {ticker}")
        try:
            frame = pd.read_csv(path, usecols=["Date"], parse_dates=["Date"])
            if frame.empty or frame["Date"].isna().all():
                raise ValueError("empty or invalid market dates")
        except (ValueError, KeyError, pd.errors.ParserError) as exc:
            raise RuntimeError(f"SNAPSHOT_INPUT_CACHE_INCOMPLETE: {ticker}") from exc
    return cache, snapshot_manifest


@contextmanager
def round_trip_market_csv_reads(snapshot_cache: Path):
    """Scope lossless float parsing to one verified raw-market cache only."""
    import pandas as pd

    raw_root = (snapshot_cache / "raw_market_data").resolve()
    original = pd.read_csv

    def scoped_read_csv(source, *args, **kwargs):
        if isinstance(source, (str, os.PathLike)):
            path = Path(source).resolve()
            if path.suffix.lower() == ".csv" and path.parent == raw_root:
                kwargs.setdefault("float_precision", "round_trip")
        return original(source, *args, **kwargs)

    pd.read_csv = scoped_read_csv
    try:
        yield
    finally:
        pd.read_csv = original


@contextmanager
def prohibit_market_downloads():
    """Make any reconstruction-time yfinance download attempt a hard failure."""
    import yfinance as yf

    original = yf.download

    def prohibited(*_args, **_kwargs):
        raise RuntimeError("SECOND_MARKET_REFRESH_PROHIBITED")

    yf.download = prohibited
    try:
        yield
    finally:
        yf.download = original


def _build_candidates(session: str, snapshot_dir: Path, protocol_repo: Path, metadata: dict):
    from stage4a3.candidate_input_builder import build_signal_close_input, verify_candidate_input
    from stage4a3.hashing import canonical_json_hash
    cache, snapshot_manifest = resolve_snapshot_input_cache(protocol_repo, snapshot_dir, metadata)
    with round_trip_market_csv_reads(cache), prohibit_market_downloads():
        frame, manifest, market = build_signal_close_input(protocol_repo, session, cache, "REFRESH")
    frozen_universe = json.loads((protocol_repo / "Stage 4A.3/results/stage4a3_frozen_universe_hash.json").read_text())
    verify_candidate_input(frame, manifest, frozen_universe["FROZEN_UNIVERSE_HASH"])
    if (manifest != snapshot_manifest or canonical_json_hash(manifest) != json.loads(
            (snapshot_dir / "snapshot_metadata.json").read_text(encoding="utf-8"))["Candidate Input Manifest Hash"]):
        raise RuntimeError("CANDIDATE_PROVENANCE_MISMATCH")
    snapshot_market = json.loads((snapshot_dir / "market_data_manifest.json").read_text(encoding="utf-8"))
    stable_fields = ("maximum_market_data_date", "nifty_maximum_date", "ticker_count_requested",
                     "ticker_count_received", "missing_tickers", "raw_data_logical_hash")
    if any(market[field] != snapshot_market[field] for field in stable_fields):
        raise RuntimeError("CANDIDATE_PROVENANCE_MISMATCH: market data manifest")
    if (manifest["Signal Date"] != session or manifest["Candidate Count"] != len(frame)
            or manifest["Candidate Count"] != metadata["Candidate Count"]
            or manifest["Raw Market Data Hash"] != snapshot_market["raw_data_logical_hash"]):
        raise RuntimeError("CANDIDATE_PROVENANCE_MISMATCH: snapshot identity")
    if (manifest["Signal Date"] != session or market["maximum_market_data_date"] != session
            or market["nifty_maximum_date"] != session):
        raise RuntimeError("MARKET_DATE_MISMATCH")
    if market["missing_tickers"] or market["ticker_count_received"] != market["ticker_count_requested"]:
        raise RuntimeError("INCOMPLETE_MARKET_DATA")
    sessions = list(dict.fromkeys(market["nifty_valid_sessions"]))
    if not sessions or sessions[-1] != session or len(sessions) < 2:
        raise RuntimeError("MISSING_COMPLETED_MARKET_SESSION")
    candidates = [normalize_source_candidate(row) for row in frame.to_dict("records")]
    if any(row["signal_date"] != session for row in candidates):
        raise RuntimeError("SCANNER_DATE_MISMATCH")
    if len({row["signal_id"] for row in candidates}) != len(candidates):
        raise RuntimeError("DUPLICATE_SCANNER_SIGNAL_ID")
    return candidates, manifest, snapshot_market, sessions[-2], cache


def _holding_observations(ledger: Stage5DLedger, session: str, snapshot_cache: Path,
                          candidate_manifest: dict):
    import pandas as pd
    from stage4a3.candidate_input_builder import BUILDER_FILES, _module
    from stage4a3.hashing import dataframe_content_hash

    stage221 = _module("stage5d5_frozen_stage221", REPO / BUILDER_FILES[1])
    stage21 = stage221.load_stage21_module(REPO / BUILDER_FILES[0])
    config = stage21.BacktestConfig()
    feature_engine = stage21.FeatureEngine(config)
    prices, observations = {}, []
    for position in ledger.derive_positions():
        ticker = position.ticker
        cache = snapshot_cache / "raw_market_data" / stage221.CandidateSignalEngine._cache_name(ticker)
        if not cache.is_file() or cache.stat().st_size == 0:
            raise RuntimeError(f"MISSING_REQUIRED_HOLDING_PRICE_CACHE: {ticker}")
        try:
            with round_trip_market_csv_reads(snapshot_cache):
                frame = pd.read_csv(cache, parse_dates=["Date"], index_col="Date")
            frame = stage21.normalize_index(frame)
        except Exception as exc:
            raise RuntimeError(f"MISSING_REQUIRED_HOLDING_PRICE_CACHE: {ticker}") from exc
        expected_hash = candidate_manifest.get("Per-Ticker Raw Hashes", {}).get(ticker)
        actual_hash = dataframe_content_hash(frame.reset_index()) if not frame.empty else None
        if expected_hash is None or actual_hash != expected_hash:
            raise RuntimeError(f"HOLDING_MARKET_DATA_PROVENANCE_MISMATCH: {ticker}")
        if frame.empty or pd.Timestamp(frame.index.max()).date().isoformat() != session:
            raise RuntimeError(f"MISSING_REQUIRED_HOLDING_PRICE_CACHE: {ticker}")
        if len(frame) < config.min_daily_history:
            raise RuntimeError(f"INCOMPLETE_HOLDING_HISTORY: {ticker}")
        features = feature_engine.add_stock_features(frame)
        row = features.iloc[-1]
        if pd.isna(row["ST"]) or pd.isna(row["SwingLow10"]):
            raise RuntimeError(f"MISSING_REQUIRED_MANAGEMENT_OBSERVATION: {ticker}")
        prices[ticker] = str(row["Close"])
        observations.append({"ticker": ticker, "session_date": session,
                             "open": str(row["Open"]), "high": str(row["High"]),
                             "low": str(row["Low"]), "close": str(row["Close"]),
                             "daily_supertrend": str(row["ST"]), "swing_low_10": str(row["SwingLow10"]),
                             "source_name": "STAGE4A3_SNAPSHOT_CACHE_FROZEN_STAGE2_1_FEATURE_ENGINE",
                             "source_data_hash": actual_hash})
    return prices, observations


def _previous_management_date(manager: Stage5D3Manager, actual_predecessor: str, session: str) -> str | None:
    row = manager.connection.execute("SELECT session_date FROM management_session_runs ORDER BY session_date DESC LIMIT 1").fetchone()
    if row is None:
        return None
    if row[0] == session:
        return manager.connection.execute(
            "SELECT json_extract(canonical_input_json,'$.previous_market_session_date') FROM management_session_runs WHERE session_date=?",
            (session,)).fetchone()[0]
    if row[0] != actual_predecessor:
        raise RuntimeError(f"MISSING_COMPLETED_MARKET_SESSION: expected {actual_predecessor}, latest {row[0]}")
    return actual_predecessor


def _run_with_clock(config_path: Path, *, db_override: str | None = None, now: datetime) -> dict:
    """Internal synthetic-fixture seam; production CLI never accepts a date."""
    started = now
    session = require_after_close(started)
    config = _config(config_path)
    database = _database_path(config, db_override)
    database.parent.mkdir(parents=True, exist_ok=True)
    runtime = REPO / "Stage 5D/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    profile = _profile(config, runtime)
    with Stage5DLedger(database) as ledger:
        manager, overlay = Stage5D3Manager(ledger), Stage5D4Overlay(ledger)
        _initialize_runs(ledger)
        verify_live_run_integrity(ledger)
        _assert_integrity(ledger, manager, overlay)
        protocol_repo = Path(config.get("stage4a3_runtime_repo") or REPO)
        snapshot_dir, snapshot_metadata = _snapshot(session, datetime.now(timezone.utc), protocol_repo)
        candidates, candidate_manifest, market_manifest, actual_previous, snapshot_cache = _build_candidates(
            session, snapshot_dir, protocol_repo, snapshot_metadata)
        existing = _existing_run(ledger, session)
        if existing:
            if (existing["market_data_hash"] != market_manifest["raw_data_logical_hash"]
                    or existing["candidate_input_hash"] != candidate_manifest["Full Input Logical Hash"]
                    or existing["candidate_count"] != len(candidates)
                    or existing["stage4a3_snapshot_id"] != snapshot_metadata["Snapshot ID"]
                    or existing["stage4a3_snapshot_content_hash"] != json.loads(
                        (snapshot_dir / "snapshot_manifest.json").read_text())["Snapshot Content Hash"]
                    or existing["profile_version"] != profile.profile_version
                    or existing["selected_horizon"] != profile.preferred_horizon.value
                    or existing["portfolio"]["capital_ceiling_inr"] != str(profile.capital_ceiling_inr)):
                raise RuntimeError("CONFLICTING_SAME_SESSION_EVIDENCE")
            _persist_report_file(existing, runtime)
            return existing | {"status": "IDEMPOTENT_SUCCESS"}
        prices, observations = _holding_observations(ledger, session, snapshot_cache, candidate_manifest)
        positions = ledger.build_allocator_open_positions(prices, as_of_date=session)
        pending = ledger.get_active_pending_reservations()
        predecessor = _previous_management_date(manager, actual_previous, session)
        management = manager.process_completed_session(session, observations, previous_market_session_date=predecessor)
        allocation = allocate_candidates(profile, positions, candidates,
                                         pending_entry_reservations=pending, decision_date=session)
        ledger.persist_allocation_result(allocation)
        adapter = Stage4A3ShadowAdapter(protocol_repo / "Stage 4A.3")
        recommendation_rows = []
        for recommendation in allocation.recommendations:
            ticker = str(recommendation["ticker"])
            events, quarantined, news_status = _collect_news(ticker)
            decision_cutoff = _utc(datetime.now(timezone.utc))
            result = overlay.evaluate_recommendation_overlay(
                str(recommendation["recommendation_id"]), decision_cutoff, events, adapter, snapshot_dir)
            if result["ml_influence"] != "NONE":
                raise RuntimeError("ML_PRODUCTION_INFLUENCE_BLOCKED")
            admission = admission_status(recommendation, result, news_status,
                                         (position.ticker for position in positions), pending)
            recommendation_rows.append({"recommendation": recommendation, "overlay": result,
                                        "news_status": news_status, "news_event_ids": [event["event_id"] for event in events],
                                        "quarantined_news": quarantined, "paper_admission": admission})
        _assert_integrity(ledger, manager, overlay)
        completed = _utc(datetime.now(timezone.utc))
        run_id = "S5D5_RUN_" + payload_sha256(canonical_json({
            "session": session, "market": market_manifest["raw_data_logical_hash"],
            "candidates": candidate_manifest["Full Input Logical Hash"],
            "profile_version": profile.profile_version, "snapshot": snapshot_metadata["Snapshot ID"]}))[:24]
        report = {
            "schema_version": SCHEMA_VERSION, "run_id": run_id, "market_session_date": session,
            "run_started_utc": _utc(started), "run_completed_utc": completed,
            "data_provider": market_manifest["provider_identifier"],
            "market_data_hash": market_manifest["raw_data_logical_hash"],
            "candidate_input_hash": candidate_manifest["Full Input Logical Hash"],
            "candidate_count": len(candidates),
            "stage4a3_snapshot_id": snapshot_metadata["Snapshot ID"],
            "stage4a3_snapshot_content_hash": json.loads((snapshot_dir / "snapshot_manifest.json").read_text())["Snapshot Content Hash"],
            "allocation_run_id": allocation.allocation_run_id,
            "profile_version": profile.profile_version,
            "selected_horizon": profile.preferred_horizon.value,
            "management_session_run_id": management["session_run_id"],
            "management": management, "recommendations": recommendation_rows,
            "recommendation_count": len(recommendation_rows),
            "news_status": ("NEWS_DATA_UNAVAILABLE" if any(row["news_status"] == "NEWS_DATA_UNAVAILABLE" for row in recommendation_rows)
                            else "AVAILABLE_WITH_QUARANTINE" if any(row["news_status"] == "AVAILABLE_WITH_QUARANTINE" for row in recommendation_rows)
                            else "AVAILABLE"),
            "portfolio": {"open_positions": len(positions), "active_pending": len(pending),
                          "available_slots": available_slots((item.ticker for item in positions), pending),
                          "capital_ceiling_inr": str(profile.capital_ceiling_inr),
                          "committed_capital_inr": str(sum((item.current_price_inr * item.quantity for item in positions), start=0)
                                                       + sum((item.reserved_capital_inr for item in pending), start=0))},
            "status": "CREATED", "ml_production_influence": "NO",
        }
        canonical = canonical_json(report)
        digest = payload_sha256(canonical)
        with ledger.connection:
            ledger.connection.execute("""INSERT INTO stage5d5_live_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, session, report["run_started_utc"], completed, report["data_provider"],
                 report["market_data_hash"], report["candidate_input_hash"], report["candidate_count"],
                 report["stage4a3_snapshot_id"], report["allocation_run_id"], report["management_session_run_id"],
                 report["recommendation_count"], report["news_status"], canonical, digest))
        _persist_report_file(report, runtime)
        return report


def run(config_path: Path, *, db_override: str | None = None) -> dict:
    """Production entry: always use the actual current clock."""
    return _run_with_clock(config_path, db_override=db_override, now=datetime.now(timezone.utc))


def render_report(report: dict) -> str:
    lines = [f"LIVE PAPER REPORT — {report['market_session_date']}", "=" * 64,
             f"Run: {report['run_id']} ({report['status']})", "NEW RECOMMENDATIONS"]
    for item in report["recommendations"]:
        rec, overlay = item["recommendation"], item["overlay"]
        lines += [f"\n{rec['ticker']} — {rec['recommendation_id']}",
                  f"Deterministic: {rec['deterministic_signal']} | Official paper: {overlay['official_paper_action']}",
                  f"Entry: ₹{rec.get('entry_low')} – ₹{rec.get('entry_high')} | Stop: ₹{rec.get('stop')}",
                  f"Targets: ₹{rec.get('target_1')} / ₹{rec.get('target_2')} | Quantity: {rec['recommended_quantity']}",
                  f"Horizon: {rec['selected_horizon']} | News: {overlay['news_risk_level']} / {overlay['news_action']} / {item['news_status']}",
                  f"ML shadow: {overlay['ml_shadow_classification']} | R3: {overlay['r3_score']} | Influence: NONE",
                  f"Paper admission: {item['paper_admission']}"]
    lines += ["\nCURRENT POSITIONS"]
    for state in report["management"]["states"]:
        lines += [f"{state['ticker']}: quantity={state['managed_quantity']} policy={state['management_policy_id']} "
                  f"sessions={state['bars_held']} decision={state['decision']} stop={state['effective_stop']} "
                  f"next_stop={state['next_session_stop']} target={state['active_target']}"]
    lines += ["\nEXIT / ACTION REQUIRED"]
    for state in report["management"]["states"]:
        if state["decision"] not in {"HOLD", "CLOSED_RECORDED"}:
            lines.append(f"{state['ticker']}: {state['decision']} reason={state['reason']} reference={state['reference_trigger_price']}")
    portfolio = report["portfolio"]
    lines += ["\nPORTFOLIO", f"Open={portfolio['open_positions']} Pending={portfolio['active_pending']} "
              f"Available slots={portfolio['available_slots']}",
              f"Capital ceiling=₹{portfolio['capital_ceiling_inr']} Committed=₹{portfolio['committed_capital_inr']}"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=STAGE_ROOT / "live_paper/config.json")
    parser.add_argument("--db", help="Override the live SQLite database path")
    args = parser.parse_args()
    try:
        print(render_report(run(args.config, db_override=args.db)))
    except Exception as exc:
        print(f"STAGE5D5_RUN_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
