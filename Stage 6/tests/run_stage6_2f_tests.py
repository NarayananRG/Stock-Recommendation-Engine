"""Stage 6.2F controlled lifecycle acceptance and adversarial tests."""
from __future__ import annotations

import ast, csv, importlib.util, json, socket, sqlite3, subprocess, sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock

STAGE_ROOT=Path(__file__).resolve().parents[1]; REPO_ROOT=STAGE_ROOT.parent
sys.path.insert(0,str(STAGE_ROOT))
spec=importlib.util.spec_from_file_location("stage6_2e_test_support",Path(__file__).with_name("run_stage6_2e_tests.py"))
base=importlib.util.module_from_spec(spec); spec.loader.exec_module(base)

from stage6_events import build_event
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_lifecycle import (AUTHORITY,DIRECTIVE_SCHEMA_VERSION,LIFECYCLE_SCHEMA_VERSION,PROCESSOR_VERSION,
    POLICY_ID,POLICY_VERSION,LifecycleConflict,LifecycleIntegrityFailure,LifecycleStore,Stage6LifecycleError,
    build_directive,directive_identity,lifecycle_identity,load_policy,validate_directive,validate_lifecycle,validate_policy)
from stage6_lifecycle.lifecycle_mapper import build_event_v3,build_lifecycle_record

RESULT_PATH=STAGE_ROOT/"results"/"stage6_2f_test_results.csv"
BASELINE_2E_TAG="stage6-2e-controlled-event-evolution-baseline"; BASELINE_2E_COMMIT="4fff221bbbf4125a7e32ac6ade1dd5269c871c5b"
ARCHITECTURE_TAG="stage6-decision-intelligence-architecture-baseline-v2"; PRODUCTION_TAG="stage5d5-live-paper-runner-baseline"
CUTOFF="2026-09-26T12:00:00.000000Z"; LINK_TIME="2026-09-26T11:00:00.000000Z"
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
def restore_trigger(store,table,operation):
    store.connection.executescript(f"CREATE TRIGGER protect_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TABLE_{operation}'); END;")

def linked(ingestion,ctx,key,target,relation="CORRECTION",source=None,time=LINK_TIME,status="RETRIEVED",both=False):
    old=json.loads(ingestion.connection.execute("SELECT canonical_json FROM ingestion_records WHERE record_id=?",(target,)).fetchone()[0])
    source=source or old["source_id"]; entity=base.RBI_ENTITY_ID if source==base.RBI_SOURCE_ID else base.SEBI_ENTITY_ID
    links={"correction_of_evidence_id":target} if relation=="CORRECTION" else {"retraction_of_evidence_id":target}
    if both: links={"correction_of_evidence_id":target,"retraction_of_evidence_id":target}
    return ingestion.capture_evidence(idempotency_key=key,source_registry_snapshot_id=ctx["registries"]["source_v2"]["registry_snapshot_id"],
        entity_registry_snapshot_id=ctx["registries"]["entity_v2"]["registry_snapshot_id"],source_id=source,
        source_reference="fixture://stage6-2f/"+key,raw_payload=("synthetic-"+key).encode(),content_type="text/plain",
        publication_timestamp_utc="2026-09-20T00:00:00Z",observed_timestamp_utc=time,retrieved_timestamp_utc=time,
        entity_ids=[entity],retrieval_status=status,**links)["record"]

@contextmanager
def environment(mode="same"):
    with base.fresh_environment() as (ing,ext,cand,events,mat,evo,ctx,root):
        if mode=="conflict":
            ids=sorted([ctx["base"]["evidence_id"],ctx["cross"]["evidence_id"]])
            base.evolve(evo,ctx,ctx["cross"],"OPEN_CONFLICT",conflicts=ids,description="Synthetic explicit conflict.")
        elif mode=="multi": base.evolve(evo,ctx,ctx["cross"])
        else: base.evolve(evo,ctx)
        life=LifecycleStore(root/"lifecycle.sqlite3",evo)
        try: yield ing,ext,cand,events,mat,evo,life,ctx,root
        finally:
            try: life.close()
            except sqlite3.Error: pass

def apply_correction(life,ing,ctx,target=None,key="correction"):
    target=target or ctx["same"]["evidence_id"]; item=linked(ing,ctx,key,target)
    return life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],
        lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[target],lifecycle_cutoff=CUTOFF)

