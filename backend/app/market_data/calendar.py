"""NSE session rules used to judge whether a stored end-of-day price is current.

The rule (also documented in docs/market-data.md):

1. A day is an NSE session if it is a configured special session, or a Monday to Friday
   that is not a configured exchange holiday. Holidays and special sessions come from
   configuration (``TradingCalendar``), so a new year's list needs no code change.
2. A session's end-of-day price is expected to be available from 18:00 IST on that day.
   The market closes at 15:30 IST; the buffer allows for the provider to publish.
3. The latest expected session at a moment is that day, if it is a session day and the
   time is 18:00 IST or later; otherwise it is the most recent earlier session day. It is
   the latest session whose end-of-day close can be treated as complete.
4. A price is FRESH if its trade date is on or after the latest expected session, and
   STALE otherwise.
5. A provider bar is accepted as an end-of-day close only if its trade date is a session
   day and is not after the latest expected session. A bar for the current session before
   18:00 IST, a future date or a non-session day is ignored.

All functions are deterministic: callers pass the current time explicitly.
"""

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class TradingCalendar:
    """Weekday exchange holidays, and special sessions on days that are normally closed."""

    holidays: frozenset[date] = frozenset()
    special_sessions: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "holidays", frozenset(self.holidays))
        object.__setattr__(self, "special_sessions", frozenset(self.special_sessions))
        overlap = self.holidays & self.special_sessions
        if overlap:
            raise ValueError(f"Dates cannot be both holidays and special sessions: {sorted(overlap)}.")

    def is_session_day(self, day: date) -> bool:
        if day in self.special_sessions:
            return True
        return day.weekday() < 5 and day not in self.holidays


WEEKDAYS_ONLY = TradingCalendar()


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_ist(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required.")
    return moment.astimezone(IST)


def today_in_ist(moment: datetime | None = None) -> date:
    return to_ist(moment or now_utc()).date()


def is_session_day(day: date, calendar: TradingCalendar = WEEKDAYS_ONLY) -> bool:
    return calendar.is_session_day(day)


def previous_session_day(day: date, calendar: TradingCalendar = WEEKDAYS_ONLY) -> date:
    candidate = day
    for _ in range(_MAX_LOOKBACK_DAYS):
        candidate -= timedelta(days=1)
        if calendar.is_session_day(candidate):
            return candidate
    raise ValueError(f"No trading session found in the {_MAX_LOOKBACK_DAYS} days before {day}.")


def eod_available_at(session_day: date) -> datetime:
    """The moment a session's end-of-day price is expected to be available."""
    return datetime.combine(session_day, EOD_AVAILABLE_FROM, tzinfo=IST)


def latest_expected_session(moment: datetime, calendar: TradingCalendar = WEEKDAYS_ONLY) -> date:
    local = to_ist(moment)
    today = local.date()
    if calendar.is_session_day(today) and local.time() >= EOD_AVAILABLE_FROM:
        return today
    return previous_session_day(today, calendar)


def is_completed_session_close(trade_date: date, expected_session: date, calendar: TradingCalendar) -> bool:
    """Whether a provider bar dated ``trade_date`` may be stored as an end-of-day close."""
    return trade_date <= expected_session and calendar.is_session_day(trade_date)


def classify_freshness(trade_date: date, expected_session: date) -> PriceFreshness:
    return PriceFreshness.FRESH if trade_date >= expected_session else PriceFreshness.STALE


def ist_month_start(moment: datetime) -> datetime:
    """Start of the current calendar month in IST, used for monthly request accounting."""
    local = to_ist(moment)
    return datetime(local.year, local.month, 1, tzinfo=IST)
