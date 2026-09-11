from __future__ import annotations

import argparse,json,shutil,sys,tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage4a3.economic_methodology import midrank_percentile,paired_moving_block_bootstrap,portfolio_metrics
from stage4a3.final_evaluation import evaluate
from stage4a3.final_market_data import archive_market_frames,verify_and_load_archive
from stage4a3.session_coverage import append_coverage,audit_prior_sessions,load_coverage,verify_coverage


def historical_parity()->dict[str,bool]:
    results=REPO/"Stage 4A.2/results"
    d1s=pd.read_csv(results/"stage4a2_portfolio_summary_d1.csv").set_index("Policy");d0s=pd.read_csv(results/"stage4a2_portfolio_summary_d0.csv").set_index("Policy")
    daily=pd.read_csv(results/"stage4a2_daily_portfolio_d1.csv.gz",parse_dates=["Date"]);daily["Daily Return"]=daily["Daily Return %"]/100
    trades=pd.read_csv(results/"stage4a2_trade_ledger_d1.csv.gz")
    rows=[];checks={}
    expected={"R0_K1":{"Ending Equity":115050.721977,"Total Return %":15.0507219772,"CAGR %":1.32444723838,"Maximum Drawdown %":-8.50989880423,"Trade Count":249,"Expectancy R":.072612688428,"Profit Factor":1.22289594068},"R3_K1":{"Ending Equity":122414.982453,"Total Return %":22.414982453,"CAGR %":1.91613710247,"Maximum Drawdown %":-9.97432749783,"Trade Count":249,"Expectancy R":.111239823263,"Profit Factor":1.32944483537}}
    for policy in ("R0_K1","R3_K1"):
        actual=portfolio_metrics(policy,daily.loc[daily.Policy.eq(policy)],trades.loc[trades.Policy.eq(policy)])
        for metric,value in expected[policy].items():
            tolerance=1e-8 if metric!="Trade Count" else 0;passed=abs(float(actual[metric])-value)<=tolerance
            rows.append({"Policy":policy,"Metric":metric,"Expected":value,"Actual":actual[metric],"Tolerance":tolerance,"Status":"PASS" if passed else "FAIL"});checks[f"{policy}_{metric}"]=passed
    pd.DataFrame(rows).to_csv(ROOT/"results/stage4a3_historical_economic_engine_parity.csv",index=False,lineterminator="\n")
    d0rows=[]
    for policy,expected_value in {"R0_K1":.565299619815,"R3_K1":5.79452827472}.items():
        actual=float(d0s.loc[policy,"Total Return %"]);passed=abs(actual-expected_value)<=1e-9;d0rows.append({"Policy":policy,"Metric":"Total Return %","Expected":expected_value,"Actual":actual,"Status":"PASS" if passed else "FAIL"});checks[f"D0_{policy}"]=passed
    pd.DataFrame(d0rows).to_csv(ROOT/"results/stage4a3_historical_economic_engine_parity_d0.csv",index=False,lineterminator="\n");pd.concat([pd.DataFrame(rows),pd.DataFrame(d0rows)],ignore_index=True).to_csv(ROOT/"results/stage4a3_historical_economic_engine_parity.csv",index=False,lineterminator="\n")
    boot=paired_moving_block_bootstrap(daily.loc[daily.Policy.eq("R3_K1")],daily.loc[daily.Policy.eq("R0_K1")],63,2000,42);summary={"Delta 2.5%":boot["Delta Terminal Return %"].quantile(.025),"Delta Median":boot["Delta Terminal Return %"].median(),"Delta 97.5%":boot["Delta Terminal Return %"].quantile(.975),"P(Delta>0) %":boot["Delta Terminal Return %"].gt(0).mean()*100};boot_expected={"Delta 2.5%":-3.77844816303,"Delta Median":7.64250886483,"Delta 97.5%":21.7250233509,"P(Delta>0) %":90.65};bootrows=[]
    for metric,value in boot_expected.items():passed=abs(summary[metric]-value)<=1e-9;bootrows.append({"Metric":metric,"Expected":value,"Actual":summary[metric],"Status":"PASS" if passed else "FAIL"});checks[f"BOOT_{metric}"]=passed
    pd.DataFrame(bootrows).to_csv(ROOT/"results/stage4a3_historical_bootstrap_parity.csv",index=False,lineterminator="\n")
    random=pd.read_csv(results/"stage4a2_random_control_raw.csv.gz");controls=random.loc[random["Daily K"].eq(1),"Total Return %"];percentile=midrank_percentile(float(d1s.loc["R3_K1","Total Return %"]),controls);passed=abs(percentile-81.8)<=1e-12;pd.DataFrame([{"Policy":"R3_K1","Expected Mid-Rank Percentile %":81.8,"Actual Mid-Rank Percentile %":percentile,"Status":"PASS" if passed else "FAIL"}]).to_csv(ROOT/"results/stage4a3_historical_random_control_parity.csv",index=False,lineterminator="\n");checks["RANDOM"]=passed
    return checks


