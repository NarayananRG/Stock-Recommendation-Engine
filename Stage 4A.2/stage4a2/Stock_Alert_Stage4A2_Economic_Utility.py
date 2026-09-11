from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import io
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stage4a2.bootstrap import paired_block_bootstrap, summarize_bootstrap
from stage4a2.candidate_selection import select_named, select_random
from stage4a2.data_contract import load_baseline_primary
from stage4a2.diagnostics import exposure_matched_control, selection_attribution
from stage4a2.economic_metrics import enrich_trades, normalize_daily, period_metrics, portfolio_metrics
from stage4a2.hashing import canonical_json_hash, dataframe_content_hash, package_hash, sha256_file
from stage4a2.policies import registry
from stage4a2.portfolio_adapter import load_frozen_context, run_d0, run_d1
from stage4a2.prediction_contract import load_scores
from stage4a2.random_controls import distribution_summary, named_percentiles
from stage4a2.validation import checks_to_frame, evidence_classification, require_pass


EXPECTED_TAGS = {
    "stage4a1-executable-cohort-robustness-baseline": "012fd37df9158d4c5f7b2165de1d0ec1debbde6f",
    "stage4a-chronological-ml-research-baseline": "9e2ce2f4bcba7a97e08193ae6e84491df02307f5",
    "stage3.1-point-in-time-ml-dataset-baseline": "ac62c35f2a47bc862e406030b81f93da17c75d74",
    "stage2b.1-dynamic-research-baseline": "c9cc9f4fcaf2fe81128365be09515fbf9fa67c28",
}
PREDICTION_HASHES = {
    "stage4a1_primary_only_oos_predictions.csv.gz": "fd0dda139164ec969b74b3498140b9e32694104eaf6c8cf2eeeadf1a75bfeb92",
    "stage4a1_primary_only_joint_oos_predictions.csv.gz": "3bf899fba9f915c8a1f88d3ce342fd67c616e68a4e91d81b30909c1c28e854ac",
    "stage4a1_transfer_baseline_primary_predictions.csv.gz": "76e658d369f9af32884fdc9d9ffc89a69d18a59a0261c73e72ec1609ea029d74",
    "stage4a1_transfer_baseline_primary_joint_predictions.csv.gz": "2b01a10fd4f7db7fb45578225632e5d5e4925598f3b226601238fd5ad9b46c7e",
}
STAGE31_HASH = "3da733b3f1a9fa03c107c960495690290e7fe065901e4f0822c2905ba62d11d5"
STAGE4A1_ID = "S4A1_20160101_20260828_89fadf5b6425"
STAGE4A1_PACKAGE = "8faeb82028289186c5d3bef40d242298b2d4f812c606b20b9b3cd7eb7e2a319d"
STAGE2B1_PACKAGE = "9bba171b9917b9d125d2487e4afa53f6cc047e0a5ccbe3055ebb3e84363d854e"
STAGE2B1_POLICY_HASH = "1830639ace2e2ddcdb24a899b52e44e3305b3ec297b74a6e620a5ee1d1d93e28"
STAGE2B_MAIN_HASH = "5cdf4b4060ea093d0c6655c76e8d262f9a33e36f728655fd7fad35ede7d4e673"
AUDITED_STAGE4A2_COMMIT = "67977db730c8b9ae27fbc9862cd0a9c1d89dcf5d"

_RANDOM_CONTEXT: Any = None
_RANDOM_UNIVERSE: pd.DataFrame | None = None
_RANDOM_MEMBERSHIP: pd.DataFrame | None = None


def _init_random_worker(repo_text: str, dependency_text: str) -> None:
    global _RANDOM_CONTEXT, _RANDOM_UNIVERSE, _RANDOM_MEMBERSHIP
    repo = Path(repo_text)
    _RANDOM_UNIVERSE = load_baseline_primary(repo)
    _RANDOM_MEMBERSHIP = _RANDOM_UNIVERSE[["Signal ID", "Ticker", "Signal Date", "Stop Loss", "Target 1", "Target 2", "T1_BEFORE_STOP_63", "T2_BEFORE_STOP_63"]].copy()
    _RANDOM_MEMBERSHIP["Same-Date Candidate Count"] = _RANDOM_MEMBERSHIP.groupby("Signal Date")["Signal ID"].transform("size")
    _RANDOM_CONTEXT = load_frozen_context(repo, Path(dependency_text))


