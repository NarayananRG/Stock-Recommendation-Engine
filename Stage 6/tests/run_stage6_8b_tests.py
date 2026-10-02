import ast,csv,hashlib,json,sqlite3,subprocess,sys,tempfile
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_connectors.live_registries import build_multisource_registries
from stage6_connectors.policy import APPROVED_ENDPOINTS,RBI_RSS_URL,SEBI_RSS_URL
from stage6_connectors.transport import TransportFailure,TransportResponse
from stage6_prospective_validation.policy import *
from stage6_prospective_validation.operations_config import OPERATIONS_CONTRACT,DAILY_OPERATOR,SOURCE_COVERAGE_SCHEMA,PRIMARY_CAPTURE_SCHEMA,CAPTURE_SUMMARY_STORE_SCHEMA,READINESS_SCHEMA,OPERATIONS_POLICY,OPERATIONAL_SOURCES,ADDITIONAL_SOURCE_STATUS,YFINANCE_STATUS,SOURCE_REGISTRY_V2_ID,SOURCE_REGISTRY_V2_HASH,ENTITY_REGISTRY_V2_ID,ENTITY_REGISTRY_V2_HASH,load_operations_policy,load_operations_contract,verify_operations_configuration
from stage6_prospective_validation.operations_config import BASELINE as STAGE8B_BASELINE,EXPECTED_POLICY_HASH as OPS_POLICY_HASH,EXPECTED_CONTRACT_HASH as OPS_CONTRACT_HASH
from stage6_prospective_validation.source_coverage import attest_sources,verify_source_attestation
from stage6_prospective_validation.runtime_status import prospective_status
import stage6_prospective_validation.runtime_status as status_module
from stage6_prospective_validation.primary_evidence_capture import CaptureSummaryStore,capture_primary_evidence,verify_capture_summary_store,_aggregate_capture_cycle_status
import stage6_prospective_validation.primary_evidence_capture as capture_module
from stage6_prospective_validation.pre_session_readiness import pre_session_check,_capture_cycle_status
import stage6_prospective_validation.pre_session_readiness as readiness_module
from stage6_prospective_validation.daily_operator import enroll_control,_parser
from stage6_prospective_validation.prospective_store import ProspectiveValidationStore
from stage6_prospective_validation.control_reader import Stage5DControlReader,canonical_json as cjson,payload_sha256
from stage6_prospective_validation.errors import *

OUT=ROOT/'results/stage6_8b_test_results.csv';CASES=[];CTX={}
def case(group,name,fn):CASES.append((group,name,fn))
def require(value,message='assertion failed'):
 if not value:raise AssertionError(message)
def expect(error,fn):
 try:fn()
 except error:return
 raise AssertionError('expected '+error.__name__)
def git(*args):return subprocess.check_output(['git',f'--git-dir={REPO/"_git"}',f'--work-tree={REPO}',*args],cwd=REPO,text=True).strip()
def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def result_count(stage):
 rows=list(csv.DictReader((ROOT/'results'/f'stage6_{stage}_test_results.csv').open(encoding='utf-8')));require(all(x['result']=='PASS' for x in rows));return len(rows)
def prior_count():return sum(result_count(x) for x in ('1a','1b','1c','2a','2b','2c','2d','2e','2f','3a','3b','3c','3d','3e','3f','3g','3h','3i','4a','4b','4c','4d','4e','5a','5b','5c','5d','6a','6b','6c','6d','6e','6f','6g','7a','7b','8a'))
def aggregate(*statuses):return _aggregate_capture_cycle_status([{'retrieval_status':x} for x in statuses])

for name,actual,wanted in (
 ('contract',OPERATIONS_CONTRACT,'STAGE6_8B_PROSPECTIVE_OPERATIONS_CONTRACT_V1'),('operator',DAILY_OPERATOR,'STAGE6_8B_DAILY_OPERATOR_V1'),('coverage',SOURCE_COVERAGE_SCHEMA,'STAGE6_8B_SOURCE_COVERAGE_V1'),('capture',PRIMARY_CAPTURE_SCHEMA,'STAGE6_8B_PRIMARY_EVIDENCE_CAPTURE_V2'),('capture store',CAPTURE_SUMMARY_STORE_SCHEMA,'STAGE6_8B_CAPTURE_SUMMARY_STORE_V2'),('readiness',READINESS_SCHEMA,'STAGE6_8B_PRE_SESSION_READINESS_V1'),('policy',OPERATIONS_POLICY,'S6PROSOPSPOL_STAGE6_8B_V1'),('authority',AUTHORITY,'SHADOW_ONLY')):case('IDENTITY',name,lambda actual=actual,wanted=wanted:require(actual==wanted))
case('BASELINE','branch',lambda:require(git('branch','--show-current')=='stage6-prospective-shadow-validation'));case('BASELINE','exact 8A ancestor',lambda:require(git('merge-base','HEAD',STAGE8B_BASELINE)==STAGE8B_BASELINE));case('BASELINE','8A tests',lambda:require(result_count('8a')==373));case('BASELINE','prior 4973',lambda:require(prior_count()-373==4973));case('BASELINE','combined 5346',lambda:require(prior_count()==5346));case('BASELINE','Stage5D frozen',lambda:require(subprocess.run(['git',f'--git-dir={REPO/"_git"}',f'--work-tree={REPO}','diff','--quiet',CONTROL_COMMIT,'HEAD','--','Stage 5D']).returncode==0));case('CONFIG','policy hash',lambda:require(load_operations_policy()[2]==OPS_POLICY_HASH));case('CONFIG','contract hash',lambda:require(load_operations_contract()[2]==OPS_CONTRACT_HASH));case('CONFIG','verify',lambda:require(verify_operations_configuration()['result']=='PASS'))
case('SOURCE','count',lambda:require(CTX['coverage']['operational_primary_count']==2));case('SOURCE','exact set',lambda:require(tuple(CTX['coverage']['activated_v1_operational_primary_source_set'])==OPERATIONAL_SOURCES));case('SOURCE','endpoint count',lambda:require(len(APPROVED_ENDPOINTS)==2));case('SOURCE','SEBI endpoint',lambda:require(CTX['sources']['SEBI_OFFICIAL_RSS']['endpoint']==SEBI_RSS_URL));case('SOURCE','RBI endpoint',lambda:require(CTX['sources']['RBI_OFFICIAL_PRESS_RELEASES_RSS']['endpoint']==RBI_RSS_URL));case('SOURCE','registry V2',lambda:require(CTX['coverage']['source_registry_v2_binding']['record_id']=='S6SRCREG_39b7deae3a0e811e7327af2c'));case('SOURCE','entity V2',lambda:require(CTX['coverage']['entity_registry_v2_binding']['record_id']=='S6ENTREG_2aed0e083e1186bcade4ede9'));case('SOURCE','source hash',lambda:require(CTX['coverage']['source_registry_v2_binding']['record_hash']=='7d91f4c72365757b6cdfaef0c4027c46bfbdb11c3541c229e828f9ee28d58e90'));case('SOURCE','entity hash',lambda:require(CTX['coverage']['entity_registry_v2_binding']['record_hash']=='23438181ad6b3cea20c1bc2f4b3cd4236f5f3a1d5bbfcbb5c8cf0b3d0a2a258f'));case('SOURCE','record hash',lambda:require(CTX['coverage']['record_hash']==canonical_hash(without(CTX['coverage'],'record_hash'))));case('SOURCE','attestation replay',lambda:require(verify_source_attestation(CTX['coverage'],CTX['activation_path'])))
for source_id in OPERATIONAL_SOURCES:
 for key,wanted in (('authority_level','PRIMARY_OFFICIAL'),('verification_status','VERIFIED'),('enabled',True),('automation_status','ALLOWED'),('licensing_status','REVIEWED_ALLOWED'),('supports_machine_access',True),('requires_auth',False),('cost_class','FREE'),('connector_implementation_status','IMPLEMENTED_FROZEN_STAGE6_1')):case('SOURCE_CAPABILITY',source_id+' '+key,lambda source_id=source_id,key=key,wanted=wanted:require(CTX['sources'][source_id][key]==wanted))
