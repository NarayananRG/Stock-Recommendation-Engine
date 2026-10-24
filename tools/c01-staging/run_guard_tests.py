from pathlib import Path
import json,sys,time,unittest
ROOT=Path(__file__).resolve().parent;records=[]
class Result(unittest.TextTestResult):
 def addSuccess(self,test):super().addSuccess(test);records.append({'test':test.id(),'status':'PASS'})
 def addFailure(self,test,err):super().addFailure(test,err);records.append({'test':test.id(),'status':'FAIL','assertion':self._exc_info_to_string(err,test)})
 def addError(self,test,err):super().addError(test,err);records.append({'test':test.id(),'status':'ERROR','assertion':self._exc_info_to_string(err,test)})
t=time.perf_counter();r=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')));output={'scope':'Synthetic staging/source-transaction guard tests only. No actual private restore or application startup.','tests_run':r.testsRun,'passed':sum(x['status']=='PASS'for x in records),'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'wall_seconds':time.perf_counter()-t,'tests':records};(ROOT/'GUARD_TEST_RESULTS.json').write_text(json.dumps(output,indent=2));sys.exit(0 if r.wasSuccessful()else 1)