def _run_random_task(task: tuple[int, int]) -> dict[str, Any]:
    k, seed = task
    assert _RANDOM_CONTEXT is not None and _RANDOM_UNIVERSE is not None and _RANDOM_MEMBERSHIP is not None
    name = f"RANDOM_K{k}_SEED_{seed:03d}"
    ids = select_random(_RANDOM_UNIVERSE, seed, k)
    result = run_d1(_RANDOM_CONTEXT, ids, name)
    ledger = enrich_trades(result, name, "D1_TRAIL_ONLY", _RANDOM_MEMBERSHIP)
    daily = normalize_daily(result, name, "D1_TRAIL_ONLY")
    row = portfolio_metrics(name, daily, ledger, result["orders"], len(_RANDOM_UNIVERSE), len(ids))
    row.update({"Daily K": k, "Seed": seed})
    return row


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", date_format="%Y-%m-%d", float_format="%.12g")


def write_csv_gz(frame: pd.DataFrame, path: Path) -> None:
    payload = frame.to_csv(index=False, lineterminator="\n", date_format="%Y-%m-%d", float_format="%.12g", na_rep="").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(payload)


def write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8", newline="\n")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-c", f"safe.directory={repo.as_posix()}", *args], cwd=repo, text=True).strip()


def source_paths() -> list[str]:
    return [
        "config/stage4a2_config.json", "stage4a2/Stock_Alert_Stage4A2_Economic_Utility.py", "stage4a2/data_contract.py",
        "stage4a2/prediction_contract.py", "stage4a2/policies.py", "stage4a2/candidate_selection.py", "stage4a2/portfolio_adapter.py",
        "stage4a2/economic_metrics.py", "stage4a2/random_controls.py", "stage4a2/bootstrap.py", "stage4a2/diagnostics.py",
        "stage4a2/validation.py", "stage4a2/hashing.py", "tests/run_stage4a2_tests.py",
    ]


def reference_gate(repo: Path) -> pd.DataFrame:
    checks: list[tuple[str, bool, Any, Any]] = []
    for tag, expected in EXPECTED_TAGS.items():
        actual = git(repo, "rev-parse", f"{tag}^{{commit}}")
        checks.append((f"{tag} dereference", actual == expected, expected, actual))
    identity = json.loads((repo / "Stage 4A.1" / "results" / "stage4a1_experiment_identity.json").read_text(encoding="utf-8"))
    checks.append(("Stage 4A.1 experiment ID", identity.get("EXPERIMENT_ID") == STAGE4A1_ID, STAGE4A1_ID, identity.get("EXPERIMENT_ID")))
    checks.append(("Stage 4A.1 package hash", identity.get("STAGE4A1_CODE_PACKAGE_HASH") == STAGE4A1_PACKAGE, STAGE4A1_PACKAGE, identity.get("STAGE4A1_CODE_PACKAGE_HASH")))
    s2 = json.loads((repo / "Stage 2B.1" / "results" / "stage2b_1_experiment_identity.json").read_text(encoding="utf-8"))
    for name, expected, actual in (("Stage 2B.1 package hash", STAGE2B1_PACKAGE, s2.get("STAGE2B1_PACKAGE_HASH")),
                                   ("Stage 2B.1 policy config hash", STAGE2B1_POLICY_HASH, s2.get("POLICY_CONFIG_HASH")),
                                   ("Stage 2B accepted main hash", STAGE2B_MAIN_HASH, s2.get("ACCEPTED_STAGE2B_MAIN_HASH"))):
        checks.append((name, actual == expected, expected, actual))
    for file_name, expected in PREDICTION_HASHES.items():
        frame = pd.read_csv(repo / "Stage 4A.1" / "results" / file_name, low_memory=False)
        actual = dataframe_content_hash(frame)
        checks.append((f"prediction logical hash: {file_name}", actual == expected, expected, actual))
    s31 = pd.read_csv(repo / "Stage 3.1" / "results" / "stage3_1_trade_opportunity_dataset.csv.gz", low_memory=False)
    actual = dataframe_content_hash(s31)
    checks.append(("Stage 3.1 opportunity logical hash", actual == STAGE31_HASH, STAGE31_HASH, actual))
    merge_base = git(repo, "merge-base", "HEAD", EXPECTED_TAGS["stage4a1-executable-cohort-robustness-baseline"])
    checks.append(("branch merge-base is frozen Stage 4A.1", merge_base == EXPECTED_TAGS["stage4a1-executable-cohort-robustness-baseline"], EXPECTED_TAGS["stage4a1-executable-cohort-robustness-baseline"], merge_base))
    frame = checks_to_frame(checks); require_pass(frame); return frame