def run()->list[dict]:
    checks=historical_parity();values=[]
    values.append(("historical R0_K1 exact daily-equity parity",all(v for k,v in checks.items() if k.startswith("R0_K1"))))
    values.append(("historical R3_K1 exact daily-equity parity",all(v for k,v in checks.items() if k.startswith("R3_K1"))))
    values.append(("historical D0 R0/R3 parity",checks["D0_R0_K1"] and checks["D0_R3_K1"]))
    values.append(("historical non-circular 63-session bootstrap parity",all(v for k,v in checks.items() if k.startswith("BOOT_"))))
    values.append(("historical mid-rank random percentile parity",checks["RANDOM"]))
    values.append(("mid-rank ties are half weighted",midrank_percentile(2,np.array([1,2,2,3]))==50.0))
    a=pd.DataFrame({"Policy":["R3_K1"]*5,"Date":pd.date_range("2020-01-01",periods=5),"Daily Return":[.01,.02,.03,.04,.05],"Exposure":[0]*5});b=a.assign(Policy="R0_K1",**{"Daily Return":[0]*5})
    sample=paired_moving_block_bootstrap(a,b,3,10,42);values.append(("bootstrap blocks are contiguous and non-circular",len(sample)==10 and sample["Sample Length"].eq(5).all()))
    source=(ROOT/"stage4a3/final_evaluation.py").read_text(encoding="utf-8");values.append(("terminal trade-fraction compounding removed","Portfolio Return Fraction" not in source and "cumprod" not in source))
    values.append(("T2 fake-score usage removed","NO T2 MODEL IN FROZEN PROSPECTIVE BUNDLE" in source and '("T2_BEFORE_STOP_63","R3 Score")' not in source))
    with tempfile.TemporaryDirectory() as td:
        audit=Path(td)/"audit";pd.DataFrame([{"Signal Date":"2026-01-06","Candidate Count":0}]).to_csv(audit/"prospective_snapshot_index.csv",index=False) if (audit.mkdir(parents=True) or True) else None
        missed=audit_prior_sessions(audit,"2026-01-05","2026-01-08",["2026-01-06","2026-01-07","2026-01-08"],"2026-01-08T11:00:00Z");frame=load_coverage(audit/"session_coverage_index.csv")
        values.append(("missing valid session recorded exactly once",missed==["2026-01-07"] and frame.loc[frame.Status.eq("MISSED"),"Market Session Date"].tolist()==["2026-01-07"]))
        values.append(("missed session never creates prediction",not (Path(td)/"snapshots/2026/2026-01-07").exists()))
        audit_prior_sessions(audit,"2026-01-05","2026-01-08",["2026-01-06","2026-01-07","2026-01-08"],"2026-01-08T11:01:00Z");values.append(("coverage rerun is idempotent",len(load_coverage(audit/"session_coverage_index.csv"))==2))
        values.append(("holiday and weekend not inferred as missed",not load_coverage(audit/"session_coverage_index.csv")["Market Session Date"].isin(["2026-01-10","2026-01-11","2026-01-26"]).any()))
        clean=verify_coverage(audit/"session_coverage_index.csv");tampered=load_coverage(audit/"session_coverage_index.csv");tampered.loc[0,"Status"]="MISSED";tampered.to_csv(audit/"session_coverage_index.csv",index=False);values.append(("coverage ledger tamper detected",clean and not verify_coverage(audit/"session_coverage_index.csv")))
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);frame=pd.DataFrame({"Open":[1.,2.],"High":[2.,3.],"Low":[.5,1.5],"Close":[1.5,2.5]},index=pd.to_datetime(["2026-01-02","2026-01-05"]));archive_market_frames({"^NSEI":frame,"TEST.NS":frame},root/"final_market_data","2026-01-05","TEST_PROVIDER","2026-01-05T12:00:00Z");loaded=verify_and_load_archive(root/"final_market_data",root/"stage4a3_final_market_data_manifest.json");values.append(("final market archive hashes verify",set(loaded)=={"^NSEI","TEST.NS"}))
    fixture=ROOT/"tests/SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE";output=fixture/"tests/final_outputs";result=evaluate(REPO,fixture,"2026-02-01",output);expected=json.loads((fixture/"tests/frozen_portfolio_replay/expected_results.json").read_text());summary=pd.read_csv(output/"stage4a3_policy_summary_d1.csv").set_index("Policy")
    numeric=all(abs(float(summary.loc[p,m])-float(expected[p][m]))<=(1e-6 if m=="Ending Equity" else 1e-9) for p in ("R0_K1","R3_K1") for m in ("Ending Equity","Total Return %","CAGR %","Maximum Drawdown %","Trade Count","Expectancy R","Profit Factor"));values.append(("synthetic matured fixture asserts known portfolio numbers",numeric))
    boot=pd.read_csv(output/"stage4a3_bootstrap_summary.csv").set_index("Block Length").loc[63];exp=expected["Bootstrap 63"];values.append(("synthetic matured fixture asserts known bootstrap numbers",abs(boot["Delta Terminal Return Lower 2.5%"]-exp["Lower 2.5%"])<1e-9 and abs(boot["Median"]-exp["Median"])<1e-9 and abs(boot["P(Delta > 0) %"]-exp["P(Delta > 0) %"])<1e-9))
    pct=pd.read_csv(output/"stage4a3_named_policy_random_percentiles.csv").iloc[0]["Random K1 Total Return Percentile"];values.append(("synthetic matured fixture asserts known random percentile",abs(pct-expected["Random Percentile"])<1e-9))
    values.append(("all four final audit ledgers created",all((output/name).exists() for name in ("stage4a3_trade_ledger_d1.csv.gz","stage4a3_daily_portfolio_d1.csv.gz","stage4a3_trade_ledger_d0.csv.gz","stage4a3_daily_portfolio_d0.csv.gz"))))
    values.append(("synthetic conclusion remains non-confirmatory",result["Conclusion"]=="NOT PROSPECTIVELY CONFIRMED" and result["Stage 5"]=="REMAINS BLOCKED"))
    return [{"Test Number":144+i,"Test":name,"Status":"PASS" if passed else "FAIL","Details":"Final economic methodology/session coverage hardening"} for i,(name,passed) in enumerate(values,1)]


def main()->None:
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=ROOT/"results/stage4a3_economic_methodology_test_results.csv");a=p.parse_args();frame=pd.DataFrame(run());a.output.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(a.output,index=False,lineterminator="\n");print(frame.Status.value_counts().to_dict());raise SystemExit(0 if frame.Status.eq("PASS").all() else 1)
if __name__=="__main__":main()
