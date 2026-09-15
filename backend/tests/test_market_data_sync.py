"""Market-data sync against PostgreSQL with a fake provider (no network)."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.market_data.calendar import IST
from app.market_data.exceptions import (
    ProviderAuthenticationError,
    ProviderGranularityError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
    SyncAlreadyRunningError,
)
from app.market_data.ingestion.sync import SYNC_LOCK_ID, SyncOutcome, sync_daily_prices, sync_security_master
from app.market_data.models import DailyPrice, Listing, MarketDataSyncRun
from app.market_data.nse_calendar import NSE_SPECIAL_TRADING_SESSIONS, NSE_TRADING_HOLIDAYS
from app.market_data.providers.indian_api import parse_historical_prices, parse_security_master
from app.market_data.records import DailyPriceBar, DailyPriceSeries, SecurityMasterSnapshot
from app.portfolios.rules import Exchange
from market_data_fakes import FakeProvider, load_fixture

MONDAY_EVENING = datetime(2026, 9, 14, 13, 0, tzinfo=UTC)  # 18:30 IST: latest expected session is 14 Sep
FRIDAY_EVENING = datetime(2026, 9, 11, 13, 0, tzinfo=UTC)  # 18:30 IST: latest expected session is 11 Sep
TODAY = date(2026, 9, 14)
FIXTURE_FOR = {
    "RELIANCE": "historical_reliance.json",
    "TCS": "historical_tcs.json",
    "INFY": "historical_infy.json",
    "HDFCBANK": "historical_hdfcbank.json",
    "M&M": "historical_mm.json",
}

SessionFactory = sessionmaker[Session]


def history(symbol: str) -> DailyPriceSeries:
    return parse_historical_prices(load_fixture(FIXTURE_FOR[symbol]), symbol=symbol, today=TODAY)


def all_history() -> dict[str, DailyPriceSeries]:
    return {symbol: history(symbol) for symbol in FIXTURE_FOR}


@pytest.fixture
def sync_settings(migrated_database_url: str) -> Settings:
    # The recorded fixtures treat Monday 14 Sep 2026 as a normal session, so these tests use a
    # plain weekday calendar. Tests of the real NSE calendar pass it explicitly.
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated_database_url,
        indian_api_key="test-key-not-real",
        nse_trading_holidays=[],
        nse_special_trading_sessions=[],
    )


@pytest.fixture
def snapshot() -> SecurityMasterSnapshot:
    return parse_security_master(load_fixture("security_master.json"), min_rows=1)


@pytest.fixture
def load_listings(db_session_factory: SessionFactory, db_engine: Engine, snapshot: SecurityMasterSnapshot) -> None:
    outcome = sync_security_master(
        db_session_factory, db_engine, FakeProvider(snapshot=snapshot), clock=lambda: MONDAY_EVENING
    )
    assert outcome.status == "succeeded", outcome


@pytest.fixture
def make_portfolio(db_client: TestClient) -> Callable[..., str]:
    def _make(*holdings: tuple[str, str]) -> str:
        payload = {
            "name": "Sync test",
            "holdings": [
                {"symbol": symbol, "exchange": exchange, "quantity": 1, "average_buy_price": "100"}
                for exchange, symbol in holdings
            ],
        }
        response = db_client.post("/api/v1/portfolios", json=payload)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return _make


@pytest.fixture
def run_prices(
    db_session_factory: SessionFactory, db_engine: Engine, sync_settings: Settings
) -> Callable[..., SyncOutcome]:
    def _run(provider: FakeProvider, *, now: datetime = MONDAY_EVENING, settings: Settings | None = None, **kwargs: object) -> SyncOutcome:
        return sync_daily_prices(
            db_session_factory, db_engine, provider, settings or sync_settings, clock=lambda: now, **kwargs  # type: ignore[arg-type]
        )

    return _run


def prices_for(factory: SessionFactory, symbol: str) -> list[DailyPrice]:
    with factory() as session:
        statement = (
            select(DailyPrice)
            .join(Listing, Listing.id == DailyPrice.listing_id)
            .where(Listing.nse_symbol == symbol)
            .order_by(DailyPrice.trade_date)
        )
        return list(session.scalars(statement))


def listing(factory: SessionFactory, **filters: object) -> Listing:
    with factory() as session:
        return session.scalars(select(Listing).filter_by(**filters)).one()


def run_record(factory: SessionFactory, outcome: SyncOutcome) -> MarketDataSyncRun:
    with factory() as session:
        return session.get_one(MarketDataSyncRun, outcome.run_id)


# --- Security master -------------------------------------------------------------------


@pytest.mark.usefixtures("load_listings")
def test_security_master_sync_loads_listings(db_session_factory: SessionFactory) -> None:
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Listing)) == 12
        run = session.scalars(select(MarketDataSyncRun)).one()

    assert listing(db_session_factory, nse_symbol="M&M").bse_code == "500520"
    assert listing(db_session_factory, bse_code="539097").nse_symbol is None
    assert run.kind == "security_master" and run.status == "succeeded"
    assert run.requests_made == 0
    assert run.records_inserted == 12
    assert run.details["dropped_rows"] == 5
    assert run.details["ambiguous_nse_symbols"] == ["DUPSYM"]


@pytest.mark.usefixtures("load_listings")
def test_security_master_sync_is_idempotent_and_deactivates_removed_securities(
    db_session_factory: SessionFactory, db_engine: Engine, snapshot: SecurityMasterSnapshot
) -> None:
    reduced = replace(snapshot, records=tuple(r for r in snapshot.records if r.nse_symbol != "KOTARISUG"))
    later = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)

    outcome = sync_security_master(db_session_factory, db_engine, FakeProvider(snapshot=reduced), clock=lambda: later)

    assert outcome.status == "succeeded"
    assert outcome.records_inserted == 0
    assert outcome.details["deactivated"] == 1
    removed = listing(db_session_factory, provider_security_id="S0004774")
    assert removed.is_active is False and removed.nse_symbol is None
    assert listing(db_session_factory, nse_symbol="RELIANCE").is_active is True


@pytest.mark.usefixtures("load_listings")
def test_security_master_refuses_a_suspiciously_small_list(
    db_session_factory: SessionFactory, db_engine: Engine, snapshot: SecurityMasterSnapshot
) -> None:
    tiny = replace(snapshot, records=snapshot.records[:2])

    outcome = sync_security_master(db_session_factory, db_engine, FakeProvider(snapshot=tiny), clock=lambda: MONDAY_EVENING)

    assert outcome.status == "failed"
    assert "refusing" in (outcome.error_summary or "")
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Listing).where(Listing.is_active.is_(True))) == 12


# --- Price sync ------------------------------------------------------------------------


@pytest.mark.usefixtures("load_listings")
def test_price_sync_requests_only_held_nse_securities(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "RELIANCE"), ("NSE", "TCS"), ("NSE", "INFY"))
    provider = FakeProvider(series=all_history())

    outcome = run_prices(provider)

    assert sorted(provider.calls) == [("INFY", "1yr"), ("RELIANCE", "1yr"), ("TCS", "1yr")]
    assert outcome.status == "succeeded"
    assert outcome.requests_made == 3
    assert outcome.records_attempted == 3
    assert outcome.records_inserted == 18
    rows = prices_for(db_session_factory, "RELIANCE")
    assert [row.trade_date for row in rows][-1] == date(2026, 9, 14)
    assert rows[-1].close_price == Decimal("2650.0000")
    assert rows[-1].volume == 5873310
    assert {row.exchange for row in rows} == {"NSE"}
    assert {row.source for row in rows} == {"indian_api"}
    assert rows[-1].fetched_at == MONDAY_EVENING
    assert rows[-1].sync_run_id == outcome.run_id
    assert prices_for(db_session_factory, "HDFCBANK") == []


@pytest.mark.usefixtures("load_listings")
def test_price_sync_is_idempotent(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "RELIANCE"), ("NSE", "TCS"), ("NSE", "INFY"))
    provider = FakeProvider(series=all_history())

    run_prices(provider)
    second = run_prices(provider)

    assert len(provider.calls) == 3
    assert second.status == "succeeded"
    assert second.requests_made == 0
    assert second.details["up_to_date"] == ["INFY", "RELIANCE", "TCS"]
    assert len(prices_for(db_session_factory, "RELIANCE")) == 6


@pytest.mark.usefixtures("load_listings")
def test_duplicate_daily_prices_are_upserted_not_duplicated(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "RELIANCE"))
    provider = FakeProvider(series=all_history())
    run_prices(provider)

    same = run_prices(provider, force=True)
    assert (same.records_inserted, same.records_updated) == (0, 0)
    assert same.details["prices_unchanged"] == 6

    original = history("RELIANCE")
    revised_bars = original.bars[:-1] + (replace(original.bars[-1], close_price=Decimal("2655.0000")),)
    provider.series["RELIANCE"] = replace(original, bars=revised_bars)
    revised = run_prices(provider, force=True)

    assert (revised.records_inserted, revised.records_updated) == (0, 1)
    rows = prices_for(db_session_factory, "RELIANCE")
    assert len(rows) == 6
    assert rows[-1].close_price == Decimal("2655.0000")


@pytest.mark.usefixtures("load_listings")
def test_bse_holdings_use_the_nse_listing_and_unmapped_holdings_are_reported(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome]
) -> None:
    make_portfolio(("BSE", "500325"), ("BSE", "539097"), ("BSE", "999999"), ("NSE", "NOTLISTED"))
    provider = FakeProvider(series=all_history())

    outcome = run_prices(provider)

    assert provider.calls == [("RELIANCE", "1yr")]
    assert outcome.details["bse_without_nse_listing"] == ["539097"]
    assert outcome.details["unmatched_bse_codes"] == ["999999"]
    assert outcome.details["unmatched_nse_symbols"] == ["NOTLISTED"]


@pytest.mark.usefixtures("load_listings")
def test_invalid_response_for_one_security_stores_nothing_for_it(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "RELIANCE"), ("NSE", "TCS"), ("NSE", "INFY"))
    provider = FakeProvider(series=all_history(), errors={"TCS": ProviderResponseError("not labelled as NSE prices")})

    outcome = run_prices(provider)

    assert outcome.status == "partial"
    assert outcome.failures == 1
    assert outcome.records_inserted == 12
    assert outcome.error_summary == "1 of 3 securities could not be updated."
    assert outcome.details["errors"][0]["symbol"] == "TCS"
    assert prices_for(db_session_factory, "TCS") == []
    assert listing(db_session_factory, nse_symbol="TCS").prices_last_request_status == "invalid_response"


@pytest.mark.usefixtures("load_listings")
def test_weekly_backfill_falls_back_to_one_month_of_daily_prices(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "RELIANCE"))
    provider = FakeProvider(series=all_history(), errors={("RELIANCE", "1yr"): ProviderGranularityError("weekly")})

    outcome = run_prices(provider)

    assert provider.calls == [("RELIANCE", "1yr"), ("RELIANCE", "1m")]
    assert outcome.status == "succeeded"
    assert outcome.requests_made == 2
    assert outcome.details["weekly_fallbacks"] == ["RELIANCE"]
    assert len(prices_for(db_session_factory, "RELIANCE")) == 6


@pytest.mark.usefixtures("load_listings")
def test_rate_limit_stops_the_sync(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "INFY"), ("NSE", "RELIANCE"), ("NSE", "TCS"))
    provider = FakeProvider(series=all_history(), errors={"RELIANCE": ProviderRateLimitError("HTTP 429")})

    outcome = run_prices(provider)

    assert provider.calls == [("INFY", "1yr"), ("RELIANCE", "1yr")]
    assert outcome.status == "rate_limited"
    assert len(prices_for(db_session_factory, "INFY")) == 6
    assert listing(db_session_factory, nse_symbol="RELIANCE").prices_last_requested_at is None


@pytest.mark.usefixtures("load_listings")
def test_request_budget_stops_before_exceeding_the_monthly_limit(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "INFY"), ("NSE", "RELIANCE"), ("NSE", "TCS"))
    with db_session_factory() as session:
        session.add(
            MarketDataSyncRun(
                provider="indian_api", kind="daily_prices", status="succeeded",
                started_at=datetime(2026, 9, 2, 13, 0, tzinfo=UTC), requests_made=449, details={},
            )
        )
        session.add(
            MarketDataSyncRun(
                provider="indian_api", kind="daily_prices", status="succeeded",
                started_at=datetime(2026, 8, 20, 13, 0, tzinfo=UTC), requests_made=400, details={},
            )
        )
        session.commit()
    provider = FakeProvider(series=all_history())

    outcome = run_prices(provider)

    assert provider.calls == [("INFY", "1yr")]
    assert outcome.status == "budget_exhausted"
    assert outcome.requests_made == 1
    assert outcome.records_attempted == 1
    assert "budget" in (outcome.error_summary or "")


@pytest.mark.usefixtures("load_listings")
@pytest.mark.parametrize(
    "error",
    [ProviderAuthenticationError("HTTP 401"), ProviderUnavailableError("HTTP 503 after retries")],
)
def test_authentication_and_outage_errors_stop_the_sync(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], error: Exception
) -> None:
    make_portfolio(("NSE", "INFY"), ("NSE", "RELIANCE"))
    provider = FakeProvider(series=all_history(), errors={"INFY": error})

    outcome = run_prices(provider)

    assert provider.calls == [("INFY", "1yr")]
    assert outcome.status == "failed"


@pytest.mark.usefixtures("load_listings")
def test_a_single_bad_request_does_not_stop_the_sync(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "INFY"), ("NSE", "RELIANCE"))
    provider = FakeProvider(series=all_history(), errors={"INFY": ProviderRequestError("HTTP 400: invalid request")})

    outcome = run_prices(provider)

    assert provider.calls == [("INFY", "1yr"), ("RELIANCE", "1yr")]
    assert outcome.status == "partial"
    assert outcome.failures == 1
    assert len(prices_for(db_session_factory, "RELIANCE")) == 6


@pytest.mark.usefixtures("load_listings")
def test_repeated_rejections_stop_the_sync_before_spending_more_requests(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome]
) -> None:
    make_portfolio(("NSE", "HDFCBANK"), ("NSE", "INFY"), ("NSE", "M&M"), ("NSE", "RELIANCE"), ("NSE", "TCS"))
    errors: dict[object, Exception] = {
        "HDFCBANK": ProviderRequestError("HTTP 400"),
        "INFY": ProviderNotFoundError("HTTP 404"),  # a missing security is not a provider-wide failure
        "M&M": ProviderResponseError("error body with HTTP 200"),
        "RELIANCE": ProviderRequestError("HTTP 400"),
    }
    provider = FakeProvider(series=all_history(), errors=errors)

    outcome = run_prices(provider)

    assert [symbol for symbol, _ in provider.calls] == ["HDFCBANK", "INFY", "M&M", "RELIANCE"]
    assert outcome.status == "failed"
    assert outcome.requests_made == 4
    assert "consecutive" in (outcome.error_summary or "")


# --- Completed sessions only ------------------------------------------------------------


def ist_on(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


def with_nse_calendar(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "nse_trading_holidays": sorted(NSE_TRADING_HOLIDAYS),
            "nse_special_trading_sessions": sorted(NSE_SPECIAL_TRADING_SESSIONS),
        }
    )


@pytest.mark.usefixtures("load_listings")
@pytest.mark.parametrize(
    ("hour", "minute", "latest_stored"),
    [
        (16, 0, date(2026, 9, 11)),  # the provider already shows a Monday bar: ignored
        (17, 59, date(2026, 9, 11)),
        (18, 0, date(2026, 9, 14)),  # Monday's close is now a completed session close
        (19, 0, date(2026, 9, 14)),
    ],
)
def test_current_session_bar_is_stored_only_from_eod_availability(
    make_portfolio: Callable[..., str],
    run_prices: Callable[..., SyncOutcome],
    db_session_factory: SessionFactory,
    hour: int,
    minute: int,
    latest_stored: date,
) -> None:
    make_portfolio(("NSE", "RELIANCE"))

    outcome = run_prices(FakeProvider(series=all_history()), now=ist_on(date(2026, 9, 14), hour, minute))

    assert outcome.status == "succeeded"
    assert prices_for(db_session_factory, "RELIANCE")[-1].trade_date == latest_stored
    ignored = [] if latest_stored == date(2026, 9, 14) else [
        {"symbol": "RELIANCE", "trade_date": "2026-09-14", "reason": "session_not_complete"}
    ]
    assert outcome.details["ignored_bars"] == ignored


@pytest.mark.usefixtures("load_listings")
def test_early_bar_never_overwrites_the_previous_close_and_is_requested_after_the_cutoff(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "RELIANCE"))
    full = history("RELIANCE")
    run_prices(FakeProvider(series={"RELIANCE": replace(full, bars=full.bars[:-1])}), now=ist_on(date(2026, 9, 11), 19))
    friday = prices_for(db_session_factory, "RELIANCE")[-1]

    # Monday 16:00: the provider already shows a Monday bar with a provisional price.
    provisional = full.bars[:-1] + (replace(full.bars[-1], close_price=Decimal("2600.0000")),)
    early = run_prices(
        FakeProvider(series={"RELIANCE": replace(full, bars=provisional)}), now=ist_on(date(2026, 9, 14), 16), force=True
    )

    rows = prices_for(db_session_factory, "RELIANCE")
    assert (early.records_inserted, early.records_updated) == (0, 0)
    assert rows[-1].trade_date == date(2026, 9, 11)
    assert (rows[-1].close_price, rows[-1].fetched_at) == (friday.close_price, friday.fetched_at)

    # Monday 18:30: the security is requested again and the completed Monday close is stored.
    later = FakeProvider(series=all_history())
    run_prices(later, now=ist_on(date(2026, 9, 14), 18, 30))

    assert later.calls == [("RELIANCE", "1m")]
    latest = prices_for(db_session_factory, "RELIANCE")[-1]
    assert (latest.trade_date, latest.close_price) == (date(2026, 9, 14), Decimal("2650.0000"))


def budget_day_series() -> DailyPriceSeries:
    # 1347.00 is the provider's real RELIANCE close for the 1 Feb 2026 Sunday session; the
    # two earlier closes are illustrative.
    bars = (
        DailyPriceBar(trade_date=date(2026, 1, 29), close_price=Decimal("1395.0000"), volume=1000),
        DailyPriceBar(trade_date=date(2026, 1, 30), close_price=Decimal("1390.0000"), volume=1000),
        DailyPriceBar(trade_date=date(2026, 2, 1), close_price=Decimal("1347.0000"), volume=1000),
    )
    return DailyPriceSeries(symbol="RELIANCE", exchange=Exchange.NSE, bars=bars, skipped_points=0)


@pytest.mark.usefixtures("load_listings")
@pytest.mark.parametrize(
    ("special_sessions", "latest_stored", "ignored"),
    [
        ([date(2026, 2, 1)], date(2026, 2, 1), []),
        ([], date(2026, 1, 30), [{"symbol": "RELIANCE", "trade_date": "2026-02-01", "reason": "not_a_session_day"}]),
    ],
)
def test_sunday_bar_is_stored_only_for_a_configured_special_session(
    make_portfolio: Callable[..., str],
    run_prices: Callable[..., SyncOutcome],
    db_session_factory: SessionFactory,
    sync_settings: Settings,
    special_sessions: list[date],
    latest_stored: date,
    ignored: list[dict[str, str]],
) -> None:
    make_portfolio(("NSE", "RELIANCE"))
    settings = sync_settings.model_copy(update={"nse_special_trading_sessions": special_sessions})

    outcome = run_prices(
        FakeProvider(series={"RELIANCE": budget_day_series()}), now=ist_on(date(2026, 2, 1), 19), settings=settings
    )

    assert outcome.details["expected_session"] == latest_stored.isoformat()
    assert prices_for(db_session_factory, "RELIANCE")[-1].trade_date == latest_stored
    assert outcome.details["ignored_bars"] == ignored


@pytest.mark.usefixtures("load_listings")
def test_bar_dated_on_a_configured_holiday_is_never_stored(
    make_portfolio: Callable[..., str],
    run_prices: Callable[..., SyncOutcome],
    db_session_factory: SessionFactory,
    sync_settings: Settings,
) -> None:
    make_portfolio(("NSE", "RELIANCE"))  # the fixture history has a bar dated 14 Sep 2026, Ganesh Chaturthi

    outcome = run_prices(
        FakeProvider(series=all_history()), now=ist_on(date(2026, 9, 15), 19), settings=with_nse_calendar(sync_settings)
    )

    assert outcome.details["expected_session"] == "2026-09-15"
    assert prices_for(db_session_factory, "RELIANCE")[-1].trade_date == date(2026, 9, 11)
    assert outcome.details["ignored_bars"] == [
        {"symbol": "RELIANCE", "trade_date": "2026-09-14", "reason": "not_a_session_day"}
    ]


@pytest.mark.usefixtures("load_listings")
def test_syncs_cannot_run_concurrently(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_engine: Engine
) -> None:
    make_portfolio(("NSE", "INFY"))
    provider = FakeProvider(series=all_history())
    with db_engine.connect() as connection:
        connection.execute(select(func.pg_advisory_lock(SYNC_LOCK_ID)))
        try:
            with pytest.raises(SyncAlreadyRunningError):
                run_prices(provider)
        finally:
            connection.execute(select(func.pg_advisory_unlock(SYNC_LOCK_ID)))
    assert provider.calls == []


def test_price_sync_requires_the_security_master(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome]
) -> None:
    make_portfolio(("NSE", "INFY"))
    provider = FakeProvider(series=all_history())

    outcome = run_prices(provider)

    assert outcome.status == "failed"
    assert "sync-listings" in (outcome.error_summary or "")
    assert provider.calls == []


@pytest.mark.usefixtures("load_listings")
def test_dry_run_plans_without_requests_or_records(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "RELIANCE"), ("NSE", "TCS"))
    provider = FakeProvider(series=all_history())

    outcome = run_prices(provider, dry_run=True)

    assert outcome.status == "dry_run"
    assert outcome.details["planned"] == [{"symbol": "RELIANCE", "period": "1yr"}, {"symbol": "TCS", "period": "1yr"}]
    assert provider.calls == []
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MarketDataSyncRun).where(MarketDataSyncRun.kind == "daily_prices")) == 0


@pytest.mark.usefixtures("load_listings")
def test_security_without_new_data_is_not_requested_again_in_the_same_session(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome]
) -> None:
    make_portfolio(("NSE", "TCS"))
    provider = FakeProvider(series={"TCS": DailyPriceSeries(symbol="TCS", exchange=Exchange.NSE, bars=())})

    first = run_prices(provider)
    second = run_prices(provider)

    assert first.details["no_data"] == ["TCS"]
    assert provider.calls == [("TCS", "1yr")]
    assert second.details["already_requested_this_session"] == ["TCS"]


@pytest.mark.usefixtures("load_listings")
def test_existing_history_is_topped_up_with_a_one_month_request(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "RELIANCE"))
    full = history("RELIANCE")
    through_friday = replace(full, bars=tuple(bar for bar in full.bars if bar.trade_date <= date(2026, 9, 11)))
    provider = FakeProvider(series={"RELIANCE": through_friday})
    run_prices(provider, now=FRIDAY_EVENING)

    provider.series["RELIANCE"] = full
    topped_up = run_prices(provider, now=MONDAY_EVENING)

    assert provider.calls == [("RELIANCE", "1yr"), ("RELIANCE", "1m")]
    assert topped_up.records_inserted == 1
    assert prices_for(db_session_factory, "RELIANCE")[-1].trade_date == date(2026, 9, 14)


@pytest.mark.usefixtures("load_listings")
def test_large_price_moves_are_recorded_for_review(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome]
) -> None:
    make_portfolio(("NSE", "RELIANCE"))
    split_like = DailyPriceSeries(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        bars=(
            DailyPriceBar(date(2026, 9, 11), Decimal("2640.0000")),
            DailyPriceBar(date(2026, 9, 14), Decimal("1320.0000")),
        ),
    )

    outcome = run_prices(FakeProvider(series={"RELIANCE": split_like}))

    assert outcome.details["large_price_moves"] == [
        {"symbol": "RELIANCE", "from": "2026-09-11", "to": "2026-09-14", "change_pct": "-50.00"}
    ]


@pytest.mark.usefixtures("load_listings")
def test_sync_run_is_recorded_completely(
    make_portfolio: Callable[..., str], run_prices: Callable[..., SyncOutcome], db_session_factory: SessionFactory
) -> None:
    make_portfolio(("NSE", "M&M"))

    outcome = run_prices(FakeProvider(series=all_history()))
    run = run_record(db_session_factory, outcome)

    assert run.provider == "indian_api"
    assert run.kind == "daily_prices"
    assert run.status == "succeeded"
    assert run.started_at == MONDAY_EVENING
    assert run.completed_at == MONDAY_EVENING
    assert (run.requests_made, run.records_attempted, run.records_inserted, run.records_updated, run.failures) == (1, 1, 6, 0, 0)
    assert run.error_summary is None
    assert run.details["expected_session"] == "2026-09-14"
    assert run.details["periods"] == {"M&M": "1yr"}
