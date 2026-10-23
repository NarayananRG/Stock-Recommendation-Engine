"""Reviewed NSE capital-market sessions, calendar 2025/2026.

Sources: NSE CMTR/65587 (2025), CMTR/71775 (2026), and the current NSE
Indices calendar's additional 15-Jan-2026 closure. Extra budget sessions
are evidenced by original CM bhavcopies, never invented weekday bars.
For other years preserve the prior weekday fallback; not a certified calendar.
"""
from datetime import date
CALENDAR_VERSION = 'NSE_CM_REVIEWED_20261023_V1'
HOLIDAYS = frozenset('''2025-02-26 2025-03-14 2025-03-31 2025-04-10
2025-04-14 2025-04-18 2025-05-01 2025-08-15 2025-08-27 2025-10-02
2025-10-21 2025-10-22 2025-11-05 2025-12-25
2026-01-15 2026-01-26 2026-03-03 2026-03-26 2026-03-31 2026-04-03
2026-04-14 2026-05-01 2026-05-28 2026-06-26 2026-09-14 2026-10-02
2026-10-20 2026-11-10 2026-11-24 2026-12-25'''.split())
SPECIAL_SESSIONS = frozenset({'2025-02-01', '2025-10-21', '2026-02-01', '2026-11-08'})
def is_trading_day(day: date) -> bool:
    session = day.isoformat()
    return session in SPECIAL_SESSIONS or (day.weekday() < 5 and session not in HOLIDAYS)
