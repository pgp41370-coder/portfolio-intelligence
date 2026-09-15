"""Trading-session freshness rules (no database)."""

from datetime import UTC, date, datetime

import pytest

from app.market_data.calendar import (
    IST,
    WEEKDAYS_ONLY,
    PriceFreshness,
    TradingCalendar,
    classify_freshness,
    eod_available_at,
    is_completed_session_close,
    is_session_day,
    ist_month_start,
    latest_expected_session,
    previous_session_day,
    today_in_ist,
)
from app.market_data.nse_calendar import NSE_SPECIAL_TRADING_SESSIONS, NSE_TRADING_HOLIDAYS

NSE_2026 = TradingCalendar(holidays=frozenset(NSE_TRADING_HOLIDAYS), special_sessions=frozenset(NSE_SPECIAL_TRADING_SESSIONS))


def ist(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


# 11 September 2026 is a Friday; 14 September 2026 is a Monday. Without a calendar, every
# weekday is a session.
@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (ist(2026, 9, 14, 10, 0), date(2026, 9, 11)),  # Monday during market hours -> Friday
        (ist(2026, 9, 14, 17, 59), date(2026, 9, 11)),  # Monday before EOD availability
        (ist(2026, 9, 14, 18, 0), date(2026, 9, 14)),  # Monday at 18:00 IST
        (ist(2026, 9, 14, 23, 30), date(2026, 9, 14)),
        (ist(2026, 9, 12, 12, 0), date(2026, 9, 11)),  # Saturday -> Friday
        (ist(2026, 9, 13, 20, 0), date(2026, 9, 11)),  # Sunday -> Friday
        (ist(2026, 9, 15, 9, 0), date(2026, 9, 14)),  # Tuesday morning -> Monday
    ],
)
def test_latest_expected_session(moment: datetime, expected: date) -> None:
    assert latest_expected_session(moment) == expected


def test_utc_moments_use_the_indian_market_date() -> None:
    # 20:00 UTC on 14 Sep is 01:30 IST on Tuesday 15 Sep, before that day's close.
    assert latest_expected_session(datetime(2026, 9, 14, 20, 0, tzinfo=UTC)) == date(2026, 9, 14)
    # 13:00 UTC on 14 Sep is 18:30 IST on Monday.
    assert latest_expected_session(datetime(2026, 9, 14, 13, 0, tzinfo=UTC)) == date(2026, 9, 14)
    # 12:00 UTC on 14 Sep is 17:30 IST on Monday.
    assert latest_expected_session(datetime(2026, 9, 14, 12, 0, tzinfo=UTC)) == date(2026, 9, 11)


def test_configured_holidays_are_not_sessions() -> None:
    calendar = TradingCalendar(holidays=frozenset({date(2026, 9, 11)}))
    assert latest_expected_session(ist(2026, 9, 13, 12, 0), calendar) == date(2026, 9, 10)
    assert latest_expected_session(ist(2026, 9, 14, 10, 0), calendar) == date(2026, 9, 10)
    assert latest_expected_session(ist(2026, 9, 11, 19, 0), calendar) == date(2026, 9, 10)


def test_previous_session_day_skips_weekends() -> None:
    assert previous_session_day(date(2026, 9, 14)) == date(2026, 9, 11)
    assert previous_session_day(date(2026, 9, 15)) == date(2026, 9, 14)


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError):
        latest_expected_session(datetime(2026, 9, 14, 18, 0))


def test_classify_freshness() -> None:
    assert classify_freshness(date(2026, 9, 14), date(2026, 9, 14)) is PriceFreshness.FRESH
    assert classify_freshness(date(2026, 9, 11), date(2026, 9, 11)) is PriceFreshness.FRESH
    assert classify_freshness(date(2026, 9, 11), date(2026, 9, 14)) is PriceFreshness.STALE


def test_eod_availability_is_1800_ist() -> None:
    assert eod_available_at(date(2026, 9, 14)) == datetime(2026, 9, 14, 12, 30, tzinfo=UTC)


def test_ist_month_start_uses_indian_calendar_month() -> None:
    # 20:00 UTC on 30 Sep is already 1 Oct in IST.
    assert ist_month_start(datetime(2026, 9, 30, 20, 0, tzinfo=UTC)) == datetime(2026, 10, 1, tzinfo=IST)
    assert today_in_ist(datetime(2026, 9, 30, 20, 0, tzinfo=UTC)) == date(2026, 10, 1)


# --- Published 2026 NSE calendar ------------------------------------------------------------