case('YFINANCE','not registered',lambda:require(CTX['coverage']['yfinance_stage6_evidence_status']==YFINANCE_STATUS));case('YFINANCE','not source',lambda:require(all('yfinance' not in x.casefold() for x in CTX['sources'])));case('YFINANCE','not endpoint',lambda:require(all('yahoo' not in x.url.casefold() for x in APPROVED_ENDPOINTS)));case('YFINANCE','4A3 distinction',lambda:require('STAGE4A3_MARKET_DATA_DEPENDENCY' in CTX['coverage']['yfinance_stage4a3_status']));case('YFINANCE','5D distinction',lambda:require('STAGE5D_CONTROL_DEPENDENCY' in CTX['coverage']['yfinance_stage5d_status']));case('YFINANCE','Stage6 distinction',lambda:require(CTX['coverage']['stage6_event_evidence_source_status']=='ONLY_REGISTERED_PRIMARY_OFFICIAL_SOURCES'))
case('GAPS','additional exact',lambda:require(CTX['coverage']['additional_primary_source_connector_status']==ADDITIONAL_SOURCE_STATUS));case('GAPS','meaning',lambda:require(CTX['coverage']['coverage_gap_meaning']=='OPERATIONAL_COVERAGE_LIMITATION_NOT_NO_NEWS_OR_NO_RISK'));case('GAPS','no third source',lambda:require(len(CTX['sources'])==2));case('GAPS','no registry V3',lambda:require(set(CTX['registries'])=={'entity_v1','source_v1','entity_v2','source_v2'}));case('GAPS','no NSE',lambda:require('NSE' not in CTX['sources']));case('GAPS','no BSE',lambda:require('BSE' not in CTX['sources']));case('GAPS','no company IR',lambda:require(all('COMPANY' not in x for x in CTX['sources'])));case('GAPS','no crawler',lambda:require('crawler' not in CTX['impl']));case('GAPS','no search engine',lambda:require('search engine' not in CTX['impl']))
case('STATUS','active',lambda:require(CTX['status']['activation_status']=='ACTIVE'));case('STATUS','activation exact',lambda:require(CTX['status']['activation_id']==CTX['activation']['activation_id']));case('STATUS','activation hash',lambda:require(CTX['status']['activation_hash']==CTX['activation']['record_hash']));case('STATUS','protocol',lambda:require(CTX['status']['protocol_hash']==EXPECTED_PROTOCOL_HASH));case('STATUS','component',lambda:require(CTX['status']['component_under_test']==COMPONENT));case('STATUS','sessions',lambda:require(CTX['status']['completed_prospective_sessions']==1));case('STATUS','remaining',lambda:require(CTX['status']['remaining_sessions']==19));case('STATUS','active collecting',lambda:require(CTX['status']['observation_window_status']=='ACTIVE_COLLECTING'));case('STATUS','case count',lambda:require(CTX['status']['case_count']==0));case('STATUS','outcomes',lambda:require(CTX['status']['outcome_count']==0));case('STATUS','last date',lambda:require(CTX['status']['last_enrolled_session_date']=='2026-10-01'));case('STATUS','control date',lambda:require(CTX['status']['last_stage5d5_control_date']=='2026-10-01'));case('STATUS','read only files',lambda:require(CTX['status_before']==CTX['status_after']));case('STATUS','absent no create',lambda:require(not CTX['absent_db'].exists()));case('STATUS','minimum reached',lambda:require(CTX['minimum_status']()['observation_window_status']=='MINIMUM_WINDOW_REACHED'));case('STATUS','not validated',lambda:require('VALIDATED' not in canonical_json(CTX['status'])));case('STATUS','not promotable',lambda:require('PROMOTABLE' not in canonical_json(CTX['status'])));case('STATUS','not production',lambda:require('PRODUCTION_READY' not in canonical_json(CTX['status'])));case('STATUS','trading false',lambda:require(CTX['status']['trading_authority'] is False))
case('ENROLL','created',lambda:require(CTX['enroll']['status']=='CREATED'));case('ENROLL','exact ID',lambda:require(CTX['enroll']['session_enrollment_id'].startswith('S6PROSSESS_')));case('ENROLL','ordinal',lambda:require(CTX['enroll']['session_ordinal']==1));case('ENROLL','date',lambda:require(CTX['enroll']['market_session_date']=='2026-10-01'));case('ENROLL','zero candidates',lambda:require(CTX['enroll']['zero_candidate']));case('ENROLL','zero recommendations',lambda:require(CTX['enroll']['zero_recommendation']));case('ENROLL','one of twenty',lambda:require(CTX['enroll']['sessions_display']=='1/20'));case('ENROLL','integrity',lambda:require(CTX['enroll']['integrity_result']=='PASS'));case('ENROLL','idempotent',lambda:require(CTX['enroll_replay']['status']=='IDEMPOTENT_SUCCESS'));case('ENROLL','run required',lambda:expect(ValueError,lambda:enroll_control(activation_record=CTX['activation_path'],prospective_database=CTX['prospective_db'],control_database=CTX['control_db'],run_id='')));case('ENROLL','control unchanged',lambda:require(CTX['control_hash']==file_hash(CTX['control_db'])));case('ENROLL','activation unchanged',lambda:require(CTX['activation_hash']==file_hash(CTX['activation_path'])))
case('CAPTURE','live required',lambda:require(CTX['no_live']['status']=='LIVE_FLAG_REQUIRED' and CTX['no_live']['network_request_count']==0));case('CAPTURE','no-live no root',lambda:require(not CTX['no_live_root'].exists()));case('CAPTURE','live temp rejected',lambda:expect(Stage6ProspectiveError,CTX['live_temp_rejected']));case('CAPTURE','all created',lambda:require(CTX['capture']['status']=='CREATED'));case('CAPTURE','schema',lambda:require(CTX['capture_summary']['schema_version']==PRIMARY_CAPTURE_SCHEMA));case('CAPTURE','two invocations',lambda:require(CTX['capture_summary']['source_invocation_count']==2));case('CAPTURE','two requests',lambda:require(CTX['capture_summary']['network_request_count']==2));case('CAPTURE','hosts',lambda:require(CTX['capture_summary']['contacted_hosts']==['www.sebi.gov.in','rbi.org.in']));case('CAPTURE','registries four',lambda:require(CTX['capture']['ingestion_integrity']['registries']==4));case('CAPTURE','records two',lambda:require(CTX['capture']['ingestion_integrity']['records']==2));case('CAPTURE','raw two',lambda:require(CTX['capture']['ingestion_integrity']['raw_payloads']==2));case('CAPTURE','summary hash',lambda:require(CTX['capture_summary']['record_hash']==canonical_hash(without(CTX['capture_summary'],'record_hash'))));case('CAPTURE','summary store',lambda:require(CTX['capture']['summary_integrity']['result']=='PASS'));case('CAPTURE','raw preserved',lambda:require(len([x for x in (CTX['capture_root']/'stage6_primary_raw').rglob('*') if x.is_file()])==2));case('CAPTURE','partial',lambda:require(CTX['partial_status']=='PARTIAL'));case('CAPTURE','failed',lambda:require(CTX['failed_status']=='FAILED'));case('CAPTURE','available',lambda:require(CTX['available_status']=='AVAILABLE'));case('CAPTURE','not captured',lambda:require(_capture_cycle_status()=='NOT_CAPTURED'));case('CAPTURE','failure evidence',lambda:require(all(x['record_kind']=='ACQUISITION_ATTEMPT' for x in CTX['failed']['summary']['source_results'])));case('CAPTURE','partial exact',lambda:require(sorted(x['record_kind'] for x in CTX['partial']['summary']['source_results'])==['ACQUISITION_ATTEMPT','EVIDENCE']));case('CAPTURE','no news inference',lambda:require('NO_NEWS' not in canonical_json(CTX['failed'])));case('CAPTURE','append update blocked',lambda:expect(sqlite3.DatabaseError,CTX['summary_update']));case('CAPTURE','append delete blocked',lambda:expect(sqlite3.DatabaseError,CTX['summary_delete']));case('CAPTURE','restart integrity',lambda:require(CTX['summary_restart']()['result']=='PASS'))
case('READINESS','ready',lambda:require(CTX['ready']['status']=='READY_FOR_MORNING_PIPELINE'));case('READINESS','origin run',lambda:require(CTX['ready']['origin_run_id']=='RUN1'));case('READINESS','origin enrolled',lambda:require(CTX['ready']['origin_session_enrollment_id']==CTX['enroll']['session_enrollment_id']));case('READINESS','ordinary proof',lambda:require(CTX['ready']['calendar_proof']['session_date']=='2026-10-05'));case('READINESS','sources expected',lambda:require(CTX['ready']['operational_primary_sources_expected']==2));case('READINESS','not captured',lambda:require(CTX['ready']['primary_evidence_capture_status']=='NOT_CAPTURED'));case('READINESS','no proposal',lambda:require(CTX['ready']['proposal_generated'] is False));case('READINESS','recommendation required',lambda:require('CONTROL_RECOMMENDATION_ID_REQUIRED' in CTX['no_rec']['blocking_reason']));case('READINESS','target required',lambda:require('TARGET_SESSION_DATE_REQUIRED' in CTX['no_target']['blocking_reason']));case('READINESS','weekend blocked',lambda:require(CTX['weekend']['status']=='BLOCKED'));case('READINESS','holiday blocked',lambda:require(CTX['holiday']['status']=='BLOCKED'));case('READINESS','special blocked',lambda:require(CTX['special']['status']=='BLOCKED'));case('READINESS','year blocked',lambda:require(CTX['unsupported']['status']=='BLOCKED'));case('READINESS','at deadline blocked',lambda:require(CTX['at_deadline']['status']=='BLOCKED'));case('READINESS','after deadline blocked',lambda:require(CTX['after_deadline']['status']=='BLOCKED'));case('READINESS','target enrolled blocked',lambda:require(CTX['target_enrolled']['status']=='BLOCKED'));case('READINESS','available source status',lambda:require(CTX['ready_available']['primary_evidence_capture_status']=='AVAILABLE'));case('READINESS','partial source status',lambda:require(CTX['ready_partial']['primary_evidence_capture_status']=='PARTIAL'));case('READINESS','failed source status',lambda:require(CTX['ready_failed']['primary_evidence_capture_status']=='FAILED'))
case('QUARANTINE','retrieved retrieved available',lambda:require(aggregate('RETRIEVED','RETRIEVED')==('AVAILABLE',2)))
case('QUARANTINE','partial retrieved available',lambda:require(aggregate('PARTIAL','RETRIEVED')==('AVAILABLE',2)))
case('QUARANTINE','retrieved quarantined partial',lambda:require(aggregate('RETRIEVED','QUARANTINED')==('PARTIAL',1)))
case('QUARANTINE','quarantined retrieved partial',lambda:require(aggregate('QUARANTINED','RETRIEVED')==('PARTIAL',1)))
case('QUARANTINE','retrieved failed partial',lambda:require(aggregate('RETRIEVED','FAILED')==('PARTIAL',1)))
case('QUARANTINE','quarantined quarantined failed',lambda:require(aggregate('QUARANTINED','QUARANTINED')==('FAILED',0)))
case('QUARANTINE','quarantined failed failed',lambda:require(aggregate('QUARANTINED','FAILED')==('FAILED',0)))
case('QUARANTINE','failed failed failed',lambda:require(aggregate('FAILED','FAILED')==('FAILED',0)))
case('QUARANTINE','quarantined status preserved',lambda:require(CTX['quarantine_one']['source_results'][1]['retrieval_status']=='QUARANTINED'))
case('QUARANTINE','no capture not captured',lambda:require(_capture_cycle_status()=='NOT_CAPTURED'))
case('QUARANTINE','one quarantine readiness partial',lambda:require(CTX['ready_quarantine_one']['status']=='READY_FOR_MORNING_PIPELINE' and CTX['ready_quarantine_one']['primary_evidence_capture_status']=='PARTIAL'))
case('QUARANTINE','two quarantine readiness failed',lambda:require(CTX['ready_quarantine_both']['status']=='READY_FOR_MORNING_PIPELINE' and CTX['ready_quarantine_both']['primary_evidence_capture_status']=='FAILED'))

