"""Stage 6.2E controlled Event V2 evolution acceptance tests."""
from __future__ import annotations

import ast, csv, json, socket, sqlite3, subprocess, sys, tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock

STAGE_ROOT=Path(__file__).resolve().parents[1]; REPO_ROOT=STAGE_ROOT.parent
sys.path.insert(0,str(STAGE_ROOT))

from stage6_candidates import CandidateStore
from stage6_connectors.live_registries import (RBI_ENTITY_ID,RBI_SOURCE_ID,SEBI_ENTITY_ID,SEBI_SOURCE_ID,build_multisource_registries)
from stage6_events import EventStore
from stage6_extraction import ExtractionStore
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_ingestion.evidence_store import IngestionStore
from stage6_materialization import MaterializationStore
from stage6_evolution import (AUTHORITY,DIRECTIVE_SCHEMA_VERSION,EVOLUTION_SCHEMA_VERSION,EVOLVER_VERSION,
    POLICY_ID,POLICY_VERSION,EvolutionConflict,EvolutionIntegrityFailure,EvolutionStore,Stage6EvolutionError,
    build_directive,directive_identity,load_policy,validate_directive,validate_policy)
from stage6_evolution.evolution_mapper import build_event_v2,build_evolution_record

RESULT_PATH=STAGE_ROOT/"results"/"stage6_2e_test_results.csv"
BASELINE_2D_TAG="stage6-2d-candidate-event-materialization-baseline"; BASELINE_2D_COMMIT="117208546dd9b02c288ddd34d712761d73ea2b79"
BASELINE_2C_TAG="stage6-2c-event-candidate-classification-baseline"; BASELINE_2B_TAG="stage6-2b-rss-item-extraction-baseline"
BASELINE_2A_TAG="stage6-2a-event-intelligence-foundation-baseline"; BASELINE_1C_TAG="stage6-1c-multisource-rss-ingestion-baseline"
ARCHITECTURE_TAG="stage6-decision-intelligence-architecture-baseline-v2"; PRODUCTION_TAG="stage5d5-live-paper-runner-baseline"
EXTRACTION_CUTOFF="2026-09-26T08:00:01.000000Z"; MATERIALIZATION_CUTOFF="2026-09-26T08:30:00.000000Z"
SAME_TIME="2026-09-26T09:00:00.000000Z"; CROSS_TIME="2026-09-26T09:01:00.000000Z"; LATER_CUTOFF="2026-09-26T10:00:00.000000Z"
POLICY,POLICY_JSON,POLICY_HASH=load_policy(); CHECKS=[]

def check(category,name):
    def register(function): CHECKS.append((category,name,function)); return function
    return register
def require(value,message="assertion failed"):
    if not value: raise AssertionError(message)
def expect(error,function,contains=None):
    try: function()
    except error as exc:
        if contains: require(contains in str(exc),f"expected {contains!r} in {exc!r}")
        return exc
    raise AssertionError(f"expected {error.__name__}")
def git(*args): return subprocess.check_output(["git",*args],cwd=REPO_ROOT,text=True).strip()

def capture(store,registries,source,key,retrieved,status="RETRIEVED",payload=b"synthetic evidence"):
    entity=RBI_ENTITY_ID if source==RBI_SOURCE_ID else SEBI_ENTITY_ID
    return store.capture_evidence(idempotency_key=key,source_registry_snapshot_id=registries["source_v2"]["registry_snapshot_id"],
        entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"],source_id=source,
        source_reference="fixture://stage6-2e/"+key,raw_payload=payload,content_type="text/plain",
        publication_timestamp_utc="2026-09-20T00:00:00Z",observed_timestamp_utc=retrieved,
        retrieved_timestamp_utc=retrieved,entity_ids=[entity],retrieval_status=status)["record"]

