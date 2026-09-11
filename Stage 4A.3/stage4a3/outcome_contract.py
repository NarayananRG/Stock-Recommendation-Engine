from __future__ import annotations

OUTCOME_COLUMNS=["Event ID","Generated UTC","Signal ID","Signal Date","Ticker","Outcome Type","Outcome State","Outcome Value","Observation Through Date","Label Available Date","Source Market Data Hash","Frozen Rule Semantics Version","Is Terminal","Prior Event Hash","Event Hash"]
OUTCOME_TYPES=("ENTRY_FILLED","T1_BEFORE_STOP_63","T2_BEFORE_STOP_63","D1_TRADE_COMPLETION")
OUTCOME_SCHEMA={"schema_version":"STAGE4A3_OUTCOME_V1","columns":OUTCOME_COLUMNS,"outcome_types":list(OUTCOME_TYPES),"location":"prospective/outcomes only","entry_semantics":"frozen Stage 3.1","target_semantics":"STOP_FIRST, 63-session maximum hold","d1_semantics":"TRAIL_ONLY frozen Stage 2B.1","append_only":True}