for key,token in (
 ('missing_target','TARGET_SESSION_DATE_REQUIRED'),('weekend','TARGET_SESSION_WEEKEND'),
 ('holiday','TARGET_SESSION_OFFICIAL_CLOSED_DATE'),('special','UNSUPPORTED_FOR_STAGE6_8_V1'),
 ('unsupported','NSE_CALENDAR_YEAR_UNSUPPORTED'),('activation_date','TARGET_SESSION_NOT_AFTER_ACTIVATION'),
 ('prior_local_date','CAPTURE_TARGET_LOCAL_DATE_MISMATCH'),('exact_deadline','CAPTURE_DEADLINE_PASSED'),
 ('after_deadline','CAPTURE_DEADLINE_PASSED')):
 case('CAPTURE_TARGET',key+' rejected',lambda key=key,token=token:require(token in CTX['target_errors'][key]['error']))
 case('CAPTURE_TARGET',key+' zero network',lambda key=key:require(CTX['target_errors'][key]['requests']==0))
case('CAPTURE_TARGET','valid target before deadline',lambda:require(CTX['capture_summary']['prospective_cycle_eligibility']=='ELIGIBLE'))
case('CAPTURE_TARGET','late crossing ineligible',lambda:require(CTX['late_summary']['prospective_cycle_eligibility']=='LATE_NOT_ELIGIBLE'))
case('CAPTURE_TARGET','late crossing raw retained',lambda:require(CTX['late_raw_count']==2))
case('CAPTURE_TARGET','late crossing readiness rejects',lambda:require(CTX['ready_late']['status']=='BLOCKED' and 'CAPTURE_LATE_NOT_ELIGIBLE' in CTX['ready_late']['blocking_reason']))

