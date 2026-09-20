from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from .ledger import OperationResult, Stage5DLedger, canonical_json, payload_sha256
from .source_contract import canonical_date


STAGE5D4_SCHEMA_VERSION = "STAGE5D4_SCHEMA_V1"
STAGE5D4_TABLES = (
    "stage5d4_meta",
    "stage5d4_news_events",
    "stage5d4_ml_predictions",
    "stage5d4_decision_overlays",
)

FROZEN_ML_PROTOCOL_ID = "S4A3_PROTOCOL_ee14ae516b33deac"
FROZEN_ML_MODEL_BUNDLE_HASH = "4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da"
FROZEN_ML_PROTOCOL_COMMIT = "3ff3c0283174589d43883ce75b1dfd87a33613ce"

NEWS_CATEGORIES = frozenset({
    "EARNINGS", "GUIDANCE", "REGULATORY", "LEGAL", "GOVERNANCE",
    "FRAUD_ALLEGATION", "PROMOTER", "MANAGEMENT_CHANGE", "CREDIT_RATING",
    "DEBT_LIQUIDITY", "LARGE_ORDER", "ORDER_CANCELLATION", "CORPORATE_ACTION",
    "M_AND_A", "CAPITAL_RAISE", "PRODUCT", "MACRO_SECTOR", "OTHER",
})
NEWS_SEVERITIES = ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL")
NEWS_SENTIMENTS = frozenset({"POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"})
NEWS_ACTIONS = frozenset({"NO_CHANGE", "REVIEW", "WAIT"})
ML_CLASSES = frozenset({"ML_SUPPORTS", "ML_NEUTRAL", "ML_OPPOSES", "ML_NOT_AVAILABLE"})