@contextmanager
def fresh_environment():
    with tempfile.TemporaryDirectory(prefix="stage6_2e_test_") as folder:
        root=Path(folder); registries=build_multisource_registries(); ingestion=IngestionStore(root/"ingestion.sqlite3",root/"raw")
        for name in ("entity_v1","source_v1","entity_v2","source_v2"): ingestion.import_registry(registries[name])
        base=store_capture_feed(ingestion,registries)
        extraction=ExtractionStore(root/"extraction.sqlite3",ingestion)
        extraction_batch=extraction.extract(parent_evidence_id=base["evidence_id"],extraction_cutoff=EXTRACTION_CUTOFF)["batch_id"]
        candidates=CandidateStore(root/"candidates.sqlite3",extraction)
        classification_batch=candidates.classify_batch(extraction_batch_id=extraction_batch,classification_cutoff=EXTRACTION_CUTOFF)["classification_batch_id"]
        events=EventStore(root/"events.sqlite3",ingestion); materializations=MaterializationStore(root/"materializations.sqlite3",candidates,events)
        result=materializations.materialize_batch(classification_batch_id=classification_batch,materialization_cutoff=MATERIALIZATION_CUTOFF)
        matched=next(record for record in result["records"] if record["decision_status"]=="MATERIALIZED")
        same=capture(ingestion,registries,RBI_SOURCE_ID,"same-support",SAME_TIME)
        cross=capture(ingestion,registries,SEBI_SOURCE_ID,"cross-support",CROSS_TIME)
        evolution=EvolutionStore(root/"evolution.sqlite3",candidates,materializations,events)
        context={"registries":registries,"base":base,"same":same,"cross":cross,"target_event_id":matched["event_id"],
                 "materialization":matched,"classification_batch":classification_batch}
        try: yield ingestion,extraction,candidates,events,materializations,evolution,context,root
        finally:
            for store in (evolution,materializations,events,candidates,extraction,ingestion):
                try: store.close()
                except sqlite3.Error: pass

def store_capture_feed(store,registries):
    payload=b"<rss><channel><item><title>Repo rate raised</title><guid>base-hike</guid></item><item><title>Annual report</title><guid>no-match</guid></item></channel></rss>"
    entity=RBI_ENTITY_ID
    return store.capture_evidence(idempotency_key="base-feed",source_registry_snapshot_id=registries["source_v2"]["registry_snapshot_id"],
        entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"],source_id=RBI_SOURCE_ID,
        source_reference="fixture://stage6-2e/base",raw_payload=payload,content_type="application/rss+xml",
        publication_timestamp_utc=None,observed_timestamp_utc="2026-09-26T08:00:00Z",retrieved_timestamp_utc="2026-09-26T08:00:01Z",entity_ids=[entity])["record"]

def evolve(store,ctx,evidence=None,directive="ADD_SUPPORT",cutoff=LATER_CUTOFF,conflicts=None,description=None):
    evidence=evidence or ctx["same"]
    return store.evolve_event(directive_type=directive,target_event_id=ctx["target_event_id"],
        additional_evidence_ids=[evidence["evidence_id"]],evolution_cutoff=cutoff,
        conflict_evidence_ids=conflicts,conflict_description=description)

def restore_trigger(store,table,operation):
    store.connection.executescript(f"CREATE TRIGGER protect_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_{operation}'); END;")

@check("BASELINE","Stage 6.2D tag exact ancestor")
def _():
    require(git("rev-parse",f"{BASELINE_2D_TAG}^{{}}") == BASELINE_2D_COMMIT)
    subprocess.check_call(["git","merge-base","--is-ancestor",BASELINE_2D_COMMIT,"HEAD"],cwd=REPO_ROOT)
@check("BASELINE","authority SHADOW_ONLY")
def _(): require(AUTHORITY=="SHADOW_ONLY")

@check("POLICY","valid policy and deterministic hash")
def _(): require(validate_policy(deepcopy(POLICY))==POLICY and canonical_hash(POLICY)==POLICY_HASH)
@check("POLICY","wrong identity and directives rejected")
def _():
    for field,value in (("schema_version","X"),("policy_id","X"),("policy_version",2),("evolver_version","X"),("supported_directives",["ADD_SUPPORT"])):
        bad=deepcopy(POLICY); bad[field]=value; expect(Stage6EvolutionError,lambda b=bad:validate_policy(b),"POLICY")
@check("POLICY","wrong authority and description limit rejected")
def _():
    for field,value in (("trustworthy_authorities",["PRIMARY_OFFICIAL"]),("maximum_conflict_description_characters",999)):
        bad=deepcopy(POLICY); bad[field]=value; expect(Stage6EvolutionError,lambda b=bad:validate_policy(b),"POLICY")

@check("V1_ANCHOR","valid materialized V1 accepted")
def _():
    with fresh_environment() as (*_,store,ctx,root): require(store._validate_v1_anchor(ctx["target_event_id"])[0]["event_version"]==1)