case('CAPTURE_BINDING','target date recorded',lambda:require(CTX['capture_summary']['target_session_date']=='2026-10-05'))
case('CAPTURE_BINDING','calendar proof exact',lambda:require(CTX['capture_summary']['target_session_calendar_proof']['calendar_payload_hash']=='c93f0340ca55ace9650b4c68e85836d01303f35f8abd7dc22cad5ef34800a656'))
case('CAPTURE_BINDING','deadline exact',lambda:require(CTX['capture_summary']['pre_session_deadline_utc']=='2026-10-05T03:45:00Z'))
case('CAPTURE_BINDING','activation schema',lambda:require(CTX['capture_summary']['activation_binding']['record_type']==ACTIVATION_SCHEMA))
case('CAPTURE_BINDING','activation id',lambda:require(CTX['capture_summary']['activation_binding']['record_id']==CTX['activation']['activation_id']))
case('CAPTURE_BINDING','activation hash',lambda:require(CTX['capture_summary']['activation_binding']['record_hash']==CTX['activation']['record_hash']))
case('CAPTURE_BINDING','source registry id exact',lambda:require(CTX['capture_summary']['source_registry_v2_binding']['record_id']==SOURCE_REGISTRY_V2_ID))
case('CAPTURE_BINDING','source registry hash exact',lambda:require(CTX['capture_summary']['source_registry_v2_binding']['record_hash']==SOURCE_REGISTRY_V2_HASH))
case('CAPTURE_BINDING','entity registry id exact',lambda:require(CTX['capture_summary']['entity_registry_v2_binding']['record_id']==ENTITY_REGISTRY_V2_ID))
case('CAPTURE_BINDING','entity registry hash exact',lambda:require(CTX['capture_summary']['entity_registry_v2_binding']['record_hash']==ENTITY_REGISTRY_V2_HASH))
case('CAPTURE_BINDING','target changes capture id',lambda:require(CTX['target_changed_id']!=CTX['capture_summary']['capture_run_id']))
case('CAPTURE_BINDING','target changes record hash',lambda:require(CTX['target_changed_hash']!=CTX['capture_summary']['record_hash']))

for key,token in (
 ('cross_activation','CAPTURE_ACTIVATION_BINDING_MISMATCH'),('wrong_activation_hash','CAPTURE_ACTIVATION_BINDING_MISMATCH'),
 ('wrong_target','CAPTURE_TARGET_SESSION_MISMATCH'),('stale_date','CAPTURE_OBSERVED_DATE_MISMATCH'),
 ('future_date','CAPTURE_OBSERVED_DATE_MISMATCH'),('post_deadline','CAPTURE_LATE_NOT_ELIGIBLE'),
 ('future_completion','CAPTURE_COMPLETED_IN_FUTURE'),('wrong_calendar','CAPTURE_CALENDAR_PROOF_MISMATCH'),
 ('source_registry_id','CAPTURE_SOURCE_REGISTRY_BINDING_MISMATCH'),('source_registry_hash','CAPTURE_SOURCE_REGISTRY_BINDING_MISMATCH'),
 ('entity_registry_id','CAPTURE_ENTITY_REGISTRY_BINDING_MISMATCH'),('entity_registry_hash','CAPTURE_ENTITY_REGISTRY_BINDING_MISMATCH'),
 ('missing_sebi','CAPTURE_SOURCE_SET_INVALID'),('missing_rbi','CAPTURE_SOURCE_SET_INVALID'),
 ('duplicate_sebi','CAPTURE_SOURCE_SET_INVALID'),('third_source','CAPTURE_SOURCE_SET_INVALID'),
 ('yfinance','CAPTURE_SOURCE_SET_INVALID'),('aggregate_mismatch','CAPTURE_SOURCE_STATUS_INVALID'),
 ('not_eligible','CAPTURE_LATE_NOT_ELIGIBLE')):
 case('READINESS_BINDING',key+' fail closed',lambda key=key,token=token:require(CTX['invalid_ready'][key]['status']=='BLOCKED' and token in CTX['invalid_ready'][key]['blocking_reason']))
case('READINESS_BINDING','exact source set accepted',lambda:require(CTX['ready_available']['status']=='READY_FOR_MORNING_PIPELINE'))
case('READINESS_BINDING','source status does not infer decision',lambda:require(all(x not in canonical_json(CTX['ready_failed']) for x in ('ENTRY_VALID','WAIT','CANCEL_ENTRY'))))
case('READINESS_BINDING','missing exact capture id rejected',lambda:require('EXACT_CAPTURE_RUN_ID_REQUIRED' in CTX['missing_capture_id']['blocking_reason']))
case('READINESS_BINDING','missing capture database rejected',lambda:require('CAPTURE_SUMMARY_DATABASE_REQUIRED' in CTX['missing_capture_db']['blocking_reason']))
case('READINESS_BINDING','unknown exact id rejected',lambda:require('CAPTURE_RUN_ID_NOT_FOUND' in CTX['unknown_capture_id']['blocking_reason']))

case('SUMMARY_STORE','read verifier pass',lambda:require(CTX['summary_read_integrity']['result']=='PASS'))
case('SUMMARY_STORE','read verifier query only',lambda:require(CTX['summary_read_integrity']['query_only'] is True))
case('SUMMARY_STORE','read does not mutate',lambda:require(CTX['summary_read_hash_before']==CTX['summary_read_hash_after']))
case('SUMMARY_STORE','mode ro source',lambda:require('mode=ro' in CTX['capture_source']))
case('SUMMARY_STORE','query only source',lambda:require('PRAGMA query_only=ON' in CTX['capture_source']))
for key,token in (
 ('metadata','CAPTURE_SUMMARY_METADATA_INVALID'),('trigger','CAPTURE_SUMMARY_TRIGGER_INVALID'),
 ('canonical','CAPTURE_SUMMARY_RECORD_INVALID'),('record_hash','CAPTURE_SUMMARY_RECORD_INVALID'),
 ('authority','CAPTURE_SUMMARY_RECORD_INVALID'),('trading','CAPTURE_SUMMARY_RECORD_INVALID')):
 case('SUMMARY_STORE',key+' tamper fails',lambda key=key,token=token:require(token in CTX['store_errors'][key]))
case('SUMMARY_STORE','no latest lookup',lambda:require(' latest ' not in (' '+CTX['readiness_source'].casefold()+' ')))
case('SUMMARY_STORE','no max lookup',lambda:require('max(' not in CTX['readiness_source'].casefold()))
case('SUMMARY_STORE','no auto discovery',lambda:require('CAPTURE_RUN_ID_NOT_FOUND' in CTX['unknown_capture_id']['blocking_reason']))
case('SUMMARY_STORE','readiness no network imports',lambda:require(all(x not in CTX['readiness_imports'] for x in ('requests','urllib','httpx','aiohttp','socket'))))
case('CLI','commands exact',lambda:require(set(_parser()._subparsers._group_actions[0].choices)=={'status','attest-sources','capture-primary-evidence','enroll-control','pre-session-check'}));case('CLI','capture target required',lambda:require(next(x for x in _parser()._subparsers._group_actions[0].choices['capture-primary-evidence']._actions if x.dest=='target_session_date').required is True));case('CLI','help',lambda:require('prospective shadow-validation' in _parser().description));case('SAFETY','shadow',lambda:require(all(x.get('authority',AUTHORITY)==AUTHORITY for x in (CTX['coverage'],CTX['status'],CTX['capture_summary'],CTX['ready']))));case('SAFETY','trading false',lambda:require(all(x['trading_authority'] is False for x in (CTX['coverage'],CTX['status'],CTX['capture_summary'],CTX['ready']))));case('SAFETY','broker zero',lambda:require(CTX['capture_summary']['broker_calls']==0));case('SAFETY','Stage5D prohibited',lambda:require(CTX['capture_summary']['stage5d_mutation_status']=='PROHIBITED'))
for token in ('yfinance','selenium','playwright','openai','transformers','torch','tensorflow','sklearn'):case('IMPORT_BOUNDARY',token,lambda token=token:require(token not in CTX['imports']))
for phrase in ('ENTRY_VALID','WAIT','CANCEL_ENTRY','event classification','company effect','thesis change','outcome scoring'):case('NO_SEMANTICS',phrase,lambda phrase=phrase:require(phrase.casefold() not in CTX['impl']))
for i in range(150):case('DETERMINISTIC_REPLAY',str(i),lambda:require(CTX['coverage']['record_hash']==canonical_hash(without(CTX['coverage'],'record_hash')) and CTX['capture_summary']['record_hash']==canonical_hash(without(CTX['capture_summary'],'record_hash'))))

