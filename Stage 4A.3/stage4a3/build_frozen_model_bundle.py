from __future__ import annotations

import argparse
import importlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
import threadpoolctl
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from .hashing import canonical_json_hash, dataframe_content_hash, package_manifest, sha256_file
from .validation import checks_frame, require_pass


def write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str)+"\n",encoding="utf-8",newline="\n")


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path,index=False,lineterminator="\n",date_format="%Y-%m-%d",float_format="%.17g")


def load_config(stage_root: Path) -> dict[str, Any]:
    return json.loads((stage_root/"config"/"stage4a3_protocol.json").read_text(encoding="utf-8"))


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git","-c",f"safe.directory={repo.as_posix()}",*args],cwd=repo,text=True).strip()


def frozen_modules(repo: Path):
    frozen_path=str(repo/"Stage 4A"/"stage4a")
    if frozen_path not in sys.path:
        sys.path.insert(0,frozen_path)
    return importlib.import_module("features"),importlib.import_module("models"),importlib.import_module("preprocessing")


def training_mask(frame: pd.DataFrame, target: str, spec: dict[str, Any], mode: str) -> pd.Series:
    signal=pd.to_datetime(frame["Signal Date"]).dt.normalize()
    available=pd.to_datetime(frame[spec["available_date"]],errors="coerce").dt.normalize()
    applicable=frame[spec["applicable"]].fillna(False).astype(bool)
    resolved=frame[spec["status"]].astype("string").isin(spec["available_statuses"]) & frame[target].notna() & available.notna()
    mask=applicable & resolved & signal.lt(pd.Timestamp("2026-01-01")) & available.lt(pd.Timestamp("2026-01-01"))
    if mode=="PRIMARY_ONLY":
        mask &= frame["Dataset Cohort"].eq("BASELINE_PRIMARY")
    return mask


def estimator_for(variant: str, stage4_config: dict[str, Any]):
    if variant.startswith("LOGIT_"):
        return LogisticRegression(**stage4_config["logistic_parameters"])
    if variant=="RF_FULL":
        return RandomForestClassifier(**stage4_config["random_forest_parameters"])
    raise ValueError(variant)


def reference_predictions(repo: Path, component: dict[str, str]) -> pd.DataFrame:
    path=repo/("Stage 4A.1/results/stage4a1_primary_only_oos_predictions.csv.gz" if component["mode"]=="PRIMARY_ONLY" else "Stage 4A/results/stage4a_oos_predictions.csv.gz")
    frame=pd.read_csv(path,low_memory=False)
    return frame[(frame["Evaluation Year"]==2026)&(frame["Target"]==component["target"])&(frame["Model Variant"]==component["variant"])].sort_values("Signal ID",kind="mergesort").reset_index(drop=True)


