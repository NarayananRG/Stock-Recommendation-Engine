from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path

script=Path(__file__).resolve().parents[1]/"scripts"/"compare_live_snapshot_recovery.py"
spec=importlib.util.spec_from_file_location("recovery_compare",script)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SnapshotRecoverySafety(unittest.TestCase):
 def base(self):
  return {"run":{"run_id":"r1","market_session":"2026-10-16"},"candidates":[{"symbol":f"S{i:03d}.NS","live_decision":{"evidence":{"official_current":True}}} for i in range(200)]}
 def test_real_200_unique_passes_schema(self):
  module.validate_recovery_snapshot(self.base())
 def test_missing_or_nonboolean_official_is_not_valid(self):
  for v in (None,False,0,1,"true","True",[],{}):
   with self.subTest(v=v):
    self.assertFalse(module.verified_official_current({"evidence":{"official_current":v}}))
  self.assertFalse(module.verified_official_current({}))
  self.assertTrue(module.verified_official_current({"evidence":{"official_current":True}}))
 def test_missing_and_duplicate_candidates_rejected(self):
  for mutate in ("missing","duplicate","bad"):
   d=self.base()
   if mutate=="missing":d["candidates"].pop()
   if mutate=="duplicate":d["candidates"][1]["symbol"]="S000"
   if mutate=="bad":d["candidates"][0]=None
   with self.subTest(mutate=mutate),self.assertRaises(ValueError):module.validate_recovery_snapshot(d)
 def test_no_run_rejected(self):
  with self.assertRaises(ValueError):module.validate_recovery_snapshot({"candidates":[]})
if __name__=="__main__":unittest.main()
