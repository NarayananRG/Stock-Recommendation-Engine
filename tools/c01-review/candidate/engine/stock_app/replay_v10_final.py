"""V10 performance correction; research-only, immutable input partitions.

The production router, accounting and authoritative analyzers remain unchanged.
"""
from __future__ import annotations
from pathlib import Path
from bisect import bisect_right
from copy import deepcopy
import csv,json,math,time
import pandas as pd
from .replay_v10 import (ReplayCacheV10,FundamentalTimeline,ColumnarStore,SCHEMA,RUNTIME,
                        digest,file_hash,numpy_supertrend,rolling_context,atomic_parquet)
VERSION='SRE_V10_PERFORMANCE_CORRECTION_1'


def atomic_json(path,value):
    import os,tempfile
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.v10-final-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as h:json.dump(value,h,allow_nan=False);h.flush();os.fsync(h.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def contract(config,sessions,source,market):
    return {'schema':VERSION,'config':config,'sessions':list(sessions),
            'source':source,'market':market,'runtime':RUNTIME}


def valid_result(result,identity):
    """Validate persisted completed output, not merely the presence of a cache file."""
    try:
        proof=result['v10_acceptance'];key=digest(identity)
        if proof['contract']!=identity or proof['key']!=key:return False
        payload={k:v for k,v in result.items() if k not in ('v10_acceptance','replay_cache_status','replay_request_stats','replay_input_cache_stats')}
        if proof['payload_sha256']!=digest(payload):return False
        sessions=identity['sessions'];coverage=result['coverage'];series=result['series']
        if result.get('schema')!='SRE_POINT_IN_TIME_HISTORICAL_REPLAY_V2' or result.get('requested_period')!=identity['config']['period']:return False
        if result['requested_range']!={'start':sessions[0] if sessions else None,'end':sessions[-1] if sessions else None}:return False
        if [r['date'] for r in coverage]!=sessions:return False
        eligible=[r['date'] for r in coverage if r['replayability'] in ('FULL_PIT_VALID','PIT_VALID_WITH_OPTIONAL_GAPS')]
        if [r['date'] for r in series]!=eligible:return False
        if len(set(sessions))!=len(sessions):return False
        if result['sessions_replayed']!=len(series) or result['sessions_excluded']!=len(coverage)-len(series):return False
        a=result['execution_assumptions'];c=identity['config']
        for k in ('starting_capital','slippage_bps','transaction_cost_bps'):
            if float(a[k])!=c[k]:return False
        if a.get('broker_execution') is not False or result.get('automatic_yfinance_fallback') is not False:return False
        for r in series:
            if not all(math.isfinite(float(r[k])) for k in ('portfolio_nav','cash','invested_value')):return False
            if abs(r['portfolio_nav']-r['cash']-r['invested_value'])>.021:return False
        expected='COMPLETE' if coverage and len(series)==len(coverage) else ('PARTIAL' if series else 'NOT REPLAYABLE')
        return result['pit_completeness']==expected and result['v10']['affects_live_decisions'] is False
    except (KeyError,TypeError,ValueError,OverflowError):return False


def attest(result,identity):
    result.pop('v10_acceptance',None)
    payload={k:v for k,v in result.items() if k not in ('replay_cache_status','replay_request_stats','replay_input_cache_stats')}
    result['v10_acceptance']={'key':digest(identity),'contract':identity,'payload_sha256':digest(payload)}
    if not valid_result(result,identity):raise RuntimeError('V10_COMPLETED_RESULT_VALIDATION_FAILED')


from .replay_checkpoint_v2 import CheckpointStore
class VerifiedCheckpointStore(CheckpointStore):
    def write_checkpoint(self,value):
        super().write_checkpoint({**value,'_v10_checkpoint_key':self.key,'_v10_checkpoint_sha256':digest(value)})
    def read_checkpoint(self):
        value=super().read_checkpoint()
        if value is None:return None
        key=value.pop('_v10_checkpoint_key',None);expected=value.pop('_v10_checkpoint_sha256',None)
        if key!=self.key or expected!=digest(value):raise ValueError('INVALID_REPLAY_CHECKPOINT_PROOF')
        return value


class InstrumentedColumnarStore(ColumnarStore):
    def __init__(self,root):
        super().__init__(root)
        self.stats.update(disk_reads=0,disk_read_bytes=0,disk_write_bytes=0,rows_written=0,timeline_memory_hits=0,store_access_seconds_including_build=0.0)
    def frame(self,key,builder):
        start=time.perf_counter();p=self.root/'timelines'/(key+'.parquet');before=self.stats['parquet_writes']
        if key in self.frames:self.stats['timeline_memory_hits']+=1
        elif p.is_file():self.stats['disk_reads']+=1;self.stats['disk_read_bytes']+=p.stat().st_size
        result=super().frame(key,builder)
        if self.stats['parquet_writes']>before:
            self.stats['disk_write_bytes']+=p.stat().st_size;self.stats['rows_written']+=len(result)
        self.stats['store_access_seconds_including_build']+=time.perf_counter()-start
        return result
    def _chunk(self,name):
        start=time.perf_counter();p=self.root/'scores'/(name+'.parquet')
        if name not in self.chunks and p.is_file():self.stats['disk_reads']+=1;self.stats['disk_read_bytes']+=p.stat().st_size
        result=super()._chunk(name);self.stats['store_access_seconds_including_build']+=time.perf_counter()-start;return result
    def flush(self):
        if not self.pending:return
        start=time.perf_counter();name=digest([SCHEMA,list(self.pending.items())]);count=len(self.pending)
        super().flush();p=self.root/'scores'/(name+'.parquet')
        self.stats['disk_write_bytes']+=p.stat().st_size;self.stats['rows_written']+=count;self.stats['store_access_seconds_including_build']+=time.perf_counter()-start


class LazyFundamentalTimeline(FundamentalTimeline):
    """Typed availability indexes; decode raw rows only for actual cache misses."""
    def __init__(self,store,roots):
        super().__init__(store,roots);self.raw={};self.chains={};self.local_days={};self.decoded={}
    def _load(self,path):
        from . import fundamental_v3 as f
        p=Path(path);name=str(p.resolve())
        if name in self.sources:return
        if not p.is_file():self.sources[name]={};return
        key=digest([VERSION,'typed-fundamental-v2-local-dates',RUNTIME,file_hash(__file__),file_hash(p),file_hash(Path(f.__file__))])
        def build():
            from datetime import timezone
            with p.open(encoding='utf-8-sig',newline='') as h:
                rows=list(csv.DictReader(h)) if p.suffix.lower()=='.csv' else [json.loads(x) for x in h if x.strip()]
            def dt(r,k):
                v=f._dt(r.get(k) or (r.get('effective_availability_ts') if k=='availability_ts' else None))
                return v.astimezone(timezone.utc) if v is not None else None
            return pd.DataFrame({'symbol':[f._symbol(r.get('symbol')) for r in rows],
                'row_json':[json.dumps(r,separators=(',',':'),allow_nan=False) for r in rows],
                'availability_utc':pd.Series([dt(r,'availability_ts') for r in rows],dtype=object),
                'effective_utc':pd.Series([dt(r,'effective_availability_ts') for r in rows],dtype=object),
                'availability_day':pd.Series([(f._dt(r.get('availability_ts') or r.get('effective_availability_ts')).date().toordinal() if f._dt(r.get('availability_ts') or r.get('effective_availability_ts')) is not None else None) for r in rows],dtype='Int64'),
                'effective_day':pd.Series([(f._dt(r.get('effective_availability_ts')).date().toordinal() if f._dt(r.get('effective_availability_ts')) is not None else None) for r in rows],dtype='Int64')})
        frame=self.store.frame(key,build);groups={};times={};days={}
        for i,r in enumerate(frame.itertuples(index=False,name=None)):
            symbol,raw,a,e,ad,ed=r;groups.setdefault(symbol,[]).append(raw)
            times[id(raw)]={'availability_ts':a if pd.notna(a) else None,'effective_availability_ts':e if pd.notna(e) else None}
            days[id(raw)]={'availability_ts':int(ad) if pd.notna(ad) else None,'effective_availability_ts':int(ed) if pd.notna(ed) else None}
        self.sources[name]=groups
        for k in ('availability_ts','effective_availability_ts'):
            indexed={}
            for symbol,rows in groups.items():
                dated=[(times[id(raw)][k],i,raw) for i,raw in enumerate(rows) if times[id(raw)][k] is not None]
                dated.sort(key=lambda v:(v[0],v[1]));ts=tuple(v[0] for v in dated);raws=tuple(v[2] for v in dated)
                indexed[symbol]=(ts,raws)
                chain=[digest([VERSION,'rows'])]
                for raw in raws:chain.append(digest([chain[-1],raw]))
                self.chains[(name,k,symbol)]=chain
                self.local_days[(name,k,symbol)]=tuple(days[id(x[2])][k] for x in dated)
            self.indexes[name,k]=indexed
    def _decode(self,raw):
        if raw not in self.decoded:self.decoded[raw]=json.loads(raw)
        return self.decoded[raw]
    def symbol_rows(self,path,symbol):
        from .fundamental_v3 import _symbol
        self._load(path)
        return [self._decode(x) for x in self.sources[str(Path(path).resolve())].get(_symbol(symbol),[])]
    def timeline_rows(self,path,symbol,cutoff,timestamp_key):
        from .fundamental_v3 import _symbol
        self._load(path);entry=self.indexes.get((str(Path(path).resolve()),timestamp_key),{}).get(_symbol(symbol))
        if not entry:return []
        times,raws=entry;return [self._decode(x) for x in raws[:bisect_right(times,cutoff)]]
    def regime(self,symbol,cutoff):
        from .fundamental_v3 import _symbol
        from .fundamental_v3 import STALE_FILING_DAYS
        stale_day=cutoff.date().toordinal()-STALE_FILING_DAYS
        symbol=_symbol(symbol);out=[]
        for name,groups in sorted(self.sources.items()):
            out.append((name,bool(groups.get(symbol))))
            for k in ('availability_ts','effective_availability_ts'):
                ts,_=self.indexes.get((name,k),{}).get(symbol,((),()))
                chain=self.chains.get((name,k,symbol),[None]);n=bisect_right(ts,cutoff)
                local=self.local_days.get((name,k,symbol),())
                out.append((chain[n],sum(d is not None and d<stale_day for d in local[:n])))
        return digest(out)


class ReplayCacheV10Final(ReplayCacheV10):
    def __init__(self,**kw):
        super().__init__(**kw)
        self.store.close();self.store=InstrumentedColumnarStore(kw["store_directory"])
        self._code=digest([self._code,VERSION,file_hash(__file__)])
        self.fundamental_index=LazyFundamentalTimeline(self.store,kw.get('source_roots',()))
        self.roots=tuple(dict.fromkeys(Path(r).resolve() for r in kw.get('source_roots',())))
        self._snapshots={};self._context_frames=__import__("collections").OrderedDict();self._vix_contexts={};self._full_sources={};self._numeric={};self._numeric_inputs={};self._benchmark_by_symbol={};self._profiles={};self._valuations={};self._valuation_table=None
        self._algorithm=digest([VERSION,RUNTIME,file_hash(__file__),file_hash(Path(__file__).with_name('fundamental_v3.py'))])
        self.stats.update(profile_builds=0,profile_hits=0,valuation_lookups=0,valuation_table_builds=0,
                          feature_appends=0,feature_revisions=0,feature_rows_written=0,numeric_rows_computed=0)
        from . import fundamental_v3 as f
        self._independent=[]
        for root in self.roots:
            p=f.discover_sources(root).get('independent_validation')
            self._independent.append((str(root),str(p),file_hash(p) if p else None))
        state_path=self.store.root/'input-generation.json'
        try:prior=json.loads(state_path.read_text())
        except (OSError,ValueError):prior={}
        state={'source':kw['source_fingerprint'],'market':kw['market_fingerprint']}
        self.stats['source_generation_changes']=int(bool(prior) and prior.get('source')!=state['source'])
        self.stats['market_generation_changes']=int(bool(prior) and prior.get('market')!=state['market'])
        if prior!=state:atomic_json(state_path,state)
        self._started=time.perf_counter()
    def _signature(self,role,rows):
        """Hash each immutable accepted row once; exact equality guards caller revisions."""
        state=self._snapshots.get(role)
        if state is None or (len(rows)>len(state[0])) or rows!=state[0][:len(rows)]:
            copy=[dict(r) for r in rows];chain=[digest([VERSION,'prefix'])]
            for row in copy:chain.append(digest([chain[-1],row]))
            state=(copy,chain);self._snapshots[role]=state
        return state[1][len(rows)]
    def _profile_key(self,symbol,session):
        from . import fundamental_v3 as f
        return digest([self._algorithm,'profile',symbol,self.fundamental_index.regime(symbol,f._cutoff(session)),self._independent])

    def fundamental(self,symbol,price,session,provider):
        if getattr(provider,'__qualname__','')!='ModernAppContext.fundamental_v3_context':
            return super().fundamental(symbol,price,session,provider)
        from . import fundamental_v3 as f
        key=self._profile_key(symbol,session)
        def build():
            self.stats['profile_builds']+=1
            base=provider(symbol,None,session);eps=None
            p=(base.get('sources') or {}).get('canonical_panel')
            if base.get('available') and p:
                rows,_=f._pit_rows_timeline(Path(p),symbol,f._cutoff(session),'CONSOLIDATED')
                eps=f._ttm(rows,'EPS')
            return {'profile':base,'raw_eps':eps}
        if key not in self._profiles:self._profiles[key]=self.store.get_or_build(symbol,key,build)
        else:self.stats['profile_hits']+=1
        saved=self._profiles[key];out=deepcopy(saved['profile']);cut=f._cutoff(session)
        out['decision_timestamp']=cut.isoformat()
        if out.get('available'):
            eps=saved['raw_eps'];px=f._num(price);pe=None if eps is None or eps<=0 or px is None else px/eps
            value=f._round(pe,4);out['valuation']['implied_pe_from_ttm_eps']=value
            out['valuation']['basis']='PRICE_DIVIDED_BY_PIT_TTM_EPS' if pe is not None else 'UNAVAILABLE'
            out['feature_coverage']['PE']={'status':'AVAILABLE' if value not in (None,'') else 'MISSING','value':value}
            available=f._dt(out.get('effective_availability_ts'));age=None if available is None else max(0,(cut.date()-available.date()).days)
            fresh='UNAVAILABLE' if age is None else ('STALE' if age>f.STALE_FILING_DAYS else 'CURRENT_FOR_DECISION_TIME')
            out['filing_age_days_at_decision']=age;out['filing_freshness']=fresh
            out['feature_coverage']['Filing freshness']={'status':'STALE' if fresh=='STALE' else 'AVAILABLE','value':fresh}
            # Age provenance changes each day even while immutable filing values
            # and their stale/non-stale classification stay in the same regime.
            for provenance in [out['cash_flow']['source'],*out['balance_sheet']['sources'].values()]:
                available=f._dt(provenance.get('as_of'))
                if available is not None:provenance['age_days']=max(0,(cut.date()-available.date()).days)
        return out
    def _load_valuations(self):
        from . import fundamental_v3 as f
        paths=[]
        for root in self.roots:
            p=f.discover_sources(root).get('canonical_panel');s=f._pit_safety_supplement_path(root)
            if p:paths.append((root,p,s))
        key=digest([self._algorithm,'valuation-table',[(str(r),str(p),file_hash(p),file_hash(s) if s else None) for r,p,s in paths]])
        def build():
            self.stats['valuation_table_builds']+=1;out=[]
            for root,p,_ in paths:
                name=str(p.resolve());groups=self.fundamental_index.sources.get(name,{})
                for symbol in groups:
                    ts,_=self.fundamental_index.indexes.get((name,'availability_ts'),{}).get(symbol,((),()))
                    for cut in sorted(set(ts)):
                        rows,basis=f._pit_rows_timeline(p,symbol,cut,'CONSOLIDATED')
                        if rows:
                            rows,_=f._merge_pit_safety_supplement(root,symbol,cut,basis,rows)
                            out.append((str(root),symbol,cut,f._ttm(rows,'EPS'),f._usable_feature(rows[-1],'PB_RATIO')))
            return pd.DataFrame(out,columns=['root','symbol','availability','eps','pb'])
        frame=self.store.frame(key,build)
        for (root,symbol),group in frame.groupby(['root','symbol'],sort=False):
            self._valuations[root,symbol]=(tuple(group['availability']),tuple(group['eps']),tuple(group['pb']))
        self._valuation_table=True
    def valuation(self,symbol,price,cutoff,provider):
        # Only the engine's research historical-valuation closure uses this fast path.
        if getattr(provider,'__qualname__','')!='ModernAppContext._validation_pit_session.<locals>.valuation_for.<locals>.reference':
            return super().valuation(symbol,price,cutoff,provider)
        from . import fundamental_v3 as f
        if self._valuation_table is None:self._load_valuations()
        cut=f._cutoff(cutoff);self.stats['valuation_lookups']+=1
        for root in self.roots:
            entry=self._valuations.get((str(root),f._symbol(symbol)))
            if entry:
                ts,epss,pbs=entry;i=bisect_right(ts,cut)-1
                if i>=0:
                    eps=f._num(epss[i]);px=f._num(price);pb=f._num(pbs[i])
                    pe=None if eps is None or eps<=0 or px is None else f._round(px/eps,4)
                    return {'available':True,'point_in_time_safe':True,'valuation':{'implied_pe_from_ttm_eps':pe,'implied_pb':pb}}
        return {'available':False,'point_in_time_safe':True,'valuation':{}}
    def _numeric_timeline(self,symbol,full,benchmark):
        from .technical_v2 import compute_features
        prior=self._numeric_inputs.get(symbol)
        if symbol in self._numeric and prior and full==prior[0] and benchmark==prior[1]:return self._numeric[symbol]
        last=max((str(r.get('date') or '')[:10] for r in full),default='')
        relevant=[r for r in benchmark if str(r.get('date') or '')[:10]<=last]
        stock_sig=self._signature(('stock-prefix',symbol),full);self._signature('benchmark-prefix',benchmark);bench_sig=self._signature('benchmark-prefix',relevant)
        key=digest([self._code,VERSION,'numeric',symbol,stock_sig,bench_sig])
        def build():
            frame=compute_features(pd.DataFrame(full),pd.DataFrame(relevant) if relevant else None,_supertrend_fn=numpy_supertrend)
            context=rolling_context(full)
            if context is not None and all(len(str(r.get('date') or ''))==10 for r in full) and frame.index.equals(pd.DatetimeIndex(pd.to_datetime([r['date'] for r in full]))):
                ctx=context.to_pandas();ctx.index=pd.to_datetime(ctx['date']);aligned=ctx.reindex(frame.index)
                frame['_V10_high126']=aligned['high_126'];frame['_V10_priorlow20']=aligned['prior_low_20']
            self.stats['numeric_rows_computed']+=len(frame)
            return frame
        rows_before=self.store.stats['rows_written']
        # Exact vectorized recurrences remain authoritative for changed histories.
        # Persist appended rows only after checking the entire immutable prefix.
        manifest=self.store.root/'partitions'/(digest([self._code,VERSION,symbol])+'.json')
        try:
            old=json.loads(manifest.read_text())
            if old.get('metadata_sha256')!=digest({k:v for k,v in old.items() if k!='metadata_sha256'}):old=None
        except (OSError,ValueError):old=None
        if old and old.get('key')!=key:
            old_len=old['source_rows'];old_bench=old['benchmark_rows']
            append=(len(full)>old_len and stock_sig!=old['stock_signature']
                and self._signature(('stock-prefix',symbol),full[:old_len])==old['stock_signature']
                and len(relevant)>=old_bench and self._signature('benchmark-prefix',relevant[:old_bench])==old['benchmark_signature'])
            if append:
                try:
                    previous=pd.concat([self.store.frame(k,lambda:(_ for _ in ()).throw(ValueError('MISSING_PARTITION'))) for k in old['parts']])
                    current=build()
                    if current.iloc[:len(previous)].equals(previous):
                        delta=current.iloc[len(previous):];part=digest([key,'append'])
                        self.store.frame(part,lambda:delta);parts=old['parts']+[part];frame=current
                        self.stats['feature_appends']+=1
                    else:raise ValueError('PREFIX_CHANGED')
                except (OSError,ValueError,KeyError):frame=self.store.frame(key,build);parts=[key];self.stats['feature_revisions']+=1
            else:frame=self.store.frame(key,build);parts=[key];self.stats['feature_revisions']+=1
        elif old and old.get('key')==key:
            try:frame=pd.concat([self.store.frame(k,lambda:(_ for _ in ()).throw(ValueError('MISSING_PARTITION'))) for k in old['parts']]);parts=old['parts']
            except (OSError,ValueError,KeyError):frame=self.store.frame(key,build);parts=[key]
        else:frame=self.store.frame(key,build);parts=[key]
        ranges=[]
        for part in parts:
            if old and part in old.get('parts',[]) and old.get('ranges'):
                ranges.append(old['ranges'][old['parts'].index(part)])
            else:
                block=self.store.frames[part]
                ranges.append({'start':str(block.index[0].date()) if len(block) else None,'end':str(block.index[-1].date()) if len(block) else None,'rows':len(block)})
        data={'key':key,'parts':parts,'ranges':ranges,'source_rows':len(full),'benchmark_rows':len(relevant),'stock_signature':stock_sig,'benchmark_signature':bench_sig}
        data['metadata_sha256']=digest(data)
        if old!=data:atomic_json(manifest,data)
        self.stats['feature_rows_written']+=self.store.stats['rows_written']-rows_before
        self._numeric_inputs[symbol]=(self._snapshots[('stock-prefix',symbol)][0],self._snapshots['benchmark-prefix'][0])
        self._numeric[symbol]=frame
        return frame
    def technical_timeline(self,symbol,horizon,source_bars,benchmark_bars,vix_bars):
        from .technical_v2 import analyze,canonical_ohlcv
        if not source_bars:return analyze(pd.DataFrame(source_bars))
        self._benchmark_by_symbol[symbol]=benchmark_bars
        cutoff=max(str(r.get('date') or '')[:10] for r in source_bars)
        bench=[r for r in benchmark_bars if str(r.get('date') or '')[:10]<=cutoff]
        vix=[r for r in vix_bars if str(r.get('date') or '')[:10]<=cutoff]
        if symbol not in self._full_sources:
            self._full_sources[symbol]=self.history(symbol,5000,self.history_provider)
            self._signature(('stock-prefix',symbol),self._full_sources[symbol])
        self._signature('benchmark-prefix',benchmark_bars)
        self._signature('vix-prefix',vix_bars)
        key=digest([self._code,VERSION,'technical',symbol,horizon,self._signature(('stock-prefix',symbol),source_bars),self._signature('benchmark-prefix',bench),self._signature('vix-prefix',vix)])
        def build():
            full=self._full_sources[symbol];features=self._numeric_timeline(symbol,full,benchmark_bars).loc[:pd.Timestamp(cutoff)]
            known=('_V10_high126' in features and source_bars==full[:len(source_bars)])
            expected=None if known else canonical_ohlcv(pd.DataFrame(source_bars))
            if not known and (not features.index.equals(expected.index) or not features[['Open','High','Low','Close','Volume']].equals(expected)):
                return analyze(pd.DataFrame(source_bars),pd.DataFrame(bench) if bench else None,horizon_sessions=horizon,india_vix=pd.DataFrame(vix) if vix else None)
            from .technical_v2 import _india_vix_context
            vk=(cutoff,self._signature('vix-prefix',vix))
            if vk not in self._vix_contexts:self._vix_contexts[vk]=_india_vix_context(pd.DataFrame(vix) if vix else None)
            return analyze(pd.DataFrame(),horizon_sessions=horizon,_precomputed_features=features,
                           _precomputed_analogue=historical_analogues_numpy(features,horizon),_precomputed_market_vix=self._vix_contexts[vk])
        return self.store.get_or_build(symbol,key,build)
    def _projected_context(self,symbol,cutoff,full,benchmark):
        import pyarrow.parquet as pq
        manifest=self.store.root/'partitions'/(digest([self._code,VERSION,symbol])+'.json')
        try:
            info=json.loads(manifest.read_text())
            if info.get('metadata_sha256')!=digest({k:v for k,v in info.items() if k!='metadata_sha256'}):return None
            last=max((str(r.get('date') or '')[:10] for r in full),default='')
            relevant=[r for r in benchmark if str(r.get('date') or '')[:10]<=last]
            stock_sig=self._signature(('stock-prefix',symbol),full);self._signature('benchmark-prefix',benchmark)
            expected=digest([self._code,VERSION,'numeric',symbol,stock_sig,self._signature('benchmark-prefix',relevant)])
            if info['key']!=expected or not info.get('ranges'):return None
            starts=[r['start'] for r in info['ranges']]
            if any(x is None for x in starts):return None
            n=bisect_right(starts,cutoff)-1
            if n<0:return None,None,False
            part=info['parts'][n]
            if len(part)!=64 or any(c not in '0123456789abcdef' for c in part):return None
            if part not in self._context_frames:
                path=self.store.root/'timelines'/(part+'.parquet');metadata=pq.read_metadata(path)
                if (metadata.metadata or {}).get(b'v10_key')!=part.encode():return None
                schema=json.loads(metadata.metadata[b'pandas']);index=schema['index_columns']
                if not all(isinstance(k,str) for k in index):return None
                table=pq.read_table(path,columns=['_V10_high126','_V10_priorlow20',*index],page_checksum_verification=True)
                self._context_frames[part]=table.to_pandas()
                self.store.stats['disk_reads']+=1;self.store.stats['disk_read_bytes']+=path.stat().st_size
                self.stats['projected_context_reads']=self.stats.get('projected_context_reads',0)+1
                self.stats['projected_context_bytes_materialized']=self.stats.get('projected_context_bytes_materialized',0)+table.nbytes
                while len(self._context_frames)>512:self._context_frames.popitem(last=False)
            self._context_frames.move_to_end(part);frame=self._context_frames[part]
            i=frame.index.searchsorted(pd.Timestamp(cutoff),side='right')-1
            if i<0:return None
            row=frame.iloc[i]
            def valid(v):return float(v) if pd.notna(v) else None
            count=bisect_right(tuple(str(r.get('date') or '')[:10] for r in full),cutoff)
            return valid(row['_V10_high126']),valid(row['_V10_priorlow20']),count>=126
        except (OSError,ValueError,KeyError,TypeError,IndexError):
            self.stats['projected_context_invalidations']=self.stats.get('projected_context_invalidations',0)+1
            return None
    def rolling_price_context(self,symbol,cutoff,*,limit,provider,finite):
        frame=self._numeric.get(symbol)
        if frame is None:
            full=self._full_sources.get(symbol)
            if full is None:full=self.history(symbol,limit,provider);self._full_sources[symbol]=full
            benchmark=self._benchmark_by_symbol.get(symbol)
            if benchmark is None:
                benchmark=[]
                for alias in ('INDEX_NSEI','NSEI','^NSEI','NIFTY'):
                    candidate=self.history(alias,5000,self.history_provider)
                    if candidate:benchmark=candidate;break
            projected=self._projected_context(symbol,cutoff,full,benchmark)
            if projected is not None:return projected
            frame=self._numeric_timeline(symbol,full,benchmark)
        if '_V10_high126' in frame:
            idx=frame.index.searchsorted(pd.Timestamp(cutoff),side='right')-1
            if idx<0:return None,None,False
            row=frame.iloc[idx]
            def valid(v):return float(v) if pd.notna(v) else None
            return valid(row['_V10_high126']),valid(row['_V10_priorlow20']),idx+1>=126
        return super().rolling_price_context(symbol,cutoff,limit=limit,provider=provider,finite=finite)
    def flush(self):
        super().flush();self.stats['feature_elapsed_seconds']=round(time.perf_counter()-self._started,6)


def historical_analogues_numpy(features,horizon_sessions=20,k=None):
    """Exact policies and stable first-tie selection; only matured prefix outcomes."""
    import numpy as np
    from . import technical_v2 as t
    if k is None:k=t.ANALOGUE_K
    if features is None or len(features)<max(t.MIN_BARS,horizon_sessions+80):return {'status':'INSUFFICIENT_HISTORY','sample_size':0,'confidence':'LOW'}
    horizon_sessions=max(1,int(horizon_sessions))
    names=['RSI14','ADX14','MACDHist','ROC20','ATRPct','BBBandwidthPct','CMF20','EMA20Slope5Pct','EMA50Slope5Pct','RS20VsNifty','RS60VsNifty','MarketRegimeCode']
    cols=[c for c in names if c in features]
    insufficient={'status':'INSUFFICIENT_FEATURE_COVERAGE','sample_size':0,'confidence':'LOW'}
    if len(cols)<6:return insufficient
    if any(features[c].dtype.kind not in 'fiu' for c in cols):return t.historical_analogues(features,horizon_sessions,k)
    matrix=np.asfortranarray(features[cols].to_numpy(dtype=float));current=matrix[-1];numeric=matrix[:-horizon_sessions]
    close=features['Close'].to_numpy(dtype=float);returns=close[horizon_sessions:]/close[:-horizon_sessions]-1.0
    regime=t._finite(features.iloc[-1].get('MarketRegimeCode'))
    if regime is not None and 'MarketRegimeCode' in cols:
        same=np.round(numeric[:,cols.index('MarketRegimeCode')],0)==round(regime)
        if int(same.sum())>=t.ANALOGUE_MIN_SAMPLE:numeric=numeric[same];returns=returns[same]
    valid=~np.isnan(current)&(np.sum(~np.isnan(numeric),axis=0)>=30)
    if int(valid.sum())<6:return insufficient
    numeric=np.asfortranarray(numeric[:,valid]);current=current[valid]
    with np.errstate(invalid='ignore',divide='ignore'):
        med=np.nanmedian(numeric,axis=0);quantiles=np.nanquantile(numeric,[.25,.75],axis=0);scale=quantiles[1]-quantiles[0]
        # pandas nanvar uses this two-pass, float64 sum order, ddof=1.
        count=np.sum(~np.isnan(numeric),axis=0);avg=np.nansum(numeric,axis=0)/count
        fallback=np.sqrt(np.nansum((numeric-avg)**2,axis=0)/(count-1))
        scale=np.where((scale==0)|np.isnan(scale),np.where(fallback==0,np.nan,fallback),scale)
        scale=np.where((scale==0)|np.isnan(scale),1.0,scale)
        z=(numeric-med)/scale;cz=(current-med)/scale
        distances=np.sqrt(np.nanmean((z-cz)**2,axis=1))
    eligible=~np.isnan(distances)&~np.isnan(returns)
    if not eligible.any():return {'status':'NO_ELIGIBLE_ANALOGUES','sample_size':0,'confidence':'LOW'}
    dist=distances[eligible];ret=returns[eligible];chosen=np.argsort(dist,kind='stable')[:min(k,len(dist))]
    ret=ret[chosen];distance=float(np.median(dist[chosen]));similarity=1/(1+max(0.,distance));sample=len(chosen)
    return {'status':'READY' if sample>=t.ANALOGUE_MIN_SAMPLE else 'LOW_SAMPLE','sample_size':sample,'requested_k':k,'horizon_sessions':horizon_sessions,
        'median_forward_return':round(float(np.median(ret)),6),'mean_forward_return':round(float(np.mean(ret)),6),'positive_rate':round(float(np.mean(ret>0)),6),
        'p25_forward_return':round(float(np.quantile(ret,.25)),6),'p75_forward_return':round(float(np.quantile(ret,.75)),6),
        'median_distance':round(distance,6),'similarity':round(similarity,6),'confidence':'MEDIUM' if sample>=15 and similarity>=.55 else 'LOW',
        'regime':t._regime_label(regime),'point_in_time_safe':True}


def completed_evidence(directory,source_fingerprint,market_fingerprint,context_signature):
    import zlib
    results=[];stale=invalid=partial=complete=0
    for p in sorted(Path(directory).glob('*.complete.zlib')):
        try:
            obj=json.loads(zlib.decompress(p.read_bytes()));r=obj['value'];proof=r.get('v10_acceptance')
            if not proof:stale+=1;continue
            if (r.get('replay_fundamental_source_fingerprint')!=source_fingerprint or r.get('replay_market_content_signature')!=market_fingerprint or r.get('replay_context_signature')!=context_signature):stale+=1;continue
            if obj.get('key')!=p.name.split('.')[0] or obj.get('schema')!='SRE_REPLAY_CHECKPOINT_V2' or not valid_result(r,proof['contract']):invalid+=1;continue
            if r['pit_completeness']=='COMPLETE':complete+=1
            else:partial+=1
            sessions=r['sessions_replayed'];trades=len(r.get('trades',[]))
            results.append({'period':r['requested_period'],'requested_range':r['requested_range'],'replayed_sessions':sessions,'pit_completeness':r['pit_completeness'],
                'excluded_sessions':r['sessions_excluded'],'metrics':r['metrics'],'research_only':True,'survivorship_bias_warning':r.get('survivorship_bias_warning',True),
                'closed_trade_sample':trades,'sample_status':'INSUFFICIENT_SAMPLE' if sessions<20 or trades<3 else 'RESEARCH_SAMPLE_ONLY',
                'benchmark_status':r.get('benchmark_status'),'benchmark_comparison_available':r.get('benchmark_status')=='ACTUAL_NIFTY_50' and r['metrics'].get('benchmark_return') is not None,'strategy_validated':False,'replay_integrity_checked':True})
        except (OSError,ValueError,KeyError,TypeError,zlib.error):invalid+=1
    return {'schema':VERSION,'authority':'RESEARCH_ONLY','affects_live_decisions':False,'complete_replays':complete,'partial_replays':partial,
        'stale_replays':stale,'invalid_replays':invalid,'results':results,'strategy_validated':False,
        'status':'RESEARCH_RESULTS_AVAILABLE' if complete else ('INSUFFICIENT_PIT_COVERAGE' if partial else 'NOT_VALIDATED'),
        'notice':'Current surviving universe; replay integrity is not out-of-sample strategy validation. Stale, corrupt or unattested caches never validate evidence. Frozen LIVE_DECISION_V1 rules are unchanged.'}
