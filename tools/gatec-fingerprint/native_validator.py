def valid_result(result, identity):
    """Validate persisted completed output, not merely the presence of a cache file."""
    try:
        proof = result['v10_acceptance']
        key = digest(identity)
        if proof['contract'] != identity or proof['key'] != key:
            return False
        payload = {k: v for k, v in result.items() if k not in ('v10_acceptance', 'replay_cache_status', 'replay_request_stats', 'replay_input_cache_stats')}
        if proof['payload_sha256'] != digest(payload):
            return False
        sessions = identity['sessions']
        coverage = result['coverage']
        series = result['series']
        if result.get('schema') != 'SRE_POINT_IN_TIME_HISTORICAL_REPLAY_V2' or result.get('requested_period') != identity['config']['period']:
            return False
        if result['requested_range'] != {'start': sessions[0] if sessions else None, 'end': sessions[-1] if sessions else None}:
            return False
        if [r['date'] for r in coverage] != sessions:
            return False
        eligible = [r['date'] for r in coverage if r['replayability'] in ('FULL_PIT_VALID', 'PIT_VALID_WITH_OPTIONAL_GAPS')]
        if [r['date'] for r in series] != eligible:
            return False
        if len(set(sessions)) != len(sessions):
            return False
        if result['sessions_replayed'] != len(series) or result['sessions_excluded'] != len(coverage) - len(series):
            return False
        a = result['execution_assumptions']
        c = identity['config']
        for k in ('starting_capital', 'slippage_bps', 'transaction_cost_bps'):
            if float(a[k]) != c[k]:
                return False
        if a.get('broker_execution') is not False or result.get('automatic_yfinance_fallback') is not False:
            return False
        for r in series:
            if not all((math.isfinite(float(r[k])) for k in ('portfolio_nav', 'cash', 'invested_value'))):
                return False
            if abs(r['portfolio_nav'] - r['cash'] - r['invested_value']) > 0.021:
                return False
        expected = 'COMPLETE' if coverage and len(series) == len(coverage) else 'PARTIAL' if series else 'NOT REPLAYABLE'
        return result['pit_completeness'] == expected and result['v10']['affects_live_decisions'] is False
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

def attest(result, identity):
    result.pop('v10_acceptance', None)
    payload = {k: v for k, v in result.items() if k not in ('replay_cache_status', 'replay_request_stats', 'replay_input_cache_stats')}
    result['v10_acceptance'] = {'key': digest(identity), 'contract': identity, 'payload_sha256': digest(payload)}
    if not valid_result(result, identity):
        raise RuntimeError('V10_COMPLETED_RESULT_VALIDATION_FAILED')

def completed_evidence(directory, source_fingerprint, market_fingerprint, context_signature):
    import zlib
    results = []
    stale = invalid = partial = complete = 0
    for p in sorted(Path(directory).glob('*.complete.zlib')):
        try:
            obj = json.loads(zlib.decompress(p.read_bytes()))
            r = obj['value']
            proof = r.get('v10_acceptance')
            if not proof:
                stale += 1
                continue
            if r.get('replay_fundamental_source_fingerprint') != source_fingerprint or r.get('replay_market_content_signature') != market_fingerprint or r.get('replay_context_signature') != context_signature:
                stale += 1
                continue
            if obj.get('key') != p.name.split('.')[0] or obj.get('schema') != 'SRE_REPLAY_CHECKPOINT_V2' or (not valid_result(r, proof['contract'])):
                invalid += 1
                continue
            if r['pit_completeness'] == 'COMPLETE':
                complete += 1
            else:
                partial += 1
            sessions = r['sessions_replayed']
            trades = len(r.get('trades', []))
            results.append({'period': r['requested_period'], 'requested_range': r['requested_range'], 'replayed_sessions': sessions, 'pit_completeness': r['pit_completeness'], 'excluded_sessions': r['sessions_excluded'], 'metrics': r['metrics'], 'research_only': True, 'survivorship_bias_warning': r.get('survivorship_bias_warning', True), 'closed_trade_sample': trades, 'sample_status': 'INSUFFICIENT_SAMPLE' if sessions < 20 or trades < 3 else 'RESEARCH_SAMPLE_ONLY', 'benchmark_status': r.get('benchmark_status'), 'benchmark_comparison_available': r.get('benchmark_status') == 'ACTUAL_NIFTY_50' and r['metrics'].get('benchmark_return') is not None, 'strategy_validated': False, 'replay_integrity_checked': True})
        except (OSError, ValueError, KeyError, TypeError, zlib.error):
            invalid += 1
    return {'schema': VERSION, 'authority': 'RESEARCH_ONLY', 'affects_live_decisions': False, 'complete_replays': complete, 'partial_replays': partial, 'stale_replays': stale, 'invalid_replays': invalid, 'results': results, 'strategy_validated': False, 'status': 'RESEARCH_RESULTS_AVAILABLE' if complete else 'INSUFFICIENT_PIT_COVERAGE' if partial else 'NOT_VALIDATED', 'notice': 'Current surviving universe; replay integrity is not out-of-sample strategy validation. Stale, corrupt or unattested caches never validate evidence. Frozen LIVE_DECISION_V1 rules are unchanged.'}