def apply_retraction(life,ing,events,ctx):
    v2=events.get_event(ctx["target_event_id"],2); notices=[linked(ing,ctx,"retract-"+str(i),target,"RETRACTION") for i,target in enumerate(v2["source_evidence_ids"])]
    return life.apply_lifecycle(directive_type="RETRACT_EVENT",target_event_id=ctx["target_event_id"],
        lifecycle_evidence_ids=[item["evidence_id"] for item in notices],affected_evidence_ids=v2["source_evidence_ids"],lifecycle_cutoff=CUTOFF)

def resolve(life,ing,ctx,relation="RETRACTION"):
    target=ctx["cross"]["evidence_id"]; item=linked(ing,ctx,"resolve-"+relation.casefold(),target,relation)
    return life.apply_lifecycle(directive_type="RESOLVE_CONFLICT",target_event_id=ctx["target_event_id"],
        lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[target],lifecycle_cutoff=CUTOFF)

@check("BASELINE","6.2E tag exact ancestor")
def _(): require(git("rev-parse",f"{BASELINE_2E_TAG}^{{}}") == BASELINE_2E_COMMIT); subprocess.check_call(["git","merge-base","--is-ancestor",BASELINE_2E_COMMIT,"HEAD"],cwd=REPO_ROOT)
@check("BASELINE","authority SHADOW_ONLY")
def _(): require(AUTHORITY=="SHADOW_ONLY")
@check("POLICY","policy canonical identity and hash")
def _(): require(validate_policy(deepcopy(POLICY))==POLICY and canonical_hash(POLICY)==POLICY_HASH)
@check("POLICY","policy rejects identity changes")
def _():
    for field,value in (("policy_id","X"),("policy_version",2),("processor_version","X"),("authority","LIVE")):
        bad=deepcopy(POLICY);bad[field]=value;expect(Stage6LifecycleError,lambda b=bad:validate_policy(b),"POLICY")
@check("POLICY","supported directives exact")
def _(): require(POLICY["supported_directives"]==["APPLY_CORRECTION","RETRACT_EVENT","RESOLVE_CONFLICT"])

@check("ANCHOR","valid frozen V1 V2 anchor accepted")
def _():
    with environment() as (*_,life,ctx,root): require(life._validate_v2_anchor(ctx["target_event_id"])[1]["event_version"]==2)
@check("ANCHOR","missing evolution record rejected")
def _():
    with environment() as (*prefix,evo,life,ctx,root):
        evo.connection.execute("DROP TRIGGER protect_evolution_records_delete");evo.connection.execute("PRAGMA foreign_keys=OFF");evo.connection.execute("DELETE FROM evolution_records");evo.connection.commit();expect(LifecycleIntegrityFailure,lambda:life._validate_v2_anchor(ctx["target_event_id"]),"RECORD_MISSING")
@check("ANCHOR","non-6.2D event rejected")
def _():
    with environment() as (*_,life,ctx,root): expect(Exception,lambda:life._validate_v2_anchor("RANDOM"))
@check("ANCHOR","V2 predecessor tamper rejected")
def _():
    with environment() as (*prefix,events,mat,evo,life,ctx,root):
        events.connection.execute("DROP TRIGGER protect_event_records_update");events.connection.execute("UPDATE event_records SET previous_event_version_hash=? WHERE event_id=? AND event_version=2",("f"*64,ctx["target_event_id"]));events.connection.commit();expect(LifecycleIntegrityFailure,lambda:life._validate_v2_anchor(ctx["target_event_id"]),"TYPED_BINDING")
@check("ANCHOR","missing materialization rejected")
def _():
    with environment() as (*prefix,mat,evo,life,ctx,root):
        for table in ("materialization_dependencies","batch_materializations","materialization_records"):
            mat.connection.execute(f"DROP TRIGGER protect_{table}_delete");mat.connection.execute(f"DELETE FROM {table}")
        mat.connection.commit();expect(Exception,lambda:life._validate_v2_anchor(ctx["target_event_id"]),"ANCHOR")
@check("ANCHOR","V1 and V2 typed hash tampering rejected")
def _():
    for version in (1,2):
        with environment() as (*prefix,events,mat,evo,life,ctx,root):
            events.connection.execute("DROP TRIGGER protect_event_records_update");events.connection.execute("UPDATE event_records SET record_hash=? WHERE event_id=? AND event_version=?",(("d" if version==1 else "e")*64,ctx["target_event_id"],version));events.connection.commit();expect(LifecycleIntegrityFailure,lambda:life._validate_v2_anchor(ctx["target_event_id"]),"TYPED_BINDING")

@check("DIRECTIVE","APPLY_CORRECTION valid")
def _():
    with environment() as (ing,*_,life,ctx,root): require(apply_correction(life,ing,ctx)["directive"]["directive_type"]=="APPLY_CORRECTION")
