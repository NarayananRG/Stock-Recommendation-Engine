from pathlib import Path
import json,sys,time,unittest
ROOT=Path(__file__).resolve().parent
class Result(unittest.TextTestResult):
 def startTest(self,test):super().startTest(test);self.started=time.perf_counter()
 def addSuccess(self,test):super().addSuccess(test);records.append({'test':test.id(),'status':'PASS','seconds':time.perf_counter()-self.started})
 def addFailure(self,test,err):super().addFailure(test,err);records.append({'test':test.id(),'status':'FAIL','assertion':self._exc_info_to_string(err,test)})
 def addError(self,test,err):super().addError(test,err);records.append({'test':test.id(),'status':'ERROR','assertion':self._exc_info_to_string(err,test)})
records=[];start=time.perf_counter();suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py');result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
out={'scope':'isolated synthetic data and subprocesses only','tests_run':result.testsRun,'passed':sum(r['status']=='PASS' for r in records),'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'wall_seconds':time.perf_counter()-start,'tests':records,'live_installation_modified':False,'real_official_retrieval_executed':False,'real_official_correction_executed':False,'historical_replays_run':0}
(ROOT/'reports').mkdir(exist_ok=True);(ROOT/'reports/C01_REGRESSION_RESULTS.json').write_text(json.dumps(out,indent=2));sys.exit(0 if result.wasSuccessful() else 1)