def make_activation(path):
 value={'schema_version':ACTIVATION_SCHEMA,'activation_id':'','protocol_id':PROTOCOL_ID,'protocol_hash':EXPECTED_PROTOCOL_HASH,'policy_id':POLICY_ID,'policy_hash':EXPECTED_POLICY_HASH,'contract_id':CONTRACT_VERSION,'contract_hash':EXPECTED_CONTRACT_HASH,'stage6_7_closure_baseline':BASELINE,'stage6_8a_activation_head':STAGE8B_BASELINE,'branch':'stage6-prospective-shadow-validation','stage5d5_control_tag':CONTROL_TAG,'stage5d5_control_commit':CONTROL_COMMIT,'stage5d_subtree_verification':'PASS','stage6_7b_schema':SHADOW_SCHEMA,'stage6_7b_policy_id':SHADOW_POLICY,'stage6_7b_policy_hash':SHADOW_POLICY_HASH,'stage6_7b_contract_id':SHADOW_CONTRACT,'stage6_7b_contract_hash':SHADOW_CONTRACT_HASH,'stage6_7b_decision_engine_version':SHADOW_ENGINE,'stage6_7b_decision_code_hash':SHADOW_CODE_HASH,'activated_at_utc':'2026-09-30T15:56:00Z','activation_date_ist':'2026-09-30','minimum_completed_control_sessions':20,'performance_based_early_stopping':'PROHIBITED','authority':'SHADOW_ONLY','trading_authority':False,'record_hash':''}
 value['activation_id']='S6PROSACT_'+canonical_hash(without(value,'activation_id','record_hash'))[:24];value['record_hash']=canonical_hash(without(value,'record_hash'));path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n',encoding='utf-8');return value
def create_control(path):
 c=sqlite3.connect(path);c.executescript("""CREATE TABLE ledger_meta(singleton INTEGER PRIMARY KEY,schema_version TEXT,database_id TEXT,created_at_utc TEXT);CREATE TABLE stage5d5_meta(singleton INTEGER PRIMARY KEY,schema_version TEXT);CREATE TABLE allocation_runs(allocation_run_id TEXT PRIMARY KEY);CREATE TABLE stage5d5_live_runs(run_id TEXT PRIMARY KEY,market_session_date TEXT UNIQUE,run_started_utc TEXT,run_completed_utc TEXT,data_provider TEXT,market_data_hash TEXT,candidate_input_hash TEXT,candidate_count INTEGER,stage4a3_snapshot_id TEXT,allocation_run_id TEXT,management_session_run_id TEXT,recommendation_count INTEGER,news_status TEXT,canonical_payload_json TEXT,payload_sha256 TEXT);CREATE TABLE recommendations(recommendation_id TEXT PRIMARY KEY,allocation_run_id TEXT,signal_id TEXT,ticker TEXT,signal_date TEXT,decision_date TEXT,portfolio_action_status TEXT,recommended_quantity INTEGER,selected_horizon TEXT,management_policy_id TEXT,entry_low TEXT,entry_high TEXT,stop TEXT,target_1 TEXT,target_2 TEXT,persisted_at_utc TEXT,canonical_payload_json TEXT,payload_sha256 TEXT);CREATE TABLE recommendation_events(event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE,recommendation_id TEXT,event_type TEXT,effective_date TEXT,recorded_at_utc TEXT,payload_json TEXT,payload_sha256 TEXT,idempotency_key TEXT UNIQUE);""");c.execute("INSERT INTO ledger_meta VALUES(1,'STAGE5D2_SCHEMA_V1','CONTROL_DB','2026-09-30T00:00:00Z')");c.execute("INSERT INTO stage5d5_meta VALUES(1,?)",(CONTROL_SCHEMA,));run={'run_id':'RUN1','market_session_date':'2026-10-01','run_started_utc':'2026-10-01T10:00:00Z','run_completed_utc':'2026-10-01T11:00:00Z','data_provider':'FIXTURE','market_data_hash':'MARKET1','candidate_input_hash':'CANDIDATE1','candidate_count':0,'stage4a3_snapshot_id':'S4A3_1','allocation_run_id':'ALLOC1','management_session_run_id':'MGMT1','recommendation_count':0,'news_status':'AVAILABLE'};text=cjson(run);c.execute('INSERT INTO allocation_runs VALUES(?)',('ALLOC1',));c.execute('INSERT INTO stage5d5_live_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(*[run[k] for k in ('run_id','market_session_date','run_started_utc','run_completed_utc','data_provider','market_data_hash','candidate_input_hash','candidate_count','stage4a3_snapshot_id','allocation_run_id','management_session_run_id','recommendation_count','news_status')],text,payload_sha256(text)));rec={'recommendation_id':'REC1','allocation_run_id':'ALLOC1','signal_id':'SIG1','ticker':'AAA.NS','signal_date':'2026-10-01','decision_date':'2026-10-01','portfolio_action_status':'ACTIONABLE_BUY','recommended_quantity':10,'selected_horizon':'SWING','management_policy_id':'POL','entry_low':'100','entry_high':'105','stop':'95','target_1':'115','target_2':'125','thesis_id':'THESIS1'};text=cjson(rec);c.execute('INSERT INTO recommendations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(*[rec[k] for k in ('recommendation_id','allocation_run_id','signal_id','ticker','signal_date','decision_date','portfolio_action_status','recommended_quantity','selected_horizon','management_policy_id','entry_low','entry_high','stop','target_1','target_2')],'2026-10-01T11:10:00Z',text,payload_sha256(text)));event={'recommendation_id':'REC1','event_type':'PENDING_ENTRY','effective_date':'2026-10-05'};text=cjson(event);c.execute('INSERT INTO recommendation_events(event_id,recommendation_id,event_type,effective_date,recorded_at_utc,payload_json,payload_sha256,idempotency_key) VALUES(?,?,?,?,?,?,?,?)',('EVT1','REC1','PENDING_ENTRY','2026-10-05','2026-10-01T11:20:00Z',text,payload_sha256(text),'KEY1'));c.commit();c.close()
class StaticTransport:
 def __init__(self,body,url,fetched='2026-10-05T03:00:30Z'):self.body=body;self.url=url;self.fetched=fetched;self.request_count=0
 def fetch(self):self.request_count+=1;return TransportResponse(200,{'content-type':'application/rss+xml'},self.body,self.fetched,self.url)
