"""Stage 3: auditable point-in-time research dataset construction.

This builder trains no model, selects no features, tunes no thresholds, and
treats Stage 2B.1 plus every earlier stage as immutable dependencies.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE_ROOT = HERE.parent
REPO_ROOT = STAGE_ROOT.parent
sys.path.insert(0, str(HERE))

from diagnostics import (ambiguity_summary, censoring_summary, dataset_summary,
                         d1_position_day_summary, feature_distribution_by_era,
                         feature_missingness, target_summary)
from features import (build_signal_state_dataset, feature_registry,
                      load_frozen_context, point_in_time_audit,
                      read_split_gzip_csv)
from hashing import (canonical_json_hash, dataframe_content_hash,
                     dataframe_schema, dataframe_schema_hash,
                     environment_report, sha256_file,
                     source_package_manifest, write_deterministic_csv_gz,
                     write_json)
from labels import add_opportunity_labels, label_registry
from opportunity_engine import build_opportunities
from position_day_builder import build_d1_datasets
from splits import build_walk_forward_manifest
from validation import (baseline_gate, candidate_outcome_parity,
                        d1_shadow_parity, fail_if_any, integration_checks,
                        ml_column_registry, source_parity)


BEHAVIOR_SOURCES = (
    "stage3/Stock_Alert_Stage3_Dataset_Builder.py",
    "stage3/features.py",
    "stage3/labels.py",
    "stage3/opportunity_engine.py",
    "stage3/position_day_builder.py",
    "stage3/splits.py",
    "stage3/validation.py",
    "stage3/hashing.py",
    "stage3/diagnostics.py",
)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", na_rep="<NA>", float_format="%.12g", date_format="%Y-%m-%d")


def _normalize_date_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        # Only normalize true calendar-date fields.  State features such as
        # "Current MFE Conservative To Date" are numeric and must never be
        # interpreted as nanosecond timestamps merely because their English
        # name contains the words "To Date".
        human_date = column.endswith(" Date") and not column.endswith(" To Date")
        machine_date = column.endswith("_DATE")
        if human_date or machine_date:
            converted = pd.to_datetime(result[column], errors="coerce")
            if converted.notna().any() or result[column].isna().all():
                result[column] = converted.dt.normalize()
    return result


def _add_labels(opportunities: pd.DataFrame, features: Mapping[str, pd.DataFrame], config: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for opportunity in opportunities.to_dict("records"):
        rows.append(add_opportunity_labels(opportunity, features[str(opportunity["Ticker"])], config))
    labels = pd.DataFrame(rows, index=opportunities.index)
    return pd.concat([opportunities, labels], axis=1)


def _run_self_tests(context: Mapping[str, Any]) -> pd.DataFrame:
    module = _load_module("stage3_self_tests", STAGE_ROOT / "tests/run_stage3_tests.py")
    return module.run_tests(context)


def _write_validation_report(checks: pd.DataFrame, path: Path) -> None:
    lines = [f"{row.Status}: [{row.Type}] {row.Check} | expected={row.Expected} | actual={row.Actual} | {row.Detail}" for row in checks.itertuples(index=False)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _delivery_report(identity: Mapping[str, Any], summary: Mapping[str, Any], dataset_manifest: Mapping[str, Any], status: str, runtime: float) -> str:
    artifacts = dataset_manifest["datasets"]
    lines = [
        "# Stage 3 Delivery Report",
        "",
        f"ENGINEERING STATUS: **{status}**",
        "",
        "Stage 3 constructed point-in-time research datasets only. It did not train or evaluate a predictive model.",
        "",
        "## Frozen baseline",
        "",
        f"- Tag: `{identity['baseline_tag']}`",
        f"- Commit: `{identity['baseline_commit']}`",
        f"- Stage 2B.1 experiment: `{identity['source_experiment_id']}`",
        f"- Stage 2B.1 package hash: `{identity['expected_hashes']['STAGE2B1_PACKAGE_HASH']}`",
        "- Immutable baseline hashes verified before and after execution: **PASS**",
        *[f"- {name}: `{value}`" for name, value in identity["expected_hashes"].items() if name != "STAGE2B1_PACKAGE_HASH"],
        "",
        "## Stage 3 identity",
        "",
        f"- Experiment ID: `{identity['experiment_id']}`",
        f"- Code package hash: `{identity['STAGE3_CODE_PACKAGE_HASH']}`",
        f"- Config hash: `{identity['STAGE3_CONFIG_HASH']}`",
        f"- Combined schema hash: `{dataset_manifest['STAGE3_SCHEMA_HASH']}`",
        "",
        "## Dataset research findings (descriptive only)",
        "",
        f"- Signal-state rows: {summary['signal_rows']:,}",
        f"- Opportunity rows: {summary['opportunity_rows']:,}",
        f"- Filled opportunities: {summary['filled_rows']:,}",
        f"- Observed non-filled opportunities: {summary['nonfilled_rows']:,}",
        f"- Entry-censored opportunities: {summary['entry_censored']:,}",
        f"- BASELINE_PRIMARY rows: {summary['baseline_primary_rows']:,}",
        f"- RESEARCH_EXTENDED rows: {summary['research_extended_rows']:,}",
        f"- D1 position-day rows: {summary['position_day_rows']:,}",
        f"- T1 positive / negative / censored: {summary['t1_positive']:,} / {summary['t1_negative']:,} / {summary['t1_censored']:,}",
        f"- T2 positive / negative / censored: {summary['t2_positive']:,} / {summary['t2_negative']:,} / {summary['t2_censored']:,}",
        f"- Fill rate: {summary['fill_rate_pct']:.4f}%",
        f"- Entry / T1 / T2 censoring rates: {summary['entry_censor_rate_pct']:.4f}% / {summary['t1_censor_rate_pct']:.4f}% / {summary['t2_censor_rate_pct']:.4f}%",
        f"- Entry-day ambiguity rate: {summary['entry_ambiguity_pct']:.4f}%",
        f"- Same-bar ambiguity rate: {summary['same_bar_ambiguity_pct']:.4f}%",
        f"- High-missingness feature records: {summary['high_missingness_records']:,}",
        f"- High-missingness examples: {summary['high_missingness_examples'] or 'NONE'}",
        "",
        "## Acceptance audits",
        "",
        f"- Point-in-time prefix audit: {summary['point_in_time_status']}",
        f"- Signal source parity: {summary['source_parity_status']}",
        f"- Candidate outcome parity: {summary['candidate_parity_status']}",
        f"- D1 shadow parity: {summary['d1_parity_status']}",
        f"- Walk-forward manifest rows / targets / evaluation years: {summary['split_rows']:,} / {summary['split_targets']:,} / {summary['split_years']:,}",
        f"- Runtime: {runtime:.2f} seconds",
        "",
        "## Dataset identities",
        "",
    ]
    for artifact in artifacts:
        lines.append(f"- `{artifact['dataset_name']}`: rows={artifact['row_count']:,}, columns={artifact['column_count']}, content=`{artifact['content_hash']}`, artifact=`{artifact['artifact_hash']}`, bytes={artifact['artifact_size_bytes']:,}")
    lines += [
        "",
        "## Required scope declarations",
        "",
        "STAGE 2.2.2 FINAL MODIFIED: NO",
        "",
        "STAGE 2B MODIFIED: NO",
        "",
        "STAGE 2B.1 MODIFIED: NO",
        "",
        "STAGE 1 SIGNAL RULES CHANGED: NO",
        "",
        "D1 MANAGEMENT RULES CHANGED: NO",
        "",
        "ML MODEL TRAINED: NO",
        "",
        "FEATURE SELECTION PERFORMED: NO",
        "",
        "HYPERPARAMETER TUNING PERFORMED: NO",
        "",
        "POINT-IN-TIME DATASET BUILT: YES",
        "",
        "WALK-FORWARD SPLIT MANIFEST BUILT: YES",
        "",
        "## Known limitations",
        "",
        "- Current-universe survivorship bias; the universe is not point-in-time NIFTY membership.",
        "- Historical pseudo-OOS is not prospective unseen data.",
        "- Daily OHLC cannot establish intraday sequence; entry-day and exit-day ambiguity remain explicit.",
        "- Stage 1 retains the known holiday-short weekly delay.",
        "- Costs remain a generic basis-point model.",
        "- D1 evidence and 2024-2026 performance remain historically weak.",
        "- Stage 2B.1 empirical confidence was historically overconfident.",
        "- Sector/index-membership history is not point-in-time.",
        "- No ML model has been validated.",
    ]
    return "\n".join(lines) + "\n"


def run(sanity: bool = False, requested_tickers: Sequence[str] = ()) -> dict[str, Any]:
    started = time.perf_counter()
    config_path = STAGE_ROOT / "config/stage3_dataset_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    baseline_pre, baseline_metadata = baseline_gate(REPO_ROOT, config)
    package_pre = source_package_manifest(STAGE_ROOT, BEHAVIOR_SOURCES)
    config_hash = canonical_json_hash(config)
    identity_basis = {"stage": "3", "package": package_pre["package_hash"], "config": config_hash, "baseline_commit": config["baseline_commit"], "source_experiment": config["source_experiment_id"]}
    experiment_id = f"S3_{config['test_start'].replace('-', '')}_{config['test_end'].replace('-', '')}_{canonical_json_hash(identity_basis)[:12]}"
    if sanity:
        experiment_id += "_SANITY"

    source, source_parts = read_split_gzip_csv(REPO_ROOT, config["source_paths"]["accepted_candidates_glob"])
    source["Signal Date"] = pd.to_datetime(source["Signal Date"]).dt.normalize()
    tickers = list(dict.fromkeys(source["Ticker"].astype(str)))
    if requested_tickers:
        unknown = sorted(set(requested_tickers) - set(tickers))
        if unknown:
            raise ValueError(f"Unknown requested tickers: {unknown}")
        tickers = list(requested_tickers)
    elif sanity:
        tickers = [ticker for ticker in ("TCS.NS", "INFY.NS") if ticker in tickers]
    source = source[source["Ticker"].isin(tickers)].copy().reset_index(drop=True)

    frozen = load_frozen_context(REPO_ROOT, config, tickers)
    signal_state = build_signal_state_dataset(source, frozen["features"], frozen["market"], config, experiment_id)
    opportunities = build_opportunities(signal_state, frozen["features"], frozen["stage221"], frozen["frozen_config"], config)
    opportunities = _add_labels(opportunities, frozen["features"], config)

    policies = _load_module("stage3_stage2b1_policies", REPO_ROOT / "Stage 2B.1/stage2b/policies.py")
    policy_config = policies.PolicyConfig.from_mapping(config)
    opportunities, position_day = build_d1_datasets(opportunities, frozen["features"], frozen["market"], policies, policy_config, config, experiment_id)
    signal_state = _normalize_date_columns(signal_state)
    opportunities = _normalize_date_columns(opportunities)
    position_day = _normalize_date_columns(position_day)

    feature_reg = feature_registry(signal_state, position_day)
    label_reg = label_registry(config)
    ml_reg = ml_column_registry(
        {"signal_state": signal_state, "trade_opportunity": opportunities, "d1_position_day": position_day},
        feature_reg["Feature Name"], label_reg["Label Name"],
    )
    pit = point_in_time_audit(frozen, config)
    source_summary, source_diff = source_parity(source, signal_state)
    candidate_summary, candidate_diff = candidate_outcome_parity(source, opportunities)
    d1_summary, d1_diff = d1_shadow_parity(REPO_ROOT, config, opportunities)
    split_manifest, availability_audit = build_walk_forward_manifest(opportunities, position_day, config)

    integration = integration_checks(signal_state, opportunities, position_day, feature_reg, ml_reg, pit, source_summary, candidate_summary, d1_summary, config)
    baseline_post, _ = baseline_gate(REPO_ROOT, config)
    package_post = source_package_manifest(STAGE_ROOT, BEHAVIOR_SOURCES)
    package_check = pd.DataFrame([{"Type": "HASH_GATE_POST_RUN", "Check": "Stage 3 source package unchanged during execution", "Status": "PASS" if package_post["package_hash"] == package_pre["package_hash"] else "FAIL", "Expected": package_pre["package_hash"], "Actual": package_post["package_hash"], "Detail": ""}])
    checks = pd.concat([baseline_pre, integration, availability_audit.rename(columns={"Target": "Check", "Rows": "Actual"}).assign(Type="LABEL_AVAILABILITY", Expected="0 violations", Detail="")[['Type','Check','Status','Expected','Actual','Detail']], baseline_post.assign(Type="HASH_GATE_POST_RUN"), package_check], ignore_index=True)

    test_context = {
        "repo_root": REPO_ROOT, "stage_root": STAGE_ROOT, "config": config, "baseline_metadata": baseline_metadata,
        "package_manifest": package_pre, "source": source, "signal_state": signal_state, "opportunities": opportunities,
        "position_day": position_day, "feature_registry": feature_reg, "label_registry": label_reg, "ml_registry": ml_reg,
        "point_in_time": pit, "source_summary": source_summary, "candidate_summary": candidate_summary, "d1_summary": d1_summary,
        "split_manifest": split_manifest, "availability_audit": availability_audit, "frozen": frozen,
    }
    unit_tests = _run_self_tests(test_context)
    unit_check = pd.DataFrame([{"Type": "SELF_TESTS", "Check": "all deterministic Stage 3 self-tests", "Status": "PASS" if (unit_tests["Status"] == "PASS").all() else "FAIL", "Expected": len(unit_tests), "Actual": int((unit_tests["Status"] == "PASS").sum()), "Detail": ""}])
    checks = pd.concat([checks, unit_check], ignore_index=True)

    output = STAGE_ROOT / ("tests/sanity_results" if sanity else "results")
    output.mkdir(parents=True, exist_ok=True)
    audit_outputs = {
        "stage3_signal_source_parity_summary.csv": source_summary, "stage3_signal_source_parity_differences.csv": source_diff,
        "stage3_candidate_outcome_parity_summary.csv": candidate_summary, "stage3_candidate_outcome_parity_differences.csv": candidate_diff,
        "stage3_d1_shadow_parity_summary.csv": d1_summary, "stage3_d1_shadow_parity_differences.csv": d1_diff,
        "stage3_point_in_time_audit.csv": pit, "stage3_label_availability_audit.csv": availability_audit,
        "stage3_validation_checks.csv": checks, "stage3_unit_test_results.csv": unit_tests,
    }
    for name, frame in audit_outputs.items():
        _write_csv(frame, output / name)
    _write_validation_report(checks, output / "stage3_validation_report.txt")
    fail_if_any(checks, "Stage 3 acceptance")

    missingness = feature_missingness({"signal_state": signal_state, "d1_position_day": position_day}, feature_reg["Feature Name"])
    distribution = feature_distribution_by_era(signal_state, feature_reg["Feature Name"])
    overall_target = target_summary(opportunities)
    by_year_source = opportunities.assign(**{"Signal Year": pd.to_datetime(opportunities["Signal Date"]).dt.year})
    target_outputs = {
        "stage3_target_summary.csv": overall_target,
        "stage3_target_summary_by_year.csv": target_summary(by_year_source, ["Signal Year"]),
        "stage3_target_summary_by_setup.csv": target_summary(opportunities, ["Setup"]),
        "stage3_target_summary_by_regime.csv": target_summary(opportunities, ["Market Regime"]),
        "stage3_target_summary_by_signal.csv": target_summary(opportunities, ["Original Signal"]),
        "stage3_target_summary_by_ticker.csv": target_summary(opportunities, ["Ticker"]),
    }
    score_source = opportunities.copy()
    score_source["Technical Score Band"] = pd.cut(pd.to_numeric(score_source["Technical Score"]), [-np.inf, 40, 60, 70, 80, np.inf], right=False).astype(str)
    score_source["Actionability Score Band"] = pd.cut(pd.to_numeric(score_source["Actionability Score"]), [-np.inf, 40, 60, 70, 80, np.inf], right=False).astype(str)
    target_outputs["stage3_target_summary_by_technical_score_band.csv"] = target_summary(score_source, ["Technical Score Band"])
    target_outputs["stage3_target_summary_by_actionability_score_band.csv"] = target_summary(score_source, ["Actionability Score Band"])

    dataset_files = {
        "signal_state": (signal_state, output / "stage3_signal_state_dataset.csv.gz"),
        "trade_opportunity": (opportunities, output / "stage3_trade_opportunity_dataset.csv.gz"),
        "d1_position_day": (position_day, output / "stage3_d1_position_day_dataset.csv.gz"),
    }
    for frame, path in dataset_files.values():
        write_deterministic_csv_gz(frame, path)
    dataset_entries = []
    for name, (frame, path) in dataset_files.items():
        dataset_entries.append({
            "dataset_name": name, "artifact": path.name, "row_count": len(frame), "column_count": frame.shape[1],
            "schema": dataframe_schema(frame), "schema_hash": dataframe_schema_hash(frame),
            "content_hash": dataframe_content_hash(frame), "artifact_hash": sha256_file(path), "artifact_size_bytes": path.stat().st_size,
            "source_experiment": config["source_experiment_id"], "schema_version": config["dataset_schema_versions"][name],
        })
    schema_hash = canonical_json_hash([{"dataset": row["dataset_name"], "schema_hash": row["schema_hash"]} for row in dataset_entries])
    dataset_manifest = {"STAGE3_SCHEMA_HASH": schema_hash, "canonical_content": {"column_order": "artifact order", "dates": "YYYY-MM-DD", "floats": "%.12g", "nan": "<NA>", "encoding": "UTF-8", "line_ending": "LF"}, "datasets": dataset_entries, "creation_environment": environment_report()}

    identity = {
        "stage": "3", "experiment_id": experiment_id, "baseline_tag": config["baseline_tag"], "baseline_commit": config["baseline_commit"],
        "source_experiment_id": config["source_experiment_id"], "expected_hashes": config["expected_hashes"],
        "STAGE3_CODE_PACKAGE_HASH": package_pre["package_hash"], "STAGE3_CONFIG_HASH": config_hash,
        "STAGE3_SCHEMA_HASH": schema_hash, "sanity_mode": sanity, "tickers": tickers,
        "ML_MODEL_TRAINED": False, "FEATURE_SELECTION_PERFORMED": False, "HYPERPARAMETER_TUNING_PERFORMED": False,
    }
    _write_csv(feature_reg, output / "stage3_feature_registry.csv")
    _write_csv(label_reg, output / "stage3_label_registry.csv")
    _write_csv(ml_reg, output / "stage3_ml_column_registry.csv")
    _write_csv(split_manifest, output / "stage3_walk_forward_split_manifest.csv")
    _write_csv(ambiguity_summary(opportunities, position_day), output / "stage3_ambiguity_summary.csv")
    _write_csv(censoring_summary(opportunities, position_day, config), output / "stage3_censoring_summary.csv")
    _write_csv(missingness, output / "stage3_feature_missingness.csv")
    _write_csv(distribution, output / "stage3_feature_distribution_by_era.csv")
    _write_csv(dataset_summary(signal_state, opportunities, position_day), output / "stage3_dataset_summary.csv")
    _write_csv(d1_position_day_summary(position_day), output / "stage3_d1_position_day_summary.csv")
    for name, frame in target_outputs.items():
        _write_csv(frame, output / name)
    write_json(identity, output / "stage3_experiment_identity.json")
    write_json(package_pre, output / "stage3_source_manifest.json")
    write_json(dataset_manifest, output / "stage3_dataset_manifest.json")
    write_json(environment_report(), output / "stage3_environment_report.json")

    summary = {
        "signal_rows": len(signal_state), "opportunity_rows": len(opportunities), "filled_rows": int(opportunities["ENTRY_FILLED"].sum()),
        "nonfilled_rows": int((opportunities["ENTRY_FILLED"] == False).sum()), "entry_censored": int(opportunities["ENTRY_CENSORED"].fillna(True).sum()),
        "baseline_primary_rows": int((opportunities["Dataset Cohort"] == "BASELINE_PRIMARY").sum()),
        "research_extended_rows": int((opportunities["Dataset Cohort"] == "RESEARCH_EXTENDED").sum()), "position_day_rows": len(position_day),
        "t1_positive": int((opportunities["T1_BEFORE_STOP_63"] == True).sum()), "t1_negative": int((opportunities["T1_BEFORE_STOP_63"] == False).sum()), "t1_censored": int(opportunities["T1_CENSORED"].sum()),
        "t2_positive": int((opportunities["T2_BEFORE_STOP_63"] == True).sum()), "t2_negative": int((opportunities["T2_BEFORE_STOP_63"] == False).sum()), "t2_censored": int(opportunities["T2_CENSORED"].sum()),
        "fill_rate_pct": float(opportunities["ENTRY_FILLED"].mean() * 100.0), "entry_ambiguity_pct": float(opportunities["ENTRY_DAY_SEQUENCE_AMBIGUOUS"].mean() * 100.0),
        "entry_censor_rate_pct": float(opportunities["ENTRY_CENSORED"].fillna(True).mean() * 100.0), "t1_censor_rate_pct": float(opportunities["T1_CENSORED"].fillna(True).mean() * 100.0), "t2_censor_rate_pct": float(opportunities["T2_CENSORED"].fillna(True).mean() * 100.0),
        "same_bar_ambiguity_pct": float(opportunities["OUTCOME_SEQUENCE_AMBIGUOUS"].mean() * 100.0), "point_in_time_status": "PASS" if not (pit["Status"] == "FAIL").any() else "FAIL",
        "source_parity_status": source_summary.iloc[0]["Status"], "candidate_parity_status": candidate_summary.iloc[0]["Status"], "d1_parity_status": d1_summary.iloc[0]["Status"], "split_rows": len(split_manifest),
        "split_targets": int(split_manifest["Target"].nunique()), "split_years": int(split_manifest["Evaluation Year"].nunique()),
        "high_missingness_records": int(missingness["HIGH_MISSINGNESS"].fillna(False).sum()),
        "high_missingness_examples": " | ".join(missingness.loc[missingness["HIGH_MISSINGNESS"].fillna(False), "Feature"].drop_duplicates().astype(str).head(8)),
    }
    runtime = time.perf_counter() - started
    report = _delivery_report(identity, summary, dataset_manifest, "PASS", runtime)
    (output / "Stage3_Delivery_Report.md").write_text(report, encoding="utf-8", newline="\n")
    if not sanity:
        (STAGE_ROOT / "Stage3_Delivery_Report.md").write_text(report, encoding="utf-8", newline="\n")
    print(report)
    return {"identity": identity, "summary": summary, "dataset_manifest": dataset_manifest, "runtime_seconds": runtime, "output": str(output)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanity", action="store_true", help="Run the two-ticker gated sanity build")
    parser.add_argument("--tickers", nargs="*", default=(), help="Optional exact frozen ticker subset")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(sanity=args.sanity, requested_tickers=args.tickers)
