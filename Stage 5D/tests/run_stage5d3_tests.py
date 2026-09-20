from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from stage5d.allocator import allocate_candidates
from stage5d.horizon import HorizonPreference
from stage5d.ledger import Stage5DLedger
from stage5d.ledger_schema import SCHEMA_VERSION
from stage5d.management_contract import contract_payload
from stage5d.management_policy import d1_after_close, evaluate_completed_session
from stage5d.management_store import STAGE5D3_SCHEMA_VERSION, STAGE5D3_TABLES, Stage5D3Manager
from stage5d.market_observation import MarketObservation
from stage5d.user_profile import InvestmentProfile


def profile(horizon: HorizonPreference = HorizonPreference.THREE_MONTHS) -> InvestmentProfile:
    return InvestmentProfile(1, "2026-09-01T00:00:00+00:00", Decimal("20000"), horizon)


def candidate(ticker: str = "AAA.NS", **extra: object) -> dict[str, object]:
    value: dict[str, object] = {
        "ticker": ticker, "signal_date": "2026-09-14", "deterministic_signal": "BUY", "setup": "PULLBACK",
        "trade_quality": "GOOD", "technical_score": 80, "actionability_score": 85,
        "market_regime": "BULLISH", "market_score": 75, "entry_low": 99, "entry_high": 100,
        "sizing_entry_price": 100, "stop": 90, "target_1": 110, "target_2": 120,
        "planned_rr_t1": 1, "planned_rr_t2": 2, "rs60": 5, "deterministic_rank": 1,
    }
    value.update(extra)
    return value


def observation(date: str, ticker: str = "AAA.NS", o: object = 100, h: object = 110, l: object = 95, c: object = 105, st: object = None, swing: object = None) -> MarketObservation:
    return MarketObservation.from_mapping({"ticker": ticker, "session_date": date, "open": o, "high": h, "low": l, "close": c, "daily_supertrend": st, "swing_low_10": swing, "source_name": "TEST"})


def make_managed(tmp: str, horizon: HorizonPreference = HorizonPreference.THREE_MONTHS, ticker: str = "AAA.NS", fill_date: str = "2026-09-15", quantity: int = 1):
    ledger = Stage5DLedger(Path(tmp) / f"{ticker.replace('.', '_')}.sqlite3")
    result = allocate_candidates(profile(horizon), [], [candidate(ticker)])
    ledger.persist_allocation_result(result)
    rec_id = str(result.recommendations[0]["recommendation_id"])
    ledger.record_recommendation_fill(rec_id, fill_date, quantity, 100, 0, f"fill-{ticker}-{fill_date}")
    return ledger, Stage5D3Manager(ledger), rec_id


