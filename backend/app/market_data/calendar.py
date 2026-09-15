"""NSE session rules used to judge whether a stored end-of-day price is current.

The rule (also documented in docs/market-data.md):

1. NSE sessions run Monday to Friday, excluding configured exchange holidays.
2. A session's end-of-day price is expected to be available from 18:00 IST on that day.
   The market closes at 15:30 IST; the buffer allows for the provider to publish.
3. The latest expected session at a moment is that day, if it is a session day and the
   time is 18:00 IST or later; otherwise it is the most recent earlier session day.
4. A price is FRESH if its trade date is on or after the latest expected session, and
   STALE otherwise.

All functions are deterministic: callers pass the current time explicitly.
"""

from collections.abc import Collection
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = time(15, 30)
EOD_AVAILABLE_FROM = time(18, 0)
_MAX_LOOKBACK_DAYS = 31


class PriceFreshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_ist(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required.")
    return moment.astimezone(IST)


def today_in_ist(moment: datetime | None = None) -> date:
    return to_ist(moment or now_utc()).date()


def is_session_day(day: date, holidays: Collection[date] = ()) -> bool:
    return day.weekday() < 5 and day not in holidays


def previous_session_day(day: date, holidays: Collection[date] = ()) -> date:
    candidate = day
    for _ in range(_MAX_LOOKBACK_DAYS):
        candidate -= timedelta(days=1)
        if is_session_day(candidate, holidays):
            return candidate
    raise ValueError(f"No trading session found in the {_MAX_LOOKBACK_DAYS} days before {day}.")


def eod_available_at(session_day: date) -> datetime:
    """The moment a session's end-of-day price is expected to be available."""
    return datetime.combine(session_day, EOD_AVAILABLE_FROM, tzinfo=IST)


def latest_expected_session(moment: datetime, holidays: Collection[date] = ()) -> date:
    local = to_ist(moment)
    today = local.date()
    if is_session_day(today, holidays) and local.time() >= EOD_AVAILABLE_FROM:
        return today
    return previous_session_day(today, holidays)


def classify_freshness(trade_date: date, expected_session: date) -> PriceFreshness:
    return PriceFreshness.FRESH if trade_date >= expected_session else PriceFreshness.STALE


def ist_month_start(moment: datetime) -> datetime:
    """Start of the current calendar month in IST, used for monthly request accounting."""
    local = to_ist(moment)
    return datetime(local.year, local.month, 1, tzinfo=IST)