@check("DIRECTIVE","RETRACT_EVENT valid")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root): require(apply_retraction(life,ing,events,ctx)["directive"]["directive_type"]=="RETRACT_EVENT")
@check("DIRECTIVE","RESOLVE_CONFLICT valid")
def _():
    with environment("conflict") as (ing,*_,life,ctx,root): require(resolve(life,ing,ctx)["directive"]["directive_type"]=="RESOLVE_CONFLICT")
@check("DIRECTIVE","unknown action rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        item=linked(ing,ctx,"unknown",ctx["same"]["evidence_id"]);expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="RECLASSIFY_EVENT",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF),"IDENTITY")
@check("DIRECTIVE","empty duplicate and cardinality-invalid IDs rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        target=ctx["same"]["evidence_id"];item=linked(ing,ctx,"ids",target)
        for lifecycle,affected in (([],[target]),([item["evidence_id"]]*2,[target]),([item["evidence_id"]],[target]*2),([item["evidence_id"]],[target,ctx["base"]["evidence_id"]])):
            expect(Stage6LifecycleError,lambda l=lifecycle,a=affected:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=l,affected_evidence_ids=a,lifecycle_cutoff=CUTOFF),"DIRECTIVE")
@check("DIRECTIVE","internally consistent wrong policy hash rejected")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        _v1,v2,materialization,evolution=life._validate_v2_anchor(ctx["target_event_id"]);item=linked(ing,ctx,"wrong-policy",ctx["same"]["evidence_id"])
        directive=build_directive(directive_type="APPLY_CORRECTION",base_event=v2,evolution=evolution,materialization=materialization,lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF,policy=POLICY,policy_hash=POLICY_HASH)
        directive["policy_hash"]="f"*64;directive["directive_id"]=directive_identity(directive);directive["record_hash"]=canonical_hash(without(directive,"record_hash"))
        expect(Stage6LifecycleError,lambda:validate_directive(directive,v2,evolution,materialization,expected_policy_hash=POLICY_HASH),"POLICY_HASH")
@check("DIRECTIVE","wrong base version and hash rejected")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        _v1,v2,materialization,evolution=life._validate_v2_anchor(ctx["target_event_id"]);item=linked(ing,ctx,"wrong-anchor",ctx["same"]["evidence_id"]);directive=build_directive(directive_type="APPLY_CORRECTION",base_event=v2,evolution=evolution,materialization=materialization,lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF,policy=POLICY,policy_hash=POLICY_HASH)
        for field,value in (("base_event_version",1),("base_event_hash","f"*64)):
            bad=deepcopy(directive);bad[field]=value;expect(Stage6LifecycleError,lambda b=bad:validate_directive(b,v2,evolution,materialization,expected_policy_hash=POLICY_HASH),"ANCHOR")

@check("CORRECTION","active evidence replaced and history preserved")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        before1=canonical_json(events.get_event(ctx["target_event_id"],1));before2=canonical_json(events.get_event(ctx["target_event_id"],2));result=apply_correction(life,ing,ctx);v3=result["event"]
        require(canonical_json(events.get_event(ctx["target_event_id"],1))==before1 and canonical_json(events.get_event(ctx["target_event_id"],2))==before2)
        require(ctx["same"]["evidence_id"] not in v3["source_evidence_ids"] and v3["event_version"]==3 and v3["previous_event_version_hash"]==events.get_event(ctx["target_event_id"],2)["record_hash"] and v3["evidence_conflicts"]==[])
@check("CORRECTION","same-source correction does not inflate corroboration")
def _():
    with environment() as (ing,*_,life,ctx,root): require(apply_correction(life,ing,ctx)["event"]["corroboration_status"]=="SINGLE_SOURCE_OFFICIAL")
@check("CORRECTION","multi-source correction remains corroborated")
def _():
    with environment("multi") as (ing,*_,life,ctx,root): require(apply_correction(life,ing,ctx,target=ctx["cross"]["evidence_id"],key="cross-correction")["event"]["corroboration_status"]=="CORROBORATED")
@check("CORRECTION","unlinked evidence rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        item=base.capture(ing,ctx["registries"],base.RBI_SOURCE_ID,"unlinked",LINK_TIME);expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF),"RELATION")
@check("CORRECTION","target outside active evidence rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        item=linked(ing,ctx,"outside",ctx["cross"]["evidence_id"]);expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["cross"]["evidence_id"]],lifecycle_cutoff=CUTOFF),"TARGET")
@check("CORRECTION","cross-source mutation rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        item=linked(ing,ctx,"cross-source",ctx["same"]["evidence_id"],source=base.SEBI_SOURCE_ID);expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF),"SAME_SOURCE")
@check("CORRECTION","dual relation rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        item=linked(ing,ctx,"both",ctx["same"]["evidence_id"],both=True);expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF),"EXACTLY_ONE")
@check("CORRECTION","earlier correction rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        item=linked(ing,ctx,"early",ctx["same"]["evidence_id"],time="2026-09-26T08:30:00Z");expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF),"TIMING")
@check("CORRECTION","partial and quarantined lifecycle evidence rejected")
def _():
    for status in ("PARTIAL","QUARANTINED"):
        with environment() as (ing,*_,life,ctx,root):
            target=ctx["same"]["evidence_id"];item=linked(ing,ctx,"bad-status-"+status,target,status=status);expect(Exception,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[target],lifecycle_cutoff=CUTOFF))
@check("CORRECTION","duplicate correction of one active evidence rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        target=ctx["same"]["evidence_id"];items=[linked(ing,ctx,"duplicate-"+str(i),target) for i in range(2)];expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[x["evidence_id"] for x in items],affected_evidence_ids=[target],lifecycle_cutoff=CUTOFF),"ONE_TO_ONE")

@check("RETRACTION","complete single-source event retraction")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        result=apply_retraction(life,ing,events,ctx);require(result["event"]["event_status"]=="RETRACTED" and set(result["event"]["source_evidence_ids"])=={t["lifecycle_evidence_id"] for t in result["lifecycle"]["evidence_transitions"]} and result["event"]["evidence_conflicts"]==[])
@check("RETRACTION","complete multi-source event retraction remains corroborated")
def _():
    with environment("multi") as (ing,ext,cand,events,mat,evo,life,ctx,root): require(apply_retraction(life,ing,events,ctx)["event"]["corroboration_status"]=="CORROBORATED")
@check("RETRACTION","partial event retraction rejected")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        target=ctx["same"]["evidence_id"];item=linked(ing,ctx,"partial",target,"RETRACTION");expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="RETRACT_EVENT",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[target],lifecycle_cutoff=CUTOFF),"COMPLETE")
@check("RETRACTION","correction relation cannot retract event")
def _():
    with environment() as (ing,*_,life,ctx,root):
        item=linked(ing,ctx,"wrong-rel",ctx["same"]["evidence_id"]);expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="RETRACT_EVENT",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF),"RETRACTION_RELATION")

@check("RESOLUTION","conflict resolved by retraction with audit snapshot")
def _():
    with environment("conflict") as (ing,ext,cand,events,mat,evo,life,ctx,root):
        before=canonical_json(events.get_event(ctx["target_event_id"],2));result=resolve(life,ing,ctx);v3=result["event"];snap=result["lifecycle"]["resolved_conflict"]
        require(canonical_json(events.get_event(ctx["target_event_id"],2))==before and v3["event_status"]=="CANDIDATE" and v3["evidence_conflicts"]==[] and ctx["cross"]["evidence_id"] not in v3["source_evidence_ids"])
        require(snap=={"evidence_ids":sorted([ctx["base"]["evidence_id"],ctx["cross"]["evidence_id"]]),"description":"Synthetic explicit conflict.","status":"RESOLVED"})
@check("RESOLUTION","conflict resolved by correction")
def _():
    with environment("conflict") as (ing,*_,life,ctx,root):
        result=resolve(life,ing,ctx,"CORRECTION");require(result["event"]["evidence_conflicts"]==[] and result["lifecycle"]["evidence_transitions"][0]["relation"]=="CORRECTION")
@check("RESOLUTION","non-conflicted base rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        item=linked(ing,ctx,"not-conflict",ctx["same"]["evidence_id"],"RETRACTION");expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="RESOLVE_CONFLICT",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF),"OPEN_CONFLICT")
@check("RESOLUTION","resolution target outside conflict rejected")
def _():
    with environment("conflict") as (ing,*_,life,ctx,root):
        unrelated=base.capture(ing,ctx["registries"],base.RBI_SOURCE_ID,"unrelated-resolution",LINK_TIME);item=linked(ing,ctx,"outside-conflict",unrelated["evidence_id"],"RETRACTION")
        expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="RESOLVE_CONFLICT",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[unrelated["evidence_id"]],lifecycle_cutoff=CUTOFF),"TARGET")
@check("RESOLUTION","resolution leaving no active support rejected")
def _():
    with environment("conflict") as (ing,ext,cand,events,mat,evo,life,ctx,root):
        v2=events.get_event(ctx["target_event_id"],2);items=[linked(ing,ctx,"resolve-all-"+str(i),target,"RETRACTION") for i,target in enumerate(v2["source_evidence_ids"])]
        expect(Exception,lambda:life.apply_lifecycle(directive_type="RESOLVE_CONFLICT",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[x["evidence_id"] for x in items],affected_evidence_ids=v2["source_evidence_ids"],lifecycle_cutoff=CUTOFF),"ACTIVE_EVIDENCE_EMPTY")
@check("RESOLUTION","frozen validator rejects historical conflict IDs absent from active set")
def _():
    expect(Exception,lambda:build_event(event_key="stage6_2d_candidate:negative",event_version=3,previous_event_version_hash="a"*64,event_type="RATE_HIKE",event_status="CANDIDATE",direction="UNKNOWN",severity="UNKNOWN",materiality="UNKNOWN",confidence=0.0,entities=[],sectors=[],geographies=[],commodities=[],currencies=[],source_evidence_ids=["B"],corroboration_status="SINGLE_SOURCE_OFFICIAL",first_known_timestamp="2026-09-26T08:00:00Z",last_updated_timestamp=CUTOFF,entity_resolution_version="registry",event_horizon="UNKNOWN",transmission_channels=[],causality_assessment="NO_SUPPORTED_CAUSE_FOUND",evidence_conflicts=[{"evidence_ids":["A","B"],"description":"history","status":"RESOLVED"}]),"CONFLICT_EVIDENCE_NOT_EVENT_DEPENDENCY")

@check("PRESERVATION","all conservative V2 fields preserved")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        v2=events.get_event(ctx["target_event_id"],2);v3=apply_correction(life,ing,ctx)["event"]
        for field in ("event_type","direction","severity","materiality","confidence","entities","sectors","geographies","commodities","currencies","first_known_timestamp","entity_resolution_version","event_horizon","transmission_channels","causality_assessment"):require(v3[field]==v2[field],field)
@check("PIT","cutoff equality accepted")
def _():
    with environment() as (ing,*_,life,ctx,root):
        target=ctx["same"]["evidence_id"];item=linked(ing,ctx,"equal",target,time=CUTOFF);require(life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[target],lifecycle_cutoff=CUTOFF)["event"]["last_updated_timestamp"]==CUTOFF)