@check("V1_ANCHOR","non-6.2D event rejected")
def _():
    with fresh_environment() as (ingestion,_,_,events,_,store,ctx,_):
        source=ctx["base"]; defaults={"event_status":"CANDIDATE","direction":"UNKNOWN","severity":"UNKNOWN","materiality":"UNKNOWN","confidence":0.0,"entities":[],"sectors":[],"geographies":[],"commodities":[],"currencies":[],"corroboration_status":"SINGLE_SOURCE_OFFICIAL","event_horizon":"UNKNOWN","transmission_channels":[],"causality_assessment":"NO_SUPPORTED_CAUSE_FOUND","evidence_conflicts":[]}
        result=events.append_event(event_key="unrelated",event_version=1,previous_event_version_hash=None,source_evidence_ids=[source["evidence_id"]],entity_resolution_version=source["entity_registry_snapshot_id"],event_type="RATE_HIKE",first_known_timestamp=source["retrieved_timestamp_utc"],last_updated_timestamp=MATERIALIZATION_CUTOFF,**defaults)
        expect(Stage6EvolutionError,lambda:store._validate_v1_anchor(result["event"]["event_id"]),"NOT_STAGE6_2D")
@check("V1_ANCHOR","missing materialization rejected")
def _():
    with fresh_environment() as (*prefix,mat,store,ctx,root):
        for table in ("materialization_dependencies","batch_materializations","materialization_records"):
            mat.connection.execute(f"DROP TRIGGER protect_{table}_delete"); mat.connection.execute(f"DELETE FROM {table}")
        mat.connection.commit(); expect(EvolutionIntegrityFailure,lambda:store._validate_v1_anchor(ctx["target_event_id"]),"ANCHOR_MISSING")
@check("V1_ANCHOR","wrong materialization hash rejected")
def _():
    with fresh_environment() as (*prefix,mat,store,ctx,root):
        mat.connection.execute("DROP TRIGGER protect_materialization_records_update"); mat.connection.execute("UPDATE materialization_records SET record_hash=? WHERE event_id=?",("f"*64,ctx["target_event_id"])); mat.connection.commit()
        expect(Exception,lambda:store._validate_v1_anchor(ctx["target_event_id"]))

@check("DIRECTIVE","ADD_SUPPORT valid")
def _():
    with fresh_environment() as (*_,store,ctx,root): require(evolve(store,ctx)["directive"]["directive_type"]=="ADD_SUPPORT")
@check("DIRECTIVE","OPEN_CONFLICT valid")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        conflicts=sorted([ctx["base"]["evidence_id"],ctx["cross"]["evidence_id"]]); require(evolve(store,ctx,ctx["cross"],"OPEN_CONFLICT",conflicts=conflicts,description="Explicit synthetic disagreement.")["directive"]["directive_type"]=="OPEN_CONFLICT")
@check("DIRECTIVE","unknown directive rejected")
def _():
    with fresh_environment() as (*_,store,ctx,root): expect(Stage6EvolutionError,lambda:evolve(store,ctx,directive="MERGE_EVENTS"),"IDENTITY_FIELDS")
@check("DIRECTIVE","random target rejected")
def _():
    with fresh_environment() as (*_,store,ctx,root): expect(Stage6EvolutionError,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id="RANDOM",additional_evidence_ids=[ctx["same"]["evidence_id"]],evolution_cutoff=LATER_CUTOFF),"NOT_FOUND")
@check("DIRECTIVE","empty and duplicate additional evidence rejected")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        expect(Stage6EvolutionError,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=[],evolution_cutoff=LATER_CUTOFF),"IDS_INVALID")
        expect(Stage6EvolutionError,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=[ctx["same"]["evidence_id"]]*2,evolution_cutoff=LATER_CUTOFF),"IDS_INVALID")
@check("DIRECTIVE","existing V1 evidence alone is not new support")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        expect(Stage6EvolutionError,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=[ctx["base"]["evidence_id"]],evolution_cutoff=LATER_CUTOFF),"NEW_EVIDENCE")
@check("DIRECTIVE","wrong base version and hash rejected")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        v1,mat,_=store._validate_v1_anchor(ctx["target_event_id"]); directive=build_directive(directive_type="ADD_SUPPORT",target_event_id=v1["event_id"],base_event=v1,materialization=mat,additional_evidence_ids=[ctx["same"]["evidence_id"]],conflict_evidence_ids=[],conflict_description=None,evolution_cutoff=LATER_CUTOFF,policy=POLICY,policy_hash=POLICY_HASH)
        bad=deepcopy(directive); bad["base_event_version"]=2; expect(Stage6EvolutionError,lambda:validate_directive(bad,v1,mat),"ANCHOR_BINDING")
        bad=deepcopy(directive); bad["base_event_hash"]="f"*64; expect(Stage6EvolutionError,lambda:validate_directive(bad,v1,mat),"ANCHOR_BINDING")