REASON_BY_CATEGORY = {
    "REGULATORY": "MATERIAL_REGULATORY_RISK",
    "LEGAL": "MATERIAL_LEGAL_RISK",
    "GOVERNANCE": "GOVERNANCE_RISK",
    "FRAUD_ALLEGATION": "GOVERNANCE_RISK",
    "CREDIT_RATING": "CREDIT_DETERIORATION",
    "DEBT_LIQUIDITY": "LIQUIDITY_RISK",
    "EARNINGS": "EARNINGS_MISS",
    "GUIDANCE": "GUIDANCE_CUT",
    "PROMOTER": "PROMOTER_RISK",
    "ORDER_CANCELLATION": "ORDER_CANCELLATION",
    "MANAGEMENT_CHANGE": "MANAGEMENT_UNCERTAINTY",
}

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS stage5d4_meta(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version TEXT NOT NULL,
        created_at_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS stage5d4_news_events(
        event_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, headline TEXT NOT NULL,
        source TEXT NOT NULL, source_url TEXT, published_at_utc TEXT NOT NULL,
        observed_at_utc TEXT NOT NULL, event_date TEXT NOT NULL, category TEXT NOT NULL,
        sentiment TEXT NOT NULL, severity TEXT NOT NULL, materiality TEXT NOT NULL,
        confidence TEXT NOT NULL, summary TEXT NOT NULL, source_hash TEXT,
        canonical_payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
        persisted_at_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS stage5d4_ml_predictions(
        ml_prediction_id TEXT PRIMARY KEY,
        recommendation_id TEXT NOT NULL REFERENCES recommendations(recommendation_id),
        signal_id TEXT NOT NULL, ticker TEXT NOT NULL, protocol_id TEXT NOT NULL,
        model_bundle_hash TEXT NOT NULL, protocol_commit TEXT NOT NULL,
        snapshot_signal_date TEXT NOT NULL, snapshot_content_hash TEXT NOT NULL,
        prediction_at_utc TEXT NOT NULL,
        probability TEXT NOT NULL, shadow_classification TEXT NOT NULL,
        experimental_action TEXT NOT NULL, eligibility_status TEXT NOT NULL,
        canonical_payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
        persisted_at_utc TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS stage5d4_decision_overlays(
        overlay_id TEXT PRIMARY KEY,
        recommendation_id TEXT NOT NULL REFERENCES recommendations(recommendation_id),
        signal_id TEXT NOT NULL, ticker TEXT NOT NULL, decision_date TEXT NOT NULL,
        decision_cutoff_utc TEXT NOT NULL, deterministic_action TEXT NOT NULL,
        news_risk_level TEXT NOT NULL, news_action TEXT NOT NULL,
        news_reason_codes_json TEXT NOT NULL, news_event_ids_json TEXT NOT NULL,
        material_event_count INTEGER NOT NULL, latest_material_event_time TEXT,
        news_summary TEXT NOT NULL, official_paper_action TEXT NOT NULL,
        ml_protocol_id TEXT, ml_prediction_id TEXT REFERENCES stage5d4_ml_predictions(ml_prediction_id),
        ml_probability TEXT, ml_shadow_classification TEXT NOT NULL,
        ml_experimental_action TEXT NOT NULL, ml_influence TEXT NOT NULL,
        research_views_json TEXT NOT NULL, canonical_payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL, persisted_at_utc TEXT NOT NULL,
        UNIQUE(recommendation_id, decision_cutoff_utc))""",
    "CREATE INDEX IF NOT EXISTS idx_s5d4_news_ticker_time ON stage5d4_news_events(ticker,published_at_utc)",
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


def _probability(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("probability must be a finite decimal from 0 to 1") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise ValueError("probability must be a finite decimal from 0 to 1")
    return result


def _sha256_text(value: Any, name: str) -> str:
    result = _required_text(value, name).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return result


def normalize_news_event(event: Mapping[str, Any]) -> dict[str, Any]:
    published = _utc_timestamp(event.get("published_at_utc"), "published_at_utc")
    observed = _utc_timestamp(event.get("observed_at_utc", published), "observed_at_utc")
    if observed < published:
        raise ValueError("observed_at_utc cannot precede published_at_utc")
    category = _required_text(event.get("category"), "category").upper()
    if category not in NEWS_CATEGORIES:
        raise ValueError(f"Unsupported news category: {category}")
    sentiment = _required_text(event.get("sentiment"), "sentiment").upper()
    if sentiment not in NEWS_SENTIMENTS:
        raise ValueError(f"Unsupported news sentiment: {sentiment}")
    severity = _required_text(event.get("severity"), "severity").upper()
    if severity not in NEWS_SEVERITIES:
        raise ValueError(f"Unsupported news severity: {severity}")
    materiality = _required_text(event.get("materiality"), "materiality").upper()
    confidence = _probability(event.get("confidence"))
    source_url = None if event.get("source_url") in (None, "") else str(event["source_url"]).strip()
    source_hash = None if event.get("source_hash") in (None, "") else str(event["source_hash"]).strip()
    event_date = canonical_date(event.get("event_date", published[:10]), "event_date")
    return {
        "event_id": _required_text(event.get("event_id"), "event_id"),
        "ticker": _ticker(event.get("ticker")),
        "headline": _required_text(event.get("headline"), "headline"),
        "source": _required_text(event.get("source"), "source"),
        "source_url": source_url,
        "published_at_utc": published,
        "observed_at_utc": observed,
        "event_date": event_date,
        "category": category,
        "sentiment": sentiment,
        "severity": severity,
        "materiality": materiality,
        "confidence": format(confidence, "f"),
        "summary": _required_text(event.get("summary"), "summary"),
        "source_hash": source_hash,
    }


def _is_material(event: Mapping[str, Any]) -> bool:
    return str(event["materiality"]).upper() in {"MATERIAL", "HIGH", "CRITICAL", "TRUE", "YES"}


def evaluate_news_overlay(deterministic_action: str, events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    normalized_action = " ".join(str(deterministic_action).strip().upper().split())
    included = tuple(sorted(events, key=lambda item: (str(item["published_at_utc"]), str(item["event_id"]))))
    adverse = [
        event for event in included
        if str(event["sentiment"]).upper() in {"NEGATIVE", "MIXED"}
        and _is_material(event)
        and str(event["severity"]).upper() in {"MEDIUM", "HIGH", "CRITICAL"}
    ]
    if adverse:
        highest = max(adverse, key=lambda item: NEWS_SEVERITIES.index(str(item["severity"]).upper()))
        risk = str(highest["severity"]).upper()
        news_action = "WAIT" if risk in {"HIGH", "CRITICAL"} else "REVIEW"
        reasons = sorted({REASON_BY_CATEGORY.get(str(item["category"]), "MATERIAL_ADVERSE_EVENT") for item in adverse})
        latest = max(str(item["published_at_utc"]) for item in adverse)
        summary = f"{risk}: {len(adverse)} material adverse event(s); latest publication {latest}."
    else:
        low = [event for event in included if str(event["sentiment"]).upper() in {"NEGATIVE", "MIXED"}]
        supportive = [event for event in included if str(event["sentiment"]).upper() == "POSITIVE"]
        risk = max((str(item["severity"]).upper() for item in low), key=NEWS_SEVERITIES.index, default="NONE")
        news_action = "NO_CHANGE"
        reasons = []
        latest = None
        summary = "No material adverse event at or before the decision cutoff."
        if supportive:
            summary += f" {len(supportive)} supportive event(s) retained as context with no alpha upgrade."
    if normalized_action in {"BUY", "STRONG BUY"}:
        official = normalized_action if news_action == "NO_CHANGE" else news_action
    elif normalized_action == "HOLD":
        official = "HOLD" if news_action == "NO_CHANGE" else ("REVIEW" if news_action == "REVIEW" else "RISK_HOLD")
    else:
        official = normalized_action
    return {
        "news_risk_level": risk,
        "news_action": news_action,
        "news_reason_codes": reasons,
        "news_event_ids": [str(item["event_id"]) for item in included],
        "material_event_count": len(adverse),
        "latest_material_event_time": latest,
        "news_summary": summary,
        "official_paper_action": official,
    }


def normalize_ml_prediction(prediction: Mapping[str, Any], recommendation: Mapping[str, Any], cutoff: str) -> dict[str, Any]:
    protocol_id = _required_text(prediction.get("protocol_id"), "protocol_id")
    bundle_hash = _required_text(prediction.get("model_bundle_hash"), "model_bundle_hash")
    if protocol_id != FROZEN_ML_PROTOCOL_ID or bundle_hash != FROZEN_ML_MODEL_BUNDLE_HASH:
        raise ValueError("ML prediction is not from the frozen Stage 4A.3 protocol/model bundle")
    protocol_commit = _required_text(prediction.get("protocol_commit"), "protocol_commit")
    if protocol_commit != FROZEN_ML_PROTOCOL_COMMIT:
        raise ValueError("ML prediction is not from the frozen Stage 4A.3 protocol commit")
    if _required_text(prediction.get("eligibility_status"), "eligibility_status").upper() != "ELIGIBLE":
        raise ValueError("ML prediction is not eligible under the frozen Stage 4A.3 prospective protocol")
    prediction_at = _utc_timestamp(prediction.get("prediction_at_utc"), "prediction_at_utc")
    if prediction_at > cutoff:
        raise ValueError("ML prediction is later than the decision cutoff")
    if _ticker(prediction.get("ticker")) != str(recommendation["ticker"]):
        raise ValueError("ML prediction ticker lineage mismatch")
    if _required_text(prediction.get("signal_id"), "signal_id") != str(recommendation["signal_id"]):
        raise ValueError("ML prediction signal lineage mismatch")
    snapshot_signal_date = canonical_date(prediction.get("snapshot_signal_date"), "snapshot_signal_date")
    if snapshot_signal_date != canonical_date(recommendation["signal_date"], "signal_date"):
        raise ValueError("ML prediction snapshot signal-date lineage mismatch")
    snapshot_content_hash = _sha256_text(prediction.get("snapshot_content_hash"), "snapshot_content_hash")
    rec_id = prediction.get("recommendation_id")
    if rec_id not in (None, "", recommendation["recommendation_id"]):
        raise ValueError("ML prediction recommendation lineage mismatch")
    probability = _probability(prediction.get("probability"))
    if probability >= Decimal("0.60"):
        shadow, experimental = "ML_SUPPORTS", "PROMOTE"
    elif probability <= Decimal("0.40"):
        shadow, experimental = "ML_OPPOSES", "FILTER"
    else:
        shadow, experimental = "ML_NEUTRAL", "KEEP"
    return {
        "ml_prediction_id": _required_text(prediction.get("ml_prediction_id"), "ml_prediction_id"),
        "recommendation_id": str(recommendation["recommendation_id"]),
        "signal_id": str(recommendation["signal_id"]),
        "ticker": str(recommendation["ticker"]),
        "protocol_id": protocol_id,
        "model_bundle_hash": bundle_hash,
        "protocol_commit": protocol_commit,
        "snapshot_signal_date": snapshot_signal_date,
        "snapshot_content_hash": snapshot_content_hash,
        "prediction_at_utc": prediction_at,
        "probability": format(probability, "f"),
        "shadow_classification": shadow,
        "experimental_action": experimental,
        "eligibility_status": "ELIGIBLE",
    }


class Stage5D4Overlay:
    """Immutable news-risk and Stage 4A.3 shadow evidence; never an execution engine."""

    def __init__(self, ledger: Stage5DLedger):
        self.ledger = ledger
        self.connection = ledger.connection
        self._initialize_or_validate()

    def _initialize_or_validate(self) -> None:
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
            canonical = canonical_json(event)
            digest = payload_sha256(canonical)
            prior = seen.get(event["event_id"])
            if prior is not None and prior != (digest, canonical):
                raise ValueError(f"Conflicting immutable news event identity: {event['event_id']}")
            seen[event["event_id"]] = (digest, canonical)
            row = self.connection.execute(
                "SELECT payload_sha256,canonical_payload_json FROM stage5d4_news_events WHERE event_id=?",
                (event["event_id"],),
            ).fetchone()
            if row is not None and (row[0] != digest or row[1] != canonical):
                raise ValueError(f"Conflicting immutable news event identity: {event['event_id']}")
        results: list[OperationResult] = []
        with self.connection:
            for event in normalized:
                canonical = canonical_json(event)
                digest = payload_sha256(canonical)
                exists = self.connection.execute(
                    "SELECT 1 FROM stage5d4_news_events WHERE event_id=?", (event["event_id"],)
                ).fetchone()
                if exists:
                    results.append(OperationResult("IDEMPOTENT_SUCCESS", event["event_id"]))
                    continue
                self.connection.execute(
                    "INSERT INTO stage5d4_news_events VALUES(" + ",".join("?" for _ in range(18)) + ")",
                    tuple(event[key] for key in (
                        "event_id", "ticker", "headline", "source", "source_url", "published_at_utc",
                        "observed_at_utc", "event_date", "category", "sentiment", "severity",
                        "materiality", "confidence", "summary", "source_hash",
                    )) + (canonical, digest, _now()),
                )
                results.append(OperationResult("CREATED", event["event_id"]))
        return tuple(results)

    def _persist_ml_prediction(self, prediction: Mapping[str, Any]) -> OperationResult:
        canonical = canonical_json(prediction)
        digest = payload_sha256(canonical)
        row = self.connection.execute(
            "SELECT payload_sha256,canonical_payload_json FROM stage5d4_ml_predictions WHERE ml_prediction_id=?",
            (prediction["ml_prediction_id"],),
        ).fetchone()
        if row is not None:
            if row[0] != digest or row[1] != canonical:
                raise ValueError(f"Conflicting immutable ML prediction identity: {prediction['ml_prediction_id']}")
            return OperationResult("IDEMPOTENT_SUCCESS", str(prediction["ml_prediction_id"]))
        with self.connection:
            self.connection.execute(
                "INSERT INTO stage5d4_ml_predictions VALUES(" + ",".join("?" for _ in range(17)) + ")",
                tuple(prediction[key] for key in (
                    "ml_prediction_id", "recommendation_id", "signal_id", "ticker", "protocol_id",
                    "model_bundle_hash", "protocol_commit", "snapshot_signal_date", "snapshot_content_hash",
                    "prediction_at_utc", "probability", "shadow_classification",
                    "experimental_action", "eligibility_status",
                )) + (canonical, digest, _now()),
            )
        return OperationResult("CREATED", str(prediction["ml_prediction_id"]))

    def evaluate_recommendation_overlay(
        self,
        recommendation_id: str,
        decision_cutoff_utc: Any,
        news_events: Iterable[Mapping[str, Any]],
        ml_shadow_prediction: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        recommendation = self.ledger.get_recommendation(recommendation_id)
        if recommendation is None:
            raise ValueError(f"Unknown recommendation: {recommendation_id}")
        cutoff = _utc_timestamp(decision_cutoff_utc, "decision_cutoff_utc")
        supplied_events = tuple(news_events)
        self.persist_news_events(supplied_events)
        eligible_events = [
            normalize_news_event(event) for event in supplied_events
            if _ticker(event.get("ticker")) == str(recommendation["ticker"])
            and _utc_timestamp(event.get("published_at_utc"), "published_at_utc") <= cutoff
        ]
        news = evaluate_news_overlay(str(recommendation["deterministic_signal"]), eligible_events)
        if ml_shadow_prediction is None:
            ml = {
                "ml_prediction_id": None, "protocol_id": None, "probability": None,
                "shadow_classification": "ML_NOT_AVAILABLE", "experimental_action": "KEEP",
            }
        else:
            ml = normalize_ml_prediction(ml_shadow_prediction, recommendation, cutoff)
            self._persist_ml_prediction(ml)
        views = {
            "R0": {"action": recommendation["deterministic_signal"], "source": "FROZEN_DETERMINISTIC"},
            "R1": {"action": news["official_paper_action"], "news_action": news["news_action"]},
            "R2": {"action": recommendation["deterministic_signal"], "ml_shadow": ml["shadow_classification"], "research_only": True},
            "R3": {"action": news["official_paper_action"], "ml_shadow": ml["shadow_classification"], "research_only": True},
        }
        overlay_id = _identity("S5D4_OVR_", f"{recommendation_id}|{cutoff}")
        payload = {
            "overlay_id": overlay_id,
            "recommendation_id": recommendation_id,
            "signal_id": recommendation["signal_id"],
            "ticker": recommendation["ticker"],
            "decision_date": canonical_date(recommendation["decision_date"], "decision_date"),
            "decision_cutoff_utc": cutoff,
            "deterministic_action": recommendation["deterministic_signal"],
            **news,
            "ml_protocol_id": ml["protocol_id"],
            "ml_prediction_id": ml["ml_prediction_id"],
            "ml_probability": ml["probability"],
            "ml_shadow_classification": ml["shadow_classification"],
            "ml_experimental_action": ml["experimental_action"],
            "ml_influence": "NONE",
            "research_views": views,
            "official_quantity": recommendation.get("recommended_quantity"),
            "official_stop": recommendation.get("stop"),
            "official_target_1": recommendation.get("target_1"),
            "official_target_2": recommendation.get("target_2"),
            "official_horizon": recommendation.get("selected_horizon"),
            "official_ranking_identity": recommendation.get("allocation_run_id"),
        }
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        row = self.connection.execute(
            "SELECT payload_sha256,canonical_payload_json FROM stage5d4_decision_overlays WHERE overlay_id=?",
            (overlay_id,),
        ).fetchone()
        if row is not None:
            if row[0] != digest or row[1] != canonical:
                raise ValueError(f"Conflicting immutable Stage 5D.4 overlay: {overlay_id}")
            return payload | {"status": "IDEMPOTENT_SUCCESS"}
        with self.connection:
            self.connection.execute(
                "INSERT INTO stage5d4_decision_overlays VALUES(" + ",".join("?" for _ in range(25)) + ")",
                (
                    overlay_id, recommendation_id, recommendation["signal_id"], recommendation["ticker"],
                    payload["decision_date"], cutoff, recommendation["deterministic_signal"],
                    news["news_risk_level"], news["news_action"], canonical_json(news["news_reason_codes"]),
                    canonical_json(news["news_event_ids"]), news["material_event_count"],
                    news["latest_material_event_time"], news["news_summary"], news["official_paper_action"],
                    ml["protocol_id"], ml["ml_prediction_id"], ml["probability"],
                    ml["shadow_classification"], ml["experimental_action"], "NONE", canonical_json(views),
                    canonical, digest, _now(),
                ),
            )
        return payload | {"status": "CREATED"}

    def evaluate_daily_overlays(
        self,
        recommendation_ids: Iterable[str],
        decision_cutoff_utc: Any,
        news_events_by_ticker: Mapping[str, Iterable[Mapping[str, Any]]],
        ml_predictions: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        predictions = ml_predictions or {}
        output: list[dict[str, Any]] = []
        for recommendation_id in recommendation_ids:
            recommendation = self.ledger.get_recommendation(recommendation_id)
            if recommendation is None:
                raise ValueError(f"Unknown recommendation: {recommendation_id}")
            output.append(self.evaluate_recommendation_overlay(
                recommendation_id,
                decision_cutoff_utc,
                news_events_by_ticker.get(str(recommendation["ticker"]), ()),
                predictions.get(recommendation_id),
            ))
        return tuple(output)

    def get_overlay(self, overlay_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT canonical_payload_json FROM stage5d4_decision_overlays WHERE overlay_id=?", (overlay_id,)
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def integrity_check(self) -> dict[str, Any]:
        checks: dict[str, bool] = {}
        checks["news_hashes"] = all(
            payload_sha256(row[0]) == row[1]
            for row in self.connection.execute("SELECT canonical_payload_json,payload_sha256 FROM stage5d4_news_events")
        )
        checks["ml_hashes"] = all(
            payload_sha256(row[0]) == row[1]
            for row in self.connection.execute("SELECT canonical_payload_json,payload_sha256 FROM stage5d4_ml_predictions")
        )
        checks["ml_frozen_identity"] = all(
            row[0] == FROZEN_ML_PROTOCOL_ID
            and row[1] == FROZEN_ML_MODEL_BUNDLE_HASH
            and row[2] == FROZEN_ML_PROTOCOL_COMMIT
            for row in self.connection.execute(
                "SELECT protocol_id,model_bundle_hash,protocol_commit FROM stage5d4_ml_predictions"
            )
        )
        checks["overlay_hashes"] = all(
            payload_sha256(row[0]) == row[1]
            for row in self.connection.execute("SELECT canonical_payload_json,payload_sha256 FROM stage5d4_decision_overlays")
        )
        checks["recommendation_lineage"] = all(
            self.connection.execute(
                "SELECT 1 FROM recommendations WHERE recommendation_id=? AND signal_id=? AND ticker=?",
                (row[0], row[1], row[2]),
            ).fetchone()
            for row in self.connection.execute(
                "SELECT recommendation_id,signal_id,ticker FROM stage5d4_decision_overlays"
            )
        )
        checks["news_cutoff_binding"] = all(
            all(
                self.connection.execute(
                    "SELECT 1 FROM stage5d4_news_events WHERE event_id=? AND published_at_utc<=?",
                    (event_id, row[1]),
                ).fetchone()
                for event_id in json.loads(row[0])
            )
            for row in self.connection.execute(
                "SELECT news_event_ids_json,decision_cutoff_utc FROM stage5d4_decision_overlays"
            )
        )
        checks["ml_influence_none"] = all(
            row[0] == "NONE" for row in self.connection.execute("SELECT ml_influence FROM stage5d4_decision_overlays")
        )
        return {"ok": all(checks.values()), "checks": checks}


def evaluate_recommendation_overlay(
    ledger: Stage5DLedger,
    recommendation_id: str,
    decision_cutoff_utc: Any,
    news_events: Iterable[Mapping[str, Any]],
    ml_shadow_prediction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return Stage5D4Overlay(ledger).evaluate_recommendation_overlay(
        recommendation_id, decision_cutoff_utc, news_events, ml_shadow_prediction
    )


def evaluate_daily_overlays(
    ledger: Stage5DLedger,
    recommendation_ids: Iterable[str],
    decision_cutoff_utc: Any,
    news_events_by_ticker: Mapping[str, Iterable[Mapping[str, Any]]],
    ml_predictions: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], ...]:
    return Stage5D4Overlay(ledger).evaluate_daily_overlays(
        recommendation_ids, decision_cutoff_utc, news_events_by_ticker, ml_predictions
    )