class FailureTransport:
 def __init__(self):self.request_count=0
 def fetch(self):self.request_count+=1;raise TransportFailure('NETWORK_FAILURE')
def run_capture(root,activation_path,sebi,rbi,target='2026-10-05',times=None):
 times=iter(times or (datetime(2026,10,5,3,0,tzinfo=timezone.utc),datetime(2026,10,5,3,1,tzinfo=timezone.utc)));old=capture_module._clock_utc;capture_module._clock_utc=lambda:next(times)
 try:return capture_primary_evidence(activation_record=activation_path,runtime_root=root,target_session_date=target,live=True,_fixture_transports={'SEBI_OFFICIAL_RSS':sebi,'RBI_OFFICIAL_PRESS_RELEASES_RSS':rbi},_allow_fixture_runtime=True)
 finally:capture_module._clock_utc=old
def seal_summary(record):
 record['capture_run_id']='';record['record_hash']='';record['capture_run_id']='S6PROSCAP_'+canonical_hash(without(record,'capture_run_id','record_hash'))[:24];record['record_hash']=canonical_hash(without(record,'record_hash'));return record
def write_summary_store(path,record):
 store=CaptureSummaryStore(path)
 try:store.persist(record)
 finally:store.close()
 return path
def setup(temp):
 root=Path(temp.name);activation_path=root/'activation_record.json';activation=make_activation(activation_path);CTX.update({'activation_path':activation_path,'activation':activation,'activation_hash':file_hash(activation_path)})
 old=__import__('stage6_prospective_validation.source_coverage',fromlist=['_now_utc']);old_now=old._now_utc;old._now_utc=lambda:'2026-10-01T12:00:00Z'
 try:coverage=attest_sources(activation_path)
 finally:old._now_utc=old_now
 CTX['coverage']=coverage;CTX['sources']={x['source_id']:x for x in coverage['operational_sources']};CTX['registries']=build_multisource_registries()
 control_db=root/'control.sqlite3';create_control(control_db);CTX['control_db']=control_db;CTX['control_hash']=file_hash(control_db);prospective_db=root/'prospective.sqlite3';CTX['prospective_db']=prospective_db;enroll=enroll_control(activation_record=activation_path,prospective_database=prospective_db,control_database=control_db,run_id='RUN1');CTX['enroll']=enroll;CTX['enroll_replay']=enroll_control(activation_record=activation_path,prospective_database=prospective_db,control_database=control_db,run_id='RUN1')
 before=(file_hash(activation_path),file_hash(prospective_db),file_hash(control_db));status=prospective_status(activation_record=activation_path,prospective_database=prospective_db,control_database=control_db);after=(file_hash(activation_path),file_hash(prospective_db),file_hash(control_db));CTX.update({'status':status,'status_before':before,'status_after':after});absent=root/'absent.sqlite3';prospective_status(activation_record=activation_path,prospective_database=absent);CTX['absent_db']=absent
 original_read=status_module._read_prospective;CTX['minimum_status']=lambda:None
 def minimum_status():
  status_module._read_prospective=lambda path,activation_record:{'sessions':20,'cases':0,'paired':0,'control_only':0,'outcomes':0,'last_session_date':'2026-11-01','database_status':'READ_ONLY_VERIFIED'}
  try:return prospective_status(activation_record=activation_path,prospective_database=prospective_db)
  finally:status_module._read_prospective=original_read
 CTX['minimum_status']=minimum_status;no_live_root=root/'no_live';CTX['no_live_root']=no_live_root;CTX['no_live']=capture_primary_evidence(activation_record=activation_path,runtime_root=no_live_root,target_session_date='2026-10-05',live=False);CTX['live_temp_rejected']=lambda:capture_primary_evidence(activation_record=activation_path,runtime_root=root/'rejected',target_session_date='2026-10-05',live=True)
 sebi_body=(ROOT/'fixtures/stage6_1b/valid_sebi_rss.xml').read_bytes();rbi_body=(ROOT/'fixtures/stage6_1c/valid_rbi_press_releases_rss.xml').read_bytes();capture_root=root/'capture';capture=run_capture(capture_root,activation_path,StaticTransport(sebi_body,SEBI_RSS_URL),StaticTransport(rbi_body,RBI_RSS_URL));partial_root=root/'partial';partial=run_capture(partial_root,activation_path,StaticTransport(sebi_body,SEBI_RSS_URL),FailureTransport());failed_root=root/'failed';failed=run_capture(failed_root,activation_path,FailureTransport(),FailureTransport());verification=datetime(2026,10,5,3,30,tzinfo=timezone.utc);CTX.update({'capture_root':capture_root,'capture':capture,'capture_summary':capture['summary'],'partial':partial,'failed':failed,'available_status':_capture_cycle_status(capture_root/'stage6_primary_capture_summaries.sqlite3',capture['summary']['capture_run_id'],activation=activation,target_session_date='2026-10-05',verification_time=verification),'partial_status':_capture_cycle_status(partial_root/'stage6_primary_capture_summaries.sqlite3',partial['summary']['capture_run_id'],activation=activation,target_session_date='2026-10-05',verification_time=verification),'failed_status':_capture_cycle_status(failed_root/'stage6_primary_capture_summaries.sqlite3',failed['summary']['capture_run_id'],activation=activation,target_session_date='2026-10-05',verification_time=verification)})
 summary_db=capture_root/'stage6_primary_capture_summaries.sqlite3'
 def summary_mutate(sql):
  s=CaptureSummaryStore(summary_db)
  try:s.connection.execute(sql)
  finally:s.close()
 CTX['summary_update']=lambda:summary_mutate("UPDATE capture_summaries SET record_hash='bad'");CTX['summary_delete']=lambda:summary_mutate('DELETE FROM capture_summaries');CTX['summary_restart']=lambda:(lambda s:(s.integrity_check(),s.close())[0])(CaptureSummaryStore(summary_db))
 old_ready=readiness_module._now_utc;readiness_module._now_utc=lambda:datetime(2026,10,5,3,30,tzinfo=timezone.utc)
 try:
  common=dict(activation_record=activation_path,prospective_database=prospective_db,control_database=control_db,recommendation_id='REC1',target_session_date='2026-10-05');ready=pre_session_check(**common);no_rec=pre_session_check(**{**common,'recommendation_id':''});no_target=pre_session_check(**{**common,'target_session_date':''});weekend=pre_session_check(**{**common,'target_session_date':'2026-10-03'});holiday=pre_session_check(**{**common,'target_session_date':'2026-10-02'});special=pre_session_check(**{**common,'target_session_date':'2026-11-08'});unsupported=pre_session_check(**{**common,'target_session_date':'2027-10-05'});ready_available=pre_session_check(**common,capture_summary_database=summary_db,capture_run_id=capture['summary']['capture_run_id']);ready_partial=pre_session_check(**common,capture_summary_database=partial_root/'stage6_primary_capture_summaries.sqlite3',capture_run_id=partial['summary']['capture_run_id']);ready_failed=pre_session_check(**common,capture_summary_database=failed_root/'stage6_primary_capture_summaries.sqlite3',capture_run_id=failed['summary']['capture_run_id'])
 finally:readiness_module._now_utc=old_ready
 readiness_module._now_utc=lambda:datetime(2026,10,5,3,45,tzinfo=timezone.utc)
 try:at_deadline=pre_session_check(**common)
 finally:readiness_module._now_utc=old_ready
 readiness_module._now_utc=lambda:datetime(2026,10,5,3,46,tzinfo=timezone.utc)
 try:after_deadline=pre_session_check(**common)
 finally:readiness_module._now_utc=old_ready
 target_db=root/'target_enrolled.sqlite3';target_db.write_bytes(prospective_db.read_bytes());c=sqlite3.connect(target_db);c.execute('DROP TRIGGER protect_prospective_sessions_update');origin=json.loads(c.execute('SELECT canonical_json FROM prospective_sessions').fetchone()[0]);target={**origin,'enrollment_id':'S6PROSSESS_TARGET','stage5d5_run_id':'TARGET','market_session_date':'2026-10-05','session_ordinal_since_activation':2,'record_hash':''};target['record_hash']=canonical_hash(without(target,'record_hash'));c.execute('INSERT INTO prospective_sessions VALUES(?,?,?,?,?,?)',(target['enrollment_id'],'TARGET','2026-10-05',2,target['record_hash'],canonical_json(target)));c.commit();c.close();readiness_module._now_utc=lambda:datetime(2026,10,5,3,30,tzinfo=timezone.utc)
 try:target_enrolled=pre_session_check(**{**common,'prospective_database':target_db})
 finally:readiness_module._now_utc=old_ready
 CTX.update({'ready':ready,'no_rec':no_rec,'no_target':no_target,'weekend':weekend,'holiday':holiday,'special':special,'unsupported':unsupported,'at_deadline':at_deadline,'after_deadline':after_deadline,'target_enrolled':target_enrolled,'ready_available':ready_available,'ready_partial':ready_partial,'ready_failed':ready_failed})

 def capture_attempt(name,target,when):
  attempt_root=root/('target_'+name);sebi=StaticTransport(sebi_body,SEBI_RSS_URL);rbi=StaticTransport(rbi_body,RBI_RSS_URL);old=capture_module._clock_utc;capture_module._clock_utc=lambda:when
  try:
   capture_primary_evidence(activation_record=activation_path,runtime_root=attempt_root,target_session_date=target,live=True,_fixture_transports={'SEBI_OFFICIAL_RSS':sebi,'RBI_OFFICIAL_PRESS_RELEASES_RSS':rbi},_allow_fixture_runtime=True);error='NO_ERROR'
  except Exception as exc:error=str(exc)
  finally:capture_module._clock_utc=old
  return {'error':error,'requests':sebi.request_count+rbi.request_count,'root_exists':attempt_root.exists()}
 target_errors={
  'missing_target':capture_attempt('missing',None,datetime(2026,10,5,3,0,tzinfo=timezone.utc)),
  'weekend':capture_attempt('weekend','2026-10-03',datetime(2026,10,3,3,0,tzinfo=timezone.utc)),
  'holiday':capture_attempt('holiday','2026-10-02',datetime(2026,10,2,3,0,tzinfo=timezone.utc)),
  'special':capture_attempt('special','2026-11-08',datetime(2026,11,8,3,0,tzinfo=timezone.utc)),
  'unsupported':capture_attempt('unsupported','2027-10-05',datetime(2027,10,5,3,0,tzinfo=timezone.utc)),
  'activation_date':capture_attempt('activation','2026-09-30',datetime(2026,9,30,3,0,tzinfo=timezone.utc)),
  'prior_local_date':capture_attempt('prior','2026-10-05',datetime(2026,10,4,3,0,tzinfo=timezone.utc)),
  'exact_deadline':capture_attempt('deadline','2026-10-05',datetime(2026,10,5,3,45,tzinfo=timezone.utc)),
  'after_deadline':capture_attempt('after','2026-10-05',datetime(2026,10,5,3,46,tzinfo=timezone.utc)),
 }
 CTX['target_errors']=target_errors

 late_root=root/'late_capture';late=run_capture(late_root,activation_path,StaticTransport(sebi_body,SEBI_RSS_URL,'2026-10-05T03:44:30Z'),StaticTransport(rbi_body,RBI_RSS_URL,'2026-10-05T03:44:30Z'),times=(datetime(2026,10,5,3,44,tzinfo=timezone.utc),datetime(2026,10,5,3,45,tzinfo=timezone.utc)));late_db=late_root/'stage6_primary_capture_summaries.sqlite3';old_ready=readiness_module._now_utc;readiness_module._now_utc=lambda:datetime(2026,10,5,3,44,50,tzinfo=timezone.utc)
 try:ready_late=pre_session_check(**common,capture_summary_database=late_db,capture_run_id=late['summary']['capture_run_id'])
 finally:readiness_module._now_utc=old_ready
 CTX.update({'late_summary':late['summary'],'late_raw_count':len([x for x in (late_root/'stage6_primary_raw').rglob('*') if x.is_file()]),'ready_late':ready_late})

 target_probe=deepcopy(capture['summary']);target_probe['target_session_date']='2026-10-06';seal_summary(target_probe);CTX['target_changed_id']=target_probe['capture_run_id'];CTX['target_changed_hash']=target_probe['record_hash']
 def make_variant(name,mutate):
  record=deepcopy(capture['summary']);mutate(record);seal_summary(record);db=write_summary_store(root/('variant_'+name+'.sqlite3'),record);return record,db
 variants={}
 variants['cross_activation']=make_variant('cross_activation',lambda r:r['activation_binding'].__setitem__('record_id','S6PROSACT_OTHER'))
 variants['wrong_activation_hash']=make_variant('wrong_activation_hash',lambda r:r['activation_binding'].__setitem__('record_hash','0'*64))
 variants['wrong_target']=make_variant('wrong_target',lambda r:r.__setitem__('target_session_date','2026-10-06'))
 variants['stale_date']=make_variant('stale_date',lambda r:r.__setitem__('observed_start_utc','2026-10-04T03:00:00Z'))
 variants['future_date']=make_variant('future_date',lambda r:(r.__setitem__('observed_start_utc','2026-10-06T03:00:00Z'),r.__setitem__('completed_utc','2026-10-06T03:01:00Z')))
 variants['post_deadline']=make_variant('post_deadline',lambda r:(r.__setitem__('observed_start_utc','2026-10-05T03:44:00Z'),r.__setitem__('completed_utc','2026-10-05T03:45:00Z')))
 variants['future_completion']=make_variant('future_completion',lambda r:r.__setitem__('completed_utc','2026-10-05T03:40:00Z'))
 variants['wrong_calendar']=make_variant('wrong_calendar',lambda r:r['target_session_calendar_proof'].__setitem__('calendar_payload_hash','0'*64))
 variants['source_registry_id']=make_variant('source_registry_id',lambda r:r['source_registry_v2_binding'].__setitem__('record_id','S6SRCREG_OTHER'))
 variants['source_registry_hash']=make_variant('source_registry_hash',lambda r:r['source_registry_v2_binding'].__setitem__('record_hash','0'*64))
 variants['entity_registry_id']=make_variant('entity_registry_id',lambda r:r['entity_registry_v2_binding'].__setitem__('record_id','S6ENTREG_OTHER'))
 variants['entity_registry_hash']=make_variant('entity_registry_hash',lambda r:r['entity_registry_v2_binding'].__setitem__('record_hash','0'*64))
 variants['missing_sebi']=make_variant('missing_sebi',lambda r:r.__setitem__('source_results',[x for x in r['source_results'] if x['source_id']!='SEBI_OFFICIAL_RSS']))
 variants['missing_rbi']=make_variant('missing_rbi',lambda r:r.__setitem__('source_results',[x for x in r['source_results'] if x['source_id']!='RBI_OFFICIAL_PRESS_RELEASES_RSS']))
 variants['duplicate_sebi']=make_variant('duplicate_sebi',lambda r:r.__setitem__('source_results',[deepcopy(r['source_results'][0]),deepcopy(r['source_results'][0])]))
 variants['third_source']=make_variant('third_source',lambda r:r['source_results'].append({**deepcopy(r['source_results'][0]),'source_id':'NSE'}))
 variants['yfinance']=make_variant('yfinance',lambda r:r['source_results'][1].__setitem__('source_id','YFINANCE'))
 variants['aggregate_mismatch']=make_variant('aggregate_mismatch',lambda r:r.__setitem__('usable_source_count',1))
 variants['not_eligible']=make_variant('not_eligible',lambda r:r.__setitem__('prospective_cycle_eligibility','LATE_NOT_ELIGIBLE'))
 quarantine_one,quarantine_one_db=make_variant('quarantine_one',lambda r:(r['source_results'][1].__setitem__('retrieval_status','QUARANTINED'),r.__setitem__('usable_source_count',1),r.__setitem__('capture_cycle_status','PARTIAL')))
 quarantine_both,quarantine_both_db=make_variant('quarantine_both',lambda r:([x.__setitem__('retrieval_status','QUARANTINED') for x in r['source_results']],r.__setitem__('usable_source_count',0),r.__setitem__('capture_cycle_status','FAILED')))
 old_ready=readiness_module._now_utc;readiness_module._now_utc=lambda:datetime(2026,10,5,3,30,tzinfo=timezone.utc)
 try:
  invalid_ready={name:pre_session_check(**common,capture_summary_database=db,capture_run_id=record['capture_run_id']) for name,(record,db) in variants.items()}
  ready_quarantine_one=pre_session_check(**common,capture_summary_database=quarantine_one_db,capture_run_id=quarantine_one['capture_run_id']);ready_quarantine_both=pre_session_check(**common,capture_summary_database=quarantine_both_db,capture_run_id=quarantine_both['capture_run_id']);missing_capture_id=pre_session_check(**common,capture_summary_database=summary_db);missing_capture_db=pre_session_check(**common,capture_run_id=capture['summary']['capture_run_id']);unknown_capture_id=pre_session_check(**common,capture_summary_database=summary_db,capture_run_id='S6PROSCAP_UNKNOWN')
 finally:readiness_module._now_utc=old_ready
 CTX.update({'invalid_ready':invalid_ready,'quarantine_one':quarantine_one,'ready_quarantine_one':ready_quarantine_one,'ready_quarantine_both':ready_quarantine_both,'missing_capture_id':missing_capture_id,'missing_capture_db':missing_capture_db,'unknown_capture_id':unknown_capture_id})

 summary_read_hash_before=file_hash(summary_db);_,summary_read_integrity=verify_capture_summary_store(summary_db,capture['summary']['capture_run_id']);summary_read_hash_after=file_hash(summary_db);CTX.update({'summary_read_integrity':summary_read_integrity,'summary_read_hash_before':summary_read_hash_before,'summary_read_hash_after':summary_read_hash_after})
 def tamper_store(name,action):
  path=root/('tamper_'+name+'.sqlite3');path.write_bytes(summary_db.read_bytes());connection=sqlite3.connect(path)
  try:action(connection);connection.commit()
  finally:connection.close()
  try:verify_capture_summary_store(path,capture['summary']['capture_run_id']);return 'NO_ERROR'
  except Exception as exc:return str(exc)
 def raw_record_tamper(connection,field,value):
  connection.execute('DROP TRIGGER protect_capture_summaries_update');row=connection.execute('SELECT canonical_json FROM capture_summaries').fetchone();record=json.loads(row[0]);record[field]=value;record['record_hash']=canonical_hash(without(record,'record_hash'));connection.execute('UPDATE capture_summaries SET record_hash=?,canonical_json=?',(record['record_hash'],canonical_json(record)));connection.execute("CREATE TRIGGER protect_capture_summaries_update BEFORE UPDATE ON capture_summaries BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END")
 store_errors={
  'metadata':tamper_store('metadata',lambda c:(c.execute('DROP TRIGGER protect_capture_summary_meta_update'),c.execute("UPDATE capture_summary_meta SET schema_version='BAD'"))),
  'trigger':tamper_store('trigger',lambda c:c.execute('DROP TRIGGER protect_capture_summaries_delete')),
  'canonical':tamper_store('canonical',lambda c:(c.execute('DROP TRIGGER protect_capture_summaries_update'),c.execute("UPDATE capture_summaries SET canonical_json='{}'"),c.execute("CREATE TRIGGER protect_capture_summaries_update BEFORE UPDATE ON capture_summaries BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END"))),
  'record_hash':tamper_store('record_hash',lambda c:(c.execute('DROP TRIGGER protect_capture_summaries_update'),c.execute("UPDATE capture_summaries SET record_hash='bad'"),c.execute("CREATE TRIGGER protect_capture_summaries_update BEFORE UPDATE ON capture_summaries BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END"))),
  'authority':tamper_store('authority',lambda c:raw_record_tamper(c,'authority','PRODUCTION')),
  'trading':tamper_store('trading',lambda c:raw_record_tamper(c,'trading_authority',True)),
 }
 CTX['store_errors']=store_errors
 files=('operations_config.py','source_coverage.py','runtime_status.py','primary_evidence_capture.py','pre_session_readiness.py','daily_operator.py');texts=[(ROOT/'stage6_prospective_validation'/x).read_text(encoding='utf-8') for x in files];CTX['impl']='\n'.join(texts).casefold();CTX['imports']={((n.module or '').split('.')[0] if isinstance(n,ast.ImportFrom) else a.name.split('.')[0]) for text in texts for n in ast.walk(ast.parse(text)) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in ([n] if isinstance(n,ast.ImportFrom) else n.names)}
 CTX['capture_source']=(ROOT/'stage6_prospective_validation/primary_evidence_capture.py').read_text(encoding='utf-8');CTX['readiness_source']=(ROOT/'stage6_prospective_validation/pre_session_readiness.py').read_text(encoding='utf-8');tree=ast.parse(CTX['readiness_source']);CTX['readiness_imports']={((n.module or '').split('.')[0] if isinstance(n,ast.ImportFrom) else a.name.split('.')[0]) for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in ([n] if isinstance(n,ast.ImportFrom) else n.names)}
def main():
 temp=tempfile.TemporaryDirectory();rows=[];failed=0
 try:
  setup(temp)
  for i,(group,name,fn) in enumerate(CASES,1):
   try:fn();result,detail='PASS',''
   except Exception as exc:result,detail='FAIL',f'{type(exc).__name__}: {exc}';failed+=1
   rows.append({'test_id':i,'test_group':group,'test_name':name,'result':result,'detail':detail})
  OUT.parent.mkdir(parents=True,exist_ok=True)
  with OUT.open('w',newline='',encoding='utf-8') as h:w=csv.DictWriter(h,fieldnames=('test_id','test_group','test_name','result','detail'),lineterminator='\n');w.writeheader();w.writerows(rows)
  print(f'Stage 6.8B: {len(rows)-failed}/{len(rows)} PASS'+(f', {failed} FAIL' if failed else ''));[print((x['test_id'],x['test_group'],x['test_name'],x['detail'])) for x in rows if x['result']=='FAIL'];return 1 if failed else 0
 finally:temp.cleanup()
if __name__=='__main__':raise SystemExit(main())