@check("ADD_SUPPORT","V1 to V2 mapping exact")
def _():
    with fresh_environment() as (_,_,_,events,_,store,ctx,_):
        v1=events.get_event(ctx["target_event_id"],1); result=evolve(store,ctx); v2=result["event"]
        require(v2["event_id"]==v1["event_id"] and v2["event_version"]==2 and v2["previous_event_version_hash"]==v1["record_hash"])
        require(v2["event_type"]==v1["event_type"] and v2["event_status"]=="CANDIDATE")
        require(v2["source_evidence_ids"]==sorted([ctx["base"]["evidence_id"],ctx["same"]["evidence_id"]]))
@check("SAME_SOURCE","same-source duplicate is not corroborated")
def _():
    with fresh_environment() as (*_,store,ctx,root): require(evolve(store,ctx)["event"]["corroboration_status"]=="SINGLE_SOURCE_OFFICIAL")
@check("MULTI_SOURCE","distinct trustworthy sources are corroborated")
def _():
    with fresh_environment() as (*_,store,ctx,root): require(evolve(store,ctx,ctx["cross"])["event"]["corroboration_status"]=="CORROBORATED")
@check("MULTI_SOURCE","multiple added evidence dependencies are supported")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        result=store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=sorted([ctx["same"]["evidence_id"],ctx["cross"]["evidence_id"]]),evolution_cutoff=LATER_CUTOFF)
        deps=list(store.connection.execute("SELECT * FROM directive_dependencies WHERE directive_id=? AND dependency_record_type='EVIDENCE'",(result["directive"]["directive_id"],)))
        require(len(deps)==2 and result["event"]["corroboration_status"]=="CORROBORATED")
@check("CONFLICT","explicit conflict mapping exact")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        ids=sorted([ctx["base"]["evidence_id"],ctx["cross"]["evidence_id"]]); event=evolve(store,ctx,ctx["cross"],"OPEN_CONFLICT",conflicts=ids,description="Exact explicit conflict.")["event"]
        require((event["event_status"],event["corroboration_status"])==("CONFLICTED","CONFLICTING_EVIDENCE"))
        require(event["evidence_conflicts"]==[{"evidence_ids":ids,"description":"Exact explicit conflict.","status":"OPEN"}])
@check("CONFLICT_VALIDATION","invalid conflict IDs and descriptions rejected")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        base=ctx["base"]["evidence_id"]; new=ctx["cross"]["evidence_id"]
        for ids,description in (([new],"x"),([base,"MISSING"],"x"),([base,new],""),([base,new],"x"*1001)):
            expect(Stage6EvolutionError,lambda i=ids,d=description:evolve(store,ctx,ctx["cross"],"OPEN_CONFLICT",conflicts=i,description=d))

@check("CONSERVATIVE_FIELDS","V2 preserves all conservative V1 fields")
def _():
    with fresh_environment() as (_,_,_,events,_,store,ctx,_):
        v1=events.get_event(ctx["target_event_id"],1); v2=evolve(store,ctx)["event"]
        for field in ("event_type","direction","severity","materiality","confidence","entities","sectors","geographies","commodities","currencies","entity_resolution_version","event_horizon","transmission_channels","causality_assessment"): require(v2[field]==v1[field],field)
@check("FIRST_KNOWN","V2 first-known remains V1 first-known")
def _():
    with fresh_environment() as (_,_,_,events,_,store,ctx,_): require(evolve(store,ctx)["event"]["first_known_timestamp"]==events.get_event(ctx["target_event_id"],1)["first_known_timestamp"])
@check("PIT","cutoff equal latest retrieval and later cutoff accepted")
def _():
    with fresh_environment() as (*_,store,ctx,root): require(evolve(store,ctx,cutoff=SAME_TIME)["event"]["last_updated_timestamp"]==SAME_TIME)
    with fresh_environment() as (*_,store,ctx,root): require(evolve(store,ctx,cutoff=LATER_CUTOFF)["event"]["last_updated_timestamp"]==LATER_CUTOFF)
@check("PIT","future evidence and cutoff before V1 rejected")
def _():
    with fresh_environment() as (*_,store,ctx,root): expect(Stage6EvolutionError,lambda:evolve(store,ctx,cutoff="2026-09-26T08:59:59Z"),"FUTURE_EVIDENCE")
    with fresh_environment() as (*_,store,ctx,root): expect(Stage6EvolutionError,lambda:evolve(store,ctx,cutoff="2026-09-26T08:00:00Z"),"CUTOFF")

