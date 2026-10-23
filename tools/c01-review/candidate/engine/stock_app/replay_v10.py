"""Historical-only columnar timelines. No production router/accounting authority.

Canonical indicators retain the V9 formulas; the sequential Supertrend recurrence
runs on NumPy arrays. Polars supplies exact finite-count rolling price context.
Arrow/Parquet objects are content addressed and atomically published. Score rows
are keyed by cutoff, price, source/code content and all PIT market prefixes.
"""
from __future__ import annotations
from bisect import bisect_right
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import math
import os
import tempfile
import sys
_private_runtime = Path(__file__).resolve().parents[1] / ".replay-v10-deps"
if _private_runtime.is_dir():
    sys.path.insert(0, str(_private_runtime))
import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
from .replay_input_cache_v1 import ReplayInputCache
from .official_cache_guard import guarded

SCHEMA = 'SRE_REPLAY_V10_1'
RUNTIME = {'python': sys.version.split()[0], 'numpy': np.__version__,
           'pandas': pd.__version__, 'polars': pl.__version__, 'pyarrow': pa.__version__}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             allow_nan=False, default=str).encode()).hexdigest()


def file_hash(path):
    h = sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def source_signature(code_root, data_root):
    """Hash actual contents, including same-size/same-mtime source corrections."""
    from .fundamental_v3 import discover_sources, _pit_safety_supplement_path
    files = {}
    for root in (Path(code_root), Path(data_root)):
        for relative in ('data/official', 'data/external_authoritative/nse_security_master',
                         'NextGen Research/data/external_authoritative/nse_security_master'):
            folder = root / relative
            if folder.is_dir():
                for p in sorted(folder.rglob('*')):
                    if p.is_file() and p.suffix.lower() in ('.csv', '.json', '.jsonl'):
                        files[str(p.resolve())] = file_hash(p)
        p = root / 'outputs/Leg5_Official_Source_Access_Recovery/NSE_COMPANY_INDUSTRY_CLASSIFICATION.csv'
        if p.is_file():
            files[str(p.resolve())] = file_hash(p)
        for name, p in discover_sources(root).items():
            if p:
                files[str(p.resolve())] = file_hash(p)
        p = _pit_safety_supplement_path(root)
        if p:
            files[str(p.resolve())] = file_hash(p)
    files['modern_ui/api.py'] = file_hash(Path(code_root) / 'modern_ui/api.py')
    for p in sorted((Path(code_root) / 'stock_app').glob('*.py')):
        files[p.name] = file_hash(p)
    return digest([SCHEMA, RUNTIME, files])


@guarded(lambda price_service: price_service.cache_roots)
def market_signature(price_service):
    files = []
    for root in price_service.cache_roots:
        for p in sorted(Path(root).glob('*.csv')):
            files.append((str(p.resolve()), file_hash(p)))
    return digest([SCHEMA, RUNTIME, files])


