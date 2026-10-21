from pathlib import Path
import json,hashlib,zipfile,shutil,xml.etree.ElementTree as ET,platform
from stock_app.replay_v10 import source_signature,RUNTIME
root=Path('snapshot/installed-engine').resolve();code=Path('v10work').resolve();bundle=Path('v10bundle');reports=Path('reports')
def load(n):return json.loads((reports/n).read_text())
for n in ['snapshot-preservation.json','native-windows-ci.json','universe-parity.json','decision-parity.json','api-accounting.json','real-recovery.json','leakage-effective.json']:assert load(n)['status']=='PASS',n
u=load('universe-parity.json');assert load('leakage-effective.json')['future_data_violations']==0
assert u['universe']==200 and u['available_sessions']==504 and u['counts']['future_data_violations']==0
full=load('full-replay.json');r=full['result'];assert len(r['coverage'])==504
assert r['replay_fundamental_source_fingerprint']==source_signature(code,root)
assert load('V10-single.json')['replay_fundamental_source_fingerprint']==source_signature(code,root)
periods=load('all-period-reuse.json');assert {p['period'] for p in periods}=={'1W','1M','3M','6M','12M','24M'} and all(p['stats'].get('v10_score_misses',0)==0 for p in periods)
suites=list(ET.parse(reports/'all-unit-tests.xml').getroot().iter('testsuite'));tests=sum(int(s.attrib.get('tests',0)) for s in suites);assert tests==17 and all(int(s.attrib.get('failures',0))+int(s.attrib.get('errors',0))==0 for s in suites)
manifest=load('../v10bundle/manifest.json')
for n,v in manifest['files'].items():
 for folder in [code,bundle/'payload']:assert hashlib.sha256((folder/n).read_bytes()).hexdigest()==v['new_sha256'],str(folder/n)
