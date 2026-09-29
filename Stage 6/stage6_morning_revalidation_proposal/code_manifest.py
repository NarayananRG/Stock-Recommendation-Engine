from pathlib import Path
from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from .policy import DECISION_ENGINE, MANIFEST_VERSION, git_blob
from .errors import MorningProposalIntegrityFailure

FILES=("policy.py","decision_rules.py","morning_revalidation_proposal_builder.py","morning_revalidation_proposal_validation.py")
def build_code_manifest():
 root=Path(__file__).resolve().parent
 value={"manifest_version":MANIFEST_VERSION,"decision_engine_version":DECISION_ENGINE,"files":[{"relative_path":name,"git_blob_sha1":git_blob(root/name)} for name in sorted(FILES)],"decision_code_hash":""}
 value["decision_code_hash"]=canonical_hash(without(value,"decision_code_hash"));return value
def verify_code_manifest(value):
 expected=build_code_manifest()
 if value!=expected or value.get("decision_code_hash")!=canonical_hash(without(value,"decision_code_hash")):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_CODE_MANIFEST_INVALID")
 return value