def atomic_parquet(table, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.v10-', suffix='.parquet', dir=path.parent)
    os.close(fd)
    try:
        pq.write_table(table, tmp, compression='zstd', write_page_checksum=True)
        with open(tmp, 'r+b') as f:
            os.fsync(f.fileno())
        # Metadata and row count must be readable before publication.
        if pq.read_metadata(tmp).num_rows != table.num_rows:
            raise ValueError('V10_PARQUET_ROUNDTRIP_FAILURE')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def numpy_supertrend(data, period=10, multiplier=3.0):
    from .technical_v2 import _wilder, _true_range
    atr = _wilder(_true_range(data), period).to_numpy()
    high = data['High'].to_numpy()
    low = data['Low'].to_numpy()
    close = data['Close'].to_numpy()
    upper = (high + low) / 2.0 + multiplier * atr
    lower = (high + low) / 2.0 - multiplier * atr
    fu, fl = upper.copy(), lower.copy()
    trend = np.empty(len(data), dtype=float)
    st = np.full(len(data), np.nan)
    for i in range(len(data)):
        if i == 0 or not np.isfinite(atr[i]):
            trend[i] = 1.0
            continue
        fu[i] = upper[i] if np.isnan(fu[i-1]) or close[i-1] > fu[i-1] else min(upper[i], fu[i-1])
        fl[i] = lower[i] if np.isnan(fl[i-1]) or close[i-1] < fl[i-1] else max(lower[i], fl[i-1])
        prev = trend[i-1]
        trend[i] = -1.0 if prev >= 0 and close[i] < fl[i] else (1.0 if prev < 0 and close[i] > fu[i] else prev)
        st[i] = fl[i] if trend[i] >= 0 else fu[i]
    return pd.Series(st, index=data.index), pd.Series(trend, index=data.index)


def rolling_context(rows):
    """Preserve V7 row-window, invalid-value and duplicate/order semantics."""
    dates = [str(r.get('date') or '')[:10] for r in rows]
    if any(len(d) != 10 for d in dates) or any(a >= b for a, b in zip(dates, dates[1:])):
        return None
    def positive(x):
        try:
            v = float(x)
            return v if math.isfinite(v) and v > 0 else None
        except (TypeError, ValueError):
            return None
    f = pl.DataFrame({'date': dates, 'high': [positive(r.get('high')) for r in rows],
                      'low': [positive(r.get('low')) for r in rows]},
                     schema={'date': pl.String, 'high': pl.Float64, 'low': pl.Float64})
    f = f.with_columns(
        pl.col('high').rolling_max(window_size=126, min_samples=1).alias('high_126'),
        pl.col('low').shift(1).rolling_min(window_size=20, min_samples=20).alias('prior_low_20'),
    ).select('date', 'high_126', 'prior_low_20')
    return f


class ColumnarStore:
    def __init__(self, root):
        from collections import OrderedDict
        import sqlite3
        self.root = Path(root)
        self.frames = {}
        self.pending = {}
        self.memory = OrderedDict()
        self.memory_bytes = 0
        self.chunks = OrderedDict()
        self.root.joinpath('scores').mkdir(parents=True, exist_ok=True)
        index_path = self.root / 'scores' / 'index.sqlite3'
        try:
            self.db = sqlite3.connect(str(index_path), timeout=30)
            self.db.execute('CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, chunk TEXT NOT NULL)')
            self.db.commit()
        except sqlite3.DatabaseError:
            self.db.close()
            import uuid
            suffix = '.corrupt-' + uuid.uuid4().hex
            for candidate in [index_path, Path(str(index_path) + '-journal')]:
                if candidate.exists():
                    candidate.rename(Path(str(candidate) + suffix))
            self.db = sqlite3.connect(str(index_path), timeout=30)
            self.db.execute('CREATE TABLE entries (key TEXT PRIMARY KEY, chunk TEXT NOT NULL)')
            self.db.commit()
        self.stats = {'timeline_builds': 0, 'timeline_disk_hits': 0,
                      'score_hits': 0, 'score_misses': 0, 'parquet_writes': 0,
                      'invalid_objects': 0, 'score_disk_hits': 0}

    def frame(self, key, builder):
        if key in self.frames:
            return self.frames[key]
        p = self.root / 'timelines' / (key + '.parquet')
        value = None
        if p.is_file():
            try:
                t = pq.read_table(p, page_checksum_verification=True)
                if (t.schema.metadata or {}).get(b'v10_key') != key.encode():
                    raise ValueError('V10_TIMELINE_KEY_MISMATCH')
                value = t.to_pandas()
                self.stats['timeline_disk_hits'] += 1
            except Exception:
                self.stats['invalid_objects'] += 1
        if value is None:
            value = builder()
            table = pa.Table.from_pandas(value, preserve_index=True)
            table = table.replace_schema_metadata({**(table.schema.metadata or {}), b'v10_key': key.encode()})
            atomic_parquet(table, p)
            self.stats['timeline_builds'] += 1
            self.stats['parquet_writes'] += 1
        self.frames[key] = value
        return value

    def _remember(self, key, payload):
        if key in self.memory:
            self.memory_bytes -= len(self.memory.pop(key))
        self.memory[key] = payload
        self.memory_bytes += len(payload)
        while self.memory_bytes > 64 * 1024 * 1024 and len(self.memory) > 1:
            _, old = self.memory.popitem(last=False)
            self.memory_bytes -= len(old)

    def _chunk(self, name):
        if name in self.chunks:
            self.chunks.move_to_end(name)
            return self.chunks[name]
        p = self.root / 'scores' / (name + '.parquet')
        t = pq.read_table(p, page_checksum_verification=True)
        if (t.schema.metadata or {}).get(b'v10_chunk') != name.encode():
            raise ValueError('V10_SCORE_CHUNK_MISMATCH')
        entries = dict(zip(t['key'].to_pylist(), t['payload'].to_pylist()))
        self.chunks[name] = entries
        while len(self.chunks) > 64:
            self.chunks.popitem(last=False)
        return entries

    def get_or_build(self, symbol, key, builder):
        if key in self.memory:
            payload = self.memory[key]
            self.memory.move_to_end(key)
            self.stats['score_hits'] += 1
            return json.loads(payload)
        row = self.db.execute('SELECT chunk FROM entries WHERE key=?', (key,)).fetchone()
        if row:
            try:
                payload = self._chunk(row[0])[key]
                self._remember(key, payload)
                self.stats['score_hits'] += 1
                self.stats['score_disk_hits'] += 1
                return json.loads(payload)
            except Exception:
                self.stats['invalid_objects'] += 1
                self.db.execute('DELETE FROM entries WHERE chunk=?', (row[0],))
                self.db.commit()
                self.chunks.pop(row[0], None)
        value = builder()
        # Keep insertion order: frozen routing iterates feature coverage for display.
        payload = json.dumps(value, separators=(',', ':'), allow_nan=False)
        self.pending[key] = payload
        self._remember(key, payload)
        self.stats['score_misses'] += 1
        return json.loads(payload)

    def flush(self):
        if not self.pending:
            return
        name = digest([SCHEMA, list(self.pending.items())])
        table = pa.table({'key': list(self.pending), 'payload': list(self.pending.values())})
        table = table.replace_schema_metadata({b'v10_chunk': name.encode(), b'v10_schema': SCHEMA.encode()})
        # Publish immutable Arrow chunk first. An interrupted index transaction can
        # leave an unreferenced chunk, but never a reference to partial Parquet.
        atomic_parquet(table, self.root / 'scores' / (name + '.parquet'))
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO entries VALUES (?,?)', [(key, name) for key in self.pending])
        self.pending.clear()
        self.stats['parquet_writes'] += 1

    def close(self):
        self.flush()
        self.db.close()


class ReplayCacheV10(ReplayInputCache):
    def __init__(self, *, store_directory, source_fingerprint, market_fingerprint,
                 history_provider, source_roots=(), **_):
        super().__init__(source_fingerprint=source_fingerprint, market_fingerprint=market_fingerprint)
        self.store = ColumnarStore(store_directory)
        self.history_provider = history_provider
        self._prefix_hashes = {}
        self._code = digest([SCHEMA, RUNTIME, file_hash(Path(__file__).with_name('technical_v2.py')), file_hash(__file__)])
        self._full = {}
        self._v10_context = {}
        self.fundamental_index = FundamentalTimeline(self.store, source_roots)
        self._scope_token = None

    def __enter__(self):
        from .fundamental_v3 import _RESEARCH_TIMELINE_PROVIDER
        self.fundamental_index.prepare()
        self._scope_token = _RESEARCH_TIMELINE_PROVIDER.set(self.fundamental_index)
        return self

    def history(self, symbol, limit, provider):
        # Read accepted authoritative service; no global market-key invalidation of
        # unrelated stock histories and no production price-cache writes.
        k = (str(symbol).upper(), int(limit))
        if k not in self._prices:
            self._prices[k] = provider(symbol, limit=limit)
            self.stats['price_misses'] += 1
        else:
            self.stats['price_hits'] += 1
        return [dict(x) for x in self._prices[k]]

    def fundamental(self, symbol, price, session, provider):
        k = digest([SCHEMA, 'fundamental', self._fingerprint, str(symbol), str(session), price])
        return self.store.get_or_build(symbol, k, lambda: provider(symbol, price, session))

    def valuation(self, symbol, price, cutoff, provider):
        k = digest([SCHEMA, 'valuation', self._fingerprint, str(symbol), str(cutoff), price])
        return self.store.get_or_build(symbol, k, lambda: provider(symbol, price, cutoff))

    def _timeline(self, symbol, full_bars, benchmark):
        from .technical_v2 import compute_features
        key = digest([self._code, full_bars, benchmark])
        return self.store.frame(key, lambda: compute_features(
            pd.DataFrame(full_bars), pd.DataFrame(benchmark) if benchmark else None,
            _supertrend_fn=numpy_supertrend))

    def technical_timeline(self, symbol, horizon, source_bars, benchmark_bars, vix_bars):
        from .technical_v2 import analyze
        if not source_bars:
            return analyze(pd.DataFrame(source_bars))
        cutoff = max(str(r.get('date') or '')[:10] for r in source_bars)
        # Both auxiliary series are clipped before scoring, including India VIX.
        bench = [r for r in benchmark_bars if str(r.get('date') or '')[:10] <= cutoff]
        vix = [r for r in vix_bars if str(r.get('date') or '')[:10] <= cutoff]
        k = digest([self._code, 'technical', symbol, horizon, source_bars, bench, vix])
        def build():
            full = self.history(symbol, 5000, self.history_provider)
            local = digest([symbol, full, benchmark_bars])
            if local not in self._full:
                self._full[local] = self._timeline(symbol, full, benchmark_bars)
            features = self._full[local].loc[:pd.Timestamp(cutoff)].copy()
            # Fall back for callers supplying a different/truncated stock history.
            from .technical_v2 import canonical_ohlcv
            expected = canonical_ohlcv(pd.DataFrame(source_bars))
            if not features.index.equals(expected.index) or not features[['Open','High','Low','Close','Volume']].equals(expected):
                return analyze(pd.DataFrame(source_bars), pd.DataFrame(bench) if bench else None,
                               horizon_sessions=horizon, india_vix=pd.DataFrame(vix) if vix else None)
            return analyze(pd.DataFrame(source_bars), pd.DataFrame(bench) if bench else None,
                           horizon_sessions=horizon, india_vix=pd.DataFrame(vix) if vix else None,
                           _precomputed_features=features)
        return self.store.get_or_build(symbol, k, build)

    def rolling_price_context(self, symbol, cutoff, *, limit, provider, finite):
        k = (symbol, limit)
        if k not in self._v10_context:
            bars = self.history(symbol, limit, provider)
            values = rolling_context(bars)
            if values is None:
                return super().rolling_price_context(symbol, cutoff, limit=limit, provider=provider, finite=finite)
            key = digest([SCHEMA, RUNTIME, 'rolling', bars])
            frame = self.store.frame(key, lambda: values.to_pandas())
            self._v10_context[k] = (tuple(frame['date']), frame)
        dates, f = self._v10_context[k]
        i = bisect_right(dates, cutoff) - 1
        if i < 0:
            return None, None, False
        def valid(v):
            return float(v) if pd.notna(v) else None
        return valid(f.iloc[i]['high_126']), valid(f.iloc[i]['prior_low_20']), i + 1 >= 126

    def flush(self):
        self.store.flush()
        self.stats.update({'v10_' + k: v for k, v in self.store.stats.items()})

    def close(self):
        try:
            self.flush()
        finally:
            if self._scope_token is not None:
                from .fundamental_v3 import _RESEARCH_TIMELINE_PROVIDER
                _RESEARCH_TIMELINE_PROVIDER.reset(self._scope_token)
                self._scope_token = None
            self.store.close()
            super().close()

class ReplayLock:
    """OS advisory lock, automatically released after process interruption."""
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+b')
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise RuntimeError('HISTORICAL_REPLAY_ALREADY_RUNNING') from exc
        return self

    def __exit__(self, *_):
        if self.handle is not None:
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


class FundamentalTimeline:
    """Materialize filing/event availability once; retain exact source rows and ties."""
    def __init__(self, store, roots):
        self.store = store
        self.roots = tuple(Path(r) for r in roots)
        self.sources = {}
        self.indexes = {}

    def prepare(self):
        from . import fundamental_v3 as f
        paths = set()
        for root in self.roots:
            paths.update(p for k, p in f.discover_sources(root).items() if p and k != 'independent_validation')
            p = f._pit_safety_supplement_path(root)
            if p:
                paths.add(p)
        for p in sorted(paths):
            self._load(p)

    def _load(self, path):
        from . import fundamental_v3 as f
        path = Path(path)
        name = str(path.resolve())
        if name in self.sources:
            return
        if not path.is_file():
            self.sources[name] = {}
            return
        key = digest([SCHEMA, RUNTIME, 'fundamental-source-v2', file_hash(path), file_hash(Path(f.__file__))])
        def build():
            import csv
            with path.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle)) if path.suffix.lower() == '.csv' else [json.loads(line) for line in handle if line.strip()]
            from datetime import timezone
            def when(row, key):
                value = f._dt(row.get(key) or (row.get('effective_availability_ts') if key == 'availability_ts' else None))
                return value.astimezone(timezone.utc) if value is not None else None
            return pd.DataFrame({'row_json': [json.dumps(r, separators=(',', ':'), allow_nan=False) for r in rows],
                                 'availability_utc': pd.Series([when(r, 'availability_ts') for r in rows], dtype=object),
                                 'effective_utc': pd.Series([when(r, 'effective_availability_ts') for r in rows], dtype=object)})
        frame = self.store.frame(key, build)
        grouped = {}
        timestamps = {}
        for text, available, effective in zip(frame['row_json'], frame['availability_utc'], frame['effective_utc']):
            row = json.loads(text)
            grouped.setdefault(f._symbol(row.get('symbol')), []).append(row)
            timestamps[id(row)] = {'availability_ts': available.to_pydatetime() if hasattr(available, 'to_pydatetime') and pd.notna(available) else (available if pd.notna(available) else None),
                                   'effective_availability_ts': effective.to_pydatetime() if hasattr(effective, 'to_pydatetime') and pd.notna(effective) else (effective if pd.notna(effective) else None)}
        self.sources[name] = grouped
        for timestamp_key in ('availability_ts', 'effective_availability_ts'):
            indexed = {}
            for symbol, rows in grouped.items():
                dated = []
                for i, row in enumerate(rows):
                    when = timestamps[id(row)][timestamp_key]
                    if when is not None:
                        dated.append((when, i, row))
                dated.sort(key=lambda x: (x[0], x[1]))
                indexed[symbol] = (tuple(x[0] for x in dated), tuple(x[2] for x in dated))
            self.indexes[(name, timestamp_key)] = indexed

    def symbol_rows(self, path, symbol):
        from .fundamental_v3 import _symbol
        self._load(path)
        return self.sources[str(Path(path).resolve())].get(_symbol(symbol), [])

    def timeline_rows(self, path, symbol, cutoff, timestamp_key):
        from .fundamental_v3 import _symbol
        self._load(path)
        entry = self.indexes.get((str(Path(path).resolve()), timestamp_key), {}).get(_symbol(symbol))
        if not entry:
            return []
        times, rows = entry
        return list(rows[:bisect_right(times, cutoff)])


