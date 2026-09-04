"""Deterministic Stage 3 acceptance tests.

These tests deliberately exercise the built datasets and small synthetic OHLC
paths.  A PASS is recorded only after the corresponding assertion executes.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from hashing import (canonical_json_hash, dataframe_content_hash,
                     deterministic_row_id)
from labels import add_opportunity_labels
from opportunity_engine import (LEVEL_COLUMNS, opportunity_eligibility,
                                simulate_entry)


def _assert(condition: Any, detail: str) -> None:
    if not bool(condition):
        raise AssertionError(detail)


def _ohlc(rows: list[tuple[float, float, float, float]], start: str = "2020-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=dates)


def _entry_source(setup: str) -> dict[str, Any]:
    return {
        "Signal ID": f"SYNTHETIC-{setup}",
        "Ticker": "TEST.NS",
        "Signal Date": pd.Timestamp("2020-01-01"),
        "Signal": "BUY",
        "Original Signal": "BUY",
        "Setup": setup,
        "Entry Low": 98.0,
        "Entry High": 100.0,
        "Stop Loss": 90.0,
        "Target 1": 110.0,
        "Target 2": 120.0,
        "Actionability Score": 70.0,
        "Technical Score": 75.0,
        "R:R T1": 1.0,
        "RS 60D": 2.0,
        "Market Regime": "BULL",
    }


def _filled_label_source(intraday: bool = False) -> dict[str, Any]:
    return {
        **_entry_source("PULLBACK" if intraday else "BREAKOUT"),
        "ENTRY_FILLED": True,
        "ENTRY_RISK_VALID": True,
        "ENTRY_DATE": pd.Timestamp("2020-01-02"),
        "NOMINAL_ENTRY": 100.0,
        "EXECUTED_ENTRY": 100.0,
        "ENTRY_INTRADAY_LIMIT": intraday,
        "INITIAL_RISK_PER_SHARE": 10.0,
    }


def _label_path() -> pd.DataFrame:
    rows = [(100.0, 104.0, 96.0, 101.0) for _ in range(63)]
    rows[1] = (101.0, 111.0, 99.0, 110.0)
    rows[2] = (110.0, 121.0, 105.0, 120.0)
    rows[9] = (108.0, 114.0, 98.0, 110.0)
    rows[20] = (110.0, 130.0, 95.0, 112.0)
    rows[62] = (120.0, 126.0, 99.0, 125.0)
    return _ohlc(rows)


def run_tests(context: Mapping[str, Any]) -> pd.DataFrame:
    config = context["config"]
    metadata = context["baseline_metadata"]
    source = context["source"]
    signal_state = context["signal_state"]
    opportunities = context["opportunities"]
    position_day = context["position_day"]
    frozen = context["frozen"]
    stage_root = Path(context["stage_root"])
    repo_root = Path(context["repo_root"])
    records: list[dict[str, Any]] = []

    def record(number: int, name: str, assertion: Callable[[], None]) -> None:
        started = time.perf_counter()
        status, detail = "PASS", "assertion satisfied"
        try:
            assertion()
        except Exception as exc:  # each failure must remain visible in the report
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        records.append({
            "Test Number": number,
            "Test": name,
            "Status": status,
            "Detail": detail,
            "Runtime Milliseconds": round((time.perf_counter() - started) * 1000.0, 3),
        })

    def immutable_tag() -> None:
        actual = subprocess.check_output(
            ["git", "rev-list", "-n", "1", config["baseline_tag"]], cwd=repo_root, text=True
        ).strip()
        _assert(actual == config["baseline_commit"], f"tag resolved to {actual}")

    def package_hash() -> None:
        _assert(metadata["package_hash"] == config["expected_hashes"]["STAGE2B1_PACKAGE_HASH"], metadata["package_hash"])

    def frozen_hashes() -> None:
        _assert(metadata["data_hash"] == config["expected_hashes"]["DATA_CONTENT_HASH"], metadata["data_hash"])

    def signal_ids_unique() -> None:
        _assert(signal_state["Signal ID"].notna().all() and signal_state["Signal ID"].is_unique, "Signal ID missing or duplicated")

    def row_id_determinism() -> None:
        row = signal_state.iloc[0]
        expected = deterministic_row_id(config["dataset_schema_versions"]["signal_state"], row["Signal ID"])
        _assert(row["STAGE3_ROW_ID"] == expected, f"{row['STAGE3_ROW_ID']} != {expected}")

    def source_parity() -> None:
        summary = context["source_summary"].iloc[0]
        _assert(summary["Status"] == "PASS" and int(summary["Difference Count"]) == 0 and len(source) == len(signal_state), str(summary.to_dict()))

    def valid_eligibility() -> None:
        _assert(not opportunities.empty, "no opportunities")
        allowed = set(config["baseline_primary_signals"]) | set(config["research_extended_signals"])
        _assert(opportunities["Opportunity Eligible"].astype(bool).all(), "ineligible opportunity retained")
        _assert(set(opportunities["Signal"]).issubset(allowed), "unexpected signal cohort")

    def no_fake_levels() -> None:
        _assert(opportunities[list(LEVEL_COLUMNS)].notna().all().all(), "eligible opportunity has missing levels")
        excluded_ids = set(signal_state.loc[signal_state["Signal"].isin(config["explicitly_excluded_signals"]), "Signal ID"])
        _assert(excluded_ids.isdisjoint(set(opportunities["Signal ID"])), "excluded signal became an opportunity")

    pullback_frame = _ohlc([(105.0, 108.0, 99.0, 104.0)])
    breakout_frame = _ohlc([(100.0, 104.0, 97.0, 102.0)])
    pullback = simulate_entry(_entry_source("PULLBACK"), pullback_frame, frozen["stage221"], frozen["frozen_config"], config)
    breakout = simulate_entry(_entry_source("BREAKOUT"), breakout_frame, frozen["stage221"], frozen["frozen_config"], config)

    def pullback_fill() -> None:
        _assert(pullback["ENTRY_FILLED"] and pullback["ENTRY_METHOD"] == "PULLBACK_LIMIT", str(pullback))

    def breakout_fill() -> None:
        _assert(breakout["ENTRY_FILLED"] and breakout["ENTRY_METHOD"] == "NEXT_OPEN", str(breakout))

    def buy_limit_ceiling() -> None:
        _assert(float(pullback["EXECUTED_ENTRY"]) <= 100.0 and np.isclose(float(pullback["EXECUTED_ENTRY"]), 100.0), str(pullback))

    def entry_ambiguity() -> None:
        _assert(bool(pullback["ENTRY_DAY_SEQUENCE_AMBIGUOUS"]) and not bool(breakout["ENTRY_DAY_SEQUENCE_AMBIGUOUS"]), "ambiguity flags incorrect")

    collision_frame = _ohlc([(100.0, 121.0, 89.0, 101.0)] + [(101.0, 105.0, 95.0, 102.0)] * 62)
    collision = add_opportunity_labels(_filled_label_source(intraday=True), collision_frame, config)

    def stop_t1_collision() -> None:
        _assert(collision["T1_LABEL_OUTCOME"] == "STOP" and collision["T1_BEFORE_STOP_63"] is False, str(collision))

    def stop_t2_collision() -> None:
        _assert(collision["T2_LABEL_OUTCOME"] == "STOP" and collision["T2_BEFORE_STOP_63"] is False and collision["OUTCOME_SEQUENCE_AMBIGUOUS"], str(collision))

    label_frame = _label_path()
    labels = add_opportunity_labels(_filled_label_source(), label_frame, config)

    def t1_label() -> None:
        _assert(labels["T1_BEFORE_STOP_63"] is True and labels["T1_LABEL_OUTCOME"] == "TARGET", str(labels))

    def t2_label() -> None:
        _assert(labels["T2_BEFORE_STOP_63"] is True and labels["T2_LABEL_OUTCOME"] == "TARGET", str(labels))

    def target_time() -> None:
        _assert(labels["TIME_TO_T1_SESSIONS"] == 2 and labels["TIME_TO_T2_SESSIONS"] == 3, str(labels))

    def forward_10() -> None:
        _assert(np.isclose(labels["FWD_CLOSE_RETURN_10_PCT"], 10.0) and labels["FWD_10_AVAILABLE_DATE"] == label_frame.index[9], str(labels))

    def forward_63() -> None:
        _assert(np.isclose(labels["FWD_CLOSE_RETURN_63_PCT"], 25.0) and not labels["FWD_63_CENSORED"], str(labels))

    def mfe() -> None:
        _assert(np.isclose(labels["MFE_R_63_FULL_BAR_DIAGNOSTIC"], 3.0), str(labels))

    def mae() -> None:
        _assert(np.isclose(labels["MAE_R_63_FULL_BAR_DIAGNOSTIC"], -0.5), str(labels))

    conservative_rows = [(100.0, 200.0, 99.0, 101.0)] + [(101.0, 130.0, 95.0, 105.0)] + [(105.0, 110.0, 96.0, 106.0)] * 61
    conservative = add_opportunity_labels(_filled_label_source(intraday=True), _ohlc(conservative_rows), config)

    def conservative_entry_mfe() -> None:
        _assert(np.isclose(conservative["MFE_R_10_FULL_BAR_DIAGNOSTIC"], 10.0), str(conservative))
        _assert(np.isclose(conservative["MFE_R_10_CONSERVATIVE"], 3.0), str(conservative))

    censored = add_opportunity_labels(_filled_label_source(), _ohlc([(100.0, 105.0, 95.0, 101.0)] * 5), config)

    def censored_late() -> None:
        _assert(censored["T1_CENSORED"] and pd.isna(censored["T1_BEFORE_STOP_63"]) and censored["FWD_63_CENSORED"], str(censored))

    def label_available() -> None:
        _assert(labels["T1_LABEL_AVAILABLE_DATE"] == label_frame.index[1] and labels["TARGET_TIME_LABEL_AVAILABLE_DATE"] == label_frame.index[2], str(labels))
        _assert(pullback["ENTRY_LABEL_AVAILABLE_DATE"] == pullback_frame.index[0] and not pullback["ENTRY_CENSORED"], str(pullback))

    def fold_cutoff() -> None:
        manifest = context["split_manifest"]
        _assert(not manifest.empty and (manifest["Training Availability Violations"] == 0).all(), "fold has unresolved labels")

    def no_future_training() -> None:
        manifest = context["split_manifest"].dropna(subset=["Training Signal Date Max"])
        _assert((pd.to_datetime(manifest["Training Signal Date Max"]) < pd.to_datetime(manifest["Evaluation Start"])).all(), "future-as-of row in training")
        _assert((manifest["Training Availability Violations"] == 0).all(), "label availability cutoff violation")

    def no_target_feature() -> None:
        registry = context["ml_registry"]
        forbidden = registry[(registry["Role"] == "FEATURE_ALLOWED") & registry["Column"].str.contains("BEFORE_STOP|FWD_|FULL_BAR_DIAGNOSTIC|FINAL_EXIT|LABEL_AVAILABLE|CENSORED", case=False, regex=True)]
        _assert(forbidden.empty, forbidden.to_string(index=False))
        fill_roles = registry.loc[registry["Column"] == "ENTRY_FILLED", "Role"]
        _assert(not fill_roles.empty and (fill_roles == "TARGET").all(), fill_roles.to_string(index=False))

    def no_global_imputation() -> None:
        prohibited = ("bfill(", ".bfill(", "standardscaler", "minmaxscaler", "fillna(frame.mean", "fillna(values.mean")
        text = "\n".join(path.read_text(encoding="utf-8").lower() for path in (stage_root / "stage3").glob("*.py"))
        found = [token for token in prohibited if token in text]
        _assert(not found, f"prohibited full-history operation(s): {found}")

    def current_entry_regime() -> None:
        _assert({"Entry Market Regime", "Current Market Regime"}.issubset(position_day.columns), "regime lineage missing")
        _assert(position_day["Current Market Regime"].notna().all(), "missing current regime")

    def d1_parity() -> None:
        row = context["d1_summary"].iloc[0]
        _assert(row["Status"] == "PASS" and int(row["Difference Count"]) == 0, str(row.to_dict()))

    def position_label_separation() -> None:
        registry = context["ml_registry"]
        names = ["D1_EXIT_NEXT_SESSION", "D1_REMAINING_NET_R", "D1_FINAL_EXIT_REASON", "ORIGINAL_T2_REACHED_BEFORE_D1_EXIT"]
        selected = registry[(registry["Dataset"] == "d1_position_day") & registry["Column"].isin(names)]
        _assert(set(selected["Column"]) == set(names), "position labels missing from registry")
        _assert(not (selected["Role"] == "FEATURE_ALLOWED").any(), selected.to_string(index=False))
        current_path = registry[(registry["Dataset"] == "d1_position_day") & registry["Column"].isin({"Current MFE Conservative To Date", "Current MAE Conservative To Date"})]
        _assert(len(current_path) == 2 and (current_path["Role"] == "FEATURE_ALLOWED").all(), current_path.to_string(index=False))
        _assert(all(pd.api.types.is_numeric_dtype(position_day[column]) for column in current_path["Column"]), "current path state was not kept numeric")

    def package_portability() -> None:
        manifest = context["package_manifest"]
        paths = [row["relative_path"] for row in manifest["sources"]]
        _assert(all(not Path(path).is_absolute() and "\\" not in path for path in paths), str(paths))
        _assert(manifest["package_hash"] == canonical_json_hash(manifest["sources"]), manifest["package_hash"])

    def content_hash_determinism() -> None:
        sample = signal_state.iloc[: min(25, len(signal_state))].copy()
        first, second = dataframe_content_hash(sample), dataframe_content_hash(sample.copy(deep=True))
        _assert(first == second, f"{first} != {second}")

    def no_future_nifty_fill() -> None:
        signal_ok = (pd.to_datetime(signal_state["NIFTY Feature Source Date"]) <= pd.to_datetime(signal_state["Feature As-Of Date"])).all()
        position_ok = (pd.to_datetime(position_day["Current Market Feature Source Date"]) <= pd.to_datetime(position_day["Feature As-Of Date"])).all()
        _assert(signal_ok and position_ok, "NIFTY source date exceeds feature as-of")

    def prefix_invariance() -> None:
        audit = context["point_in_time"]
        _assert(not audit.empty and not (audit["Status"] == "FAIL").any() and (audit["Status"] == "PASS").any(), audit.to_string(index=False))

    tests = [
        (1, "immutable tag resolution", immutable_tag),
        (2, "Stage 2B.1 package hash", package_hash),
        (3, "frozen data hashes", frozen_hashes),
        (4, "Signal ID uniqueness", signal_ids_unique),
        (5, "Stage 3 Row ID determinism", row_id_determinism),
        (6, "signal source parity", source_parity),
        (7, "valid opportunity eligibility", valid_eligibility),
        (8, "no fake levels", no_fake_levels),
        (9, "pullback fill", pullback_fill),
        (10, "breakout fill", breakout_fill),
        (11, "buy-limit ceiling", buy_limit_ceiling),
        (12, "entry-day ambiguity flag", entry_ambiguity),
        (13, "stop/T1 same-bar conservative semantics", stop_t1_collision),
        (14, "stop/T2 same-bar conservative semantics", stop_t2_collision),
        (15, "T1 label", t1_label),
        (16, "T2 label", t2_label),
        (17, "target time", target_time),
        (18, "forward return 10", forward_10),
        (19, "forward return 63", forward_63),
        (20, "MFE calculation", mfe),
        (21, "MAE calculation", mae),
        (22, "conservative entry-day MFE", conservative_entry_mfe),
        (23, "censored late-history row", censored_late),
        (24, "label-available date", label_available),
        (25, "fold-training cutoff", fold_cutoff),
        (26, "no future row in training", no_future_training),
        (27, "no target column in feature allow-list", no_target_feature),
        (28, "no global imputation", no_global_imputation),
        (29, "current vs entry regime", current_entry_regime),
        (30, "D1 shadow parity", d1_parity),
        (31, "position-day future-label separation", position_label_separation),
        (32, "package hash portability", package_portability),
        (33, "dataset content hash determinism", content_hash_determinism),
        (34, "no future NIFTY fill", no_future_nifty_fill),
        (35, "prefix-invariance audit", prefix_invariance),
    ]
    for number, name, assertion in tests:
        record(number, name, assertion)
    result = pd.DataFrame(records)
    if len(result) != 35 or list(result["Test Number"]) != list(range(1, 36)):
        raise AssertionError("The Stage 3 suite must contain exactly 35 ordered tests")
    return result


if __name__ == "__main__":
    raise SystemExit("Run this suite through Stock_Alert_Stage3_Dataset_Builder.py")
