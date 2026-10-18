"""Official-supplement URL trust boundary, extracted without triggering network jobs."""
import ast
from pathlib import Path
from urllib.parse import urlparse
import unittest
SOURCE=Path(__file__).resolve().parents[1]/"native150"/"build_official_safety_supplement.py"
tree=ast.parse(SOURCE.read_text(encoding="utf-8"))
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="official")
env={"urlparse":urlparse,"OFFICIAL_HOST":"nsearchives.nseindia.com"}
exec(compile(ast.Module(body=[fn],type_ignores=[]),str(SOURCE),"exec"),env)
official=env["official"]
class OfficialSourceBoundary(unittest.TestCase):
 def test_exact_official_https_url(self):
  self.assertTrue(official("https://nsearchives.nseindia.com/corporate/filing.xml"))
 def test_reject_untrusted_or_insecure_urls(self):
  for url in (None,"","http://nsearchives.nseindia.com/a.xml","https://nsearchives.nseindia.com.evil.example/file.xml","https://evil.example/nsearchives.nseindia.com","https://user:pass@nsearchives.nseindia.com/a.xml","file:///tmp/data.xml","https://nsearchives.nseindia.com@evil.example/a.xml"):
   with self.subTest(url=url):
    self.assertFalse(official(url))
if __name__=="__main__":unittest.main()
