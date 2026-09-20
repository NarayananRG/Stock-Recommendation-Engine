from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ledger import OperationResult, Stage5DLedger, canonical_json, payload_sha256
from .source_contract import canonical_date
from .stage4a3_shadow_adapter import (
    FROZEN_MODEL_BUNDLE_HASH as FROZEN_ML_MODEL_BUNDLE_HASH,
    FROZEN_PROTOCOL_COMMIT as FROZEN_ML_PROTOCOL_COMMIT,
    FROZEN_PROTOCOL_ID as FROZEN_ML_PROTOCOL_ID,
    PRIMARY_COMPARATOR,
    PRIMARY_POLICY,
    Stage4A3ShadowAdapter,
)

STAGE5D4_SCHEMA_VERSION = "STAGE5D4_SCHEMA_V2"
STAGE5D4_TABLES = ("stage5d4_meta", "stage5d4_news_events", "stage5d4_ml_predictions", "stage5d4_decision_overlays")
NEWS_CATEGORIES = frozenset({"EARNINGS", "GUIDANCE", "REGULATORY", "LEGAL", "GOVERNANCE", "FRAUD_ALLEGATION", "PROMOTER", "MANAGEMENT_CHANGE", "CREDIT_RATING", "DEBT_LIQUIDITY", "LARGE_ORDER", "ORDER_CANCELLATION", "CORPORATE_ACTION", "M_AND_A", "CAPITAL_RAISE", "PRODUCT", "MACRO_SECTOR", "OTHER"})
NEWS_SEVERITIES = ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL")
NEWS_SENTIMENTS = frozenset({"POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"})
ML_CLASSES = frozenset({"R3_K1_SELECTED", "R3_K1_NOT_SELECTED", "ML_NOT_AVAILABLE"})
REASON_BY_CATEGORY = {
    "REGULATORY": "MATERIAL_REGULATORY_RISK", "LEGAL": "MATERIAL_LEGAL_RISK", "GOVERNANCE": "GOVERNANCE_RISK",
    "FRAUD_ALLEGATION": "GOVERNANCE_RISK", "CREDIT_RATING": "CREDIT_DETERIORATION", "DEBT_LIQUIDITY": "LIQUIDITY_RISK",
    "EARNINGS": "EARNINGS_MISS", "GUIDANCE": "GUIDANCE_CUT", "PROMOTER": "PROMOTER_RISK",
    "ORDER_CANCELLATION": "ORDER_CANCELLATION", "MANAGEMENT_CHANGE": "MANAGEMENT_UNCERTAINTY",
}

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS stage5d4_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version TEXT NOT NULL, created_at_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS stage5d4_news_events(
        event_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, headline TEXT NOT NULL, source TEXT NOT NULL, source_url TEXT,
        published_at_utc TEXT NOT NULL, observed_at_utc TEXT NOT NULL, event_date TEXT NOT NULL, category TEXT NOT NULL,
        sentiment TEXT NOT NULL, severity TEXT NOT NULL, materiality TEXT NOT NULL, confidence TEXT NOT NULL,
        summary TEXT NOT NULL, source_hash TEXT, canonical_payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
        persisted_at_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS stage5d4_ml_predictions(
        ml_prediction_id TEXT PRIMARY KEY, recommendation_id TEXT NOT NULL REFERENCES recommendations(recommendation_id),
        signal_id TEXT NOT NULL, ticker TEXT NOT NULL, protocol_id TEXT NOT NULL, protocol_commit TEXT NOT NULL,
        model_bundle_hash TEXT NOT NULL, snapshot_id TEXT NOT NULL, snapshot_signal_date TEXT NOT NULL,
        snapshot_content_hash TEXT NOT NULL, snapshot_created_utc TEXT NOT NULL, snapshot_chain_hash TEXT NOT NULL,
        r0_score TEXT NOT NULL, r0_same_date_rank INTEGER NOT NULL, r0_k1_selected INTEGER NOT NULL,
        r3_score TEXT NOT NULL, r3_same_date_rank INTEGER NOT NULL, r3_k1_selected INTEGER NOT NULL,
        primary_policy TEXT NOT NULL, primary_comparator TEXT NOT NULL, ml_shadow_classification TEXT NOT NULL,
        experimental_action TEXT NOT NULL, ml_influence TEXT NOT NULL, canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL, persisted_at_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS stage5d4_decision_overlays(
        overlay_id TEXT PRIMARY KEY, recommendation_id TEXT NOT NULL REFERENCES recommendations(recommendation_id),
        signal_id TEXT NOT NULL, ticker TEXT NOT NULL, decision_date TEXT NOT NULL, decision_cutoff_utc TEXT NOT NULL,
        deterministic_action TEXT NOT NULL, news_risk_level TEXT NOT NULL, news_action TEXT NOT NULL,
        news_reason_codes_json TEXT NOT NULL, news_event_ids_json TEXT NOT NULL, material_event_count INTEGER NOT NULL,
        latest_material_event_time TEXT, news_summary TEXT NOT NULL, official_paper_action TEXT NOT NULL,
        ml_protocol_id TEXT, ml_prediction_id TEXT REFERENCES stage5d4_ml_predictions(ml_prediction_id), ml_snapshot_id TEXT,
        ml_snapshot_content_hash TEXT, r0_score TEXT, r0_same_date_rank INTEGER, r0_k1_selected INTEGER,
        r3_score TEXT, r3_same_date_rank INTEGER, r3_k1_selected INTEGER, ml_shadow_classification TEXT NOT NULL,
        ml_experimental_action TEXT NOT NULL, ml_influence TEXT NOT NULL, research_views_json TEXT NOT NULL,
        canonical_payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, persisted_at_utc TEXT NOT NULL,
        UNIQUE(recommendation_id, decision_cutoff_utc))""",
    "CREATE INDEX IF NOT EXISTS idx_s5d4_news_ticker_time ON stage5d4_news_events(ticker,published_at_utc,observed_at_utc)",
    "CREATE INDEX IF NOT EXISTS idx_s5d4_overlay_date ON stage5d4_decision_overlays(decision_date,ticker)",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _identity(prefix: str, value: str) -> str:
    return prefix + payload_sha256(value)[:24]


def _required_text(value: Any, name: str) -> str:
    result = " ".join(str(value or "").strip().split())
    if not result:
        raise ValueError(f"{name} is required")
    return result


def _ticker(value: Any) -> str:
    return _required_text(value, "ticker").upper()


def _utc_timestamp(value: Any, name: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _required_text(value, name)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _probability(value: Any, name: str = "confidence") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite decimal from 0 to 1") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise ValueError(f"{name} must be a finite decimal from 0 to 1")
    return result


def normalize_news_event(event: Mapping[str, Any]) -> dict[str, Any]:
    published = _utc_timestamp(event.get("published_at_utc"), "published_at_utc")
    observed = _utc_timestamp(event.get("observed_at_utc", published), "observed_at_utc")
    if observed < published:
        raise ValueError("observed_at_utc cannot precede published_at_utc")
    category = _required_text(event.get("category"), "category").upper()
    sentiment = _required_text(event.get("sentiment"), "sentiment").upper()
    severity = _required_text(event.get("severity"), "severity").upper()
    if category not in NEWS_CATEGORIES:
        raise ValueError(f"Unsupported news category: {category}")
    if sentiment not in NEWS_SENTIMENTS:
        raise ValueError(f"Unsupported news sentiment: {sentiment}")
    if severity not in NEWS_SEVERITIES:
        raise ValueError(f"Unsupported news severity: {severity}")
    return {
        "event_id": _required_text(event.get("event_id"), "event_id"), "ticker": _ticker(event.get("ticker")),
        "headline": _required_text(event.get("headline"), "headline"), "source": _required_text(event.get("source"), "source"),
        "source_url": None if event.get("source_url") in (None, "") else str(event["source_url"]).strip(),
        "published_at_utc": published, "observed_at_utc": observed,
        "event_date": canonical_date(event.get("event_date", published[:10]), "event_date"),
        "category": category, "sentiment": sentiment, "severity": severity,
        "materiality": _required_text(event.get("materiality"), "materiality").upper(),
        "confidence": format(_probability(event.get("confidence")), "f"),
        "summary": _required_text(event.get("summary"), "summary"),
        "source_hash": None if event.get("source_hash") in (None, "") else str(event["source_hash"]).strip(),
    }


def _is_material(event: Mapping[str, Any]) -> bool:
    return str(event["materiality"]).upper() in {"MATERIAL", "HIGH", "CRITICAL", "TRUE", "YES"}


def evaluate_news_overlay(deterministic_action: str, events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    action = " ".join(str(deterministic_action).strip().upper().split())
    included = tuple(sorted(events, key=lambda item: (str(item["published_at_utc"]), str(item["event_id"]))))
    adverse = [item for item in included if str(item["sentiment"]).upper() in {"NEGATIVE", "MIXED"} and _is_material(item) and str(item["severity"]).upper() in {"MEDIUM", "HIGH", "CRITICAL"}]
    if adverse:
        highest = max(adverse, key=lambda item: NEWS_SEVERITIES.index(str(item["severity"]).upper()))
        risk = str(highest["severity"]).upper()
        news_action = "WAIT" if risk in {"HIGH", "CRITICAL"} else "REVIEW"
        reasons = sorted({REASON_BY_CATEGORY.get(str(item["category"]), "MATERIAL_ADVERSE_EVENT") for item in adverse})
        latest = max(str(item["published_at_utc"]) for item in adverse)
        summary = f"{risk}: {len(adverse)} material adverse event(s); latest publication {latest}."
    else:
        low = [item for item in included if str(item["sentiment"]).upper() in {"NEGATIVE", "MIXED"}]
        supportive = [item for item in included if str(item["sentiment"]).upper() == "POSITIVE"]
        risk = max((str(item["severity"]).upper() for item in low), key=NEWS_SEVERITIES.index, default="NONE")
        news_action, reasons, latest = "NO_CHANGE", [], None
        summary = "No material adverse event at or before the decision cutoff."
        if supportive:
            summary += f" {len(supportive)} supportive event(s) retained as context with no alpha upgrade."
    if action in {"BUY", "STRONG BUY"}:
        official = action if news_action == "NO_CHANGE" else news_action
    elif action == "HOLD":
        official = "HOLD" if news_action == "NO_CHANGE" else ("REVIEW" if news_action == "REVIEW" else "RISK_HOLD")
    else:
        official = action
    return {"news_risk_level": risk, "news_action": news_action, "news_reason_codes": reasons,
            "news_event_ids": [str(item["event_id"]) for item in included], "material_event_count": len(adverse),
            "latest_material_event_time": latest, "news_summary": summary, "official_paper_action": official}


class Stage5D4Overlay:
    """Immutable news risk plus verified Stage 4A.3 research-only shadow evidence."""

    def __init__(self, ledger: Stage5DLedger):
        self.ledger, self.connection = ledger, ledger.connection
        with self.connection:
            for statement in SCHEMA_STATEMENTS:
                self.connection.execute(statement)
            row = self.connection.execute("SELECT schema_version FROM stage5d4_meta WHERE singleton=1").fetchone()
            if row is None:
                self.connection.execute("INSERT INTO stage5d4_meta VALUES(1,?,?)", (STAGE5D4_SCHEMA_VERSION, _now()))
            elif row[0] != STAGE5D4_SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported Stage 5D.4 schema {row[0]!r}")

    @property
    def schema_version(self) -> str:
        return str(self.connection.execute("SELECT schema_version FROM stage5d4_meta WHERE singleton=1").fetchone()[0])

    def persist_news_events(self, events: Iterable[Mapping[str, Any]]) -> tuple[OperationResult, ...]:
        normalized = [normalize_news_event(event) for event in events]
        seen: dict[str, tuple[str, str]] = {}
        for event in normalized:
            canonical = canonical_json(event); digest = payload_sha256(canonical)
            if event["event_id"] in seen and seen[event["event_id"]] != (digest, canonical):
                raise ValueError(f"Conflicting immutable news event identity: {event['event_id']}")
            seen[event["event_id"]] = (digest, canonical)
            row = self.connection.execute("SELECT payload_sha256,canonical_payload_json FROM stage5d4_news_events WHERE event_id=?", (event["event_id"],)).fetchone()
            if row is not None and (row[0] != digest or row[1] != canonical):
                raise ValueError(f"Conflicting immutable news event identity: {event['event_id']}")
        results = []
        with self.connection:
            for event in normalized:
                canonical = canonical_json(event); digest = payload_sha256(canonical)
                if self.connection.execute("SELECT 1 FROM stage5d4_news_events WHERE event_id=?", (event["event_id"],)).fetchone():
                    results.append(OperationResult("IDEMPOTENT_SUCCESS", event["event_id"])); continue
                keys = ("event_id", "ticker", "headline", "source", "source_url", "published_at_utc", "observed_at_utc", "event_date", "category", "sentiment", "severity", "materiality", "confidence", "summary", "source_hash")
                self.connection.execute("INSERT INTO stage5d4_news_events VALUES(" + ",".join("?" for _ in range(18)) + ")", tuple(event[key] for key in keys) + (canonical, digest, _now()))
                results.append(OperationResult("CREATED", event["event_id"]))
        return tuple(results)

    def _persist_ml_prediction(self, prediction: Mapping[str, Any]) -> OperationResult:
        canonical = canonical_json(prediction); digest = payload_sha256(canonical)
        row = self.connection.execute("SELECT payload_sha256,canonical_payload_json FROM stage5d4_ml_predictions WHERE ml_prediction_id=?", (prediction["ml_prediction_id"],)).fetchone()
        if row is not None:
            if row[0] != digest or row[1] != canonical:
                raise ValueError(f"Conflicting immutable ML prediction identity: {prediction['ml_prediction_id']}")
            return OperationResult("IDEMPOTENT_SUCCESS", str(prediction["ml_prediction_id"]))
        keys = ("ml_prediction_id", "recommendation_id", "signal_id", "ticker", "protocol_id", "protocol_commit", "model_bundle_hash", "snapshot_id", "snapshot_signal_date", "snapshot_content_hash", "snapshot_created_utc", "snapshot_chain_hash", "r0_score", "r0_same_date_rank", "r0_k1_selected", "r3_score", "r3_same_date_rank", "r3_k1_selected", "primary_policy", "primary_comparator", "ml_shadow_classification", "experimental_action", "ml_influence")
        with self.connection:
            self.connection.execute("INSERT INTO stage5d4_ml_predictions VALUES(" + ",".join("?" for _ in range(26)) + ")", tuple(prediction[key] for key in keys) + (canonical, digest, _now()))
        return OperationResult("CREATED", str(prediction["ml_prediction_id"]))

    @staticmethod
    def _missing_ml() -> dict[str, Any]:
        return {"ml_prediction_id": None, "protocol_id": None, "snapshot_id": None, "snapshot_content_hash": None,
                "r0_score": None, "r0_same_date_rank": None, "r0_k1_selected": None, "r3_score": None,
                "r3_same_date_rank": None, "r3_k1_selected": None, "ml_primary_selected": None,
                "ml_comparator_selected": None, "ml_shadow_classification": "ML_NOT_AVAILABLE",
                "experimental_action": "NOT_AVAILABLE", "ml_influence": "NONE"}

    def evaluate_recommendation_overlay(self, recommendation_id: str, decision_cutoff_utc: Any,
                                        news_events: Iterable[Mapping[str, Any]],
                                        ml_snapshot_adapter: Stage4A3ShadowAdapter | None = None,
                                        ml_snapshot_dir: Path | None = None) -> dict[str, Any]:
        recommendation = self.ledger.get_recommendation(recommendation_id)
        if recommendation is None:
            raise ValueError(f"Unknown recommendation: {recommendation_id}")
        if ml_snapshot_adapter is not None and not isinstance(ml_snapshot_adapter, Stage4A3ShadowAdapter):
            raise TypeError("Production ML evidence must come from Stage4A3ShadowAdapter")
        if ml_snapshot_dir is not None and ml_snapshot_adapter is None:
            raise ValueError("ml_snapshot_dir requires Stage4A3ShadowAdapter")
        cutoff = _utc_timestamp(decision_cutoff_utc, "decision_cutoff_utc")
        supplied = tuple(news_events)
        self.persist_news_events(supplied)
        eligible = [item for item in map(normalize_news_event, supplied) if item["ticker"] == str(recommendation["ticker"]) and item["published_at_utc"] <= cutoff and item["observed_at_utc"] <= cutoff]
        news = evaluate_news_overlay(str(recommendation["deterministic_signal"]), eligible)
        ml = self._missing_ml() if ml_snapshot_adapter is None else ml_snapshot_adapter.load_verified_prediction(recommendation, cutoff, ml_snapshot_dir)
        if ml_snapshot_adapter is not None:
            self._persist_ml_prediction(ml)
        views = {
            "R0": {"action": recommendation["deterministic_signal"], "source": "FROZEN_DETERMINISTIC"},
            "R1": {"action": news["official_paper_action"], "news_action": news["news_action"]},
            "R2": {"action": recommendation["deterministic_signal"], "ml_shadow": ml["ml_shadow_classification"], "research_only": True},
            "R3": {"action": news["official_paper_action"], "ml_shadow": ml["ml_shadow_classification"], "research_only": True},
        }
        overlay_id = _identity("S5D4_OVR_", f"{recommendation_id}|{cutoff}")
        payload = {
            "overlay_id": overlay_id, "recommendation_id": recommendation_id, "signal_id": recommendation["signal_id"],
            "ticker": recommendation["ticker"], "decision_date": canonical_date(recommendation["decision_date"], "decision_date"),
            "decision_cutoff_utc": cutoff, "deterministic_action": recommendation["deterministic_signal"], **news,
            "ml_protocol_id": ml["protocol_id"], "ml_prediction_id": ml["ml_prediction_id"], "ml_snapshot_id": ml["snapshot_id"],
            "ml_snapshot_content_hash": ml["snapshot_content_hash"], "r0_score": ml["r0_score"],
            "r0_same_date_rank": ml["r0_same_date_rank"], "r0_k1_selected": ml["r0_k1_selected"],
            "r3_score": ml["r3_score"], "r3_same_date_rank": ml["r3_same_date_rank"], "r3_k1_selected": ml["r3_k1_selected"],
            "ml_primary_selected": ml["ml_primary_selected"], "ml_comparator_selected": ml["ml_comparator_selected"],
            "ml_shadow_classification": ml["ml_shadow_classification"], "ml_experimental_action": ml["experimental_action"],
            "ml_influence": "NONE", "research_views": views, "official_quantity": recommendation.get("recommended_quantity"),
            "official_stop": recommendation.get("stop"), "official_target_1": recommendation.get("target_1"),
            "official_target_2": recommendation.get("target_2"), "official_horizon": recommendation.get("selected_horizon"),
            "official_ranking_identity": recommendation.get("allocation_run_id"),
        }
        canonical = canonical_json(payload); digest = payload_sha256(canonical)
        row = self.connection.execute("SELECT payload_sha256,canonical_payload_json FROM stage5d4_decision_overlays WHERE overlay_id=?", (overlay_id,)).fetchone()
        if row is not None:
            if row[0] != digest or row[1] != canonical:
                raise ValueError(f"Conflicting immutable Stage 5D.4 overlay: {overlay_id}")
            return payload | {"status": "IDEMPOTENT_SUCCESS"}
        values = (overlay_id, recommendation_id, recommendation["signal_id"], recommendation["ticker"], payload["decision_date"], cutoff,
                  recommendation["deterministic_signal"], news["news_risk_level"], news["news_action"], canonical_json(news["news_reason_codes"]),
                  canonical_json(news["news_event_ids"]), news["material_event_count"], news["latest_material_event_time"], news["news_summary"],
                  news["official_paper_action"], ml["protocol_id"], ml["ml_prediction_id"], ml["snapshot_id"], ml["snapshot_content_hash"],
                  ml["r0_score"], ml["r0_same_date_rank"], ml["r0_k1_selected"], ml["r3_score"], ml["r3_same_date_rank"],
                  ml["r3_k1_selected"], ml["ml_shadow_classification"], ml["experimental_action"], "NONE", canonical_json(views), canonical, digest, _now())
        with self.connection:
            self.connection.execute("INSERT INTO stage5d4_decision_overlays VALUES(" + ",".join("?" for _ in range(32)) + ")", values)
        return payload | {"status": "CREATED"}

    def evaluate_daily_overlays(self, recommendation_ids: Iterable[str], decision_cutoff_utc: Any,
                                news_events_by_ticker: Mapping[str, Iterable[Mapping[str, Any]]],
                                ml_snapshot_adapter: Stage4A3ShadowAdapter | None = None,
                                ml_snapshot_dirs: Mapping[str, Path] | None = None) -> tuple[dict[str, Any], ...]:
        directories = ml_snapshot_dirs or {}; output = []
        for recommendation_id in recommendation_ids:
            recommendation = self.ledger.get_recommendation(recommendation_id)
            if recommendation is None:
                raise ValueError(f"Unknown recommendation: {recommendation_id}")
            output.append(self.evaluate_recommendation_overlay(recommendation_id, decision_cutoff_utc,
                news_events_by_ticker.get(str(recommendation["ticker"]), ()), ml_snapshot_adapter, directories.get(recommendation_id)))
        return tuple(output)

    def get_overlay(self, overlay_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT canonical_payload_json FROM stage5d4_decision_overlays WHERE overlay_id=?", (overlay_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def integrity_check(self) -> dict[str, Any]:
        checks: dict[str, bool] = {}
        checks["pragma_integrity_check"] = self.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        checks["pragma_foreign_key_check"] = not list(self.connection.execute("PRAGMA foreign_key_check"))

        def news_binding(row: Any) -> bool:
            payload = json.loads(row[15]); keys = ("event_id", "ticker", "headline", "source", "source_url", "published_at_utc", "observed_at_utc", "event_date", "category", "sentiment", "severity", "materiality", "confidence", "summary", "source_hash")
            return all(row[i] == payload.get(key) for i, key in enumerate(keys)) and payload_sha256(row[15]) == row[16]
        checks["news_typed_payload_binding"] = all(news_binding(row) for row in self.connection.execute("SELECT * FROM stage5d4_news_events"))

        def ml_binding(row: Any) -> bool:
            payload = json.loads(row[23]); keys = ("ml_prediction_id", "recommendation_id", "signal_id", "ticker", "protocol_id", "protocol_commit", "model_bundle_hash", "snapshot_id", "snapshot_signal_date", "snapshot_content_hash", "snapshot_created_utc", "snapshot_chain_hash", "r0_score", "r0_same_date_rank", "r0_k1_selected", "r3_score", "r3_same_date_rank", "r3_k1_selected", "primary_policy", "primary_comparator", "ml_shadow_classification", "experimental_action", "ml_influence")
            expected = [payload.get(key) for key in keys]; expected[14] = int(bool(expected[14])); expected[17] = int(bool(expected[17]))
            return list(row[:23]) == expected and payload_sha256(row[23]) == row[24]
        checks["ml_typed_payload_binding"] = all(ml_binding(row) for row in self.connection.execute("SELECT * FROM stage5d4_ml_predictions"))
        checks["ml_frozen_identity"] = all(tuple(row) == (FROZEN_ML_PROTOCOL_ID, FROZEN_ML_PROTOCOL_COMMIT, FROZEN_ML_MODEL_BUNDLE_HASH, PRIMARY_POLICY, PRIMARY_COMPARATOR, "NONE") for row in self.connection.execute("SELECT protocol_id,protocol_commit,model_bundle_hash,primary_policy,primary_comparator,ml_influence FROM stage5d4_ml_predictions"))

        def overlay_binding(row: Any) -> bool:
            payload = json.loads(row[29]); expected = [payload.get(key) for key in ("overlay_id", "recommendation_id", "signal_id", "ticker", "decision_date", "decision_cutoff_utc", "deterministic_action", "news_risk_level", "news_action")]
            expected += [canonical_json(payload["news_reason_codes"]), canonical_json(payload["news_event_ids"]), payload["material_event_count"], payload["latest_material_event_time"], payload["news_summary"], payload["official_paper_action"], payload["ml_protocol_id"], payload["ml_prediction_id"], payload["ml_snapshot_id"], payload["ml_snapshot_content_hash"], payload["r0_score"], payload["r0_same_date_rank"], payload["r0_k1_selected"], payload["r3_score"], payload["r3_same_date_rank"], payload["r3_k1_selected"], payload["ml_shadow_classification"], payload["ml_experimental_action"], payload["ml_influence"], canonical_json(payload["research_views"])]
            for index in (21, 24):
                if expected[index] is not None: expected[index] = int(bool(expected[index]))
            return list(row[:29]) == expected and row[14] == payload["official_paper_action"] and payload_sha256(row[29]) == row[30]
        checks["overlay_typed_payload_binding"] = all(overlay_binding(row) for row in self.connection.execute("SELECT * FROM stage5d4_decision_overlays"))
        checks["recommendation_lineage"] = all(self.connection.execute("SELECT 1 FROM recommendations WHERE recommendation_id=? AND signal_id=? AND ticker=?", row).fetchone() for row in self.connection.execute("SELECT recommendation_id,signal_id,ticker FROM stage5d4_decision_overlays"))
        checks["news_cutoff_binding"] = all(all(self.connection.execute("SELECT 1 FROM stage5d4_news_events WHERE event_id=? AND published_at_utc<=? AND observed_at_utc<=?", (event_id, cutoff, cutoff)).fetchone() for event_id in json.loads(event_ids)) for event_ids, cutoff in self.connection.execute("SELECT news_event_ids_json,decision_cutoff_utc FROM stage5d4_decision_overlays"))
        checks["ml_influence_none"] = all(row[0] == "NONE" for row in self.connection.execute("SELECT ml_influence FROM stage5d4_decision_overlays"))
        return {"ok": all(checks.values()), "checks": checks}


def evaluate_recommendation_overlay(ledger: Stage5DLedger, recommendation_id: str, decision_cutoff_utc: Any,
                                    news_events: Iterable[Mapping[str, Any]],
                                    ml_snapshot_adapter: Stage4A3ShadowAdapter | None = None,
                                    ml_snapshot_dir: Path | None = None) -> dict[str, Any]:
    return Stage5D4Overlay(ledger).evaluate_recommendation_overlay(recommendation_id, decision_cutoff_utc, news_events, ml_snapshot_adapter, ml_snapshot_dir)


def evaluate_daily_overlays(ledger: Stage5DLedger, recommendation_ids: Iterable[str], decision_cutoff_utc: Any,
                            news_events_by_ticker: Mapping[str, Iterable[Mapping[str, Any]]],
                            ml_snapshot_adapter: Stage4A3ShadowAdapter | None = None,
                            ml_snapshot_dirs: Mapping[str, Path] | None = None) -> tuple[dict[str, Any], ...]:
    return Stage5D4Overlay(ledger).evaluate_daily_overlays(recommendation_ids, decision_cutoff_utc, news_events_by_ticker, ml_snapshot_adapter, ml_snapshot_dirs)
