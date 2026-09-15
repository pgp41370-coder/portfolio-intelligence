"""Trading-session freshness rules (no database)."""

from datetime import UTC, date, datetime

import pytest

from app.market_data.calendar import (
    IST,
    PriceFreshness,
    classify_freshness,
    eod_available_at,
    ist_month_start,
    latest_expected_session,
    previous_session_day,
    today_in_ist,
)


def ist(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


# 11 September 2026 is a Friday; 14 September 2026 is a Monday.
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
    holidays = {date(2026, 9, 11)}
    assert latest_expected_session(ist(2026, 9, 13, 12, 0), holidays) == date(2026, 9, 10)
    assert latest_expected_session(ist(2026, 9, 14, 10, 0), holidays) == date(2026, 9, 10)
    assert latest_expected_session(ist(2026, 9, 11, 19, 0), holidays) == date(2026, 9, 10)


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