def completed_evidence(directory, source_fingerprint, market_fingerprint, context_signature):
    """Expose only complete, current-input V10 evidence; never a ranking input."""
    import zlib
    results = []
    for p in sorted(Path(directory).glob('*.complete.zlib')):
        try:
            obj = json.loads(zlib.decompress(p.read_bytes()))
            if obj.get('schema') != 'SRE_REPLAY_CHECKPOINT_V2' or obj.get('key') != p.name.split('.')[0]:
                continue
            r = obj.get('value') or {}
            if not r.get('v10') or r.get('pit_completeness') != 'COMPLETE' or not r.get('sessions_replayed'):
                continue
            if (r.get('replay_fundamental_source_fingerprint') != source_fingerprint or r.get('replay_market_content_signature') != market_fingerprint
                    or r.get('replay_context_signature') != context_signature):
                continue
            results.append({'period': r.get('requested_period'), 'requested_range': r.get('requested_range'),
                            'replayed_sessions': r['sessions_replayed'], 'pit_completeness': r['pit_completeness'],
                            'metrics': r.get('metrics'), 'research_only': True,
                            'survivorship_bias_warning': r.get('survivorship_bias_warning', True)})
        except (ValueError, OSError, KeyError, zlib.error):
            continue
    return {'schema': SCHEMA, 'authority': 'RESEARCH_ONLY', 'affects_live_decisions': False,
            'complete_replays': len(results), 'results': results,
            'status': 'RESEARCH_RESULTS_AVAILABLE' if results else 'NOT_VALIDATED',
            'notice': 'Historical simulation on the current surviving universe; incomplete or stale results are excluded. Frozen LIVE_DECISION_V1 rules are unchanged.'}
