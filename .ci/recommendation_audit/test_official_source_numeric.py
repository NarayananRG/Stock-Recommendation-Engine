"""Offline source and numeric provenance checks for NSE debt/equity supplement."""
import ast,math,unittest
from pathlib import Path
from urllib.parse import urlparse
source=Path(__file__).parents[1]/"native150"/"build_official_safety_supplement.py"
tree=ast.parse(source.read_text(encoding="utf-8"))
functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {"official","numeric"}]
env={"urlparse":urlparse,"math":math,"OFFICIAL_HOST":"nsearchives.nseindia.com"}
exec(compile(ast.Module(body=functions,type_ignores=[]),str(source),"exec"),env)
class SourceHygiene(unittest.TestCase):
 def test_official_https_only(self):
  self.assertTrue(env["official"]("https://nsearchives.nseindia.com/company/filing.xml"))
  for url in ("http://nsearchives.nseindia.com/filing.xml",
              "https://evil.test/filing.xml",
              "https://nsearchives.nseindia.com.evil.test/filing.xml",
              "https://bad@nsearchives.nseindia.com/filing.xml",
              "file:///tmp/filing.xml",""):
   with self.subTest(url=url):self.assertFalse(env["official"](url))
 def test_numeric_rejects_nonfinite_bool_and_garbled(self):
  for value in (True,False,float("nan"),float("inf"),"None","N/A","--",""):
   with self.subTest(value=value):self.assertIsNone(env["numeric"](value))
  self.assertEqual(env["numeric"]("1,234.50"),1234.5)
  self.assertEqual(env["numeric"]("0"),0.0)
if __name__=="__main__":unittest.main()
