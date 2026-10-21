from pathlib import Path
import json,hashlib
manifest=json.loads(Path('snapshot/snapshot-manifest.json').read_text())
for r in manifest['files']:
 p=Path('snapshot')/r['archive_path'];assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'],str(p)
m=json.loads(Path('v10bundle/manifest.json').read_text())
for n,v in m['files'].items():
 assert hashlib.sha256((Path('v10work')/n).read_bytes()).hexdigest()==v['new_sha256']
 assert hashlib.sha256((Path('v10bundle/payload')/n).read_bytes()).hexdigest()==v['new_sha256']
for n,h in m['protected'].items():assert hashlib.sha256((Path('v10work')/n).read_bytes()).hexdigest()==h
Path('reports/snapshot-preservation.json').write_text(json.dumps({'status':'PASS','unchanged_files':len(manifest['files']),'source_and_database_bytes_changed':0,'protected_files':m['protected']},indent=2))
print('PRESERVATION_PASS',len(manifest['files']))
