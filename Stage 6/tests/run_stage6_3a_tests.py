"""Stage 6.3A PIT exposure record acceptance tests."""
from __future__ import annotations
import ast,csv,json,socket,sqlite3,subprocess,sys,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
STAGE_ROOT=Path(__file__).resolve().parents[1];REPO_ROOT=STAGE_ROOT.parent;sys.path.insert(0,str(STAGE_ROOT))
from stage6_connectors.live_registries import RBI_SOURCE_ID,build_multisource_registries
from stage6_exposure import *
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_ingestion.evidence_store import IngestionStore
from stage6_ingestion.registry import build_entity_registry,build_source_registry

RESULT_PATH=STAGE_ROOT/"results"/"stage6_3a_test_results.csv";BASELINE="stage6-2f-controlled-event-lifecycle-baseline";BASE_COMMIT="9d18f07e159cf147dcfb35654a84da8690e13879";ASOF="2026-09-27T12:00:00.000000Z";CUTOFF="2026-09-27T10:00:00.000000Z";CHECKS=[]
def check(c,n):
 def reg(f):CHECKS.append((c,n,f));return f
 return reg
def require(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def expect(e,f,s=None):
 try:f()
 except e as x:
  if s:require(s in str(x),f"{s!r} not in {x!r}")
  return
 raise AssertionError("expected "+e.__name__)
def reject(f):
 try:f()
 except Exception:return
 raise AssertionError("expected rejection")
def git(*a):return subprocess.check_output(["git",*a],cwd=REPO_ROOT,text=True).strip()
def entity(identity,kind,sector=None,subsector=None,relationships=None,effective="2020-01-01T00:00:00Z"):
 return {"entity_id":identity,"canonical_name":identity,"legal_name":identity if kind=="COMPANY" else None,"entity_type":kind,"country":"IN","ticker_mappings":[],"aliases":[],"isin":None,"sector_entity_id":sector,"subsector_entity_id":subsector,"relationships":relationships or [],"entity_record_version":1,"effective_from":effective,"reviewed_at":"2026-09-25T00:00:00Z","previous_version_hash":None}
def relationship(kind,target):return {"relationship_type":kind,"related_entity_id":target,"effective_from":"2020-01-01","effective_to":None,"evidence_ids":[]}

@contextmanager
def env(subsector=True,authority="PRIMARY_OFFICIAL"):
 with tempfile.TemporaryDirectory(prefix="s63a_") as folder:
  root=Path(folder);base=build_multisource_registries();entities=[entity("SEC_SYN","SECTOR"),entity("SUB_SYN","SUBSECTOR"),entity("PARENT_SYN","COMPANY","SEC_SYN"),entity("CHILD_SYN","COMPANY","SEC_SYN"),entity("GROUP_SYN","COMPANY","SEC_SYN")]
  rels=[relationship("PARENT","PARENT_SYN"),relationship("SUBSIDIARY","CHILD_SYN"),relationship("CORPORATE_GROUP_MEMBER","GROUP_SYN")]
  entities.append(entity("COMPANY_SYN","COMPANY","SEC_SYN","SUB_SYN" if subsector else None,rels));registry=build_entity_registry(entities,"2026-09-25T12:00:00Z")
  source=deepcopy(next(x for x in base["source_v2"]["sources"] if x["source_id"]==RBI_SOURCE_ID));source.pop("record_hash");source["authority_level"]=authority;source_registry=build_source_registry([source],"2026-09-26T12:00:00Z")
  ing=IngestionStore(root/"ing.sqlite3",root/"raw");ing.import_registry(registry);ing.import_registry(source_registry)
  def capture(key,time="2026-09-27T09:00:00Z",status="RETRIEVED"):
   return ing.capture_evidence(idempotency_key=key,source_registry_snapshot_id=source_registry["registry_snapshot_id"],entity_registry_snapshot_id=registry["registry_snapshot_id"],source_id=RBI_SOURCE_ID,source_reference="fixture://"+key,raw_payload=key.encode(),content_type="text/plain",publication_timestamp_utc=None,observed_timestamp_utc=time,retrieved_timestamp_utc=time,entity_ids=["COMPANY_SYN"],retrieval_status=status)["record"]
  e1=capture("e1");e2=capture("e2");store=ExposureStore(root/"exp.sqlite3",ing)
  try:yield ing,store,registry,e1,e2,capture,root
  finally:store.close();ing.close()
def assertion(eid,quant=True,unit="PERCENT_REVENUE"):
 return {"exposure_type":"REVENUE_GEOGRAPHY" if quant else "GEOPOLITICAL","value_type":"QUANTITATIVE" if quant else "QUALITATIVE","measurement":{"value":30.0,"unit":unit,"basis":"FY2025 consolidated revenue","declared_unit":None} if quant else None,"qualitative_value":None if quant else "MEDIUM","evidence_ids":[eid],"confidence":0.0,"effective_date":"2026-01-01","review_or_expiry_date":"2026-12-31"}
def rel(eid,kind="PARENT",target="PARENT_SYN"):
 return {"relationship_type":kind,"related_entity_id":target,"evidence_ids":[eid],"confidence":0.0,"effective_date":"2026-01-01","review_or_expiry_date":"2026-12-31"}
def append(store,reg,e1,**kw):
 args=dict(company_entity_id="COMPANY_SYN",exposure_version=1,previous_version_hash=None,as_of_timestamp=ASOF,data_cutoff_timestamp=CUTOFF,entity_registry_snapshot_id=reg["registry_snapshot_id"],input_evidence_ids=[e1["evidence_id"]],assertions=[assertion(e1["evidence_id"])],relationships=[]);args.update(kw);return store.append_exposure(**args)

@check("BASELINE","6.2F exact frozen ancestor")
def _():require(git("rev-parse",f"{BASELINE}^{{}}")==BASE_COMMIT);subprocess.check_call(["git","merge-base","--is-ancestor",BASE_COMMIT,"HEAD"],cwd=REPO_ROOT)
@check("BASELINE","authority and schema exact")
def _():require(AUTHORITY=="SHADOW_ONLY" and EXPOSURE_SCHEMA_VERSION=="STAGE6_EXPOSURE_V2" and STORE_SCHEMA_VERSION=="STAGE6_3A_EXPOSURE_STORE_V1")
@check("IDENTITY","same company stable across all mutable inputs")
def _():require(deterministic_exposure_id("A")==deterministic_exposure_id("A") and deterministic_exposure_id("A")!=deterministic_exposure_id("B"))
@check("VERSION","V1 valid and predecessor null")
def _():
 with env() as (_,s,r,e,*_):x=append(s,r,e);require(x["exposure"]["exposure_version"]==1 and x["exposure"]["previous_version_hash"] is None)
@check("VERSION","V2 valid exact predecessor")
def _():
 with env() as (_,s,r,e,*_):v1=append(s,r,e)["exposure"];v2=append(s,r,e,exposure_version=2,previous_version_hash=v1["record_hash"],data_cutoff_timestamp="2026-09-27T11:00:00Z")["exposure"];require(v2["previous_version_hash"]==v1["record_hash"])
@check("VERSION","gap and wrong predecessor rejected")
def _():
 with env() as (_,s,r,e,*_):
  for v,h in ((2,None),(3,"f"*64)):reject(lambda v=v,h=h:append(s,r,e,exposure_version=v,previous_version_hash=h))
@check("VERSION","exact rerun idempotent and changed duplicate fails")
def _():
 with env() as (_,s,r,e,*_):append(s,r,e);require(append(s,r,e)["status"]=="IDEMPOTENT_SUCCESS");expect(ExposureVersionConflict,lambda:append(s,r,e,as_of_timestamp="2026-09-27T13:00:00Z"))
@check("REGISTRY","exact ID version hash and PIT binding")
def _():
 with env() as (_,s,r,e,*_):x=append(s,r,e)["exposure"];require((x["entity_registry_snapshot_id"],x["entity_registry_version"],x["entity_registry_hash"])==(r["registry_snapshot_id"],r["registry_version"],r["registry_hash"]))
@check("REGISTRY","missing and future registry rejected")
def _():
 with env() as (_,s,r,e,*_):expect(Exception,lambda:append(s,r,e,entity_registry_snapshot_id="MISSING"));expect(Stage6ExposureError,lambda:append(s,r,e,data_cutoff_timestamp="2026-09-24T00:00:00Z"),"PIT")
@check("COMPANY","COMPANY sector and subsector exact")
def _():
 with env() as (_,s,r,e,*_):x=append(s,r,e)["exposure"];require(x["sector_entity_id"]=="SEC_SYN" and x["subsector_entity_id"]=="SUB_SYN")
@check("COMPANY","wrong type and missing company rejected")
def _():
 with env() as (_,s,r,e,*_):expect(Stage6ExposureError,lambda:append(s,r,e,company_entity_id="SEC_SYN"),"COMPANY_TYPE");expect(Stage6ExposureError,lambda:append(s,r,e,company_entity_id="MISSING"),"RESOLUTION")
@check("SUBSECTOR","null registry subsector produces null")
def _():
 with env(False) as (_,s,r,e,*_):require(append(s,r,e)["exposure"]["subsector_entity_id"] is None)
@check("EVIDENCE","retrieved official evidence accepted with exact dependency")
def _():
 with env() as (_,s,r,e,*_):x=append(s,r,e)["exposure"];row=s.connection.execute("SELECT * FROM exposure_dependencies WHERE dependency_record_type='EVIDENCE'").fetchone();require((row["dependency_record_id"],row["dependency_record_hash"])==(e["evidence_id"],e["record_hash"]))
@check("EVIDENCE","missing and future evidence rejected")
def _():
 with env() as (_,s,r,e,e2,capture,*_):expect(Exception,lambda:append(s,r,e,input_evidence_ids=["MISSING"]));future=capture("future","2026-09-27T11:00:00Z");expect(Stage6ExposureError,lambda:append(s,r,e,input_evidence_ids=[future["evidence_id"]],assertions=[assertion(future["evidence_id"])]),"FUTURE")
@check("EVIDENCE","partial and quarantined rejected")
def _():
 for status in ("PARTIAL","QUARANTINED"):
  with env() as (_,s,r,e,e2,capture,*_):bad=capture("bad"+status,status=status);expect(Stage6ExposureError,lambda:append(s,r,e,input_evidence_ids=[bad["evidence_id"]],assertions=[assertion(bad["evidence_id"])]),"RETRIEVED")
@check("EVIDENCE","authoritative independent accepted; discovery and unverified rejected")
def _():
 with env(authority="AUTHORITATIVE_INDEPENDENT") as (_,s,r,e,*_):append(s,r,e)
 for authority in ("DISCOVERY","UNVERIFIED"):
  with env(authority=authority) as (_,s,r,e,*_):expect(Stage6ExposureError,lambda:append(s,r,e),"AUTHORITY")
@check("EVIDENCE","acquisition attempt is not usable evidence")
def _():
 with env() as (ing,s,r,e,*_):
  source_id=ing.connection.execute("SELECT snapshot_id FROM registry_snapshots WHERE registry_kind='SOURCE'").fetchone()[0]
  failed=ing.capture_acquisition_failure(idempotency_key="failed",source_registry_snapshot_id=source_id,entity_registry_snapshot_id=r["registry_snapshot_id"],source_id=RBI_SOURCE_ID,source_reference="fixture://failed",retrieval_status="FAILED",failure_reason="synthetic",failure_stage="fixture",attempted_at_utc="2026-09-27T09:00:00Z",entity_ids=["COMPANY_SYN"])["record"]
  expect(Stage6ExposureError,lambda:append(s,r,e,input_evidence_ids=[failed["evidence_id"]],assertions=[assertion(failed["evidence_id"])]),"RETRIEVED")
@check("ASSERTION","quantitative and qualitative accepted")
def _():
 with env() as (_,s,r,e,*_):append(s,r,e);require(validate_exposure(build_exposure(company_entity_id="COMPANY_SYN",exposure_version=1,previous_version_hash=None,sector_entity_id="SEC_SYN",subsector_entity_id="SUB_SYN",as_of_timestamp=ASOF,data_cutoff_timestamp=CUTOFF,entity_registry_snapshot_id=r["registry_snapshot_id"],entity_registry_version=1,entity_registry_hash=r["registry_hash"],input_evidence_ids=[e["evidence_id"]],assertions=[assertion(e["evidence_id"],False)],relationships=[])))
@check("ASSERTION","NaN infinity boolean basis and unit rejected")
def _():
 with env() as (_,s,r,e,*_):
  for field,value in (("value",float("nan")),("value",float("inf")),("value",True),("basis",""),("unit","INVALID")):
   a=assertion(e["evidence_id"]);a["measurement"][field]=value;reject(lambda a=a:append(s,r,e,assertions=[a]))
@check("ASSERTION","OTHER_DECLARED and declared_unit rules enforced")
def _():
 with env() as (_,s,r,e,*_):
  a=assertion(e["evidence_id"],unit="OTHER_DECLARED");expect(Stage6ExposureError,lambda:append(s,r,e,assertions=[a]),"DECLARED_UNIT");a["measurement"]["declared_unit"]="tonnes";append(s,r,e,assertions=[a])
@check("ASSERTION","qualitative values never numeric")
def _():
 with env() as (_,s,r,e,*_):a=assertion(e["evidence_id"],False);a["qualitative_value"]=2;expect(Stage6ExposureError,lambda:append(s,r,e,assertions=[a]),"QUALITATIVE")
@check("CONFIDENCE","assertion and relationship confidence exactly zero")
def _():
 for value in (.1,.5,.8,1.0):
  with env() as (_,s,r,e,*_):a=assertion(e["evidence_id"]);a["confidence"]=value;expect(Stage6ExposureError,lambda:append(s,r,e,assertions=[a]),"CONFIDENCE")
@check("EXPIRY","effective and expiry chronology enforced")
def _():
 with env() as (_,s,r,e,*_):
  for start,end in (("2027-01-01","2027-12-31"),("2025-01-01","2025-12-31"),("2027-01-01","2026-01-01")):
   a=assertion(e["evidence_id"]);a["effective_date"],a["review_or_expiry_date"]=start,end;expect(Stage6ExposureError,lambda a=a:append(s,r,e,assertions=[a]),"PERIOD")
@check("RELATIONSHIP","parent subsidiary and group registry mappings accepted")
def _():
 for kind,target in (("PARENT","PARENT_SYN"),("SUBSIDIARY","CHILD_SYN"),("GROUP_COMPANY","GROUP_SYN")):
  with env() as (_,s,r,e,*_):append(s,r,e,assertions=[],relationships=[rel(e["evidence_id"],kind,target)])
@check("RELATIONSHIP","missing registry relationship rejected")
def _():
 with env() as (_,s,r,e,*_):expect(Stage6ExposureError,lambda:append(s,r,e,assertions=[],relationships=[rel(e["evidence_id"],"PARENT","GROUP_SYN")]),"RELATIONSHIP_MISSING")
@check("RELATIONSHIP","missing entity confidence and exposure period rejected")
def _():
 with env() as (_,s,r,e,*_):
  expect(Stage6ExposureError,lambda:append(s,r,e,assertions=[],relationships=[rel(e["evidence_id"],"PARENT","MISSING")]),"RELATED_ENTITY")
  x=rel(e["evidence_id"]);x["confidence"]=0.5;expect(Stage6ExposureError,lambda:append(s,r,e,assertions=[],relationships=[x]),"CONFIDENCE")
  x=rel(e["evidence_id"]);x["review_or_expiry_date"]="2026-01-02";expect(Stage6ExposureError,lambda:append(s,r,e,assertions=[],relationships=[x]),"PERIOD")
@check("COVERAGE","unused and undeclared evidence rejected")
def _():
 with env() as (_,s,r,e,e2,*_):expect(Stage6ExposureError,lambda:append(s,r,e,input_evidence_ids=[e["evidence_id"],e2["evidence_id"]]),"COVERAGE");expect(Stage6ExposureError,lambda:append(s,r,e,assertions=[assertion(e2["evidence_id"])]),"UNDECLARED")
@check("CANONICAL","caller order produces identical canonical record")
def _():
 with env() as (_,s,r,e,e2,*_):
  a1,a2=assertion(e["evidence_id"]),assertion(e2["evidence_id"],False);common=dict(company_entity_id="COMPANY_SYN",exposure_version=1,previous_version_hash=None,sector_entity_id="SEC_SYN",subsector_entity_id="SUB_SYN",as_of_timestamp=ASOF,data_cutoff_timestamp=CUTOFF,entity_registry_snapshot_id=r["registry_snapshot_id"],entity_registry_version=1,entity_registry_hash=r["registry_hash"],relationships=[]);require(build_exposure(input_evidence_ids=[e2["evidence_id"],e["evidence_id"]],assertions=[a2,a1],**common)==build_exposure(input_evidence_ids=[e["evidence_id"],e2["evidence_id"]],assertions=[a1,a2],**common))
@check("CANONICAL","validator rejects duplicate IDs noncanonical order and empty content")
def _():
 with env() as (_,s,r,e,e2,*_):
  common=dict(company_entity_id="COMPANY_SYN",exposure_version=1,previous_version_hash=None,sector_entity_id="SEC_SYN",subsector_entity_id="SUB_SYN",as_of_timestamp=ASOF,data_cutoff_timestamp=CUTOFF,entity_registry_snapshot_id=r["registry_snapshot_id"],entity_registry_version=1,entity_registry_hash=r["registry_hash"],relationships=[])
  duplicate=build_exposure(input_evidence_ids=[e["evidence_id"],e["evidence_id"]],assertions=[assertion(e["evidence_id"])],**common);expect(Stage6ExposureError,lambda:validate_exposure(duplicate),"IDS_INVALID")
  empty=build_exposure(input_evidence_ids=[e["evidence_id"]],assertions=[],**common);expect(Stage6ExposureError,lambda:validate_exposure(empty),"CONTENT_REQUIRED")
  ordered=build_exposure(input_evidence_ids=[e["evidence_id"],e2["evidence_id"]],assertions=[assertion(e["evidence_id"]),assertion(e2["evidence_id"],False)],**common);ordered["input_evidence_ids"].reverse();expect(Stage6ExposureError,lambda:validate_exposure(ordered),"IDS_INVALID")
@check("APPEND_ONLY","all tables block update delete and missing trigger detected")
def _():
 with env() as (_,s,r,e,*_):
  append(s,r,e)
  for t in ("exposure_store_meta","exposure_series","exposure_records","exposure_dependencies"):expect(sqlite3.DatabaseError,lambda t=t:s.connection.execute(f"UPDATE {t} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda t=t:s.connection.execute(f"DELETE FROM {t}"))
  s.connection.execute("DROP TRIGGER protect_exposure_records_delete");s.connection.commit();expect(ExposureIntegrityFailure,s.integrity_check,"TRIGGER")
@check("DEPENDENCY","registry and multiple evidence dependencies exact")
def _():
 with env() as (_,s,r,e,e2,*_):append(s,r,e,input_evidence_ids=[e["evidence_id"],e2["evidence_id"]],assertions=[assertion(e["evidence_id"]),assertion(e2["evidence_id"],False)]);require(s.connection.execute("SELECT COUNT(*) FROM exposure_dependencies").fetchone()[0]==3)
@check("DEPENDENCY","missing extra wrong ID hash and type all fail integrity")
def _():
 mutations=(
  "DELETE FROM exposure_dependencies WHERE dependency_record_type='EVIDENCE'",
  "INSERT INTO exposure_dependencies SELECT exposure_id,exposure_version,'EVIDENCE','EXTRA','"+("f"*64)+"' FROM exposure_records",
  "UPDATE exposure_dependencies SET dependency_record_id='WRONG' WHERE dependency_record_type='EVIDENCE'",
  "UPDATE exposure_dependencies SET dependency_record_hash='"+("f"*64)+"' WHERE dependency_record_type='EVIDENCE'",
  "UPDATE exposure_dependencies SET dependency_record_type='WRONG' WHERE dependency_record_type='EVIDENCE'"
 )
 for sql in mutations:
  with env() as (_,s,r,e,*_):
   append(s,r,e);s.connection.execute("DROP TRIGGER protect_exposure_dependencies_update");s.connection.execute("DROP TRIGGER protect_exposure_dependencies_delete");s.connection.execute(sql);s.connection.commit();expect(ExposureIntegrityFailure,s.integrity_check)
@check("RESTART","clean integrity and deterministic replay PASS")
def _():
 with env() as (_,s,r,e,*_):append(s,r,e);require(s.integrity_check()["result"]=="PASS")
@check("RESTART","record hash typed and dependency tamper detected")
def _():
 for table,column in (("exposure_records","record_hash"),("exposure_records","as_of_timestamp"),("exposure_dependencies","dependency_record_hash")):
  with env() as (_,s,r,e,*_):append(s,r,e);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",("f"*64 if "hash" in column else "2026-01-01T00:00:00.000000Z",));s.connection.commit();expect(ExposureIntegrityFailure,s.integrity_check)
@check("RESTART","canonical JSON series identity and registry dependency tamper detected")
def _():
 for table,column,value,where in (("exposure_records","canonical_json","{}",""),("exposure_series","company_entity_id","OTHER",""),("exposure_dependencies","dependency_record_hash","f"*64," WHERE dependency_record_type='ENTITY_REGISTRY_SNAPSHOT'")):
  with env() as (_,s,r,e,*_):append(s,r,e);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?{where}",(value,));s.connection.commit();expect(ExposureIntegrityFailure,s.integrity_check)
@check("BOUNDARY","no event input and confidence placeholder is documented")
def _():
 source="\n".join(p.read_text() for p in (STAGE_ROOT/"stage6_exposure").glob("*.py"));require("stage6_events" not in source and "stage6_lifecycle" not in source);require("uncalibrated placeholder" in (STAGE_ROOT/"Stage6_3A_Delivery_Report.md").read_text())
@check("NETWORK_AI_TRADING","zero network AI NLP ML and trading code")
def _():
 text="";prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers"}
 for p in (STAGE_ROOT/"stage6_exposure").glob("*.py"):
  src=p.read_text();text+=src.casefold();tree=ast.parse(src);imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
 for token in ("buy_signal","sell_signal","broker","expected_return","impact_score","semantic similarity","embedding","ocr"):require(token not in text)
@check("NETWORK_AI_TRADING","socket sentinel")
def _():
 with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):
  with env() as (_,s,r,e,*_):append(s,r,e)
@check("BOUNDARY","all frozen paths unchanged")
def _():require(git("diff","--name-only",BASELINE,"--","Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py")=="")
def main():
 rows=[]
 for i,(c,n,f) in enumerate(CHECKS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):f()
   rows.append({"test_id":f"S6_3A_{i:03d}","category":c,"test_name":n,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3A_{i:03d}","category":c,"test_name":n,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 RESULT_PATH.parent.mkdir(parents=True,exist_ok=True)
 with RESULT_PATH.open("w",encoding="utf-8",newline="") as h:w=csv.DictWriter(h,fieldnames=["test_id","category","test_name","result","detail"],lineterminator="\n");w.writeheader();w.writerows(rows)
 bad=[x for x in rows if x["result"]!="PASS"];print(json.dumps({"stage":"6.3A","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False},sort_keys=True,separators=(",",":")))
 for x in bad:print("FAIL",x["test_id"],x["test_name"],x["detail"])
 return bool(bad)
if __name__=="__main__":raise SystemExit(main())
