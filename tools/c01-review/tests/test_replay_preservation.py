from pathlib import Path
import ast,hashlib,json,math,tempfile,unittest,zlib
import test_c01 as f

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
class ReplayPreservationTests(unittest.TestCase):
 def test_native_evidence_marks_changed_code_stale_without_modifying_attestation(self):
  ns={'Path':Path,'json':json,'math':math,'digest':digest,'VERSION':'SRE_V10_PERFORMANCE_CORRECTION_1'}
  tree=ast.parse((f.ENGINE/'stock_app/replay_v10_final.py').read_text())
  for node in tree.body:
   if isinstance(node,ast.FunctionDef) and node.name in ('valid_result','attest','completed_evidence'):exec(compile(ast.Module(body=[node],type_ignores=[]),'unchanged-native-validator','exec'),ns)
  day=f.BASE_DAY;config={'period':'CUSTOM','starting_capital':1000.,'slippage_bps':10.,'transaction_cost_bps':5.}
  identity={'schema':ns['VERSION'],'config':config,'sessions':[day],'source':'SYNTHETIC_OLD_CODE_HASH','market':'SYNTHETIC_UNCHANGED_MARKET','runtime':{'python':'SYNTHETIC_RUNTIME'}}
  r={'schema':'SRE_POINT_IN_TIME_HISTORICAL_REPLAY_V2','requested_period':'CUSTOM','requested_range':{'start':day,'end':day},'coverage':[{'date':day,'replayability':'FULL_PIT_VALID'}],'series':[{'date':day,'portfolio_nav':1000.,'cash':1000.,'invested_value':0.}],'sessions_replayed':1,'sessions_excluded':0,'execution_assumptions':{**config,'broker_execution':False},'automatic_yfinance_fallback':False,'pit_completeness':'COMPLETE','v10':{'affects_live_decisions':False},'replay_fundamental_source_fingerprint':identity['source'],'replay_market_content_signature':identity['market'],'replay_context_signature':'SYNTHETIC_SAME_CONTEXT','metrics':{},'trades':[]}
  ns['attest'](r,identity)
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/(r['v10_acceptance']['key']+'.complete.zlib');p.write_bytes(zlib.compress(json.dumps({'schema':'SRE_REPLAY_CHECKPOINT_V2','key':r['v10_acceptance']['key'],'value':r}).encode()));before=p.read_bytes()
   old=ns['completed_evidence'](td,identity['source'],identity['market'],r['replay_context_signature']);new=ns['completed_evidence'](td,'SYNTHETIC_CORRECTED_CODE_HASH',identity['market'],r['replay_context_signature'])
   self.assertEqual(old['complete_replays'],1);self.assertEqual(new['complete_replays'],0);self.assertEqual(new['stale_replays'],1);self.assertFalse(new['strategy_validated']);self.assertEqual(before,p.read_bytes())
 def test_production_threshold_and_accounting_modules_are_unchanged(self):
  reference=f.ROOT/'baseline/source/engine'
  if not reference.exists():
   # Windows CI carries explicit same-byte protected module fixtures, no data.
   reference=f.ROOT/'reference_engine'
  for name in ['stock_app/live_decision_v1.py','stock_app/technical_v2.py','stock_app/fundamental_v3.py','stock_app/validation_v2.py','stock_app/allocation.py','stock_app/phase81_validation.py','stock_app/replay_v10_final.py']:
   self.assertEqual((reference/name).read_bytes(),(f.ENGINE/name).read_bytes(),name)
if __name__=='__main__':unittest.main(verbosity=2)