def _old_frame(repo: Path, relative: str) -> pd.DataFrame:
    payload = subprocess.check_output(["git", "-c", f"safe.directory={repo.as_posix()}", "show", f"{AUDITED_STAGE4A2_COMMIT}:{relative}"], cwd=repo)
    return pd.read_csv(io.BytesIO(payload), compression="gzip" if relative.endswith(".gz") else None, low_memory=False)


def core_result_parity(repo: Path, out: Path) -> pd.DataFrame:
    specs: list[tuple[str, list[str] | None, list[str]]] = [
        ("stage4a2_candidate_membership_audit.csv.gz", None, ["Signal Date", "Signal ID"]),
        ("stage4a2_trade_ledger_d1.csv.gz", ["Policy", "Exit Engine", "Signal ID", "Ticker", "Signal Date", "Entry Date", "Exit Date", "Executed Entry", "Initial Stop", "Original T1", "Original T2", "Quantity", "Position Value", "Exit Reason", "Executed Exit", "Gross PnL", "Costs", "Net PnL", "Net R", "Holding Sessions", "Selection Rank", "Selection Score", "Daily K", "Same-Date Candidate Count"], ["Policy", "Signal ID"]),
        ("stage4a2_trade_ledger_d0.csv.gz", ["Policy", "Exit Engine", "Signal ID", "Ticker", "Signal Date", "Entry Date", "Exit Date", "Executed Entry", "Initial Stop", "Original T1", "Original T2", "Quantity", "Position Value", "Exit Reason", "Executed Exit", "Gross PnL", "Costs", "Net PnL", "Net R", "Holding Sessions", "Selection Rank", "Selection Score", "Daily K", "Same-Date Candidate Count"], ["Policy", "Signal ID"]),
        ("stage4a2_daily_portfolio_d1.csv.gz", ["Policy", "Exit Engine", "Date", "Equity", "Daily Return %", "Cash", "Invested Value", "Exposure", "Open Positions", "Costs"], ["Policy", "Date"]),
        ("stage4a2_daily_portfolio_d0.csv.gz", ["Policy", "Exit Engine", "Date", "Equity", "Daily Return %", "Cash", "Invested Value", "Exposure", "Open Positions", "Costs"], ["Policy", "Date"]),
        ("stage4a2_portfolio_summary_d1.csv", ["Policy", "Starting Equity", "Ending Equity", "Total Return %", "CAGR %", "Annualized Volatility %", "Sharpe Ratio RF=0", "Sharpe Ratio RF=6%", "Sortino RF=0", "Sortino RF=6%", "Calmar Ratio", "Maximum Drawdown %", "Trade Count", "Winning Trades", "Losing Trades", "Win Rate %", "Mean Net R", "Median Net R", "Expectancy R", "Profit Factor", "Average Holding Sessions", "Median Holding Sessions", "Average Exposure %", "Maximum Exposure %", "Average Open Positions", "Maximum Open Positions", "Days Fully Cash", "Candidate Count", "Selected Candidate Count", "Entry Filled Count", "Fill Rate %", "Invalid Risk Count", "Expired Entry Count", "Capital Rejection Count", "Total Costs"], ["Policy"]),
        ("stage4a2_portfolio_summary_d0.csv", ["Policy", "Starting Equity", "Ending Equity", "Total Return %", "CAGR %", "Annualized Volatility %", "Sharpe Ratio RF=0", "Sharpe Ratio RF=6%", "Sortino RF=0", "Sortino RF=6%", "Calmar Ratio", "Maximum Drawdown %", "Trade Count", "Winning Trades", "Losing Trades", "Win Rate %", "Mean Net R", "Median Net R", "Expectancy R", "Profit Factor", "Average Holding Sessions", "Median Holding Sessions", "Average Exposure %", "Maximum Exposure %", "Average Open Positions", "Maximum Open Positions", "Days Fully Cash", "Candidate Count", "Selected Candidate Count", "Entry Filled Count", "Fill Rate %", "Invalid Risk Count", "Expired Entry Count", "Capital Rejection Count", "Total Costs"], ["Policy"]),
        ("stage4a2_random_control_raw.csv.gz", ["Policy", "Daily K", "Seed", "Starting Equity", "Ending Equity", "Total Return %", "CAGR %", "Annualized Volatility %", "Maximum Drawdown %", "Trade Count", "Win Rate %", "Mean Net R", "Median Net R", "Expectancy R", "Profit Factor", "Average Exposure %", "Maximum Exposure %", "Average Open Positions", "Maximum Open Positions", "Days Fully Cash", "Candidate Count", "Selected Candidate Count", "Entry Filled Count", "Fill Rate %", "Invalid Risk Count", "Expired Entry Count", "Capital Rejection Count", "Total Costs"], ["Daily K", "Seed"]),
        ("stage4a2_random_control_summary.csv", None, ["Daily K", "Metric"]),
        ("stage4a2_block_bootstrap_63.csv.gz", None, ["Policy", "Replicate"]),
        ("stage4a2_block_bootstrap_21_sensitivity.csv.gz", None, ["Policy", "Replicate"]),
        ("stage4a2_block_bootstrap_126_sensitivity.csv.gz", None, ["Policy", "Replicate"]),
        ("stage4a2_bootstrap_summary.csv", None, ["Policy", "Block Length", "Metric"]),
        ("stage4a2_paired_economic_comparison.csv", None, ["Policy"]),
    ]
    rows = []
    for file_name, columns, keys in specs:
        current = pd.read_csv(out / file_name, low_memory=False).sort_values(keys, kind="mergesort").reset_index(drop=True)
        previous = _old_frame(repo, f"Stage 4A.2/results/{file_name}").sort_values(keys, kind="mergesort").reset_index(drop=True)
        selected = columns if columns is not None else list(current.columns)
        missing = [column for column in selected if column not in current or column not in previous]
        logical_current=current[selected].copy() if not missing else current.iloc[:,0:0]
        logical_previous=previous[selected].copy() if not missing else previous.iloc[:,0:0]
        numeric_columns=[column for column in selected if not missing and pd.api.types.is_numeric_dtype(logical_current[column]) and pd.api.types.is_numeric_dtype(logical_previous[column])]
        integer_columns=[column for column in numeric_columns if pd.api.types.is_integer_dtype(logical_current[column]) and pd.api.types.is_integer_dtype(logical_previous[column])]
        float_columns=[column for column in numeric_columns if column not in integer_columns]
        nonnumeric_columns=[column for column in selected if column not in numeric_columns]
        logical_differences=0
        if not missing and len(current)==len(previous):
            logical_differences += sum(int((current[column].to_numpy()!=previous[column].to_numpy()).sum()) for column in integer_columns)
            logical_differences += sum(int((current[column].fillna("<NA>").astype(str).to_numpy()!=previous[column].fillna("<NA>").astype(str).to_numpy()).sum()) for column in nonnumeric_columns)
            logical_differences += sum(int((~np.isclose(pd.to_numeric(current[column],errors="coerce").to_numpy(float),pd.to_numeric(previous[column],errors="coerce").to_numpy(float),rtol=0,atol=1e-6,equal_nan=True)).sum()) for column in float_columns)
        else:
            logical_differences=1
        for column in numeric_columns:
            logical_current[column]=pd.to_numeric(logical_current[column],errors="coerce").round(6)
            logical_previous[column]=pd.to_numeric(logical_previous[column],errors="coerce").round(6)
        actual_hash = "MISSING_COLUMNS" if missing else dataframe_content_hash(logical_current)
        expected_hash = "MISSING_COLUMNS" if missing else dataframe_content_hash(logical_previous)
        maximum_difference=max((float(np.nanmax(np.abs(pd.to_numeric(current[column],errors="coerce").to_numpy(float)-pd.to_numeric(previous[column],errors="coerce").to_numpy(float)))) for column in numeric_columns if len(current)),default=0.0)
        rows.append({"Artifact": file_name, "Audited Commit": AUDITED_STAGE4A2_COMMIT, "Compared Columns": "|".join(selected),
                     "Comparison Contract":"stable key order; exact nonnumeric/integer identity; float serialization normalized to 6 decimals (absolute delta also reported)",
                     "Expected Logical Hash": expected_hash, "Actual Logical Hash": actual_hash,
                     "Logical Difference Count":logical_differences,
                     "Maximum Absolute Numeric Difference":maximum_difference,
                     "Status": "PASS" if not missing and logical_differences == 0 and maximum_difference <= 1e-6 else "FAIL", "Missing Columns": "|".join(missing)})
    return pd.DataFrame(rows)