@check("PIT","future lifecycle evidence rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        target=ctx["same"]["evidence_id"];item=linked(ing,ctx,"future",target,time="2026-09-26T13:00:00Z");expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[target],lifecycle_cutoff=CUTOFF),"TIMING")
@check("PIT","cutoff before V2 rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        target=ctx["same"]["evidence_id"];item=linked(ing,ctx,"backdated",target,time=base.LATER_CUTOFF);expect(Stage6LifecycleError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[target],lifecycle_cutoff="2026-09-26T09:30:00Z"),"CUTOFF")

@check("VERSIONING","exact rerun idempotent")
def _():
    with environment() as (ing,*_,life,ctx,root):
        target=ctx["same"]["evidence_id"];item=linked(ing,ctx,"rerun",target);kwargs=dict(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[target],lifecycle_cutoff=CUTOFF);life.apply_lifecycle(**kwargs);require(life.apply_lifecycle(**kwargs)["status"]=="IDEMPOTENT_SUCCESS")
@check("VERSIONING","second distinct lifecycle rejected and no V4 API")
def _():
    with environment() as (ing,*_,life,ctx,root):
        apply_correction(life,ing,ctx);other=linked(ing,ctx,"other",ctx["base"]["evidence_id"]);expect(LifecycleConflict,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[other["evidence_id"]],affected_evidence_ids=[ctx["base"]["evidence_id"]],lifecycle_cutoff=CUTOFF))
        expect(TypeError,lambda:life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[other["evidence_id"]],affected_evidence_ids=[ctx["base"]["evidence_id"]],lifecycle_cutoff=CUTOFF,event_version=4))