@check("EVIDENCE","missing evidence rejected")
def _():
    with fresh_environment() as (*_,store,ctx,root): expect(Exception,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=["MISSING"],evolution_cutoff=LATER_CUTOFF))
@check("EVIDENCE","acquisition attempt rejected")
def _():
    with fresh_environment() as (ingestion,_,_,_,_,store,ctx,_):
        r=ctx["registries"]; attempt=ingestion.capture_acquisition_failure(idempotency_key="fail",source_registry_snapshot_id=r["source_v2"]["registry_snapshot_id"],entity_registry_snapshot_id=r["entity_v2"]["registry_snapshot_id"],source_id=RBI_SOURCE_ID,source_reference="fixture://fail",retrieval_status="NOT_FOUND",failure_reason="synthetic",failure_stage="fixture",attempted_at_utc=SAME_TIME)["record"]
        expect(Exception,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=[attempt["evidence_id"]],evolution_cutoff=LATER_CUTOFF))
@check("EVIDENCE","partial and quarantined evidence rejected")
def _():
    for status in ("PARTIAL","QUARANTINED"):
        with fresh_environment() as (ingestion,_,_,_,_,store,ctx,_):
            bad=capture(ingestion,ctx["registries"],RBI_SOURCE_ID,"bad-"+status,SAME_TIME,status)
            expect(Exception,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=[bad["evidence_id"]],evolution_cutoff=LATER_CUTOFF))

@check("VERSIONING","V1 preserved byte-for-byte and only V2 appended")
def _():
    with fresh_environment() as (_,_,_,events,_,store,ctx,_):
        before=events.connection.execute("SELECT canonical_json FROM event_records WHERE event_id=? AND event_version=1",(ctx["target_event_id"],)).fetchone()[0]
        evolve(store,ctx); after=events.connection.execute("SELECT canonical_json FROM event_records WHERE event_id=? AND event_version=1",(ctx["target_event_id"],)).fetchone()[0]
        versions=[r[0] for r in events.connection.execute("SELECT event_version FROM event_records WHERE event_id=? ORDER BY event_version",(ctx["target_event_id"],))]
        require(before==after and versions==[1,2])
@check("VERSIONING","exact rerun idempotent")
def _():
    with fresh_environment() as (*_,store,ctx,root): evolve(store,ctx); require(evolve(store,ctx)["status"]=="IDEMPOTENT_SUCCESS")
@check("VERSIONING","second distinct evolution rejected and no V3 API")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        evolve(store,ctx); expect(EvolutionConflict,lambda:evolve(store,ctx,ctx["cross"]),"DIFFERENT_V2")
        expect(TypeError,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=[ctx["same"]["evidence_id"]],evolution_cutoff=LATER_CUTOFF,event_version=3))
@check("EVENT_TYPE","evolution API cannot request an event-type change")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        expect(TypeError,lambda:store.evolve_event(directive_type="ADD_SUPPORT",target_event_id=ctx["target_event_id"],additional_evidence_ids=[ctx["same"]["evidence_id"]],evolution_cutoff=LATER_CUTOFF,event_type="RATE_CUT"))

@check("DIRECTIVE_IDENTITY","directive identity deterministic and sensitive")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        v1,mat,_=store._validate_v1_anchor(ctx["target_event_id"])
        def make(evidence,cutoff=LATER_CUTOFF,desc=None,kind="ADD_SUPPORT",conflicts=[]): return build_directive(directive_type=kind,target_event_id=v1["event_id"],base_event=v1,materialization=mat,additional_evidence_ids=[evidence],conflict_evidence_ids=conflicts,conflict_description=desc,evolution_cutoff=cutoff,policy=POLICY,policy_hash=POLICY_HASH)
        one=make(ctx["same"]["evidence_id"]); require(one["directive_id"]==make(ctx["same"]["evidence_id"])["directive_id"])
        require(one["directive_id"]!=make(ctx["cross"]["evidence_id"])["directive_id"])
        require(one["directive_id"]!=make(ctx["same"]["evidence_id"],SAME_TIME)["directive_id"])
        ids=sorted([ctx["base"]["evidence_id"],ctx["cross"]["evidence_id"]]); require(make(ctx["cross"]["evidence_id"],desc="A",kind="OPEN_CONFLICT",conflicts=ids)["directive_id"]!=make(ctx["cross"]["evidence_id"],desc="B",kind="OPEN_CONFLICT",conflicts=ids)["directive_id"])