def run_named(context: Any, universe: pd.DataFrame, selections: dict[str, set[str]], membership: pd.DataFrame, run_static: bool = True) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d1_ledgers: dict[str, pd.DataFrame] = {}; d1_daily: dict[str, pd.DataFrame] = {}; d1_rows = []
    d0_ledgers: dict[str, pd.DataFrame] = {}; d0_daily: dict[str, pd.DataFrame] = {}; d0_rows = []
    for policy, ids in selections.items():
        print(f"D1 {policy}", flush=True)
        result = run_d1(context, ids, policy)
        ledger = enrich_trades(result, policy, "D1_TRAIL_ONLY", membership)
        daily = normalize_daily(result, policy, "D1_TRAIL_ONLY")
        d1_ledgers[policy] = ledger; d1_daily[policy] = daily
        d1_rows.append(portfolio_metrics(policy, daily, ledger, result["orders"], len(universe), len(ids)))
        if run_static:
            print(f"D0 {policy}", flush=True)
            result0 = run_d0(context, ids, policy)
            ledger0 = enrich_trades(result0, policy, "D0_STATIC_COMPAT", membership)
            daily0 = normalize_daily(result0, policy, "D0_STATIC_COMPAT")
            d0_ledgers[policy] = ledger0; d0_daily[policy] = daily0
            d0_rows.append(portfolio_metrics(policy, daily0, ledger0, result0["orders"], len(universe), len(ids)))
    return d1_ledgers, d1_daily, pd.DataFrame(d1_rows), pd.DataFrame(d0_rows), pd.concat(d0_ledgers.values(), ignore_index=True) if d0_ledgers else pd.DataFrame(), pd.concat(d0_daily.values(), ignore_index=True) if d0_daily else pd.DataFrame()


