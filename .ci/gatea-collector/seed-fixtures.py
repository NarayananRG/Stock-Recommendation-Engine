"""CI-only synthetic data. Never imports the application or uses real user data."""
import pathlib, sqlite3, shutil, sys

root = pathlib.Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
for filename in ("stock_recommendation_engine.sqlite3", "phase81_validation.sqlite3", "extra-monitoring.db"):
    seed = root.parent / ("seed-" + filename)
    db = sqlite3.connect(seed)
    db.execute("pragma journal_mode=wal")
    db.execute("pragma wal_autocheckpoint=0")
    db.execute("create table positions(id text primary key, symbol text, qty integer)")
    db.executemany("insert into positions values (?,?,?)", [("paper-g", "GODREJCP", 22), ("paper-h", "HINDZINC", 36), ("legacy-h", "HINDZINC", 2)])
    db.commit()
    # Preserve a committed, uncheckpointed WAL in an otherwise quiescent fixture.
    shutil.copyfile(seed, root / filename)
    shutil.copyfile(str(seed) + "-wal", str(root / filename) + "-wal")
    db.close()
    seed.unlink()