@check("VERSIONING","only V3 appended with exact V2 predecessor")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        result=apply_correction(life,ing,ctx);require([r[0] for r in events.connection.execute("SELECT event_version FROM event_records WHERE event_id=? ORDER BY event_version",(ctx["target_event_id"],))]==[1,2,3]);require(result["event"]["previous_event_version_hash"]==events.get_event(ctx["target_event_id"],2)["record_hash"])

@check("TRANSITIONS","transition ID hash type pairing exact")
def _():
    with environment() as (ing,*_,life,ctx,root):
        result=apply_correction(life,ing,ctx);item=result["lifecycle"]["evidence_transitions"][0];require(item["relation"]=="CORRECTION" and item["affected_evidence_hash"]==ctx["same"]["record_hash"] and len(item["lifecycle_evidence_hash"])==64)
@check("TRANSITIONS","wrong relation hash and missing transition detected")
def _():
    for column,value in (("relation","RETRACTION"),("affected_evidence_hash","f"*64)):
        with environment() as (ing,*_,life,ctx,root):
            apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_transitions_update");life.connection.execute(f"UPDATE lifecycle_transitions SET {column}=?",(value,));restore_trigger(life,"lifecycle_transitions","UPDATE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"TRANSITION")
    with environment() as (ing,*_,life,ctx,root):
        apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_transitions_delete");life.connection.execute("DELETE FROM lifecycle_transitions");restore_trigger(life,"lifecycle_transitions","DELETE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"TRANSITION")