def comparisons(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in summary[summary["Policy"].str.match(r"R[1-5]_K[12]")].iterrows():
        base = summary[summary["Policy"] == f"R0_K{row['Policy'][-1]}"].iloc[0]
        rows.append({"Policy": row["Policy"], "Comparator": base["Policy"], "Trade Count": row["Trade Count"],
                     **{f"Delta {column}": row[column] - base[column] for column in ("Total Return %", "CAGR %", "Maximum Drawdown %", "Expectancy R", "Profit Factor", "Average Exposure %", "Fill Rate %")}})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sanity", action="store_true")
    args = parser.parse_args()
    repo = args.repo_root.resolve(); stage = repo / "Stage 4A.2"; out = args.output_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    ref = reference_gate(repo); write_csv(ref, out / "stage4a2_reference_gate.csv")
    universe = load_baseline_primary(repo)
    scores, lineage = load_scores(repo, universe)
    selections, membership = select_named(universe, scores)
    internal_membership = membership.merge(universe[["Signal ID", "T1_BEFORE_STOP_63", "T2_BEFORE_STOP_63"]], on="Signal ID", how="left", validate="one_to_one")
    write_csv(lineage, out / "stage4a2_prediction_lineage_audit.csv")
    prediction_rows=[]
    for name, expected in PREDICTION_HASHES.items():
        gate=ref[ref["Check"]==f"prediction logical hash: {name}"].iloc[0]
        prediction_rows.append({"Input":name,"Expected Logical Hash":expected,"Actual Logical Hash":gate["Actual"],"Status":"PASS" if gate["Actual"]==expected else "FAIL"})
    prediction_audit=pd.DataFrame(prediction_rows);require_pass(prediction_audit.rename(columns={"Expected Logical Hash":"Expected","Actual Logical Hash":"Actual"}));write_csv(prediction_audit,out/"stage4a2_prediction_input_audit.csv")
    write_csv_gz(membership, out / "stage4a2_candidate_membership_audit.csv.gz")
    reg = pd.DataFrame(registry()); write_csv(reg, out / "stage4a2_policy_registry.csv")
    context = load_frozen_context(repo, args.dependency_root.resolve())
    if args.sanity:
        allowed = set(universe[universe["Ticker"].isin(sorted(universe["Ticker"].unique())[:2])]["Signal ID"].astype(str))
        selections = {name: ids & allowed for name, ids in selections.items() if name in ("ALL_BASELINE_PRIMARY", "R0_K1", "R1_K1")}
    d1_ledgers, d1_daily, d1_summary, d0_summary, d0_ledger_all, d0_daily_all = run_named(context, universe, selections, internal_membership, run_static=True)
    d1_ledger_all = pd.concat(d1_ledgers.values(), ignore_index=True); d1_daily_all = pd.concat(d1_daily.values(), ignore_index=True)
    write_csv(d1_summary, out / "stage4a2_portfolio_summary_d1.csv"); write_csv(d0_summary, out / "stage4a2_portfolio_summary_d0.csv")
    write_csv_gz(d1_ledger_all, out / "stage4a2_trade_ledger_d1.csv.gz"); write_csv_gz(d0_ledger_all, out / "stage4a2_trade_ledger_d0.csv.gz")
    write_csv_gz(d1_daily_all, out / "stage4a2_daily_portfolio_d1.csv.gz"); write_csv_gz(d0_daily_all, out / "stage4a2_daily_portfolio_d0.csv.gz")
    baseline_d1 = d1_summary[d1_summary["Policy"] == "ALL_BASELINE_PRIMARY"].iloc[0]
    baseline_d0 = d0_summary[d0_summary["Policy"] == "ALL_BASELINE_PRIMARY"].iloc[0]
    parity1 = checks_to_frame([("D1 ending equity", abs(baseline_d1["Ending Equity"] - 120093.40818664426) < 1e-8, 120093.40818664426, baseline_d1["Ending Equity"]), ("D1 trade count", baseline_d1["Trade Count"] == 285, 285, baseline_d1["Trade Count"])])
    parity0 = checks_to_frame([("D0 ending equity", abs(baseline_d0["Ending Equity"] - 106745.30976890605) < 1e-8, 106745.30976890605, baseline_d0["Ending Equity"]), ("D0 trade count", baseline_d0["Trade Count"] == 225, 225, baseline_d0["Trade Count"])])
    if not args.sanity: require_pass(parity1); require_pass(parity0)
    write_csv(parity1, out / "stage4a2_baseline_portfolio_parity.csv"); write_csv(parity0, out / "stage4a2_static_portfolio_parity.csv")
    yearly_rows=[]; recent_rows=[]
    for policy, daily in d1_daily.items():
        ledger=d1_ledgers[policy]
        for year in range(2016,2027):
            metrics=period_metrics(daily,ledger,pd.Timestamp(f"{year}-01-01"),pd.Timestamp("2026-08-28" if year==2026 else f"{year}-12-31")); metrics.update({"Policy":policy,"Year":f"{year} partial" if year==2026 else str(year)});yearly_rows.append(metrics)
        recent=period_metrics(daily,ledger,pd.Timestamp("2024-01-01"),pd.Timestamp("2026-08-28"));recent.update({"Policy":policy});recent_rows.append(recent)
    yearly=pd.DataFrame(yearly_rows); recent=pd.DataFrame(recent_rows)
    if not args.sanity:
        for idx,row in yearly.iterrows():
            if row["Policy"].startswith(("R1_","R2_","R3_","R4_")):
                comparator=f"R0_K{row['Policy'][-1]}"; base=yearly[(yearly.Policy==comparator)&(yearly.Year==row.Year)].iloc[0];yearly.loc[idx,"Return >= R0"]=row["Return %"]>=base["Return %"]
        for idx,row in recent.iterrows():
            if row["Policy"].startswith("R") and row["Policy"] not in ("R0_K1","R0_K2"):
                base=recent[recent.Policy==f"R0_K{row['Policy'][-1]}"].iloc[0];recent.loc[idx,"Delta Return vs R0 %"]=row["Return %"]-base["Return %"]
    write_csv(yearly,out/"stage4a2_yearly_metrics_d1.csv");write_csv(recent,out/"stage4a2_recent_2024_2026_metrics.csv")
    paired=comparisons(d1_summary);write_csv(paired,out/"stage4a2_paired_economic_comparison.csv")
    d1d0=d1_summary.merge(d0_summary,on="Policy",suffixes=(" D1"," D0"));
    for col in ("Total Return %","CAGR %","Maximum Drawdown %","Expectancy R","Profit Factor"): d1d0[f"D1 minus D0 {col}"]=d1d0[f"{col} D1"]-d1d0[f"{col} D0"]
    write_csv(d1d0,out/"stage4a2_d1_vs_d0_sensitivity.csv")
    if args.sanity:
        validations=checks_to_frame([("reference gates",(ref.Status=="PASS").all(),"all PASS",ref.Status.value_counts().to_dict()),("prediction lineage",(lineage.Status=="PASS").all(),"all PASS",lineage.Status.value_counts().to_dict()),("sanity policies executed",len(d1_summary)==3,3,len(d1_summary))]);write_csv(validations,out/"stage4a2_validation_checks.csv");(out/"stage4a2_validation_report.txt").write_text("STAGE 4A.2 SANITY: PASS\n",encoding="utf-8");print("SANITY PASS",flush=True);return
    attribution=selection_attribution(selections,d1_ledgers); attribution["Same-Date Candidate Dates"]=universe["Signal Date"].nunique();write_csv(attribution,out/"stage4a2_selection_attribution.csv")
    fill=paired[paired.Policy.str.startswith("R5_")].copy();write_csv(fill,out/"stage4a2_fill_efficiency.csv")
    exposure=pd.concat([exposure_matched_control(d1_daily[p],d1_daily[f"R0_K{p[-1]}"],p) for p in [f"R{x}_K{k}" for x in range(1,6) for k in (1,2)]],ignore_index=True);write_csv(exposure,out/"stage4a2_exposure_matched_rule_control.csv")
    exposure_rows=[]
    for policy,group in exposure.sort_values("Date").groupby("Policy",sort=True):
        actual=float(d1_summary.loc[d1_summary["Policy"]==policy,"Total Return %"].iloc[0]);matched=(float(group["Exposure-Matched Equity"].iloc[-1])/100000.0-1)*100
        exposure_rows.append({"Policy":policy,"Comparator":f"R0_K{policy[-1]}","ML Actual Total Return %":actual,
                              "Prior-Session Exposure-Matched Rule Return %":matched,"Difference %":actual-matched,
                              "Exposure Lag":"t-1","Scale Cap":1.0,"Same-Day Exposure Lookahead":"NO"})
    write_csv(pd.DataFrame(exposure_rows),out/"stage4a2_exposure_matched_summary.csv")
    tasks=[(k,seed) for k in (1,2) for seed in range(500)]
    worker_count=min(4,os.cpu_count() or 1)
    print(f"random controls: {len(tasks)} tasks across {worker_count} frozen-engine workers",flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count,initializer=_init_random_worker,initargs=(str(repo),str(args.dependency_root.resolve()))) as pool:
        random_rows=[]
        for completed,row in enumerate(pool.map(_run_random_task,tasks,chunksize=2),start=1):
            random_rows.append(row)
            if completed%50==0: print(f"random controls: {completed}/1000",flush=True)
    random_raw=pd.DataFrame(random_rows);random_summary=distribution_summary(random_raw);percentiles=named_percentiles(d1_summary,random_raw)
    write_csv_gz(random_raw,out/"stage4a2_random_control_raw.csv.gz");write_csv(random_summary,out/"stage4a2_random_control_summary.csv");write_csv(percentiles,out/"stage4a2_named_policy_random_percentiles.csv")
    bootstrap_parts=[]
    for block in (63,21,126):
        pieces=[]
        for policy in [f"R{x}_K{k}" for x in range(1,6) for k in (1,2)]:
            p=d1_daily[policy]["Daily Return %"].to_numpy(float)/100;r=d1_daily[f"R0_K{policy[-1]}"]["Daily Return %"].to_numpy(float)/100
            pieces.append(paired_block_bootstrap(policy,p,r,block,policy_exposure=d1_daily[policy]["Exposure"].to_numpy(float),rule_exposure=d1_daily[f"R0_K{policy[-1]}"]["Exposure"].to_numpy(float)))
        frame=pd.concat(pieces,ignore_index=True);bootstrap_parts.append(frame)
        file={63:"stage4a2_block_bootstrap_63.csv.gz",21:"stage4a2_block_bootstrap_21_sensitivity.csv.gz",126:"stage4a2_block_bootstrap_126_sensitivity.csv.gz"}[block];write_csv_gz(frame,out/file)
    bootall=pd.concat(bootstrap_parts,ignore_index=True);bootsum=summarize_bootstrap(bootall);write_csv(bootsum,out/"stage4a2_bootstrap_summary.csv")
    evidence=evidence_classification(paired,bootsum,percentiles,recent,yearly);write_csv(evidence,out/"stage4a2_economic_evidence_classification.csv")
    old_evidence=_old_frame(repo,"Stage 4A.2/results/stage4a2_economic_evidence_classification.csv")[["Policy","Economic Evidence Classification"]].rename(columns={"Economic Evidence Classification":"Old Classification"})
    classification_audit=old_evidence.merge(evidence[["Policy","Economic Evidence Classification"]].rename(columns={"Economic Evidence Classification":"Corrected Classification"}),on="Policy",validate="one_to_one");classification_audit["Changed"]=classification_audit["Old Classification"]!=classification_audit["Corrected Classification"];write_csv(classification_audit,out/"stage4a2_evidence_classification_correction_audit.csv")
    core_parity=core_result_parity(repo,out);write_csv(core_parity,out/"stage4a2_core_result_parity.csv");require_pass(core_parity.rename(columns={"Artifact":"Check","Expected Logical Hash":"Expected","Actual Logical Hash":"Actual"}))
    expected_labels={**{f"R{x}_K1":"WEAK POSITIVE ECONOMIC UTILITY" for x in range(1,5)},**{f"R{x}_K2":"NO ECONOMIC UTILITY" for x in range(1,5)}}
    actual_labels=evidence.set_index("Policy")["Economic Evidence Classification"].to_dict()
    realized_ok=True
    for policy,group in d1_daily_all.groupby("Policy"):
        expected=d1_ledger_all[d1_ledger_all["Policy"]==policy].assign(Date=lambda f:pd.to_datetime(f["Exit Date"]).dt.normalize()).groupby("Date")["Net PnL"].sum()
        actual=group.assign(Date=lambda f:pd.to_datetime(f["Date"]).dt.normalize()).set_index("Date")["Realized PnL"]
        realized_ok &= bool(np.allclose(actual,expected.reindex(actual.index,fill_value=0.0),rtol=0,atol=1e-9))
    validations=checks_to_frame([("all reference gates pass",(ref.Status=="PASS").all(),True,(ref.Status=="PASS").all()),("all prediction lineage gates pass",(lineage.Status=="PASS").all(),True,(lineage.Status=="PASS").all()),("prediction input actual hashes",(prediction_audit.Status=="PASS").all(),True,(prediction_audit.Status=="PASS").all()),("D1 parity exact",(parity1.Status=="PASS").all(),True,(parity1.Status=="PASS").all()),("D0 parity exact",(parity0.Status=="PASS").all(),True,(parity0.Status=="PASS").all()),("core results unchanged from audited commit",(core_parity.Status=="PASS").all(),True,(core_parity.Status=="PASS").all()),("corrected classification contract",all(actual_labels.get(k)==v for k,v in expected_labels.items()),expected_labels,actual_labels),("no robust policy",not evidence["Economic Evidence Classification"].eq("ROBUST POSITIVE ECONOMIC UTILITY").any(),True,evidence["Economic Evidence Classification"].eq("ROBUST POSITIVE ECONOMIC UTILITY").sum()),("realized PnL exit-event reconciliation",realized_ok,True,realized_ok),("candidate count",len(universe)==754,754,len(universe)),("named policies",len(d1_summary)==13,13,len(d1_summary)),("random controls",len(random_raw)==1000,1000,len(random_raw)),("bootstrap replicates",len(bootall)==60000,60000,len(bootall)),("exposure bounded",d1_daily_all.Exposure.between(0,1+1e-12).all(),True,d1_daily_all.Exposure.between(0,1+1e-12).all())]);require_pass(validations);write_csv(validations,out/"stage4a2_validation_checks.csv");(out/"stage4a2_validation_report.txt").write_text("STAGE 4A.2 FINAL AUDIT HARDENING: PASS WITH WARNINGS\nAll behavior and hardening gates passed. Core economic results are unchanged. Scientific limitations remain.\n",encoding="utf-8",newline="\n")
    pkg=package_hash(stage,source_paths());config_hash=sha256_file(stage/"config/stage4a2_config.json");registry_hash=dataframe_content_hash(reg)
    seed={"stage4a1_commit":EXPECTED_TAGS["stage4a1-executable-cohort-robustness-baseline"],"stage4a1_experiment":STAGE4A1_ID,"stage4a1_package":STAGE4A1_PACKAGE,"prediction_hashes":PREDICTION_HASHES,"stage31_hash":STAGE31_HASH,"stage2b1_commit":EXPECTED_TAGS["stage2b.1-dynamic-research-baseline"],"stage2b1_package":STAGE2B1_PACKAGE,"stage2b1_policy_hash":STAGE2B1_POLICY_HASH,"code_package_hash":pkg,"config_hash":config_hash,"policy_registry_hash":registry_hash,"random":{"seeds":list(range(500)),"k":[1,2]},"bootstrap":{"seed":42,"replicates":2000,"blocks":[63,21,126]},"dates":["2016-01-01","2026-08-28"]}
    experiment="S4A2_20160101_20260828_"+canonical_json_hash(seed)[:12]
    identity={"stage":"4A.2","EXPERIMENT_ID":experiment,"STAGE4A2_PACKAGE_HASH":pkg,"CONFIG_HASH":config_hash,"POLICY_REGISTRY_HASH":registry_hash,**seed};write_json(identity,out/"stage4a2_experiment_identity.json")
    source_manifest={"package_hash":pkg,"sources":[{"relative_path":p,"sha256":sha256_file(stage/p),"bytes":(stage/p).stat().st_size} for p in source_paths()]};write_json(source_manifest,out/"stage4a2_source_manifest.json")
    environment={"python":sys.version,"platform":platform.platform(),"numpy":np.__version__,"pandas":pd.__version__,"absolute_paths_excluded_from_identity":True};write_json(environment,out/"stage4a2_environment_report.json")
    manifest_files=sorted(p for p in out.iterdir() if p.is_file() and p.name not in ("stage4a2_output_manifest.json","stage4a2_determinism_check.csv"));write_json({"outputs":[{"file":p.name,"sha256":sha256_file(p),"bytes":p.stat().st_size} for p in manifest_files]},out/"stage4a2_output_manifest.json")
    print(json.dumps({"experiment_id":experiment,"package_hash":pkg,"outputs":len(manifest_files)}),flush=True)


if __name__ == "__main__":
    main()