def test_2026_calendar_data_matches_the_published_nse_list() -> None:
    assert len([day for day in NSE_TRADING_HOLIDAYS if day.year == 2026]) == 16
    assert NSE_TRADING_HOLIDAYS[date(2026, 9, 14)] == "Ganesh Chaturthi"
    assert all(day.weekday() < 5 for day in NSE_TRADING_HOLIDAYS)  # weekend holidays need no entry
    assert all(day.weekday() >= 5 for day in NSE_SPECIAL_TRADING_SESSIONS)
    assert date(2026, 2, 1) in NSE_SPECIAL_TRADING_SESSIONS


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (ist(2026, 9, 11, 19, 0), date(2026, 9, 11)),  # Friday evening
        (ist(2026, 9, 14, 10, 0), date(2026, 9, 11)),  # Monday, Ganesh Chaturthi
        (ist(2026, 9, 14, 19, 0), date(2026, 9, 11)),  # Monday evening: no Monday close is expected
        (ist(2026, 9, 15, 17, 59), date(2026, 9, 11)),  # Tuesday before EOD availability
        (ist(2026, 9, 15, 18, 0), date(2026, 9, 15)),  # Tuesday session complete
    ],
)
def test_friday_close_stays_current_through_a_monday_holiday(moment: datetime, expected: date) -> None:
    assert latest_expected_session(moment, NSE_2026) == expected
    freshness = classify_freshness(date(2026, 9, 11), expected)
    assert freshness is (PriceFreshness.FRESH if expected == date(2026, 9, 11) else PriceFreshness.STALE)


@pytest.mark.parametrize(
    ("hour", "minute", "accepted"),
    [(16, 0, False), (17, 59, False), (18, 0, True), (19, 0, True)],
)
def test_todays_bar_is_a_close_only_from_eod_availability(hour: int, minute: int, accepted: bool) -> None:
    monday = date(2026, 9, 7)  # a regular session
    expected = latest_expected_session(ist(2026, 9, 7, hour, minute), NSE_2026)

    assert is_completed_session_close(monday, expected, NSE_2026) is accepted
    assert is_completed_session_close(date(2026, 9, 4), expected, NSE_2026) is True  # previous Friday


def test_future_bars_are_never_closes() -> None:
    expected = latest_expected_session(ist(2026, 9, 15, 19, 0), NSE_2026)

    assert is_completed_session_close(date(2026, 9, 16), expected, NSE_2026) is False


def test_sunday_special_session_comes_from_the_calendar() -> None:
    budget_day = date(2026, 2, 1)

    assert is_session_day(budget_day, NSE_2026)
    assert not is_session_day(budget_day, WEEKDAYS_ONLY)
    assert not is_session_day(date(2026, 2, 8), NSE_2026)  # an ordinary Sunday
    assert latest_expected_session(ist(2026, 2, 1, 17, 0), NSE_2026) == date(2026, 1, 30)
    assert latest_expected_session(ist(2026, 2, 1, 19, 0), NSE_2026) == budget_day
    assert latest_expected_session(ist(2026, 2, 2, 10, 0), NSE_2026) == budget_day
    assert previous_session_day(date(2026, 2, 2), NSE_2026) == budget_day
    assert is_completed_session_close(budget_day, date(2026, 2, 2), NSE_2026) is True
    # Without the special session, the Sunday bar is not a close.
    assert latest_expected_session(ist(2026, 2, 1, 19, 0), WEEKDAYS_ONLY) == date(2026, 1, 30)
    assert is_completed_session_close(budget_day, date(2026, 2, 2), WEEKDAYS_ONLY) is False


def test_a_holiday_is_never_expected_unless_configured_as_a_special_session() -> None:
    ganesh_chaturthi = date(2026, 9, 14)

    assert not is_session_day(ganesh_chaturthi, NSE_2026)
    for moment in (ist(2026, 9, 14, 19, 0), ist(2026, 9, 15, 19, 0), ist(2026, 9, 16, 10, 0)):
        expected = latest_expected_session(moment, NSE_2026)
        assert expected != ganesh_chaturthi
        assert is_completed_session_close(ganesh_chaturthi, expected, NSE_2026) is False

    reopened = TradingCalendar(special_sessions=frozenset({ganesh_chaturthi}))
    assert latest_expected_session(ist(2026, 9, 14, 19, 0), reopened) == ganesh_chaturthi


def test_a_date_cannot_be_both_a_holiday_and_a_special_session() -> None:
    with pytest.raises(ValueError):
        TradingCalendar(holidays=frozenset({date(2026, 9, 14)}), special_sessions=frozenset({date(2026, 9, 14)}))