@check("DEPENDENCY","directive and evolution dependencies exact with multiple evidence support")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        result=evolve(store,ctx,ctx["cross"]); directive=result["directive"]; record=result["evolution"]
        ddeps=list(store.connection.execute("SELECT * FROM directive_dependencies WHERE directive_id=?",(directive["directive_id"],)))
        edeps=list(store.connection.execute("SELECT * FROM evolution_dependencies WHERE evolution_id=?",(record["evolution_id"],)))
        require({r["dependency_record_type"] for r in ddeps}=={"BASE_STAGE6_EVENT","STAGE6_2D_MATERIALIZATION","EVOLUTION_POLICY","EVIDENCE"})
        require({r["dependency_record_type"] for r in edeps}=={"EVOLUTION_DIRECTIVE","BASE_STAGE6_EVENT","STAGE6_2D_MATERIALIZATION","EVOLUTION_POLICY","RESULT_STAGE6_EVENT","EVIDENCE"})
@check("IMMUTABILITY","all evolution tables block update and delete")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        evolve(store,ctx)
        for table in ("evolution_store_meta","evolution_policies","evolution_directives","directive_dependencies","evolution_records","evolution_dependencies"):
            expect(sqlite3.DatabaseError,lambda t=table:store.connection.execute(f"UPDATE {t} SET rowid=rowid"),"IMMUTABLE_TABLE_UPDATE")
            expect(sqlite3.DatabaseError,lambda t=table:store.connection.execute(f"DELETE FROM {t}"),"IMMUTABLE_TABLE_DELETE")
@check("IMMUTABILITY","trigger removal detected")
def _():
    with fresh_environment() as (*_,store,ctx,root): evolve(store,ctx); store.connection.execute("DROP TRIGGER protect_evolution_records_delete"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check,"TRIGGER_MISSING")

@check("RECOVERY","orphan V2 detected and same directive retry repairs")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        v1,mat,_=store._validate_v1_anchor(ctx["target_event_id"]); directive=build_directive(directive_type="ADD_SUPPORT",target_event_id=v1["event_id"],base_event=v1,materialization=mat,additional_evidence_ids=[ctx["same"]["evidence_id"]],conflict_evidence_ids=[],conflict_description=None,evolution_cutoff=LATER_CUTOFF,policy=POLICY,policy_hash=POLICY_HASH)
        all_ev=store._evidence(sorted([ctx["base"]["evidence_id"],ctx["same"]["evidence_id"]]),LATER_CUTOFF); expected=build_event_v2(event_key=store._event_key(v1["event_id"]),base_event=v1,directive=directive,evidence=all_ev)
        store.event_store.append_event(event_key=store._event_key(v1["event_id"]),event_version=2,previous_event_version_hash=v1["record_hash"],source_evidence_ids=expected["source_evidence_ids"],entity_resolution_version=v1["entity_resolution_version"],event_type=v1["event_type"],event_status=expected["event_status"],direction=v1["direction"],severity=v1["severity"],materiality=v1["materiality"],confidence=v1["confidence"],entities=v1["entities"],sectors=v1["sectors"],geographies=v1["geographies"],commodities=v1["commodities"],currencies=v1["currencies"],corroboration_status=expected["corroboration_status"],first_known_timestamp=v1["first_known_timestamp"],last_updated_timestamp=LATER_CUTOFF,event_horizon=v1["event_horizon"],transmission_channels=v1["transmission_channels"],causality_assessment=v1["causality_assessment"],evidence_conflicts=[])
        expect(EvolutionIntegrityFailure,store.integrity_check,"ORPHAN_STAGE6_2E_EVENT_V2")
        require(evolve(store,ctx)["status"]=="CREATED" and store.integrity_check()["result"]=="PASS")

@check("RESTART_INTEGRITY","clean restart integrity passes")
def _():
    with fresh_environment() as (*_,store,ctx,root): evolve(store,ctx); require(store.integrity_check()["result"]=="PASS")
@check("RESTART_INTEGRITY","policy tamper detected")
def _():
    with fresh_environment() as (*_,store,ctx,root): evolve(store,ctx); store.connection.execute("DROP TRIGGER protect_evolution_policies_update"); store.connection.execute("UPDATE evolution_policies SET policy_hash=?",("f"*64,)); restore_trigger(store,"evolution_policies","UPDATE"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check,"POLICY_SNAPSHOT")