def build_bundle(repo: Path, stage_root: Path, output_root: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    config=load_config(stage_root)
    stage4_config=json.loads((repo/"Stage 4A/config/stage4a_model_config.json").read_text(encoding="utf-8"))
    opportunity=pd.read_csv(repo/"Stage 3.1/results/stage3_1_trade_opportunity_dataset.csv.gz",low_memory=False)
    opportunity["Signal Date"]=pd.to_datetime(opportunity["Signal Date"]).dt.normalize()
    features_module,models_module,preprocessing_module=frozen_modules(repo)
    feature_registry=pd.read_csv(repo/"Stage 3.1/results/stage3_1_feature_registry.csv",low_memory=False)
    ml_registry=pd.read_csv(repo/"Stage 3.1/results/stage3_1_ml_column_registry.csv",low_memory=False)
    feature_sets,_,feature_hashes,type_maps=features_module.build_feature_contract(feature_registry,ml_registry,stage4_config)
    _,model_hashes,model_specs=models_module.build_model_contract(stage4_config,feature_hashes)
    model_dir=output_root/"models"/"frozen_2026";model_dir.mkdir(parents=True,exist_ok=True)
    audit_rows=[];parity_rows=[];manifest_models=[]
    for component in config["required_models"]:
        target,variant,feature_set=component["target"],component["variant"],component["feature_set"]
        mask=training_mask(opportunity,target,stage4_config["targets"][target],component["mode"])
        train=opportunity.loc[mask].copy();reference=reference_predictions(repo,component)
        evaluation=opportunity.set_index("Signal ID").loc[reference["Signal ID"]].reset_index()
        names=feature_sets[feature_set];types=type_maps[feature_set]
        preprocessor=preprocessing_module.build_preprocessor(types["numeric"],types["categorical"],variant.startswith("LOGIT_"))
        transformed=preprocessor.fit_transform(train[names]);estimator=estimator_for(variant,stage4_config);estimator.fit(transformed,train[target].astype(int).to_numpy())
        probabilities=estimator.predict_proba(preprocessor.transform(evaluation[names]))[:,1]
        maximum=float(np.max(np.abs(probabilities-reference["Predicted Probability"].to_numpy(float))))
        artifact=model_dir/f"{component['name']}.joblib"
        joblib.dump({"component":component,"feature_names":names,"numeric_features":types["numeric"],"categorical_features":types["categorical"],"preprocessor":preprocessor,"estimator":estimator,"model_spec_hash":model_hashes[variant],"feature_set_hash":feature_hashes[feature_set]},artifact,compress=3)
        training_ids=train["Signal ID"].astype(str).sort_values(kind="mergesort").reset_index(drop=True).to_frame("Signal ID")
        reference_hash=dataframe_content_hash(reference[["Signal ID","Predicted Probability"]])
        row={"Model Name":component["name"],"Mode":component["mode"],"Target":target,"Variant":variant,"Feature Set":feature_set,"Training Cutoff":"2026-01-01 EXCLUSIVE LABEL AVAILABILITY","Training Rows":len(train),"Positive Count":int(train[target].sum()),"Negative Count":int(len(train)-train[target].sum()),"Frozen Reference Rows":len(reference),"Signal IDs Match":evaluation["Signal ID"].astype(str).tolist()==reference["Signal ID"].astype(str).tolist(),"Maximum Probability Difference":maximum,"Parity Threshold":1e-12,"Parity Status":"PASS" if maximum<=1e-12 else "FAIL","Serialized SHA256":sha256_file(artifact)}
        audit_rows.append(row);parity_rows.append({key:row[key] for key in ["Model Name","Mode","Target","Variant","Feature Set","Frozen Reference Rows","Signal IDs Match","Maximum Probability Difference","Parity Threshold","Parity Status"]})
        manifest_models.append({"model_name":component["name"],"mode":component["mode"],"target":target,"variant":variant,"feature_set":feature_set,"training_cutoff":"label available strictly before 2026-01-01","training_rows":len(train),"positive_count":int(train[target].sum()),"negative_count":int(len(train)-train[target].sum()),"model_parameters":model_specs[variant]["hyperparameters"],"feature_hash":feature_hashes[feature_set],"preprocessor_hash":canonical_json_hash(model_specs[variant]["preprocessing"]),"serialized_model_sha256":sha256_file(artifact),"training_signal_id_logical_hash":dataframe_content_hash(training_ids),"frozen_reference_prediction_hash":reference_hash,"parity_maximum_absolute_difference":maximum})
    audit=pd.DataFrame(audit_rows);parity=pd.DataFrame(parity_rows)
    require_pass(parity.rename(columns={"Parity Status":"Status","Model Name":"Check"}))
    bundle_payload={"protocol_version":config["protocol_version"],"training_cutoff":"2026-01-01 exclusive","models":manifest_models}
    bundle_hash=canonical_json_hash(bundle_payload);manifest={**bundle_payload,"FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH":bundle_hash}
    write_json(manifest,model_dir/"model_bundle_manifest.json")
    return manifest,audit,parity,{"feature_sets":feature_sets,"feature_hashes":feature_hashes,"type_maps":type_maps,"model_hashes":model_hashes}


def environment_report() -> dict[str, Any]:
    return {"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,"scikit-learn":sklearn.__version__,"scipy":scipy.__version__,"joblib":joblib.__version__,"threadpoolctl":threadpoolctl.__version__}


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--repo-root",type=Path,required=True);parser.add_argument("--stage-root",type=Path,required=True);parser.add_argument("--output-root",type=Path);args=parser.parse_args()
    root=(args.output_root or args.stage_root).resolve();manifest,audit,parity,_=build_bundle(args.repo_root.resolve(),args.stage_root.resolve(),root)
    write_csv(audit,root/"results"/"stage4a3_model_reconstruction_audit.csv");write_csv(parity,root/"results"/"stage4a3_2026_prediction_parity.csv");write_json(manifest,root/"results"/"stage4a3_model_bundle_manifest.json");write_json(environment_report(),root/"results"/"stage4a3_environment_report.json")
    print(json.dumps({"bundle_hash":manifest["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"],"models":len(manifest["models"]),"max_probability_difference":float(parity["Maximum Probability Difference"].max())}),flush=True)


if __name__=="__main__":
    main()
