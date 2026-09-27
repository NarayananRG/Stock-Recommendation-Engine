"""Frozen Stage 6.3B explicit-binding policy loader."""
from __future__ import annotations
import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6BindingError

POLICY_SCHEMA_VERSION="STAGE6_3B_BINDING_POLICY_V1"
POLICY_ID="S6EXPBINDPOL_STAGE6_3B_V1"
PROCESSOR_VERSION="STAGE6_3B_EVENT_EXPOSURE_BINDER_V1"
AUTHORITY="SHADOW_ONLY"
CHANNELS=["COMMODITY","COMPANY_EXPOSURE","CURRENCY","GEOGRAPHY","MACRO","RATE","SECTOR"]
POLICY_FIELDS={"schema_version","policy_id","policy_version","processor_version","authority","supported_event_statuses","binding_basis","supported_binding_channels"}

def validate_policy(policy:dict)->dict:
    if not isinstance(policy,dict) or set(policy)!=POLICY_FIELDS:raise Stage6BindingError("BINDING_POLICY_FIELDS_INVALID")
    expected=(POLICY_SCHEMA_VERSION,POLICY_ID,1,PROCESSOR_VERSION,AUTHORITY,["CANDIDATE"],"EXPLICIT_ASSERTION_SELECTION",CHANNELS)
    actual=(policy["schema_version"],policy["policy_id"],policy["policy_version"],policy["processor_version"],policy["authority"],policy["supported_event_statuses"],policy["binding_basis"],policy["supported_binding_channels"])
    if actual!=expected:raise Stage6BindingError("BINDING_POLICY_IDENTITY_INVALID")
    return policy

def load_policy()->tuple[dict,str,str]:
    path=Path(__file__).with_name("binding_policy_v1.json");raw=path.read_text(encoding="utf-8");policy=json.loads(raw);validate_policy(policy)
    return policy,canonical_json(policy),canonical_hash(policy)