@check("DEPENDENCY","exact dependency types and multiple evidence primary keys")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        result=apply_retraction(life,ing,events,ctx);d={r[0] for r in life.connection.execute("SELECT dependency_record_type FROM directive_dependencies")};l={r[0] for r in life.connection.execute("SELECT dependency_record_type FROM lifecycle_dependencies")};require(d=={"BASE_STAGE6_EVENT_V2","STAGE6_2E_EVOLUTION","STAGE6_2D_MATERIALIZATION","LIFECYCLE_POLICY","AFFECTED_EVIDENCE","LIFECYCLE_EVIDENCE"});require(l==d|{"LIFECYCLE_DIRECTIVE","RESULT_STAGE6_EVENT_V3"})
@check("DEPENDENCY","missing extra wrong-ID and wrong-type dependencies rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_dependencies_delete");life.connection.execute("DELETE FROM lifecycle_dependencies WHERE dependency_record_type='RESULT_STAGE6_EVENT_V3'");restore_trigger(life,"lifecycle_dependencies","DELETE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"DEPENDENCY")
    with environment() as (ing,*_,life,ctx,root):
        result=apply_correction(life,ing,ctx);life.connection.execute("INSERT INTO lifecycle_dependencies VALUES(?,?,?,?)",(result["lifecycle"]["lifecycle_id"],"EXTRA","EXTRA","f"*64));life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"DEPENDENCY")
    for column,value in (("dependency_record_id","WRONG"),("dependency_record_type","WRONG_TYPE")):
        with environment() as (ing,*_,life,ctx,root):
            apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_dependencies_update");life.connection.execute(f"UPDATE lifecycle_dependencies SET {column}=? WHERE dependency_record_type='RESULT_STAGE6_EVENT_V3'",(value,));restore_trigger(life,"lifecycle_dependencies","UPDATE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"DEPENDENCY")
@check("APPEND_ONLY","all lifecycle tables reject UPDATE and DELETE")
def _():
    with environment() as (ing,*_,life,ctx,root):
        apply_correction(life,ing,ctx)
        for table in ("lifecycle_store_meta","lifecycle_policies","lifecycle_directives","directive_dependencies","lifecycle_records","lifecycle_transitions","lifecycle_dependencies"):
            expect(sqlite3.DatabaseError,lambda t=table:life.connection.execute(f"UPDATE {t} SET rowid=rowid"),"IMMUTABLE_TABLE_UPDATE");expect(sqlite3.DatabaseError,lambda t=table:life.connection.execute(f"DELETE FROM {t}"),"IMMUTABLE_TABLE_DELETE")
@check("APPEND_ONLY","removed trigger detected")
def _():
    with environment() as (ing,*_,life,ctx,root): apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_records_delete");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"TRIGGER_MISSING")

