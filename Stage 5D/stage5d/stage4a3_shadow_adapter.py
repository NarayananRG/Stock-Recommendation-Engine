from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import pandas as pd


FROZEN_PROTOCOL_ID = "S4A3_PROTOCOL_ee14ae516b33deac"
FROZEN_PROTOCOL_COMMIT = "3ff3c0283174589d43883ce75b1dfd87a33613ce"
FROZEN_MODEL_BUNDLE_HASH = "4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da"
FROZEN_PREDICTION_SEMANTICS = "SHADOW_ONLY_NO_TRADING_EFFECT"
PRIMARY_POLICY = "R3_K1"
PRIMARY_COMPARATOR = "R0_K1"
REQUIRED_SNAPSHOT_FILES = frozenset({
    "snapshot_metadata.json", "candidate_predictions.csv.gz", "feature_snapshot.csv.gz",
    "market_data_manifest.json", "candidate_input_manifest.json", "snapshot_manifest.json",
    "hash_chain.json",
})


def _utc(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _boolean(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().upper()
    if text in {"TRUE", "1"}:
        return True
    if text in {"FALSE", "0"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _integer(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be positive")
    return parsed


@contextmanager
def _frozen_stage4a3(stage4a3_root: Path) -> Iterator[dict[str, Any]]:
    """Import frozen verification code read-only without copying its semantics."""
    root_text = str(stage4a3_root)
    inserted = root_text not in sys.path
    if inserted:
        sys.path.insert(0, root_text)
    try:
        from stage4a3.hash_chain import current_chain_hash
        from stage4a3.hashing import sha256_file
        from stage4a3.immutable_ledger import verify_snapshot_files
        from stage4a3.snapshot_contract import (
            PREDICTION_COLUMNS,
            snapshot_content_hash,
            validate_candidate_predictions,
        )
        yield {
            "current_chain_hash": current_chain_hash,
            "sha256_file": sha256_file,
            "verify_snapshot_files": verify_snapshot_files,
            "PREDICTION_COLUMNS": PREDICTION_COLUMNS,
            "snapshot_content_hash": snapshot_content_hash,
            "validate_candidate_predictions": validate_candidate_predictions,
        }
    finally:
        if inserted:
            sys.path.remove(root_text)


@dataclass(frozen=True)
class Stage4A3ShadowAdapter:
    """Read-only adapter for immutable Stage 4A.3 prospective snapshots."""

    stage4a3_root: Path
    prospective_root: Path | None = None

    def __post_init__(self) -> None:
        root = Path(self.stage4a3_root).resolve()
        prospective = Path(self.prospective_root).resolve() if self.prospective_root else (root / "prospective" / "snapshots").resolve()
        object.__setattr__(self, "stage4a3_root", root)
        object.__setattr__(self, "prospective_root", prospective)
        config_path = root / "config" / "stage4a3_protocol.json"
        identity_path = root / "results" / "stage4a3_protocol_identity.json"
        if not config_path.is_file() or not identity_path.is_file():
            raise ValueError("Frozen Stage 4A.3 protocol identity files are missing")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        if identity.get("PROTOCOL_ID") != FROZEN_PROTOCOL_ID:
            raise ValueError("Frozen Stage 4A.3 protocol ID mismatch")
        if config.get("expected_model_bundle_hash") != FROZEN_MODEL_BUNDLE_HASH:
            raise ValueError("Frozen Stage 4A.3 model bundle mismatch")
        if config.get("primary_policy") != PRIMARY_POLICY or config.get("primary_comparator") != PRIMARY_COMPARATOR:
            raise ValueError("Frozen Stage 4A.3 policy identity mismatch")
        if config.get("prediction_semantics") != FROZEN_PREDICTION_SEMANTICS:
            raise ValueError("Frozen Stage 4A.3 prediction semantics mismatch")

    def _snapshot_directory(self, signal_date: str, snapshot_dir: Path | None) -> Path:
        candidate = (Path(snapshot_dir) if snapshot_dir else self.prospective_root / signal_date[:4] / signal_date).resolve()
        try:
            candidate.relative_to(self.prospective_root)
        except ValueError as exc:
            raise ValueError("Snapshot directory is outside the configured prospective root") from exc
        if not candidate.is_dir():
            raise ValueError("Stage 4A.3 snapshot directory does not exist")
        return candidate

    def load_verified_prediction(
        self,
        recommendation: Mapping[str, Any],
        decision_cutoff_utc: Any,
        snapshot_dir: Path | None = None,
    ) -> dict[str, Any]:
        signal_date = str(recommendation.get("signal_date") or "")
        signal_id = str(recommendation.get("signal_id") or "")
        ticker = str(recommendation.get("ticker") or "").upper()
        if not signal_date or not signal_id or not ticker:
            raise ValueError("Recommendation signal_date, signal_id, and ticker are required")
        cutoff = _utc(decision_cutoff_utc, "decision_cutoff_utc")
        directory = self._snapshot_directory(signal_date, snapshot_dir)
        missing = sorted(name for name in REQUIRED_SNAPSHOT_FILES if not (directory / name).is_file())
        if missing:
            raise ValueError(f"Stage 4A.3 snapshot missing required files: {missing}")

        metadata = json.loads((directory / "snapshot_metadata.json").read_text(encoding="utf-8"))
        market_manifest = json.loads((directory / "market_data_manifest.json").read_text(encoding="utf-8"))
        candidate_manifest = json.loads((directory / "candidate_input_manifest.json").read_text(encoding="utf-8"))
        snapshot_manifest = json.loads((directory / "snapshot_manifest.json").read_text(encoding="utf-8"))
        chain = json.loads((directory / "hash_chain.json").read_text(encoding="utf-8"))
        with _frozen_stage4a3(self.stage4a3_root) as frozen:
            if not frozen["verify_snapshot_files"](directory):
                raise ValueError("Stage 4A.3 snapshot manifest SHA-256 mismatch")
            manifest_files = snapshot_manifest.get("files")
            if not isinstance(manifest_files, list) or {item.get("file") for item in manifest_files} != REQUIRED_SNAPSHOT_FILES - {"snapshot_manifest.json", "hash_chain.json"}:
                raise ValueError("Stage 4A.3 snapshot manifest file inventory mismatch")
            for item in manifest_files:
                path = directory / str(item["file"])
                if item.get("bytes") != path.stat().st_size or item.get("sha256") != frozen["sha256_file"](path):
                    raise ValueError("Stage 4A.3 snapshot manifest file metadata mismatch")
            predictions = pd.read_csv(directory / "candidate_predictions.csv.gz")
            features = pd.read_csv(directory / "feature_snapshot.csv.gz")
            frozen["validate_candidate_predictions"](predictions)
            if list(predictions.columns) != list(frozen["PREDICTION_COLUMNS"]):
                raise ValueError("Candidate prediction columns do not exactly match the frozen contract")
            content_hash = frozen["snapshot_content_hash"](
                metadata, predictions, features, market_manifest, candidate_manifest
            )
            expected_chain = frozen["current_chain_hash"](
                str(chain.get("Previous Chain Hash", "")), signal_date, content_hash,
                FROZEN_PROTOCOL_COMMIT, FROZEN_MODEL_BUNDLE_HASH,
            )

        if snapshot_manifest.get("Snapshot Content Hash") != content_hash or chain.get("Snapshot Content Hash") != content_hash:
            raise ValueError("Stage 4A.3 snapshot content hash mismatch")
        if chain.get("Protocol Commit") != FROZEN_PROTOCOL_COMMIT:
            raise ValueError("Stage 4A.3 protocol commit mismatch")
        if chain.get("Model Bundle Hash") != FROZEN_MODEL_BUNDLE_HASH:
            raise ValueError("Stage 4A.3 model bundle mismatch")
        if chain.get("Signal Date") != signal_date:
            raise ValueError("Stage 4A.3 snapshot signal-date lineage mismatch")
        if chain.get("Current Chain Hash") != expected_chain:
            raise ValueError("Stage 4A.3 snapshot hash-chain mismatch")

        matches = predictions.loc[predictions["Signal ID"].astype(str).eq(signal_id)]
        if len(matches) != 1:
            raise ValueError("Stage 4A.3 snapshot must contain one unique matching Signal ID row")
        row = matches.iloc[0]
        if str(row["Signal Date"]) != signal_date:
            raise ValueError("Stage 4A.3 row signal-date lineage mismatch")
        if str(row["Ticker"]).upper() != ticker:
            raise ValueError("Stage 4A.3 row ticker lineage mismatch")
        if str(row["Protocol Commit"]) != FROZEN_PROTOCOL_COMMIT:
            raise ValueError("Stage 4A.3 row protocol commit mismatch")
        if str(row["Model Bundle Hash"]) != FROZEN_MODEL_BUNDLE_HASH:
            raise ValueError("Stage 4A.3 row model bundle mismatch")
        if str(row["Prediction Semantics"]) != FROZEN_PREDICTION_SEMANTICS:
            raise ValueError("Stage 4A.3 row prediction semantics mismatch")
        snapshot_id = str(metadata.get("Snapshot ID") or "")
        created = _utc(metadata.get("Snapshot Created UTC"), "Snapshot Created UTC")
        if str(row["Snapshot ID"]) != snapshot_id or _utc(row["Snapshot Created UTC"], "Snapshot Created UTC") != created:
            raise ValueError("Stage 4A.3 snapshot metadata-to-row binding mismatch")
        if created > cutoff:
            raise ValueError("Stage 4A.3 snapshot was created after the decision cutoff")

        r0_selected = _boolean(row["R0_K1 Selected"], "R0_K1 Selected")
        r3_selected = _boolean(row["R3_K1 Selected"], "R3_K1 Selected")
        return {
            "ml_prediction_id": f"{snapshot_id}:{signal_id}",
            "recommendation_id": str(recommendation.get("recommendation_id") or ""),
            "signal_id": signal_id,
            "ticker": ticker,
            "protocol_id": FROZEN_PROTOCOL_ID,
            "protocol_commit": FROZEN_PROTOCOL_COMMIT,
            "model_bundle_hash": FROZEN_MODEL_BUNDLE_HASH,
            "snapshot_id": snapshot_id,
            "snapshot_signal_date": signal_date,
            "snapshot_content_hash": content_hash,
            "snapshot_created_utc": created,
            "snapshot_chain_hash": str(chain["Current Chain Hash"]),
            "r0_score": format(float(row["R0 Score"]), ".17g"),
            "r0_same_date_rank": _integer(row["R0 Same-Date Rank"], "R0 Same-Date Rank"),
            "r0_k1_selected": r0_selected,
            "r3_score": format(float(row["R3 Score"]), ".17g"),
            "r3_same_date_rank": _integer(row["R3 Same-Date Rank"], "R3 Same-Date Rank"),
            "r3_k1_selected": r3_selected,
            "primary_policy": PRIMARY_POLICY,
            "primary_comparator": PRIMARY_COMPARATOR,
            "ml_primary_selected": r3_selected,
            "ml_comparator_selected": r0_selected,
            "ml_shadow_classification": "R3_K1_SELECTED" if r3_selected else "R3_K1_NOT_SELECTED",
            "experimental_action": "SELECT" if r3_selected else "NOT_SELECT",
            "ml_influence": "NONE",
        }