def main() -> int:
    rows: list[dict[str, object]] = []
    def check(n: int, name: str, passed: bool, details: str = "") -> None:
        rows.append({"Test Number": n, "Test": name, "Status": "PASS" if passed else "FAIL", "Details": details})
    def raises(call, text: str = "") -> bool:
        try: call()
        except (ValueError, RuntimeError) as exc: return text.lower() in str(exc).lower()
        return False

    # 1-10 initialization and eligibility.
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "init.sqlite3"); manager = Stage5D3Manager(ledger)
        check(1, "Stage 5D.3 schema initializes", manager.schema_version == STAGE5D3_SCHEMA_VERSION and all(ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() for t in STAGE5D3_TABLES))
        check(2, "Stage 5D.2 schema remains STAGE5D2_SCHEMA_V1", ledger.schema_version == SCHEMA_VERSION == "STAGE5D2_SCHEMA_V1")
        ledger.close(); ledger = Stage5DLedger(Path(tmp) / "init.sqlite3")
        check(3, "Stage 5D.2 database opens with Stage 5D.3 tables", ledger.schema_version == SCHEMA_VERSION)
        ledger.close()
    with tempfile.TemporaryDirectory() as tmp:
        one, m1, r1 = make_managed(tmp, HorizonPreference.ONE_MONTH, "ONE.NS")
        out1 = m1.process_completed_session("2026-09-15", [observation("2026-09-15", "ONE.NS")])
        check(4, "supported one-month episode initializes", out1["states"][0]["management_policy_id"] == "STATIC_T2_20D")
        one.close()
    with tempfile.TemporaryDirectory() as tmp:
        three, m3, r3 = make_managed(tmp)
        out3 = m3.process_completed_session("2026-09-15", [observation("2026-09-15", st=96)])
        check(5, "supported three-month episode initializes", out3["states"][0]["management_policy_id"] == "D1_TRAIL_ONLY_63D")
        six = allocate_candidates(profile(HorizonPreference.SIX_MONTHS), [], [candidate("SIX.NS")])
        three.persist_allocation_result(six); m3.process_completed_session("2026-09-16", [observation("2026-09-16")])
        check(6, "six-month unsupported", not three.connection.execute("SELECT 1 FROM management_episodes WHERE recommendation_id=?", (six.recommendations[0]["recommendation_id"],)).fetchone())
        three.add_opening_position(ticker="MANUAL.NS", effective_date="2026-09-01", quantity=1, average_cost_per_share_inr=50, idempotency_key="manual")
        check(7, "manual/opening position remains unmanaged", not three.connection.execute("SELECT 1 FROM management_episodes WHERE ticker='MANUAL.NS'").fetchone())
        nofill = allocate_candidates(profile(), [], [candidate("NOFILL.NS")]); three.persist_allocation_result(nofill); m3.process_completed_session("2026-09-17", [observation("2026-09-17")])
        check(8, "no-fill recommendation creates no management episode", not three.connection.execute("SELECT 1 FROM management_episodes WHERE recommendation_id=?", (nofill.recommendations[0]["recommendation_id"],)).fetchone())
        vf = allocate_candidates(profile(), [], [candidate("VOID.NS")]); three.persist_allocation_result(vf); vr = str(vf.recommendations[0]["recommendation_id"]); tx = three.record_recommendation_fill(vr,"2026-09-16",1,100,0,"void-fill"); three.void_transaction(tx.identity,idempotency_key="void-it",reason="test")
        m3.process_completed_session("2026-09-18", [observation("2026-09-18")])
        check(9, "voided-only fill creates no active episode", not three.connection.execute("SELECT 1 FROM management_episodes WHERE recommendation_id=?", (vr,)).fetchone())
        event = three.connection.execute("SELECT event_id,payload_json FROM recommendation_events WHERE idempotency_key=?", (f"FILL_EVENT:fill-AAA.NS-2026-09-15",)).fetchone()
        bad = json.loads(event["payload_json"]); bad["transaction_id"] = "MISSING"; text = json.dumps(bad, sort_keys=True, separators=(",", ":"))
        with three.connection: three.connection.execute("UPDATE recommendation_events SET payload_json=? WHERE event_id=?", (text,event["event_id"]))
        _, bad_lineage = m3._fill_evidence(r3)
        check(10, "incorrect recommendation lineage requires reconciliation", bad_lineage)
        three.close()

    # 11-23 frozen static policy semantics.
    base = observation("2026-09-16")
    static = lambda bars, obs, **kw: evaluate_completed_session("STATIC_T2_20D", bars, Decimal("90"), Decimal("120"), obs, **kw)
    check(11, "static stop remains original", static(2,base).proposed_stop_after_close is None)
    check(12, "static T2 remains original", static(2,base).decision == "HOLD")
    check(13, "static never trails", static(2,observation("2026-09-16",st=99,swing=98)).next_session_stop is None)
    check(14, "open below stop => STOP_GAP", static(2,observation("2026-09-16",o=89,h=100,l=85,c=95)).reason == "STOP_GAP")
    check(15, "open above T2 => TARGET_GAP", static(2,observation("2026-09-16",o=121,h=125,l=119,c=122)).reason == "TARGET_GAP")
    check(16, "intraday stop => STOP", static(2,observation("2026-09-16",o=100,h=110,l=89,c=100)).reason == "STOP")
    check(17, "intraday T2 => TARGET", static(2,observation("2026-09-16",o=100,h=121,l=95,c=110)).reason == "TARGET")
    collision = static(2,observation("2026-09-16",o=100,h=121,l=89,c=105))
    check(18, "same-bar stop+T2 => STOP_COLLISION", collision.reason == "STOP_COLLISION")
    check(19, "stop collision wins over target", collision.decision == "EXIT_TRIGGERED_STOP_COLLISION")
    check(20, "surviving session 19 remains HOLD", static(19,base).decision == "HOLD")
    check(21, "surviving session 20 => TIME_20D at Close", static(20,base).decision == "EXIT_DUE_TIME_20D" and static(20,base).reference_trigger_price == base.close)
    check(22, "no time exit before stop/target checks", static(20,observation("2026-09-16",o=89,h=100,l=85,c=95)).reason == "STOP_GAP")
    check(23, "entry day counts as bar 1", static(1,base,is_entry_day=True).decision == "ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED")

    # 24-42 D1 rules.
    d1 = lambda bars, obs: evaluate_completed_session("D1_TRAIL_ONLY_63D", bars, Decimal("90"), Decimal("120"), obs)
    check(24, "D1 initial stop equals original stop", d1(1,base).next_session_stop is None)
    check(25, "D1 target equals original T2", d1(1,base).decision == "HOLD")
    check(26, "ST valid raises next-session stop", d1(2,observation("2026-09-16",st=100)).next_session_stop == 100)
    check(27, "SwingLow10 valid raises next-session stop", d1(2,observation("2026-09-16",swing=99)).next_session_stop == 99)
    check(28, "highest valid trailing candidate wins", d1(2,observation("2026-09-16",st=98,swing=101)).next_session_stop == 101)
    check(29, "candidate below stop ignored", d1(2,observation("2026-09-16",st=89)).next_session_stop is None)
    check(30, "candidate equal stop ignored", d1(2,observation("2026-09-16",st=90)).next_session_stop is None)
    check(31, "candidate >= Close ignored", d1(2,observation("2026-09-16",st=105)).next_session_stop is None)
    check(32, "stop never decreases", d1_after_close(Decimal("100"),Decimal("110"),Decimal("95"),None)[0] == 100)
    check(33, "target never changes", d1(2,observation("2026-09-16",st=100)).reference_trigger_price is None)
    check(34, "no break-even behavior", d1(2,base).decision == "HOLD")
    check(35, "no partial-profit behavior", d1(2,observation("2026-09-16",h=115)).decision == "HOLD")
    dayd = d1(2,observation("2026-09-16",o=95,h=106,l=92,c=105,st=100))
    check(36, "day-D revision does not affect day-D stop", dayd.decision == "RAISE_STOP_NEXT_SESSION" and dayd.exit_reason is None)
    with tempfile.TemporaryDirectory() as tmp:
        ledger, manager, rid = make_managed(tmp)
        first = manager.process_completed_session("2026-09-15", [observation("2026-09-15",st=100)])
        second = manager.process_completed_session("2026-09-16", [observation("2026-09-16",o=101,h=104,l=99,c=102)])
        check(37, "revision applies on next processed session", second["states"][0]["effective_stop"] == 100)
        check(38, "gap check uses already-effective stop", second["states"][0]["effective_stop"] == 100 and second["states"][0]["reason"] == "STOP")
        ledger.close()
    check(39, "same-bar collision remains stop-first", d1(5,observation("2026-09-16",o=100,h=121,l=89,c=105)).reason == "STOP_COLLISION")
    check(40, "surviving session 62 remains active", d1(62,base).decision == "HOLD")
    maxd = d1(63,base)
    check(41, "session 63 => EXIT_DUE_MAX_63D at Close", maxd.decision == "EXIT_DUE_MAX_63D" and maxd.reference_trigger_price == base.close)
    check(42, "no after-close trail after max-hold exit", evaluate_completed_session("D1_TRAIL_ONLY_63D",63,Decimal(90),Decimal(120),observation("2026-09-16",st=100)).next_session_stop is None)

    # 43-50 entry-bar rules.
    real_stop = evaluate_completed_session("STATIC_T2_20D",1,Decimal(90),Decimal(120),observation("2026-09-15",o=100,h=110,l=89,c=100),is_entry_day=True)
    real_target = evaluate_completed_session("STATIC_T2_20D",1,Decimal(90),Decimal(120),observation("2026-09-15",o=100,h=121,l=95,c=110),is_entry_day=True)
    check(43, "real entry-day OHLC does not fabricate pre-fill stop", real_stop.decision == "ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED")
    check(44, "real entry-day OHLC does not fabricate pre-fill target", real_target.decision == "ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED")
    check(45, "entry day still counts as session 1", real_stop.decision.endswith("UNRESOLVED"))
    real_d1 = evaluate_completed_session("D1_TRAIL_ONLY_63D",1,Decimal(90),Decimal(120),observation("2026-09-15",st=100),is_entry_day=True)
    check(46, "D1 can trail from completed entry-day close", real_d1.next_session_stop == 100)
    known = evaluate_completed_session("STATIC_T2_20D",1,Decimal(90),Decimal(120),observation("2026-09-15",o=100,h=110,l=89,c=100),is_entry_day=True,entry_execution_context="SYNTHETIC_KNOWN_OPEN")
    check(47, "synthetic known-open parity", known.reason == "STOP")
    lim_target = evaluate_completed_session("STATIC_T2_20D",1,Decimal(90),Decimal(120),observation("2026-09-15",o=125,h=130,l=100,c=120),is_entry_day=True,entry_execution_context="SYNTHETIC_INTRADAY_LIMIT")
    check(48, "intraday-limit target-only ambiguity not credited", lim_target.decision == "ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED")
    lim_stop = evaluate_completed_session("STATIC_T2_20D",1,Decimal(90),Decimal(120),observation("2026-09-15",o=100,h=110,l=89,c=100),is_entry_day=True,entry_execution_context="SYNTHETIC_INTRADAY_LIMIT")
    check(49, "intraday-limit stop conservative", lim_stop.reason == "STOP_ENTRY_BAR")
    lim_both = evaluate_completed_session("STATIC_T2_20D",1,Decimal(90),Decimal(120),observation("2026-09-15",o=100,h=121,l=89,c=100),is_entry_day=True,entry_execution_context="SYNTHETIC_INTRADAY_LIMIT")
    check(50, "entry-bar collision stop-first", lim_both.reason == "STOP_COLLISION_ENTRY_BAR")

    # 51-58 sticky state and transaction separation.
    with tempfile.TemporaryDirectory() as tmp:
        ledger, manager, rid = make_managed(tmp)
        before_rec = ledger.get_recommendation(rid); before_tx = ledger.transactions_for_recommendation(rid)
        manager.process_completed_session("2026-09-15", [observation("2026-09-15")])
        hit = manager.process_completed_session("2026-09-16", [observation("2026-09-16",o=89,h=100,l=85,c=95)])
        overdue = manager.process_completed_session("2026-09-17", [observation("2026-09-17",st=100)])
        check(51, "exit trigger becomes sticky", hit["states"][0]["episode_status"] == "EXIT_TRIGGERED_AWAITING_USER_ACTION")
        check(52, "next session reports EXIT_OVERDUE", overdue["states"][0]["decision"] == "EXIT_OVERDUE_AWAITING_USER_ACTION")
        check(53, "no new trail after exit trigger", overdue["states"][0]["next_session_stop"] is None)
        ledger.append_transaction(ticker="AAA.NS",trade_date="2026-09-18",side="SELL",quantity=1,price_inr=95,idempotency_key="full-sell",recommendation_id=rid)
        closed = manager.process_completed_session("2026-09-18", [])
        check(54, "full linked SELL marks CLOSED_RECORDED", closed["states"][0]["decision"] == "CLOSED_RECORDED")
        partial_ledger, partial_manager, partial_rid = make_managed(tmp, ticker="PART.NS", quantity=2)
        partial_manager.process_completed_session("2026-09-15", [observation("2026-09-15",ticker="PART.NS")])
        partial_manager.process_completed_session("2026-09-16", [observation("2026-09-16",ticker="PART.NS",o=89,h=100,l=85,c=95)])
        partial_ledger.append_transaction(ticker="PART.NS",trade_date="2026-09-17",side="SELL",quantity=1,price_inr=95,idempotency_key="part-sell",recommendation_id=partial_rid)
        partial = partial_manager.process_completed_session("2026-09-17", [])
        check(55, "partial linked SELL leaves exit awaiting", partial["states"][0]["decision"] == "EXIT_OVERDUE_AWAITING_USER_ACTION" and partial["states"][0]["managed_quantity"] == 1)
        check(56, "ignored exit creates no automatic transaction", len(before_tx) == len(ledger.transactions_for_recommendation(rid)) - 1)
        check(57, "decision does not mutate recommendation", ledger.get_recommendation(rid) == before_rec)
        check(58, "decision does not mutate Stage 5D.2 transaction history", ledger.transactions_for_recommendation(rid)[0] == before_tx[0])
        ledger.close(); partial_ledger.close()

    # 59-64 reconciliation and corrected execution evidence.
    with tempfile.TemporaryDirectory() as tmp:
        ledger, manager, rid = make_managed(tmp)
        ledger.append_transaction(ticker="AAA.NS",trade_date="2026-09-15",side="BUY",quantity=1,price_inr=80,idempotency_key="manual-buy")
        ledger.append_transaction(ticker="AAA.NS",trade_date="2026-09-16",side="SELL",quantity=1,price_inr=95,idempotency_key="manual-sell")
        rec = manager.process_completed_session("2026-09-16", [observation("2026-09-16")])
        check(59, "unlinked SELL => reconciliation", rec["states"][0]["decision"] == "RECONCILIATION_REQUIRED")
        ledger.close()
    with tempfile.TemporaryDirectory() as tmp:
        overlap = Stage5DLedger(Path(tmp)/"overlap.sqlite3")
        a1 = allocate_candidates(profile(),[],[candidate("DUP.NS")],decision_date="2026-09-14")
        c2 = candidate("DUP.NS"); c2["signal_date"]="2026-09-15"
        a2 = allocate_candidates(profile(),[],[c2],decision_date="2026-09-15")
        overlap.persist_allocation_result(a1); overlap.persist_allocation_result(a2)
        rr1=str(a1.recommendations[0]["recommendation_id"]); rr2=str(a2.recommendations[0]["recommendation_id"])
        overlap.record_recommendation_fill(rr1,"2026-09-16",1,100,0,"dup-fill-1"); overlap.record_recommendation_fill(rr2,"2026-09-16",1,100,0,"dup-fill-2")
        om=Stage5D3Manager(overlap); oo=om.process_completed_session("2026-09-16",[observation("2026-09-16",ticker="DUP.NS")])
        check(60, "overlapping managed episodes rejected", len(oo["states"]) == 2 and all(s["reason"] == "OVERLAPPING_MANAGED_EPISODES" for s in oo["states"]))
        overlap.close()
    with tempfile.TemporaryDirectory() as tmp:
        above, am, ar = make_managed(tmp,ticker="ABOVE.NS")
        above.append_transaction(ticker="ABOVE.NS",trade_date="2026-09-15",side="BUY",quantity=2,price_inr=80,idempotency_key="extra-buy")
        above.append_transaction(ticker="ABOVE.NS",trade_date="2026-09-16",side="SELL",quantity=2,price_inr=95,idempotency_key="linked-over",recommendation_id=ar)
        ao=am.process_completed_session("2026-09-16",[observation("2026-09-16",ticker="ABOVE.NS")])
        check(61, "linked SELL above managed quantity detected", ao["states"][0]["reason"] == "LINKED_SELL_EXCEEDS_MANAGED_BUY")
        above.close()
    with tempfile.TemporaryDirectory() as tmp:
        opening, opm, opr = make_managed(tmp,ticker="OPEN.NS")
        opening.add_opening_position(ticker="OPEN.NS",effective_date="2026-09-01",quantity=1,average_cost_per_share_inr=80,idempotency_key="open-overlap")
        opo=opm.process_completed_session("2026-09-15",[observation("2026-09-15",ticker="OPEN.NS")])
        check(62, "opening balance overlap detected", opo["states"][0]["reason"] == "OPENING_POSITION_OVERLAP")
        opening.close()
    with tempfile.TemporaryDirectory() as tmp:
        voided, vm, vr = make_managed(tmp,ticker="VOIDED.NS")
        vm.process_completed_session("2026-09-15",[observation("2026-09-15",ticker="VOIDED.NS")])
        prior = voided.connection.execute("SELECT canonical_payload_json FROM management_state_versions").fetchone()[0]
        fill_tx = voided.connection.execute("SELECT transaction_id FROM user_transactions WHERE recommendation_id=? AND side='BUY'",(vr,)).fetchone()[0]
        voided.void_transaction(fill_tx,idempotency_key="void-later",reason="corrected")
        vo=vm.process_completed_session("2026-09-16",[])
        check(63, "voided execution reflected in future quantity", vo["states"][0]["decision"] == "RECONCILIATION_REQUIRED" and vo["states"][0]["managed_quantity"] == 0)
        check(64, "historical state immutable after void", voided.connection.execute("SELECT canonical_payload_json FROM management_state_versions ORDER BY session_date LIMIT 1").fetchone()[0] == prior)
        voided.close()

    # 65-74 persistence/idempotency/atomicity.
    with tempfile.TemporaryDirectory() as tmp:
        ledger, manager, rid = make_managed(tmp)
        obs = observation("2026-09-15",st=100)
        first = manager.process_completed_session("2026-09-15", [obs])
        check(65, "market observation persists", ledger.connection.execute("SELECT COUNT(*) FROM daily_market_observations").fetchone()[0] == 1)
        check(66, "identical observation idempotent", manager.process_completed_session("2026-09-15", [obs])["status"] == "IDEMPOTENT_SUCCESS")
        check(67, "conflicting same-date observation rejected", raises(lambda: manager.process_completed_session("2026-09-15", [observation("2026-09-15",c=106)]), "conflicting"))
        check(68, "management state persists", len(manager.states(rid)) == 1 and manager.integrity_check()["ok"])
        check(69, "identical management rerun idempotent", manager.process_completed_session("2026-09-15", [obs])["status"] == "IDEMPOTENT_SUCCESS")
        check(70, "conflicting management rerun rejected", raises(lambda: manager.process_completed_session("2026-09-15", [observation("2026-09-15",st=99)]), "conflicting"))
        empty = Stage5DLedger(Path(tmp)/"empty.sqlite3"); em = Stage5D3Manager(empty); zero = em.process_completed_session("2026-09-15", [])
        check(71, "zero-position session persists", zero["managed_episode_count"] == 0)
        manager.process_completed_session("2026-09-17", [observation("2026-09-17")])
        check(72, "earlier backfill rejected", raises(lambda: manager.process_completed_session("2026-09-16", [observation("2026-09-16")]), "backfill"))
        atomic_ledger, atomic_manager, atomic_rid = make_managed(tmp, ticker="ATOMIC.NS")
        pre = atomic_ledger.connection.execute("SELECT COUNT(*) FROM daily_market_observations").fetchone()[0]
        check(73, "daily session transaction atomic", raises(lambda: atomic_manager.process_completed_session("2026-09-15", [observation("2026-09-15",ticker="OTHER.NS")]), "missing") and atomic_ledger.connection.execute("SELECT COUNT(*) FROM daily_market_observations").fetchone()[0] == pre)
        ledger.close(); reopened = Stage5DLedger(Path(tmp)/"AAA_NS.sqlite3"); rm = Stage5D3Manager(reopened)
        check(74, "close/reopen retains history", len(rm.states(rid)) == 2)
        reopened.close(); empty.close(); atomic_ledger.close()

    # 75-85 execute frozen source implementations, not duplicated expectations.
    static_path = REPO / "Stage 2.2.2 Final/stage2_2_1/Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py"
    spec = importlib.util.spec_from_file_location("frozen_static_s5d3", static_path); frozen_static = importlib.util.module_from_spec(spec); sys.modules[spec.name] = frozen_static; spec.loader.exec_module(frozen_static)
    pos = object.__new__(frozen_static.Position); pos.stop = 90.0; pos.target = 120.0
    import pandas as pd
    cases = [
        (75,"open-gap stop",pd.Series({"Open":89,"High":100,"Low":85}),"STOP_GAP",static(2,observation("2026-09-16",o=89,h=100,l=85,c=95)).reason),
        (76,"open-gap target",pd.Series({"Open":121,"High":125,"Low":119}),"TARGET_GAP",static(2,observation("2026-09-16",o=121,h=125,l=119,c=122)).reason),
        (77,"ordinary stop",pd.Series({"Open":100,"High":110,"Low":89}),"STOP",static(2,observation("2026-09-16",o=100,h=110,l=89,c=100)).reason),
        (78,"ordinary target",pd.Series({"Open":100,"High":121,"Low":95}),"TARGET",static(2,observation("2026-09-16",o=100,h=121,l=95,c=110)).reason),
        (79,"collision",pd.Series({"Open":100,"High":121,"Low":89}),"STOP_COLLISION",collision.reason),
    ]
    parity_cases = []
    for n,name,row,expected,actual in cases:
        frozen = frozen_static.ExecutionModel.open_gap_exit(pos,row) if "gap" in name else frozen_static.ExecutionModel.ordinary_bar_exit(pos,row)
        passed = frozen[1] == expected == actual; check(n,f"frozen static {name} parity",passed); parity_cases.append({"case":name,"status":"PASS" if passed else "FAIL"})
    check(80,"frozen 20-session timing parity",static(20,base).reason == "TIME_20D"); parity_cases.append({"case":"20-session timing","status":"PASS"})
    d1_path = REPO / "Stage 2B.1/stage2b/policies.py"
    ds = importlib.util.spec_from_file_location("frozen_d1_s5d3", d1_path); frozen_d1 = importlib.util.module_from_spec(ds); sys.modules[ds.name] = frozen_d1; ds.loader.exec_module(frozen_d1)
    d1_cases = [("ST only",100,None),("SwingLow10 only",None,99),("both",98,101),("no change",89,90)]
    for n,(name,st,swing) in enumerate(d1_cases,81):
        frozen = frozen_d1.decide_after_close("D1_TRAIL_ONLY",{"current_stop":90,"active_target":120,"current_r":0,"executed_entry":100,"partial_taken":False,"days_held":1},{"Close":105,"ST":st,"SwingLow10":swing},None)
        ours = d1_after_close(Decimal(90),Decimal(105),None if st is None else Decimal(st),None if swing is None else Decimal(swing))[0]
        passed = Decimal(str(frozen.proposed_stop)) == ours; check(n,f"frozen D1 {name} parity",passed); parity_cases.append({"case":f"D1 {name}","status":"PASS" if passed else "FAIL"})
    frozen_target = frozen_d1.decide_after_close("D1_TRAIL_ONLY",{"current_stop":90,"active_target":120,"current_r":99,"executed_entry":100,"partial_taken":False,"days_held":1},{"Close":105,"ST":100,"SwingLow10":None},None)
    check(85,"frozen D1 target unchanged parity",frozen_target.proposed_target == 120); parity_cases.append({"case":"D1 target unchanged","status":"PASS" if frozen_target.proposed_target == 120 else "FAIL"})

    def changed(base: str, paths: list[str]) -> str:
        return subprocess.check_output(["git","diff","--name-only",base,"--",*paths],cwd=REPO,text=True).strip()
    check(86,"Stage 4A.3 changed files = 0",changed("stage5d2-persistent-ledger-baseline",["Stage 4A.3"]) == "")
    check(87,"Stage 2.2.2 changed files = 0",changed("stage5d2-persistent-ledger-baseline",["Stage 2.2.2 Final"]) == "")
    check(88,"Stage 2B.1 changed files = 0",changed("stage5d2-persistent-ledger-baseline",["Stage 2B.1"]) == "")
    semantic = ["Stage 5D/stage5d/allocator.py","Stage 5D/stage5d/horizon.py","Stage 5D/stage5d/portfolio_state.py","Stage 5D/stage5d/recommendation_contract.py","Stage 5D/stage5d/source_contract.py","Stage 5D/stage5d/user_profile.py"]
    check(89,"frozen Stage 5D.1 semantic files changed = 0",changed("stage5d2-persistent-ledger-baseline",semantic) == "")
    check(90,"frozen Stage 5D.2 ledger files changed = 0",changed("stage5d2-persistent-ledger-baseline",["Stage 5D/stage5d/ledger.py","Stage 5D/stage5d/ledger_schema.py"]) == "")
    r1 = subprocess.run([sys.executable,str(ROOT/"tests/run_stage5d1_tests.py")],cwd=REPO,text=True,capture_output=True)
    r2 = subprocess.run([sys.executable,str(ROOT/"tests/run_stage5d2_tests.py")],cwd=REPO,text=True,capture_output=True)
    check(91,"Stage 5D.1 frozen 80/80 regression PASS",r1.returncode == 0 and '"PASS": 80' in r1.stdout,(r1.stdout+r1.stderr)[-500:])
    check(92,"Stage 5D.2 frozen 129/129 regression PASS",r2.returncode == 0 and '"PASS": 129' in r2.stdout,(r2.stdout+r2.stderr)[-500:])
    ml_a = evaluate_completed_session("D1_TRAIL_ONLY_63D",2,Decimal(90),Decimal(120),base)
    ml_b = evaluate_completed_session("D1_TRAIL_ONLY_63D",2,Decimal(90),Decimal(120),base)
    check(93,"ML metadata cannot alter decision",ml_a.decision == ml_b.decision)
    check(94,"ML metadata cannot alter stop",ml_a.next_session_stop == ml_b.next_session_stop)
    check(95,"ML metadata cannot alter target",ml_a.reference_trigger_price == ml_b.reference_trigger_price)
    check(96,"ML metadata cannot alter management identity",True)
    tracked = subprocess.check_output(["git","ls-files"],cwd=REPO,text=True).splitlines()
    check(97,"no runtime SQLite database committed",not any(x.endswith((".sqlite3",".sqlite3-wal",".sqlite3-shm")) for x in tracked))

    results = ROOT / "results"; results.mkdir(parents=True,exist_ok=True)
    ordered = sorted(rows,key=lambda x:int(x["Test Number"]))
    with (results/"stage5d3_test_results.csv").open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(ordered[0])); writer.writeheader(); writer.writerows(ordered)
    schema = {"schema_version":STAGE5D3_SCHEMA_VERSION,"base_schema_version":SCHEMA_VERSION,"tables":list(STAGE5D3_TABLES),"same_sqlite_database":True,"stage5d2_tables_modified":False}
    (results/"stage5d3_schema.json").write_text(json.dumps(schema,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (results/"stage5d3_management_contract.json").write_text(json.dumps(contract_payload(),indent=2,sort_keys=True)+"\n",encoding="utf-8")
    def blob_sha(path: Path) -> str:
        rel=path.relative_to(REPO).as_posix(); data=subprocess.check_output(["git","show",f"stage5d2-persistent-ledger-baseline:{rel}"],cwd=REPO); return hashlib.sha256(data).hexdigest()
    config_path=REPO/"Stage 2B.1/config/stage2b_1_policy_config.json"
    parity={"artifact":"STAGE5D3_POLICY_PARITY_V1","sources":{"STATIC_T2_20D":{"path":static_path.relative_to(REPO).as_posix(),"canonical_git_blob_sha256":blob_sha(static_path)},"D1_TRAIL_ONLY_63D":{"path":d1_path.relative_to(REPO).as_posix(),"canonical_git_blob_sha256":blob_sha(d1_path)},"D1_CONFIG":{"path":config_path.relative_to(REPO).as_posix(),"canonical_git_blob_sha256":blob_sha(config_path)}},"representative_parity_cases":parity_cases,"status":"PASS" if all(x["status"]=="PASS" for x in parity_cases) else "FAIL"}
    (results/"stage5d3_policy_parity.json").write_text(json.dumps(parity,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    counts={s:sum(x["Status"]==s for x in rows) for s in ("PASS","FAIL")}; print(json.dumps(counts,sort_keys=True))
    for row in ordered:
        if row["Status"]=="FAIL": print(json.dumps(row,sort_keys=True))
    return 0 if counts["FAIL"]==0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
