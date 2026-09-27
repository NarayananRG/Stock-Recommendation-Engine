from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys
from copy import deepcopy
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("s63b",Path(__file__).with_name("run_stage6_3b_tests.py"));b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
from stage6_ingestion.canonical import canonical_hash,without
from stage6_transmission import *
OUT=ROOT/"results"/"stage6_3c_test_results.csv";BASE="stage6-3b-explicit-event-exposure-binding-baseline";COMMIT="d05495b250ff9abefd912b763780ec5f4f6003cb";TESTS=[]
def test(c,n):
 def d(f):TESTS.append((c,n,f));return f
 return d
def ok(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def err(e,f):
 try:f()
 except e:return
 raise AssertionError("expected "+e.__name__)
def git(*x):return subprocess.check_output(["git",*x],cwd=REPO,text=True).strip()
def frozen_binding(store,event,exposure,channel="RATE",types=None):
 items=deepcopy(exposure["assertions"]);types=types or ["INTEREST_RATE_SENSITIVITY"]
 for i,t in enumerate(types):items[i%len(items)]["exposure_type"]=t
 p,_,h=b.load_policy();return b.build_binding(event=event,exposure=exposure,selected_assertions=items[:len(types)],binding_channel=channel,binding_cutoff_timestamp=b.BIND,policy=p,policy_hash=h)
@test("BASELINE","frozen 6.3B exact ancestor")
def _():ok(git("rev-parse",f"{BASE}^{{}}")==COMMIT);subprocess.check_call(["git","merge-base","--is-ancestor",COMMIT,"HEAD"],cwd=REPO)
@test("POLICY","identity hash five rules and uniqueness")
def _():p,j,h=load_policy();ok(validate_policy(p)==p and canonical_hash(p)==h==EXPECTED_POLICY_HASH_V1 and p["rules"]==EXPECTED_RULES_V1 and len(p["rules"])==5 and len({r["rule_id"] for r in p["rules"]})==5)
@test("POLICY","overlap and unsorted arrays rejected")
def _():
 p,_,_=load_policy();q=deepcopy(p);q["rules"][1]["event_types"]=q["rules"][0]["event_types"];q["rules"][1]["binding_channel"]=q["rules"][0]["binding_channel"];err(Stage6TransmissionError,lambda:validate_policy(q));q=deepcopy(p);q["rules"][0]["event_types"].reverse();err(Stage6TransmissionError,lambda:validate_policy(q))
@test("POLICY","structurally valid semantic drift is rejected for frozen V1")
def _():
 p,_,_=load_policy()
 def rejected(change):
  q=deepcopy(p);change(q);q["rules"].sort(key=lambda r:r["rule_id"]);err(Stage6TransmissionError,lambda:validate_policy(q))
 def rate(q):return next(r for r in q["rules"] if r["rule_id"]=="S6TRANS_RATE_V1")
 rejected(lambda q:q["rules"].append({"rule_id":"S6TRANS_REGULATORY_V1","event_types":["REGULATORY_ACTION"],"binding_channel":"SECTOR","allowed_exposure_types":["GOVERNMENT_SPENDING"],"dimension_match_mode":"NOT_EVALUATED"}))
 rejected(lambda q:q["rules"].__setitem__(slice(None),[r for r in q["rules"] if r["rule_id"]!="S6TRANS_TRADE_V1"]))
 rejected(lambda q:rate(q).__setitem__("event_types",["LIQUIDITY_EVENT","RATE_CUT"]))
 rejected(lambda q:rate(q).__setitem__("event_types",["LIQUIDITY_EVENT","RATE_CUT","RATE_HIKE"]))
 rejected(lambda q:rate(q).__setitem__("binding_channel","MACRO"))
 rejected(lambda q:rate(q).__setitem__("allowed_exposure_types",["DEBT_SENSITIVITY","GOVERNMENT_SPENDING","INTEREST_RATE_SENSITIVITY"]))
 rejected(lambda q:rate(q).__setitem__("allowed_exposure_types",["INTEREST_RATE_SENSITIVITY"]))
 rejected(lambda q:rate(q).__setitem__("dimension_match_mode","NOT_EVALUATED"))
 rejected(lambda q:rate(q).__setitem__("rule_id","S6TRANS_RATE_RENAMED_V1"))
@test("TYPE_MATCH","RATE full partial no-match and unsupported")
def _():
 with b.env() as (*_,store,event,exposure,root):
  p,_,h=load_policy()
  cases=[(["INTEREST_RATE_SENSITIVITY"],"RATE","FULL_TYPE_MATCH",1),(["INTEREST_RATE_SENSITIVITY","GEOPOLITICAL"],"RATE","PARTIAL_TYPE_MATCH",1),(["GEOPOLITICAL"],"RATE","NO_TYPE_MATCH",0),(["INTEREST_RATE_SENSITIVITY"],"COMMODITY","UNSUPPORTED_EVENT_CHANNEL",0)]
  for types,ch,status,count in cases:
   x=build_transmission(frozen_binding(store,event,exposure,ch,types),p,h);ok(x["type_compatibility_status"]==status and len(x["transmission_paths"])==count)
@test("RULE","currency commodity geography trade and debt rules")
def _():
 with b.env() as (*_,store,event,exposure,root):
  p,_,h=load_policy();cases=[("CURRENCY_SHOCK","CURRENCY","CURRENCY","NOT_EVALUATED"),("OIL_SHOCK","COMMODITY","ENERGY_SENSITIVITY","NOT_EVALUATED"),("WAR_ESCALATION","GEOGRAPHY","REVENUE_GEOGRAPHY","NOT_EVALUATED"),("TARIFF_INCREASE","MACRO","IMPORT_DEPENDENCY","NOT_EVALUATED"),("RATE_CUT","RATE","DEBT_SENSITIVITY","NOT_REQUIRED")]
  for et,ch,typ,dim in cases:
   e=deepcopy(event);e["event_type"]=et;e["record_hash"]=canonical_hash(without(e,"record_hash"));x=build_transmission(frozen_binding(store,e,exposure,ch,[typ]),p,h);ok(x["type_compatibility_status"]=="FULL_TYPE_MATCH" and x["transmission_paths"][0]["dimension_match_status"]==dim)
@test("RULE","regulatory event deliberately unsupported")
def _():
 with b.env() as (*_,store,event,exposure,root):
  event["event_type"]="REGULATORY_ACTION";event["record_hash"]=canonical_hash(without(event,"record_hash"));p,_,h=load_policy();x=build_transmission(frozen_binding(store,event,exposure),p,h);ok(x["type_compatibility_status"]=="UNSUPPORTED_EVENT_CHANNEL" and x["rule_id"] is None)
@test("PARTITION","matched unmatched exact and paths equal matches")
def _():
 with b.env() as (*_,store,event,exposure,root):
  p,_,h=load_policy();x=build_transmission(frozen_binding(store,event,exposure,"RATE",["INTEREST_RATE_SENSITIVITY","GEOPOLITICAL"]),p,h);allh={a["assertion_hash"] for a in x["assertion_evaluations"]};ok(set(x["matched_assertion_hashes"])|set(x["unmatched_assertion_hashes"])==allh and not set(x["matched_assertion_hashes"])&set(x["unmatched_assertion_hashes"]) and len(x["transmission_paths"])==len(x["matched_assertion_hashes"]))
@test("STORE","exact binding evaluation idempotency and integrity")
def _():
 with b.env() as (ing,events,exposures,evidence,regs,bindings,event,exposure,root):
  binding=b.append(bindings,event,exposure,[b.assertion_hash(next(a for a in exposure["assertions"] if a["exposure_type"]=="INTEREST_RATE_SENSITIVITY"))])["binding"]
  with TransmissionStore(root/"trans.sqlite3",bindings) as s:r=s.evaluate_binding(binding_id=binding["binding_id"]);ok(r["transmission"]["type_compatibility_status"]=="FULL_TYPE_MATCH" and s.evaluate_binding(binding_id=binding["binding_id"])["status"]=="IDEMPOTENT_SUCCESS" and s.integrity_check()["result"]=="PASS")
@test("APPEND_ONLY","all tables protected and trigger loss detected")
def _():
 with b.env() as (ing,events,exposures,evidence,regs,bindings,event,exposure,root):
  binding=b.append(bindings,event,exposure,[b.assertion_hash(next(a for a in exposure["assertions"] if a["exposure_type"]=="INTEREST_RATE_SENSITIVITY"))])["binding"]
  with TransmissionStore(root/"trans.sqlite3",bindings) as s:
   s.evaluate_binding(binding_id=binding["binding_id"])
   for t in ("transmission_store_meta","transmission_policies","transmission_records","transmission_assertion_evaluations","transmission_paths","transmission_dependencies"):err(sqlite3.DatabaseError,lambda t=t:s.connection.execute(f"UPDATE {t} SET rowid=rowid"));err(sqlite3.DatabaseError,lambda t=t:s.connection.execute(f"DELETE FROM {t}"))
   s.connection.execute("DROP TRIGGER protect_transmission_records_delete");s.connection.commit();err(TransmissionIntegrityFailure,s.integrity_check)
@test("TAMPER","record policy binding child and dependency tamper rejected")
def _():
 for table,column,value in (("transmission_records","record_hash","f"*64),("transmission_policies","policy_hash","f"*64),("transmission_assertion_evaluations","type_match_status","TYPE_INCOMPATIBLE"),("transmission_paths","path_id","BAD"),("transmission_dependencies","record_hash","f"*64)):
  with b.env() as (ing,events,exposures,evidence,regs,bindings,event,exposure,root):
   binding=b.append(bindings,event,exposure,[b.assertion_hash(next(a for a in exposure["assertions"] if a["exposure_type"]=="INTEREST_RATE_SENSITIVITY"))])["binding"];s=TransmissionStore(root/"trans.sqlite3",bindings);s.evaluate_binding(binding_id=binding["binding_id"]);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.commit();err(Exception,s.integrity_check);s.close()
@test("BOUNDARY","no inference direction magnitude AI trading or frozen changes")
def _():
 text="\n".join(p.read_text().casefold() for p in (ROOT/"stage6_transmission").glob("*.py"));
 for token in ("semantic similarity","embedding","ocr","expected_return","beneficiary","stock_direction","broker"):ok(token not in text)
 ok(git("diff","--name-only",BASE,"--","Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md")=="")
@test("NETWORK_AI_TRADING","socket sentinel")
def _():
 with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):
  with b.env() as (ing,events,exposures,evidence,regs,bindings,event,exposure,root):binding=b.append(bindings,event,exposure,[b.assertion_hash(next(a for a in exposure["assertions"] if a["exposure_type"]=="INTEREST_RATE_SENSITIVITY"))])["binding"];s=TransmissionStore(root/"t.sqlite3",bindings);s.evaluate_binding(binding_id=binding["binding_id"]);s.close()
def main():
 rows=[]
 for i,(c,n,f) in enumerate(TESTS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):f()
   rows.append({"test_id":f"S6_3C_{i:03d}","category":c,"test_name":n,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3C_{i:03d}","category":c,"test_name":n,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0]);w.writeheader();w.writerows(rows);h.close();bad=[r for r in rows if r["result"]=="FAIL"];print(json.dumps({"stage":"6.3C","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","network_calls":0,"llm_calls":0,"ml":False,"nlp":False},sort_keys=True));[print("FAIL",r) for r in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