@check("RECOVERY","orphan V3 detected and exact retry repairs")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        _v1,v2,materialization,evolution=life._validate_v2_anchor(ctx["target_event_id"]);item=linked(ing,ctx,"orphan",ctx["same"]["evidence_id"]);directive=build_directive(directive_type="APPLY_CORRECTION",base_event=v2,evolution=evolution,materialization=materialization,lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF,policy=POLICY,policy_hash=POLICY_HASH);transitions,_,_=life._derive_transitions(directive,v2);active=life._active_evidence(v2,directive,transitions);expected=build_event_v3(event_key=life._event_key(v2["event_id"]),base_event=v2,directive=directive,transitions=transitions,active_evidence=active)
        events.append_event(event_key=life._event_key(v2["event_id"]),event_version=3,previous_event_version_hash=v2["record_hash"],source_evidence_ids=expected["source_evidence_ids"],entity_resolution_version=v2["entity_resolution_version"],event_type=v2["event_type"],event_status=expected["event_status"],direction=v2["direction"],severity=v2["severity"],materiality=v2["materiality"],confidence=v2["confidence"],entities=v2["entities"],sectors=v2["sectors"],geographies=v2["geographies"],commodities=v2["commodities"],currencies=v2["currencies"],corroboration_status=expected["corroboration_status"],first_known_timestamp=v2["first_known_timestamp"],last_updated_timestamp=CUTOFF,event_horizon=v2["event_horizon"],transmission_channels=v2["transmission_channels"],causality_assessment=v2["causality_assessment"],evidence_conflicts=[])
        expect(LifecycleIntegrityFailure,life.integrity_check,"ORPHAN");require(life.apply_lifecycle(directive_type="APPLY_CORRECTION",target_event_id=ctx["target_event_id"],lifecycle_evidence_ids=[item["evidence_id"]],affected_evidence_ids=[ctx["same"]["evidence_id"]],lifecycle_cutoff=CUTOFF)["status"]=="CREATED");require(life.integrity_check()["result"]=="PASS")

@check("RESTART_INTEGRITY","clean restart integrity PASS")
def _():
    with environment() as (ing,*_,life,ctx,root): apply_correction(life,ing,ctx);require(life.integrity_check()["result"]=="PASS")
@check("RESTART_INTEGRITY","policy snapshot tamper detected")
def _():
    with environment() as (ing,*_,life,ctx,root): apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_policies_update");life.connection.execute("UPDATE lifecycle_policies SET policy_hash=?",("f"*64,));restore_trigger(life,"lifecycle_policies","UPDATE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"POLICY_SNAPSHOT")
@check("RESTART_INTEGRITY","directive hash tamper detected")
def _():
    with environment() as (ing,*_,life,ctx,root): apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_directives_update");life.connection.execute("UPDATE lifecycle_directives SET record_hash=?",("f"*64,));restore_trigger(life,"lifecycle_directives","UPDATE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check)
@check("RESTART_INTEGRITY","lifecycle result tamper detected")
def _():
    with environment() as (ing,*_,life,ctx,root): apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_records_update");life.connection.execute("UPDATE lifecycle_records SET record_hash=?",("e"*64,));restore_trigger(life,"lifecycle_records","UPDATE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check)
@check("RESTART_INTEGRITY","transition tamper detected")
def _():
    with environment() as (ing,*_,life,ctx,root): apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_transitions_update");life.connection.execute("UPDATE lifecycle_transitions SET affected_evidence_hash=?",("d"*64,));restore_trigger(life,"lifecycle_transitions","UPDATE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"TRANSITION")
@check("RESTART_INTEGRITY","dependency tamper detected")
def _():
    with environment() as (ing,*_,life,ctx,root): apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_dependencies_update");life.connection.execute("UPDATE lifecycle_dependencies SET dependency_record_hash=? WHERE dependency_record_type='LIFECYCLE_POLICY'",("c"*64,));restore_trigger(life,"lifecycle_dependencies","UPDATE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"POLICY_DEPENDENCY")
@check("RESTART_INTEGRITY","resolved conflict snapshot tamper detected")
def _():
    with environment("conflict") as (ing,*_,life,ctx,root):
        resolve(life,ing,ctx);row=life.connection.execute("SELECT * FROM lifecycle_records").fetchone();record=json.loads(row["canonical_json"]);record["resolved_conflict"]["description"]="changed";record["record_hash"]=canonical_hash(without(record,"record_hash"));life.connection.execute("DROP TRIGGER protect_lifecycle_records_update");life.connection.execute("UPDATE lifecycle_records SET canonical_json=?,record_hash=?",(canonical_json(record),record["record_hash"]));restore_trigger(life,"lifecycle_records","UPDATE");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"REPLAY")
@check("RESTART_INTEGRITY","exact wrong policy hash in lifecycle record rejected")
def _():
    with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
        result=apply_correction(life,ing,ctx);row=life.connection.execute("SELECT * FROM lifecycle_records").fetchone();record=json.loads(row["canonical_json"]);directive=result["directive"];v2=events.get_event(ctx["target_event_id"],2);_v1,_v2,materialization,evolution=life._validate_v2_anchor(ctx["target_event_id"]);record["policy_hash"]="f"*64;record["lifecycle_id"]=lifecycle_identity(directive,v2,evolution,record["policy_hash"]);record["record_hash"]=canonical_hash(without(record,"record_hash"));expect(Stage6LifecycleError,lambda:validate_lifecycle(record,directive,v2,evolution,materialization,expected_policy_hash=POLICY_HASH),"POLICY_HASH")
