import os,subprocess,sys,tempfile,unittest
from pathlib import Path
PATCH=Path(__file__).with_name("patch_forecast_ui.py")
class UiIntegrationTests(unittest.TestCase):
 def test_patch_and_js_syntax(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"modern_ui/frontend"
   root.mkdir(parents=True)
   (root/"app.js").write_text("""
function escapeHtml(s){return String(s);}
function liveEvidenceHtml(x){return String(x);}
function sample(item,i){
 return \`\${liveEvidenceHtml(item.live_decision||item)} \${liveEvidenceHtml(i.live_decision||i)}\`;
}
""")
   env=dict(os.environ,SRE_ENGINE_ROOT=temp)
   subprocess.run([sys.executable,str(PATCH)],env=env,check=True)
   s=(root/"app.js").read_text()
   self.assertIn("forecastDiagnosticHtml(item)",s)
   self.assertIn("forecastDiagnosticHtml(i)",s)
   self.assertIn("Diagnostic only",s)
   self.assertNotIn("final_action=",s)
   self.assertNotIn("executable=",s)
   subprocess.run(["node","--check",str(root/"app.js")],check=True)
   self.assertNotEqual(subprocess.run([sys.executable,str(PATCH)],env=env,capture_output=True).returncode,0)
 def test_missing_anchors_fails_closed(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"modern_ui/frontend";root.mkdir(parents=True)
   (root/"app.js").write_text("function x(){}")
   self.assertNotEqual(subprocess.run([sys.executable,str(PATCH)],env=dict(os.environ,SRE_ENGINE_ROOT=temp),capture_output=True).returncode,0)
if __name__=="__main__":unittest.main()
