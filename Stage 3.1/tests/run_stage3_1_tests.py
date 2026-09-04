"""Deterministic Stage 3.1 semantic hardening self-tests."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd


def _assert(condition: Any, detail: str) -> None:
    if not bool(condition):
        raise AssertionError(detail)


def _assert_conservative_mfe_bound(opportunities: pd.DataFrame) -> None:
    conservative = pd.to_numeric(
        opportunities["MFE_R_10_CONSERVATIVE"], errors="coerce"
    ).to_numpy(dtype=float, na_value=np.nan)
    full_bar = pd.to_numeric(
        opportunities["MFE_R_10_FULL_BAR_DIAGNOSTIC"], errors="coerce"
    ).to_numpy(dtype=float, na_value=np.nan)
    comparable = np.isfinite(conservative) & np.isfinite(full_bar)
    violations = int(
        np.sum(conservative[comparable] > np.maximum(0.0, full_bar[comparable]) + 1e-10)
    )
    _assert(violations == 0, f"conservative MFE bound violations={violations}")


def _assert_entry_label_availability(opportunities: pd.DataFrame) -> None:
    available = pd.to_datetime(
        opportunities["ENTRY_LABEL_AVAILABLE_DATE"], errors="coerce"
    )
    signal_date = pd.to_datetime(opportunities["Signal Date"], errors="coerce")
    observed = available.notna()
    before_signal = observed & (available < signal_date)
    missing_without_censoring = available.isna() & ~opportunities[
        "ENTRY_DATA_END_CENSORED"
    ].fillna(False).astype(bool)
    _assert(
        not before_signal.any() and not missing_without_censoring.any(),
        "entry availability violations: "
        f"before_signal={int(before_signal.sum())}, "
        f"missing_without_censoring={int(missing_without_censoring.sum())}",
    )


def run_tests(context: Mapping[str, Any]) -> pd.DataFrame:
    config = context["config"]
    repo_root = Path(context["repo_root"])
    stage_root = Path(context["stage_root"])
    signal = context["signal_state"]
    opp = context["opportunities"]
    pos = context["position_day"]
    feature_reg = context["feature_registry"]
    label_reg = context["label_registry"]
    ml_reg = context["ml_registry"]
    split = context["split_manifest"]
    availability = context["availability_audit"]
    date_audit = context["date_audit"]
    point_in_time = context["point_in_time"]
    entry_changes = context["entry_changes"]
    records: list[dict[str, Any]] = []

    def record(number: int, name: str, assertion: Callable[[], None]) -> None:
        started = time.perf_counter()
        try:
            assertion()
            status, detail = "PASS", "assertion satisfied"
        except Exception as exc:
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        records.append({
            "Test Number": number, "Test": name, "Status": status, "Detail": detail,
            "Runtime Milliseconds": round((time.perf_counter() - started) * 1000.0, 3),
        })

    def row_id_determinism() -> None:
        ids = context["row_id_recheck"]
        _assert(ids["expected"] == ids["actual"], str(ids))

    def parity(name: str) -> None:
        row = context[name].iloc[0]
        _assert(row["Status"] == "PASS" and int(row["Difference Count"]) == 0, str(row.to_dict()))

    tests: list[tuple[int, str, Callable[[], None]]] = [
        (1, "immutable tag resolution", lambda: _assert(subprocess.check_output(["git", "rev-list", "-n", "1", config["baseline_tag"]], cwd=repo_root, text=True).strip() == config["baseline_commit"], "tag mismatch")),
        (2, "Stage 2B.1 package hash", lambda: _assert((context["reference_gate"]["Status"] == "PASS").all(), context["reference_gate"].to_string(index=False))),
        (3, "frozen data hashes", lambda: _assert(context["reference_gate"].loc[context["reference_gate"]["Check"].str.contains("artifact hash"), "Status"].eq("PASS").all(), "reference artifact hash mismatch")),
        (4, "Signal ID uniqueness", lambda: _assert(signal["Signal ID"].is_unique and signal["Signal ID"].notna().all(), "Signal ID missing or duplicated")),
        (5, "Stage 3.1 Row ID determinism", row_id_determinism),
        (6, "signal source parity", lambda: parity("signal_parity_summary")),
        (7, "valid opportunity eligibility", lambda: _assert(opp["Opportunity Eligible"].fillna(False).astype(bool).all(), "ineligible opportunity retained")),
        (8, "no fake levels", lambda: _assert(opp[["Entry Low", "Entry High", "Stop Loss", "Target 1", "Target 2"]].notna().all().all(), "missing trade level")),
        (9, "pullback fill", lambda: _assert(((opp["Setup"] == "PULLBACK") & opp["ENTRY_FILLED"].eq(True)).any(), "no pullback fill")),
        (10, "breakout fill", lambda: _assert(((opp["Setup"] == "BREAKOUT") & opp["ENTRY_FILLED"].eq(True)).any(), "no breakout fill")),
        (11, "buy-limit ceiling", lambda: _assert((pd.to_numeric(opp.loc[(opp["Setup"] == "PULLBACK") & opp["ENTRY_FILLED"].eq(True), "EXECUTED_ENTRY"]) <= pd.to_numeric(opp.loc[(opp["Setup"] == "PULLBACK") & opp["ENTRY_FILLED"].eq(True), "Entry High"]) + 1e-10).all(), "pullback entry exceeded ceiling")),
        (12, "entry-day ambiguity flag", lambda: _assert(opp["ENTRY_DAY_SEQUENCE_AMBIGUOUS"].fillna(False).astype(bool).equals(opp["ENTRY_INTRADAY_LIMIT"].fillna(False).astype(bool)), "entry ambiguity mismatch")),
        (13, "stop/T1 same-bar conservative semantics", lambda: _assert(not (opp["STOP_BEFORE_T1_63"].eq(True) & opp["T1_BEFORE_STOP_63"].eq(True)).any(), "T1 and stop both credited")),
        (14, "stop/T2 same-bar conservative semantics", lambda: _assert(not (opp["STOP_BEFORE_T2_63"].eq(True) & opp["T2_BEFORE_STOP_63"].eq(True)).any(), "T2 and stop both credited")),
        (15, "T1 label", lambda: _assert(opp.loc[opp["T1_STATUS"] == "AVAILABLE", "T1_BEFORE_STOP_63"].notna().all(), "available T1 missing")),
        (16, "T2 label", lambda: _assert(opp.loc[opp["T2_STATUS"] == "AVAILABLE", "T2_BEFORE_STOP_63"].notna().all(), "available T2 missing")),
        (17, "target time", lambda: _assert(opp.loc[opp["TIME_TO_T1_SESSIONS"].notna(), "T1_BEFORE_STOP_63"].eq(True).all() and opp.loc[opp["TIME_TO_T2_SESSIONS"].notna(), "T2_BEFORE_STOP_63"].eq(True).all(), "time-to-target exists without success")),
        (18, "forward return 10", lambda: _assert(opp["FWD_CLOSE_RETURN_10_PCT"].equals(opp["FWD_CLOSE_RETURN_10_ENTRY_INCLUSIVE_PCT"]), "10-session alias mismatch")),
        (19, "forward return 63", lambda: _assert(opp["FWD_CLOSE_RETURN_63_PCT"].equals(opp["FWD_CLOSE_RETURN_63_ENTRY_INCLUSIVE_PCT"]), "63-session alias mismatch")),
        (20, "MFE calculation", lambda: _assert(opp.loc[opp["FWD_63_STATUS"] == "AVAILABLE", "MFE_R_63_FULL_BAR_DIAGNOSTIC"].notna().all(), "available MFE missing")),
        (21, "MAE calculation", lambda: _assert(opp.loc[opp["FWD_63_STATUS"] == "AVAILABLE", "MAE_R_63_FULL_BAR_DIAGNOSTIC"].notna().all(), "available MAE missing")),
        (22, "conservative entry-day MFE", lambda: _assert_conservative_mfe_bound(opp)),
        (23, "censored late-history row", lambda: _assert(opp.loc[opp["T1_DATA_END_CENSORED"].fillna(False), "T1_BEFORE_STOP_63"].isna().all(), "censored T1 has value")),
        (24, "label-available date", lambda: _assert_entry_label_availability(opp)),
        (25, "fold-training cutoff", lambda: _assert((split["Training Availability Violations"] == 0).all(), "training availability violation")),
        (26, "no future row in training", lambda: _assert((pd.to_datetime(split["Training As-Of Date Max"]) < pd.to_datetime(split["Evaluation Start"])).fillna(True).all(), "future as-of in training")),
        (27, "no target column in feature allow-list", lambda: _assert(context["target_leak_count"] == 0, str(context["target_leak_count"]))),
        (28, "no global imputation", lambda: _assert(not any(token in "\n".join(path.read_text(encoding="utf-8").lower() for path in (stage_root / "stage3_1").glob("*.py")) for token in ("bfill(", "standardscaler", "minmaxscaler", "fillna(frame.mean")), "prohibited full-history imputation")),
        (29, "current vs entry regime", lambda: _assert({"Entry Market Regime", "Current Market Regime"}.issubset(pos.columns), "regime lineage missing")),
        (30, "D1 shadow parity", lambda: _assert(context["d1_parity_summary"].iloc[0]["Status"] == "PASS", context["d1_parity_summary"].to_string(index=False))),
        (31, "position-day future-label separation", lambda: _assert(not ml_reg.loc[ml_reg["Column"].isin(["D1_EXIT_NEXT_SESSION", "D1_REMAINING_NET_R", "D1_FINAL_EXIT_REASON"]), "Role"].eq("FEATURE_ALLOWED").any(), "position target allowed")),
        (32, "package hash portability", lambda: _assert(all(not Path(item["relative_path"]).is_absolute() and "\\" not in item["relative_path"] for item in context["package_manifest"]["sources"]), "absolute source path")),
        (33, "dataset content hash determinism", lambda: _assert(context["content_hash_recheck"]["first"] == context["content_hash_recheck"]["second"], str(context["content_hash_recheck"]))),
        (34, "no future NIFTY fill", lambda: _assert((pd.to_datetime(signal["NIFTY Feature Source Date"]) <= pd.to_datetime(signal["Feature As-Of Date"])).all() and (pd.to_datetime(pos["Current Market Feature Source Date"]) <= pd.to_datetime(pos["Feature As-Of Date"])).all(), "future NIFTY source")),
        (35, "prefix-invariance audit", lambda: _assert(not point_in_time.empty and not point_in_time["Status"].eq("FAIL").any(), "prefix audit failed")),
    ]

    def synthetic_entry(observed: int, setup: str = "PULLBACK", filled_session: int | None = None) -> pd.Series:
        from opportunity_engine import harden_entry_semantics
        signal_date = pd.Timestamp("2026-08-20")
        dates = pd.bdate_range(signal_date + pd.Timedelta(days=1), periods=observed)
        filled = filled_session is not None
        entry_date = dates[filled_session - 1] if filled else pd.NaT
        source = pd.DataFrame([{
            "Signal ID": "SYNTH", "Ticker": "SYNTH.NS", "Signal Date": signal_date,
            "Setup": setup, "ENTRY_FILLED": True if filled else False,
            "ENTRY_DATE": entry_date, "ENTRY_CENSORED": False,
            "ENTRY_RISK_VALID": True, "ENTRY_STATUS": "FILLED" if filled else "EXPIRED",
        }])
        hardened, _ = harden_entry_semantics(source, {"SYNTH.NS": pd.DatetimeIndex(dates)}, config)
        return hardened.iloc[0]

    tests.extend([
        (36, "pullback no future session => entry data-end censored", lambda: _assert(synthetic_entry(0)["ENTRY_DATA_END_CENSORED"], "not censored")),
        (37, "pullback 1 of 5 sessions/no fill => censored", lambda: _assert(synthetic_entry(1)["ENTRY_DATA_END_CENSORED"], "not censored")),
        (38, "pullback 2 of 5 sessions/no fill => censored", lambda: _assert(synthetic_entry(2)["ENTRY_DATA_END_CENSORED"], "not censored")),
        (39, "pullback 3 of 5 sessions/no fill => censored", lambda: _assert(synthetic_entry(3)["ENTRY_DATA_END_CENSORED"], "not censored")),
        (40, "pullback 4 of 5 sessions/no fill => censored", lambda: _assert(synthetic_entry(4)["ENTRY_DATA_END_CENSORED"], "not censored")),
        (41, "pullback 5 of 5 sessions/no fill => genuine non-fill", lambda: _assert(synthetic_entry(5)["ENTRY_FILLED"] == False and not synthetic_entry(5)["ENTRY_DATA_END_CENSORED"], "not genuine non-fill")),
        (42, "incomplete window but early fill => valid fill, not censored", lambda: _assert(synthetic_entry(2, filled_session=2)["ENTRY_FILLED"] == True and not synthetic_entry(2, filled_session=2)["ENTRY_DATA_END_CENSORED"], "early fill censored")),
        (43, "nonfilled opportunity => T1 NOT_APPLICABLE, not censored", lambda: _assert((opp.loc[opp["ENTRY_FILLED"].eq(False), "T1_STATUS"] == "NOT_APPLICABLE").all() and not opp.loc[opp["ENTRY_FILLED"].eq(False), "T1_DATA_END_CENSORED"].any(), "nonfill T1 semantics")),
        (44, "invalid-risk fill => T1 NOT_APPLICABLE", lambda: _assert((opp.loc[opp["ENTRY_FILLED"].eq(True) & ~opp["ENTRY_RISK_VALID"].fillna(False), "T1_STATUS"] == "NOT_APPLICABLE").all(), "invalid-risk T1 applicable")),
        (45, "filled unresolved late row => true DATA_END_CENSORED", lambda: _assert((opp.loc[opp["T1_DATA_END_CENSORED"].fillna(False), "ENTRY_FILLED"].eq(True) & opp.loc[opp["T1_DATA_END_CENSORED"].fillna(False), "ENTRY_RISK_VALID"].eq(True)).all(), "invalid T1 censoring")),
        (46, "D1 non-primary opportunity => D1 NOT_APPLICABLE", lambda: _assert((opp.loc[opp["Dataset Cohort"] != "BASELINE_PRIMARY", "D1_SHADOW_STATUS"] == "NOT_APPLICABLE").all(), "nonprimary D1 applicable")),
        (47, "applicable D1 end-of-data trajectory => true censoring", lambda: _assert((opp.loc[opp["D1_SHADOW_DATA_END_CENSORED"].fillna(False), "D1_SHADOW_STATUS"] == "DATA_END_CENSORED").all(), "D1 censor mismatch")),
        (48, "raw date fields cannot be FEATURE_ALLOWED", lambda: _assert(not date_audit["FEATURE_ALLOWED Violation"].fillna(False).any(), date_audit.to_string(index=False))),
        (49, "NIFTY Feature Source Date explicitly not FEATURE_ALLOWED", lambda: _assert(not ((ml_reg["Column"] == "NIFTY Feature Source Date") & (ml_reg["Role"] == "FEATURE_ALLOWED")).any(), "NIFTY source date allowed")),
        (50, "feature registry composite key uniqueness", lambda: _assert(not feature_reg.duplicated(["Dataset", "Feature Name"]).any(), "duplicate composite feature key")),
        (51, "same feature name can have distinct dataset semantics", lambda: _assert(feature_reg.groupby("Feature Name")["Dataset"].nunique().max() >= 2, "no dataset-specific duplicate feature names")),
        (52, "ML registry equals feature registry per dataset", lambda: _assert(context["registry_symmetric_difference"] == 0, str(context["registry_symmetric_difference"]))),
        (53, "entry-inclusive forward alias exact equality", lambda: _assert(all(opp[f"FWD_CLOSE_RETURN_{h}_PCT"].equals(opp[f"FWD_CLOSE_RETURN_{h}_ENTRY_INCLUSIVE_PCT"]) and opp[f"FWD_CLOSE_RETURN_{h}_R"].equals(opp[f"FWD_CLOSE_RETURN_{h}_ENTRY_INCLUSIVE_R"]) for h in config["forward_horizons"]), "forward alias mismatch")),
        (54, "time-to-target marked conditional", lambda: _assert((label_reg.loc[label_reg["Label Name"].isin(["TIME_TO_T1_SESSIONS", "TIME_TO_T2_SESSIONS"]), "Model Task Type"] == "CONDITIONAL_REGRESSION").all(), "time target not conditional")),
        (55, "validation report uses violation count, not row count", lambda: _assert(all(column in availability.columns for column in ["Availability Before As-Of Violations", "Unavailable Label With Value Violations", "Training Availability Violations"]), "violation columns missing")),
        (56, "not-applicable rows never receive manufactured target values", lambda: _assert(opp.loc[opp["T1_STATUS"] == "NOT_APPLICABLE", "T1_BEFORE_STOP_63"].isna().all() and opp.loc[opp["T2_STATUS"] == "NOT_APPLICABLE", "T2_BEFORE_STOP_63"].isna().all(), "manufactured non-applicable label")),
        (57, "censored rows never receive manufactured final labels", lambda: _assert(opp.loc[opp["T1_STATUS"] == "DATA_END_CENSORED", "T1_BEFORE_STOP_63"].isna().all() and opp.loc[opp["T2_STATUS"] == "DATA_END_CENSORED", "T2_BEFORE_STOP_63"].isna().all(), "manufactured censored label")),
        (58, "complete Stage 3 stable cohort numerical parity", lambda: parity("target_parity_summary")),
        (59, "incomplete-window differences only in documented rows", lambda: _assert(entry_changes.empty or entry_changes["Reason"].isin(["NO_FUTURE_SESSION", "INCOMPLETE_ENTRY_WINDOW"]).all(), entry_changes.to_string(index=False))),
        (60, "walk-forward training requires AVAILABLE and APPLICABLE", lambda: _assert((split["Training Availability Violations"] == 0).all() and (split["Training Rows"] == split["Training Label Available Rows"]).all(), "invalid training rows")),
    ])

    for number, name, assertion in tests:
        record(number, name, assertion)
    result = pd.DataFrame(records)
    if len(result) != 60 or list(result["Test Number"]) != list(range(1, 61)):
        raise AssertionError("Stage 3.1 suite must contain exactly 60 ordered tests")
    return result


if __name__ == "__main__":
    raise SystemExit("Run through Stock_Alert_Stage3_1_Dataset_Builder.py")
