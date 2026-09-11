from __future__ import annotations
import gzip,json,sys
from pathlib import Path
import joblib,pandas as pd

repo=Path(__file__).resolve().parents[2];root=repo/"Stage 4A.3";date="2025-12-10"
bundle=joblib.load(root/"models/frozen_2026/PRIMARY_ONLY_T1_LOGIT_FULL.joblib")
features=bundle["feature_names"]
identity=["Signal ID","Ticker","Signal Date","Original Signal","Signal","Setup","Market Regime","Trade Quality","Actionability Score","Technical Score","Entry Low","Stop Loss","Target 1","Target 2","Dataset Cohort"]
source=pd.read_csv(repo/"Stage 3.1/results/stage3_1_trade_opportunity_dataset.csv.gz",low_memory=False)
fixture=source.loc[source["Signal Date"].astype(str).eq(date)&source["Dataset Cohort"].eq("BASELINE_PRIMARY"),list(dict.fromkeys(identity+features))].copy()
fixture.insert(0,"Fixture Semantics","HISTORICAL_TEST_FIXTURE")
target=root/"tests/fixtures";target.mkdir(parents=True,exist_ok=True)
payload=fixture.to_csv(index=False,lineterminator="\n",float_format="%.17g").encode()
with (target/"HISTORICAL_TEST_FIXTURE_2025-12-10.csv.gz").open("wb") as raw:
    with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as zipped:zipped.write(payload)
manifest={"fixture_semantics":"HISTORICAL_TEST_FIXTURE","provider_identifier":"FROZEN_STAGE3_1_TEST_DATA","download_timestamp_utc":"2025-12-10T11:00:00+00:00","maximum_market_data_date":date,"nifty_maximum_date":date,"ticker_count_requested":19,"ticker_count_received":19,"missing_tickers":[],"raw_data_logical_hash":"HISTORICAL_TEST_FIXTURE_ONLY"}
(target/"HISTORICAL_TEST_FIXTURE_market_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
print(len(fixture))
