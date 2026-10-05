"""Focused acceptance suite for authoritative historical-data acquisition."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from common import file_sha256, load_json, sha256
from authoritative_data import (
    archive_entry, build_membership_periods, feature_pit_readiness, identity_on,
    market_data_readiness, materialize_universe, parse_corporate_actions,
    parse_identity_periods, parse_index_snapshot, parse_security_snapshot,
    readiness_v3, survivorship_assessment, validate_product,
)
from authoritative_data.acquire import acquire
from authoritative_data.cli import main as cli_main

RESULTS = []


def require(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def raises(error, fn, contains=None):
    try:
        fn()
    except error as exc:
        if contains:
            require(contains in str(exc), str(exc))
        return
    raise AssertionError(f"expected {error.__name__}")


def case(category, name, fn):
    try:
        fn(); status, detail = "PASS", ""
    except Exception as exc:
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    RESULTS.append({"category": category, "test": name, "status": status, "detail": detail})


def git(*args):
    return subprocess.check_output(["git", "--git-dir=_git", "--work-tree=.", *args], cwd=REPO, text=True).strip()


INV = load_json(ROOT/"results/official_historical_data_product_inventory_v1.json")
ARCH = load_json(ROOT/"results/authoritative_data_archive_manifest_v1.json")
POLICY = load_json(ROOT/"results/survivorship_coverage_policy_v1.json")
V3 = load_json(ROOT/"results/advanced_research_readiness_v3.json")
PRODUCT = INV["products"][0]

case("PRODUCT", "official product classification deterministic", lambda: require(validate_product(PRODUCT) == validate_product(PRODUCT)))
case("PRODUCT", "subscription product cannot become publicly acquired", lambda: raises(ValueError, lambda: validate_product({**PRODUCT,"acquisition_status":"PUBLICLY_ACQUIRED"}), "SUBSCRIPTION_PRODUCT"))
case("PRODUCT", "unverified source blocked from verified", lambda: raises(ValueError, lambda: validate_product({**PRODUCT,"source_classification":"SECONDARY_UNVERIFIED","verified":True}), "UNVERIFIED"))
case("PRODUCT", "licence metadata required", lambda: raises(ValueError, lambda: validate_product({k:v for k,v in PRODUCT.items() if k != "licence_status"}), "INCOMPLETE"))
case("PRODUCT", "all product classes allowed", lambda: require(all(x["source_classification"] in {"OFFICIAL_PUBLIC_VERIFIED","OFFICIAL_LICENSED_VERIFIED","OFFICIAL_SUBSCRIPTION_REQUIRED","OFFICIAL_MANUAL_ACQUISITION_REQUIRED","OFFICIAL_AUTOMATION_RESTRICTED","SECONDARY_UNVERIFIED","NOT_AVAILABLE"} for x in INV["products"])))
case("PRODUCT", "all references official domains", lambda: require(all(any(d in x["official_reference"] for d in ["nseindia.com","niftyindices.com","bseindia.com"]) for x in INV["products"])))
case("PRODUCT", "NSE investigated", lambda: require(any(x["provider"].startswith("National Stock") for x in INV["products"])))
case("PRODUCT", "NSE Indices investigated", lambda: require(any(x["provider"] == "NSE Indices Limited" for x in INV["products"])))
case("PRODUCT", "BSE investigated", lambda: require(any(x["provider"] == "BSE Limited" for x in INV["products"])))

data1, data2 = b"official bytes", b"official changed bytes"
ae1 = archive_entry(archive_id="A",source_id="S",publisher="P",source_reference="https://www.nseindia.com/x",original_filename="x.csv",retrieved_at="2026-10-04T00:00:00Z",content=data1,local_path="data/raw/x.csv",licence_classification="OFFICIAL_PUBLIC_VERIFIED")
case("ARCHIVE", "official file hash deterministic", lambda: require(ae1["sha256"] == hashlib.sha256(data1).hexdigest()))
case("ARCHIVE", "changed bytes change archive identity", lambda: require(ae1["sha256"] != archive_entry(archive_id="A",source_id="S",publisher="P",source_reference="https://www.nseindia.com/x",original_filename="x.csv",retrieved_at="2026-10-04T00:00:00Z",content=data2,local_path="data/raw/x.csv",licence_classification="OFFICIAL_PUBLIC_VERIFIED")["sha256"]))
case("ARCHIVE", "raw data remains gitignored", lambda: require(git("check-ignore","NextGen Research/data/external_authoritative/nifty_constituents/example.csv").endswith("example.csv")))
case("ARCHIVE", "missing source provenance rejected", lambda: raises(ValueError, lambda: archive_entry(archive_id="",source_id="S",publisher="P",source_reference="x",original_filename="x",retrieved_at="x",content=b"x",local_path="x",licence_classification="OFFICIAL_PUBLIC_VERIFIED"), "PROVENANCE"))
case("ARCHIVE", "manifest raw commit false", lambda: require(ARCH["raw_files_committed"] is False and all(x["raw_file_committed"] is False for x in ARCH["archives"])))
case("ARCHIVE", "manifest hashes well formed", lambda: require(all(len(x["sha256"]) == 64 for x in ARCH["archives"])))

SEC = ("snapshot_date,security_id,isin,symbol,company,series,listing_date,trading_status\n"
       "2024-01-02,NSE:INE001,INE001,OLD,Alpha,EQ,2010-01-01,ACTIVE\n").encode()
SEC2 = SEC.replace(b"OLD", b"NEW")
security = parse_security_snapshot(SEC,archive_id="SEC1")
case("SECURITY", "historical snapshot ingestion", lambda: require(security[0]["snapshot_date"] == "2024-01-02" and security[0]["source_archive_id"] == "SEC1"))
case("SECURITY", "source hash retained", lambda: require(security[0]["source_hash"] == hashlib.sha256(SEC).hexdigest()))
case("SECURITY", "source hash mismatch rejected", lambda: raises(ValueError, lambda: parse_security_snapshot(SEC,archive_id="S",source_hash="0"*64), "HASH"))
case("SECURITY", "duplicate ISIN conflict", lambda: raises(ValueError, lambda: parse_security_snapshot(SEC+SEC.splitlines(True)[1],archive_id="S"), "DUPLICATE"))
case("SECURITY", "unknown schema rejected", lambda: raises(ValueError, lambda: parse_security_snapshot(SEC.replace(b"trading_status",b"mystery"),archive_id="S"), "UNSUPPORTED"))
case("SECURITY", "unknown extra column rejected", lambda: raises(ValueError, lambda: parse_security_snapshot(SEC.replace(b"trading_status",b"trading_status,extra").replace(b"ACTIVE\n",b"ACTIVE,x\n"),archive_id="S"), "UNSUPPORTED"))
case("SECURITY", "future listing excluded", lambda: require(materialize_universe(profile="EXCHANGE_WIDE_PIT",as_of_date="2009-01-01",securities=security)["securities"] == []))
case("SECURITY", "exact snapshot eligible", lambda: require(len(materialize_universe(profile="EXCHANGE_WIDE_PIT",as_of_date="2024-01-02",securities=security)["securities"]) == 1))

IDENT = ("security_id,isin,symbol,company,series,effective_from,effective_to\n"
         "NSE:INE001,INE001,OLD,Alpha,EQ,2010-01-01,2023-12-31\n"
         "NSE:INE001,INE001,NEW,Alpha Ltd,EQ,2024-01-01,\n").encode()
ids = parse_identity_periods(IDENT,archive_id="ID1")
case("IDENTITY", "ticker change identity continuity", lambda: require(identity_on(ids,"INE001","2023-01-01")["symbol"] == "OLD" and identity_on(ids,"INE001","2024-01-01")["symbol"] == "NEW"))
case("IDENTITY", "identity before evidence unknown", lambda: require(identity_on(ids,"INE001","2009-01-01") is None))
case("IDENTITY", "overlapping symbol periods rejected", lambda: raises(ValueError, lambda: parse_identity_periods(IDENT.replace(b"2023-12-31",b"2024-12-31"),archive_id="I"), "CONFLICTING"))

IDX = ("index_id,snapshot_date,security_id,isin,symbol,company,weight,market_cap\n"
       "NIFTY500,2024-01-01,NSE:INE001,INE001,OLD,Alpha,1.0,100\n"
       "NIFTY500,2024-02-01,NSE:INE001,INE001,NEW,Alpha,1.1,110\n"
       "NIFTY500,2024-02-01,NSE:INE002,INE002,BETA,Beta,0.8,80\n").encode()
idx = parse_index_snapshot(IDX,archive_id="IDX1")
periods = build_membership_periods(idx)
case("INDEX", "exact snapshot membership", lambda: require(len([x for x in idx if x["snapshot_date"]=="2024-02-01"]) == 2))
case("INDEX", "non-member exclusion", lambda: require(all(x["isin"] != "INE999" for x in periods)))
case("INDEX", "membership cannot be backfilled before evidence", lambda: require(materialize_universe(profile="INDEX_CONSTITUENT_PIT",as_of_date="2023-12-01",index_membership=periods)["securities"] == []))
case("INDEX", "snapshot gap remains unknown", lambda: require("NO_SUPPORTED_INDEX_MEMBERSHIP_ON_DATE" in materialize_universe(profile="INDEX_CONSTITUENT_PIT",as_of_date="2025-01-01",index_membership=periods)["unknowns"]))
case("INDEX", "current constituents cannot masquerade historical", lambda: require(materialize_universe(profile="INDEX_CONSTITUENT_PIT",as_of_date="2020-01-01",index_membership=periods)["securities"] == []))
case("INDEX", "membership provenance retained", lambda: require(periods[0]["evidence_basis"] == "BOUNDED_BY_OFFICIAL_SNAPSHOTS" and periods[0]["source_archive_ids"] == ["IDX1"]))
case("INDEX", "index duplicate rejected", lambda: raises(ValueError, lambda: parse_index_snapshot(IDX+IDX.splitlines(True)[1],archive_id="I"), "DUPLICATE"))
case("INDEX", "index unknown schema rejected", lambda: raises(ValueError, lambda: parse_index_snapshot(IDX.replace(b"market_cap",b"mystery"),archive_id="I"), "UNSUPPORTED"))

ACTIONS=("security_id,isin,symbol,action_type,record_date,effective_date,description\n"
         "NSE:INE001,INE001,OLD,SPLIT,2024-01-10,2024-01-11,1:2 split\n").encode()
actions=parse_corporate_actions(ACTIONS,archive_id="CA1")
case("ACTION", "corporate action effective date retained", lambda: require(actions[0]["effective_date"] == "2024-01-11"))
case("ACTION", "corporate action provenance retained", lambda: require(actions[0]["source_archive_id"] == "CA1" and len(actions[0]["source_hash"]) == 64))
case("ACTION", "corporate action unknown schema rejected", lambda: raises(ValueError, lambda: parse_corporate_actions(ACTIONS.replace(b"description",b"guess"),archive_id="C"), "UNSUPPORTED"))

uwide = materialize_universe(profile="EXCHANGE_WIDE_PIT",as_of_date="2024-01-02",securities=security)
uindex = materialize_universe(profile="INDEX_CONSTITUENT_PIT",as_of_date="2024-01-15",index_membership=periods)
case("UNIVERSE", "exchange-wide profile fail closed", lambda: require(materialize_universe(profile="EXCHANGE_WIDE_PIT",as_of_date="2024-01-03",securities=security)["unknowns"]))
case("UNIVERSE", "index profile fail closed", lambda: require(materialize_universe(profile="INDEX_CONSTITUENT_PIT",as_of_date="2023-01-01",index_membership=periods)["unknowns"]))
case("UNIVERSE", "delisted security can appear historically when proven", lambda: require(any(x["isin"] == "INE001" for x in uwide["securities"])))
case("UNIVERSE", "universe hash deterministic", lambda: require(uwide == materialize_universe(profile="EXCHANGE_WIDE_PIT",as_of_date="2024-01-02",securities=security)))
case("UNIVERSE", "index universe bounded", lambda: require(len(uindex["securities"]) == 1))
case("UNIVERSE", "unsupported profile rejected", lambda: raises(ValueError, lambda: materialize_universe(profile="TODAY_BACKFILLED",as_of_date="2024-01-01"), "UNSUPPORTED"))

surv_bad = survivorship_assessment(year=2024,historical_ids=["A"],current_ids=["A"],delisted_ids=[],unknown_membership=1,unknown_identity=0,evidence_source_count=1,policy=POLICY)
surv_good = survivorship_assessment(year=2024,historical_ids=["A","B"],current_ids=["A"],delisted_ids=["B"],unknown_membership=0,unknown_identity=0,evidence_source_count=2,policy=POLICY)
case("SURVIVORSHIP", "current-survivor-only fixture fails", lambda: require(surv_bad["survivorship_distortion_materially_reduced"] is False))
case("SURVIVORSHIP", "historical delisted inclusion improves coverage", lambda: require(surv_good["known_delisted_non_surviving"] == 1 and surv_good["coverage_percentage"] > surv_bad["coverage_percentage"]))
case("SURVIVORSHIP", "unknown share calculated", lambda: require(surv_bad["unknown_share"] == 0.5))
case("SURVIVORSHIP", "threshold cannot silently change", lambda: require(surv_good["policy_hash"] == sha256(POLICY)))
case("SURVIVORSHIP", "criterion labelled governance threshold", lambda: require(surv_good["criterion_classification"] == "RESEARCH_GOVERNANCE_THRESHOLD"))

market_good=market_data_readiness(ohlc=True,volume=True,turnover=True,trading_days=True,adjustment_state="RAW_UNADJUSTED",official_provenance=True)
case("MARKET", "raw semantics explicit", lambda: require(market_good["price_adjustment_state"] == "RAW_UNADJUSTED"))
case("MARKET", "volume availability assessed", lambda: require(market_good["gates"]["volume"] is True))
case("MARKET", "unsupported adjustment rejected", lambda: raises(ValueError, lambda: market_data_readiness(ohlc=True,volume=True,turnover=True,trading_days=True,adjustment_state="GUESSED",official_provenance=True), "UNSUPPORTED"))
case("MARKET", "unknown adjustment insufficient", lambda: require(market_data_readiness(ohlc=True,volume=True,turnover=True,trading_days=True,adjustment_state="UNKNOWN",official_provenance=True)["status"] == "INSUFFICIENT"))

features=feature_pit_readiness([{"family":"technical","status":"PIT_SAFE_NOW","required_for_minimal_profile":True},{"family":"fundamentals","status":"OPTIONAL_FUTURE_FEATURE_FAMILY","required_for_minimal_profile":False}])
case("FEATURES", "technical feature PIT readiness", lambda: require(features["minimal_profile_pit_safe"] is True))
case("FEATURES", "optional fundamentals do not block", lambda: require("fundamentals" not in features["blocking_required_feature_families"]))
case("FEATURES", "required unavailable feature blocks", lambda: require(feature_pit_readiness([{"family":"liquidity","status":"UNAVAILABLE","required_for_minimal_profile":True}])["minimal_profile_pit_safe"] is False))
case("FEATURES", "invalid state rejected", lambda: raises(ValueError, lambda: feature_pit_readiness([{"family":"x","status":"MADE_UP","required_for_minimal_profile":True}]), "INVALID"))

v1_before="70b603aecd427e9947d4fbf4a68b9eb6f32ff2c1151a930049300d343c5ba6b4"
v2_before=file_sha256(ROOT/"results/advanced_research_readiness_v2.json")
case("V3", "V1 unchanged", lambda: require(file_sha256(ROOT/"results/advanced_research_readiness_v1.json") == v1_before))
case("V3", "V2 unchanged and bound", lambda: require(V3["preserved_v2_file_sha256"] == v2_before))
case("V3", "current state fail closed", lambda: require(V3["status"] == "NOT_READY" and V3["reason"] == "OFFICIAL_DATA_ACQUISITION_REQUIRED"))
partial={"gates":{"universe":True,"identity":True,"survivorship":True,"market_data":True,"costs":True,"benchmark":True,"features":True},"period":{"start_date":"2026-01-01","end_date":"2026-10-03"},"partial_year":True}
case("V3", "partial year cannot be eligible", lambda: require(readiness_v3(profiles={"EXCHANGE_WIDE_PIT":partial},v1_hash=v1_before,v2_hash=v2_before)["status"] == "NOT_READY"))
allg={"universe":True,"identity":True,"survivorship":True,"market_data":True,"costs":True,"benchmark":True,"features":True,"index_membership":True}
synthetic={"gates":allg,"period":{"start_date":"2020-01-01","end_date":"2024-12-31"},"source_manifests":["SYNTHETIC"],"security_coverage":"SUFFICIENT","identity_coverage":"SUFFICIENT","survivorship_assessment":"PASS"}
v3ready=readiness_v3(profiles={"INDEX_CONSTITUENT_PIT":synthetic},v1_hash=v1_before,v2_hash=v2_before)
case("V3", "synthetic ready requires every gate", lambda: require(v3ready["status"] == "READY_WITH_RESTRICTED_PERIOD"))
case("V3", "exact restricted dates emitted", lambda: require(v3ready["profiles"]["INDEX_CONSTITUENT_PIT"]["restricted_period"] == synthetic["period"]))
case("V3", "profile-specific index gate", lambda: require(readiness_v3(profiles={"INDEX_CONSTITUENT_PIT":{**synthetic,"gates":{**allg,"index_membership":False}}},v1_hash=v1_before,v2_hash=v2_before)["profiles"]["INDEX_CONSTITUENT_PIT"]["status"] == "NOT_READY"))
case("V3", "missing exchange profile remains not ready", lambda: require(v3ready["profiles"]["EXCHANGE_WIDE_PIT"]["status"] == "NOT_READY"))
case("V3", "no training authority", lambda: require(not V3["training_started"] and not V3["challenger_trained"] and V3["ml_authority"] == "NONE"))

class Response:
    def __init__(self, data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self.data

with tempfile.TemporaryDirectory() as td:
    target=Path(td)/"official.csv"
    got=acquire("https://www.nseindia.com/official.csv",target,opener=lambda req,timeout:Response(b"ok"),minimum_interval_seconds=0)
    case("ACQUIRE", "mocked official acquisition hashes bytes", lambda: require(got["sha256"] == hashlib.sha256(b"ok").hexdigest()))
    case("ACQUIRE", "mocked acquisition records no bypass", lambda: require(not got["cookies_used"] and not got["captcha_bypass"] and not got["authentication_bypass"]))
case("ACQUIRE", "non-official domain rejected", lambda: raises(ValueError, lambda: acquire("https://example.com/x","x",opener=lambda *_:Response(b"x"),minimum_interval_seconds=0), "ALLOWLISTED"))
case("ACQUIRE", "non-https rejected", lambda: raises(ValueError, lambda: acquire("http://www.nseindia.com/x","x",opener=lambda *_:Response(b"x"),minimum_interval_seconds=0), "ALLOWLISTED"))

with tempfile.TemporaryDirectory() as td:
    src,out=Path(td)/"s.csv",Path(td)/"out.json"; src.write_bytes(SEC)
    rc=cli_main(["ingest","--source","NSE_SECURITY_MASTER","--input",str(src),"--archive-id","CLI1","--output",str(out)])
    cli_value=json.loads(out.read_text())
    case("CLI", "offline CLI succeeds", lambda: require(rc == 0 and cli_value["network_used"] is False))
    case("CLI", "offline CLI binds source hash", lambda: require(cli_value["source_sha256"] == hashlib.sha256(SEC).hexdigest()))
    case("CLI", "offline CLI records parser", lambda: require(cli_value["records"][0]["parser_version"] == "OFFICIAL_SECURITY_MASTER_CSV_V1"))

case("REGRESSION", "active Stage4A3 unchanged", lambda: require(git("diff","--name-only","986f9e6cae2574246fa56ec8f7084addc8bcc58b","--","Stage 4A.3") == ""))
case("REGRESSION", "Stage5D unchanged", lambda: require(git("diff","--name-only","986f9e6cae2574246fa56ec8f7084addc8bcc58b","--","Stage 5D") == ""))
case("REGRESSION", "Stage6 unchanged", lambda: require(git("diff","--name-only","986f9e6cae2574246fa56ec8f7084addc8bcc58b","--","Stage 6") == ""))
case("REGRESSION", "activation unchanged", lambda: require("S6PROSACT_7a2195d6a80d73508727c088" in (ROOT/"regression_guard/active_baseline_v1.json").read_text()))
case("REGRESSION", "active model bundle identity unchanged", lambda: require("4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da" in (REPO/"Stage 4A.3/results/stage4a3_model_bundle_manifest.json").read_text()))
case("REGRESSION", "active source registry unchanged", lambda: require("7d91f4c72365757b6cdfaef0c4027c46bfbdb11c3541c229e828f9ee28d58e90" in "\n".join(p.read_text(errors="ignore") for p in (REPO/"Stage 6").rglob("*.json"))))
case("REGRESSION", "no active model training code", lambda: require(not any("fit(" in p.read_text(errors="ignore") for p in (ROOT/"authoritative_data").rglob("*.py"))))
case("REGRESSION", "no recommendation logic change", lambda: require(git("diff","--name-only","986f9e6cae2574246fa56ec8f7084addc8bcc58b","--","Stage 5D") == ""))
case("REGRESSION", "no paid raw data tracked", lambda: require(not git("ls-files","NextGen Research/data/external_authoritative").splitlines() or all(x.endswith((".gitignore","DATA_DROP_README.md")) for x in git("ls-files","NextGen Research/data/external_authoritative").splitlines())))
case("REGRESSION", "branch exact", lambda: require(git("branch","--show-current") == "nextgen-research-authoritative-data"))
case("REGRESSION", "required parent ancestor", lambda: require(git("merge-base","HEAD","986f9e6cae2574246fa56ec8f7084addc8bcc58b") == "986f9e6cae2574246fa56ec8f7084addc8bcc58b"))

out=ROOT/"results/nextgen_authoritative_data_test_results.csv"
with out.open("w",newline="",encoding="utf-8") as stream:
    writer=csv.DictWriter(stream,fieldnames=["category","test","status","detail"]); writer.writeheader(); writer.writerows(RESULTS)
summary={"total":len(RESULTS),"passed":sum(x["status"]=="PASS" for x in RESULTS),"failed":sum(x["status"]=="FAIL" for x in RESULTS)}
print(json.dumps(summary,sort_keys=True))
for row in RESULTS:
    if row["status"]=="FAIL": print(f"FAIL {row['category']} {row['test']}: {row['detail']}")
raise SystemExit(1 if summary["failed"] else 0)