@check("RESTART_INTEGRITY","directive hash and content tamper detected")
def _():
    with fresh_environment() as (*_,store,ctx,root): evolve(store,ctx); store.connection.execute("DROP TRIGGER protect_evolution_directives_update"); store.connection.execute("UPDATE evolution_directives SET record_hash=?",("f"*64,)); restore_trigger(store,"evolution_directives","UPDATE"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check)
    with fresh_environment() as (*_,store,ctx,root):
        evolve(store,ctx); row=store.connection.execute("SELECT * FROM evolution_directives LIMIT 1").fetchone(); directive=json.loads(row["canonical_json"]); directive["conflict_description"]="tampered"
        store.connection.execute("DROP TRIGGER protect_evolution_directives_update"); store.connection.execute("UPDATE evolution_directives SET canonical_json=? WHERE directive_id=?",(canonical_json(directive),row["directive_id"])); restore_trigger(store,"evolution_directives","UPDATE"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check)
@check("RESTART_INTEGRITY","evolution hash tamper detected")
def _():
    with fresh_environment() as (*_,store,ctx,root): evolve(store,ctx); store.connection.execute("DROP TRIGGER protect_evolution_records_update"); store.connection.execute("UPDATE evolution_records SET record_hash=?",("e"*64,)); restore_trigger(store,"evolution_records","UPDATE"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check)
@check("RESTART_INTEGRITY","dependency tamper and orphan evolution detected")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        evolve(store,ctx); store.connection.execute("DROP TRIGGER protect_evolution_dependencies_update"); store.connection.execute("UPDATE evolution_dependencies SET dependency_record_hash=? WHERE dependency_record_type='EVOLUTION_POLICY'",("1"*64,)); restore_trigger(store,"evolution_dependencies","UPDATE"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check,"DEPENDENCY_MISMATCH")
    with fresh_environment() as (*_,store,ctx,root):
        evolve(store,ctx); store.connection.execute("DROP TRIGGER protect_evolution_directives_delete"); store.connection.execute("PRAGMA foreign_keys=OFF"); store.connection.execute("DELETE FROM evolution_directives"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check)
@check("RESTART_INTEGRITY","missing and extra dependencies detected")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        evolve(store,ctx); store.connection.execute("DROP TRIGGER protect_evolution_dependencies_delete"); store.connection.execute("DELETE FROM evolution_dependencies WHERE dependency_record_type='EVOLUTION_POLICY'"); restore_trigger(store,"evolution_dependencies","DELETE"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check,"DEPENDENCY_MISMATCH")
    with fresh_environment() as (*_,store,ctx,root):
        result=evolve(store,ctx); store.connection.execute("INSERT INTO evolution_dependencies VALUES(?,?,?,?)",(result["evolution"]["evolution_id"],"EXTRA","EXTRA","2"*64)); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check,"DEPENDENCY_MISMATCH")
@check("RESTART_INTEGRITY","base and result event tamper detected transitively")
def _():
    for version in (1,2):
        with fresh_environment() as (*prefix,events,mat,store,ctx,root):
            evolve(store,ctx); events.connection.execute("DROP TRIGGER protect_event_records_update"); events.connection.execute("UPDATE event_records SET record_hash=? WHERE event_id=? AND event_version=?",(("3" if version==1 else "4")*64,ctx["target_event_id"],version)); events.connection.executescript("CREATE TRIGGER protect_event_records_update BEFORE UPDATE ON event_records BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_UPDATE'); END;"); events.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check,"UPSTREAM_EVENT")
@check("RESTART_INTEGRITY","evidence tamper detected transitively")
def _():
    with fresh_environment() as (ingestion,_,_,_,_,store,ctx,_):
        evolve(store,ctx); ingestion.connection.execute("DROP TRIGGER protect_ingestion_records_update"); ingestion.connection.execute("UPDATE ingestion_records SET record_hash=? WHERE record_id=?",("5"*64,ctx["same"]["evidence_id"])); ingestion.connection.executescript("CREATE TRIGGER protect_ingestion_records_update BEFORE UPDATE ON ingestion_records BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_UPDATE'); END;"); ingestion.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check)
@check("RESTART_INTEGRITY","evolution replay mismatch detected")
def _():
    with fresh_environment() as (*_,store,ctx,root):
        evolve(store,ctx); row=store.connection.execute("SELECT * FROM evolution_records LIMIT 1").fetchone(); record=json.loads(row["canonical_json"]); record["evolution_cutoff"]="2026-09-26T09:30:00.000000Z"; record["record_hash"]=canonical_hash(without(record,"record_hash"))
        store.connection.execute("DROP TRIGGER protect_evolution_records_update"); store.connection.execute("UPDATE evolution_records SET canonical_json=?,record_hash=? WHERE evolution_id=?",(canonical_json(record),record["record_hash"],row["evolution_id"])); restore_trigger(store,"evolution_records","UPDATE"); store.connection.commit(); expect(EvolutionIntegrityFailure,store.integrity_check)