@check("RESTART_INTEGRITY","V1 V2 and V3 tampering detected transitively")
def _():
    for version in (1,2,3):
        with environment() as (ing,ext,cand,events,mat,evo,life,ctx,root):
            apply_correction(life,ing,ctx);events.connection.execute("DROP TRIGGER protect_event_records_update");events.connection.execute("UPDATE event_records SET record_hash=? WHERE event_id=? AND event_version=?",((str(version))*64,ctx["target_event_id"],version));restore_trigger(events,"event_records","UPDATE");events.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check,"UPSTREAM_EVENT")
@check("RESTART_INTEGRITY","affected and lifecycle evidence tampering detected")
def _():
    for which in ("affected","lifecycle"):
        with environment() as (ing,*_,life,ctx,root):
            result=apply_correction(life,ing,ctx);target=ctx["same"]["evidence_id"] if which=="affected" else result["lifecycle"]["evidence_transitions"][0]["lifecycle_evidence_id"];ing.connection.execute("DROP TRIGGER protect_ingestion_records_update");ing.connection.execute("UPDATE ingestion_records SET record_hash=? WHERE record_id=?",("a"*64,target));restore_trigger(ing,"ingestion_records","UPDATE");ing.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check)
@check("RESTART_INTEGRITY","orphan directive and orphan lifecycle record rejected")
def _():
    with environment() as (ing,*_,life,ctx,root):
        apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_records_delete");life.connection.execute("PRAGMA foreign_keys=OFF");life.connection.execute("DELETE FROM lifecycle_records");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check)
    with environment() as (ing,*_,life,ctx,root):
        apply_correction(life,ing,ctx);life.connection.execute("DROP TRIGGER protect_lifecycle_directives_delete");life.connection.execute("PRAGMA foreign_keys=OFF");life.connection.execute("DELETE FROM lifecycle_directives");life.connection.commit();expect(LifecycleIntegrityFailure,life.integrity_check)

@check("NETWORK_AI_TRADING","zero network AI ML and trading implementation")
def _():
    prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers"};text=""
    for path in (STAGE_ROOT/"stage6_lifecycle").glob("*.py"):
        source=path.read_text(encoding="utf-8");text+=source.casefold();tree=ast.parse(source);imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports.intersection(prohibited))
    for token in ("requests.get","openai","embedding","semantic similarity","sentiment","buy_signal","sell_signal","broker_order","position_size"):require(token not in text)
@check("NETWORK_AI_TRADING","socket sentinel proves zero network")
def _():
    with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK_USED")):
        with environment() as (ing,*_,life,ctx,root): apply_correction(life,ing,ctx)
@check("BOUNDARY","all frozen paths unchanged")
def _():
    frozen=((ARCHITECTURE_TAG,["Stage 6/Stage6_Master_Architecture.md","Stage 6/contracts","Stage 6/policy","Stage 6/scripts/validate_stage6_0.py","Stage 6/results/stage6_0_architecture_contract.json"]),(BASELINE_2E_TAG,["Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/fixtures/stage6_2a","Stage 6/fixtures/stage6_2b","Stage 6/fixtures/stage6_2c","Stage 6/fixtures/stage6_2d","Stage 6/fixtures/stage6_2e"]),(PRODUCTION_TAG,["Stage 5D"]))
    for ref,paths in frozen:require(git("diff","--name-only",ref,"--",*paths)=="")

def main():
    rows=[]
    for number,(category,name,function) in enumerate(CHECKS,1):
        try:
            with mock.patch.object(socket,"socket",side_effect=AssertionError("STAGE6_2F_NETWORK_USED")):function()
            rows.append({"test_id":f"S6_2F_{number:03d}","category":category,"test_name":name,"result":"PASS","detail":""})
        except Exception as exc:rows.append({"test_id":f"S6_2F_{number:03d}","category":category,"test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True,exist_ok=True)
    with RESULT_PATH.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=["test_id","category","test_name","result","detail"],lineterminator="\n");writer.writeheader();writer.writerows(rows)
    failed=[row for row in rows if row["result"]!="PASS"]
    print(json.dumps({"stage":"6.2F","tests":len(rows),"passed":len(rows)-len(failed),"failed":len(failed),"result":"PASS" if not failed else "FAIL","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False},sort_keys=True,separators=(",",":")))
    for row in failed:print("FAIL",row["test_id"],row["test_name"]+":",row["detail"])
    return 1 if failed else 0
if __name__=="__main__":raise SystemExit(main())