for n,h in manifest['protected'].items():assert hashlib.sha256((code/n).read_bytes()).hexdigest()==h
summary={'status':'PASS','runtime':RUNTIME,'platform':platform.platform(),'source_signature':source_signature(code,root),'unit_tests':tests,'windows':load('native-windows-ci.json'),'processed_sessions':len(r['coverage']),'replayed':r['sessions_replayed'],'excluded':r['sessions_excluded'],'pit_completeness':r['pit_completeness'],'protected_source_files':manifest['protected'],'interactive_windows_desktop_manually_exercised':False}
(reports/'release-verification.json').write_text(json.dumps(summary,indent=2))
rows=load('V9-benchmark.json')['runs']+load('V10-benchmark.json')['runs'];by={(x['version'],x['case']):x for x in rows}
lines=['# Measured replay performance','','Linux Python 3.12; separate V9/V10 interpreters, empty application replay/feature caches, existing accepted market files. Single sequential runs; OS file cache was not flushed. These are not Windows timings or statistical latency guarantees.','','| Case | V9 seconds | V10 seconds |','|---|---:|---:|']
for case,label in [('cold_one_session','One session, empty replay/feature caches'),('warm_identical_result','Identical completed replay'),('overlap_plus_uncomputed_date','Two dates: one reused, one uncomputed'),('1W_overlapping','Overlapping 1W / matching V9 Custom')]:lines.append(f"| {label} | {by['V9',case]['elapsed_seconds']:.3f} | {by['V10',case]['elapsed_seconds']:.3f} |")
lines += ['',f"Full history with intentional interruption/recovery and concurrent verification audits: {full['elapsed_seconds']:.2f} seconds; 504 sessions processed, {r['sessions_replayed']} replayable, {r['sessions_excluded']} excluded under unchanged PIT/data gates. Peak process RSS: {full['peak_rss_kib']/1024:.1f} MiB (Linux ru_maxrss). No isolated full-history V9 comparison was run.",'','| Subsequent period | Seconds | Replayable | Excluded | New scored-input calculations |','|---|---:|---:|---:|---:|']
for p in periods:lines.append(f"| {p['period']} | {p['elapsed_seconds']:.3f} | {p['replayed']} | {p['excluded']} | {p['stats'].get('v10_score_misses',0)} |")
lines += ['', 'Both versions already cache identical completed results; that warm row is not a new V10 capability. The two-date test adds an uncomputed date inside existing history, not a real new market-file append. Append reuse and same-size/same-mtime revisions are separately tested with synthetic fixtures. Changed numeric histories are recomputed vectorially; no constant-time recurrence append claim is made.', '', 'User-reported Windows baselines (original 112.65 s, V8 49.86 s, V9 warm 10.21 s, V9 new-date 55 s) are context only; they are not directly comparable to this Linux run. Native Windows compatibility tests passed, but desktop performance remains unmeasured.']
(bundle/'PERFORMANCE_REPORT.md').write_text('\n'.join(lines)+'\n')
text=f'''# V10 test results

Final release gate: PASS. See reports/release-verification.json for exact source/runtime identity.

- 17 focused tests passed locally and on native Windows Python 3.12 and 3.14.
- All {u['universe']} stocks: {u['counts']['technical_full_frames']} exact full reference/NumPy frames; {u['counts']['technical_prefixes']} entire causal prefixes and {u['counts']['technical_outputs']} complete technical outputs over 12 cutoffs.
- {u['counts']['fundamental_outputs']} full fundamental outputs and {u['counts']['filing_selections']} timestamp-index selections matched the original source exactly.
- Fundamental availability audit: {u['counts']['leakage_queries']} source/symbol/cutoff queries, {u['counts']['selected_rows_checked']} selected rows checked, zero future-data violations. Effective-availability timestamps were separately checked over {load('leakage-effective.json')['queries']} additional queries and {load('leakage-effective.json')['selected_rows_checked']} selected rows, also with zero violations. Synthetic tests perturb future stock/benchmark/VIX values and require unchanged historical outputs.
- Four full 200-stock historical decision packages match the original router/allocator evidence, ranks and allocations. Only wall-clock allocation generated_at is excluded from equality.
- Full history: 504 processed, {r['sessions_replayed']} replayable, {r['sessions_excluded']} correctly excluded; PIT completeness {r['pit_completeness']}. Missing data was neither downloaded nor fabricated.
- A deliberate interruption retained nine completed sessions; real replay resumed and ended with 504 unique coverage rows. Focused tests also cover filled trades, pending exits and cash/position checkpoint recovery, plus incompatible-checkpoint rejection.
- Every preset reused scored historical inputs with zero new score calculations. Tests cover a new cutoff from persisted numeric Parquet, appended histories, changed-source invalidation, exact dictionary order, interrupted/corrupted objects, index recovery, and automatic OS-lock release after process termination.
- Deployment tests cover source mismatch refusal, idempotence, native preflight, injected mid-apply failure, and byte-exact rollback. Original source guards remain active on user APPLY.
- Real uploaded portfolio/production database copies are unchanged outside existing replay-result tables. All 407 uploaded source/data/state files retain their original checksums. Frozen LIVE_DECISION_V1, allocator, replay execution/accounting and portfolio source hashes are unchanged.
- Node tests cover all seven UI period requests, exact Custom dates and research-only evidence. HTTP smoke tests cover health, authority, historical evidence and application page; validated historical evidence does not affect live decisions.

Native Windows CI: {load('native-windows-ci.json')['url']}. The backend/persistence/deployment tests ran on Windows; the interactive desktop was not manually exercised. Real-data audits/performance ran on Linux Python 3.12. APPLY repeats native indicator/PIT/Parquet/lock preflight before source changes.

The previous temporary runner reset during a verification attempt. The recovered final source was retested; only this completed rerun is used for the final gate. No claim is made about the cause of that infrastructure reset.
'''
(bundle/'TEST_RESULTS.md').write_text(text)
(bundle/'reports').mkdir(exist_ok=True)
for p in reports.iterdir():
 if p.is_file() and p.suffix in ['.json','.xml','.log']:shutil.copy2(p,bundle/'reports'/p.name)
(bundle/'verification').mkdir(exist_ok=True)
for p in Path('verification').iterdir():
 if p.is_file() and p.suffix in ['.py','.js']:shutil.copy2(p,bundle/'verification'/p.name)
for name in ['__pycache__','.pytest_cache']:
 for p in list(bundle.rglob(name)):
  if p.is_dir():shutil.rmtree(p)
out=Path('deliverables/SRE-01413-V10-Consolidated-InPlace-Upgrade.zip').resolve();out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for p in sorted(bundle.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(bundle).as_posix())
with zipfile.ZipFile(out) as z:assert z.testzip() is None
print(json.dumps({'path':str(out),'bytes':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'gate':summary},indent=2))