@check("BOUNDARY","frozen materialization V1 remains unchanged while evolution validator passes")
def _():
    with fresh_environment() as (_,_,_,events,_,store,ctx,_):
        before=events.connection.execute("SELECT canonical_json FROM event_records WHERE event_id=? AND event_version=1",(ctx["target_event_id"],)).fetchone()[0]; evolve(store,ctx); after=events.connection.execute("SELECT canonical_json FROM event_records WHERE event_id=? AND event_version=1",(ctx["target_event_id"],)).fetchone()[0]; require(before==after and store.integrity_check()["result"]=="PASS")
@check("NETWORK_AI_TRADING","zero network AI ML text interpretation and trading code")
def _():
    prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers"}; text=""
    for path in (STAGE_ROOT/"stage6_evolution").glob("*.py"):
        source=path.read_text(encoding="utf-8"); text+=source.casefold(); tree=ast.parse(source)
        imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        require(not imports.intersection(prohibited))
    for token in ("requests.get","openai","transformers","embedding","semantic similarity","sentiment model","buy_signal","sell_signal","broker_order","position_size"): require(token not in text)
@check("NETWORK_AI_TRADING","socket sentinel proves zero network")
def _():
    with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK_USED")):
        with fresh_environment() as (*_,store,ctx,root): evolve(store,ctx)
@check("BASELINE","all frozen paths unchanged")
def _():
    arch=["Stage 6/Stage6_Master_Architecture.md","Stage 6/contracts","Stage 6/policy","Stage 6/scripts/validate_stage6_0.py","Stage 6/results/stage6_0_architecture_contract.json"]
    require(git("diff","--name-only",ARCHITECTURE_TAG,"--",*arch)==""); require(git("diff","--name-only",BASELINE_1C_TAG,"--","Stage 6/stage6_ingestion","Stage 6/stage6_connectors")=="")
    frozen=((BASELINE_2A_TAG,["Stage 6/stage6_events","Stage 6/fixtures/stage6_2a","Stage 6/results/stage6_2a_contract.json","Stage 6/results/stage6_2a_test_results.csv","Stage 6/Stage6_2A_Delivery_Report.md"]),(BASELINE_2B_TAG,["Stage 6/stage6_extraction","Stage 6/fixtures/stage6_2b","Stage 6/results/stage6_2b_contract.json","Stage 6/results/stage6_2b_test_results.csv","Stage 6/Stage6_2B_Delivery_Report.md"]),(BASELINE_2C_TAG,["Stage 6/stage6_candidates","Stage 6/fixtures/stage6_2c","Stage 6/results/stage6_2c_contract.json","Stage 6/results/stage6_2c_test_results.csv","Stage 6/Stage6_2C_Delivery_Report.md"]),(BASELINE_2D_TAG,["Stage 6/stage6_materialization","Stage 6/fixtures/stage6_2d","Stage 6/results/stage6_2d_contract.json","Stage 6/results/stage6_2d_test_results.csv","Stage 6/Stage6_2D_Delivery_Report.md"]))
    for ref,paths in frozen: require(git("diff","--name-only",ref,"--",*paths)=="")
    require(git("diff","--name-only",PRODUCTION_TAG,"--","Stage 5D")=="")

def main():
    rows=[]
    for number,(category,name,function) in enumerate(CHECKS,1):
        try:
            with mock.patch.object(socket,"socket",side_effect=AssertionError("STAGE6_2E_NETWORK_USED")): function()
            rows.append({"test_id":f"S6_2E_{number:03d}","category":category,"test_name":name,"result":"PASS","detail":""})
        except Exception as exc: rows.append({"test_id":f"S6_2E_{number:03d}","category":category,"test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True,exist_ok=True)
    with RESULT_PATH.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=["test_id","category","test_name","result","detail"],lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    failed=[r for r in rows if r["result"]!="PASS"]
    print(json.dumps({"stage":"6.2E","tests":len(rows),"passed":len(rows)-len(failed),"failed":len(failed),"result":"PASS" if not failed else "FAIL","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False},sort_keys=True,separators=(",",":")))
    for row in failed: print("FAIL",row["test_id"],row["test_name"]+":",row["detail"])
    return 1 if failed else 0
if __name__=="__main__": raise SystemExit(main())
