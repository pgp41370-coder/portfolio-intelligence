"""Value a transaction ledger once, for every view that needs it.

Performance, attribution, the timeline and P&L all need the same thing: the position held at the
close of each session, what it was worth, and what money moved that day. Computing it in one
place keeps them from disagreeing — a P&L card and a performance card that quietly used different
session sets would be worse than either alone.

The coverage rules are unchanged from M4.2: a session is valued only when every security held
that day has a stored close, nothing is interpolated or carried forward, and the window ends at
the newest stored close.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.market_data import repository
from app.market_data.calendar import latest_expected_session
from app.performance.positions import LedgerEvent, SecurityKey, Timeline, build_timeline
from app.performance.schemas import ExcludedHoldingRead, ExcludedReason
from app.portfolios.rules import Exchange


@dataclass(slots=True)
class LedgerValuation:
    """One pass over the ledger: sessions, values, flows and everything derived from them."""

    window_start: date
    window_end: date
    window_end_cap: date  # the latest completed session, before clamping to the data
    expected_sessions: list[date]
    sessions: list[date] = field(default_factory=list)  # the valued ones, in order
    totals: list[Decimal] = field(default_factory=list)
    flows: list[Decimal] = field(default_factory=list)
    values: dict[SecurityKey, list[Decimal]] = field(default_factory=dict)
    security_flows: dict[SecurityKey, list[Decimal]] = field(default_factory=dict)
    positions: list[dict[SecurityKey, int]] = field(default_factory=list)
    events_on: list[list[LedgerEvent]] = field(default_factory=list)
    adjacent: list[bool] = field(default_factory=list)
    missing: list[date] = field(default_factory=list)
    missing_without_any_price: list[date] = field(default_factory=list)
    empty_sessions: int = 0
    excluded: list[ExcludedHoldingRead] = field(default_factory=list)
    closes: dict[SecurityKey, dict[date, Decimal]] = field(default_factory=dict)
    timeline: Timeline | None = None

    @property
    def is_empty(self) -> bool:
        return not self.sessions

    def latest_closes(self) -> dict[SecurityKey, Decimal]:
        """The newest stored close per security within the window."""
        return {
            key: series[max(series)] for key, series in self.closes.items() if series
        }


def value_ledger(
    session: Session,
    portfolio_id: uuid.UUID,
    events: list[LedgerEvent],
    *,
    settings: Settings,
    now: datetime,
    start: date | None = None,
    end: date | None = None,
) -> LedgerValuation:
    calendar = settings.trading_calendar
    provider = settings.market_data_provider
    window_end_cap = min(end, latest_expected_session(now, calendar)) if end else latest_expected_session(now, calendar)
    window_start = start or min(event.trade_date for event in events)

    keys = sorted({event.key for event in events})
    listings, excluded = resolve_keys(session, provider, keys)

    closes: dict[SecurityKey, dict[date, Decimal]] = {}
    if listings:
        rows = repository.price_series(
            session, list(listings.values()), Exchange.NSE, start=window_start, end=window_end_cap
        )
        for key, listing_id in listings.items():
            closes[key] = {row.trade_date: row.close_price for row in rows.get(listing_id, [])}

    last_priced = max((max(dates) for dates in closes.values() if dates), default=None)
    window_end = min(window_end_cap, last_priced) if last_priced is not None else window_end_cap

    result = LedgerValuation(
        window_start=window_start,
        window_end=window_end,
        window_end_cap=window_end_cap,
        expected_sessions=[],
        excluded=excluded,
        closes=closes,
    )
    if window_start > window_end:
        return result

    result.expected_sessions = [
        day for day in _days(window_start, window_end) if calendar.is_session_day(day)
    ]
    timeline = build_timeline(events, result.expected_sessions, opening_before=window_start)
    result.timeline = timeline

    tracked = sorted(set(keys))
    result.values = {key: [] for key in tracked}
    result.security_flows = {key: [] for key in tracked}
    position_index: dict[date, int] = {}

    for index, day in enumerate(result.expected_sessions):
        held = {key: quantity for key, quantity in timeline.positions[index].items() if quantity > 0}
        prices = {key: closes.get(key, {}).get(day) for key in held}
        if held and any(price is None for price in prices.values()):
            result.missing.append(day)
            if all(price is None for price in prices.values()):
                result.missing_without_any_price.append(day)
            continue
        if not held:
            result.empty_sessions += 1

        total = Decimal(0)
        for key in tracked:
            quantity = held.get(key, 0)
            value = Decimal(quantity) * prices[key] if quantity and prices.get(key) is not None else Decimal(0)
            result.values[key].append(value)
            result.security_flows[key].append(timeline.security_flows[index].get(key, Decimal(0)))
            total += value

        position_index[day] = index
        result.sessions.append(day)
        result.totals.append(total)
        result.flows.append(timeline.flows[index])
        result.positions.append(dict(held))
        result.events_on.append(timeline.events_on[index])

    result.adjacent = (
        [False]
        + [
            position_index[result.sessions[i]] == position_index[result.sessions[i - 1]] + 1
            for i in range(1, len(result.sessions))
        ]
        if result.sessions
        else []
    )
    return result


def resolve_keys(
    session: Session, provider: str, keys: list[SecurityKey]
) -> tuple[dict[SecurityKey, uuid.UUID], list[ExcludedHoldingRead]]:
    """Map (symbol, exchange) pairs to NSE-priceable listings, naming what cannot be priced."""
    nse = {symbol for symbol, exchange in keys if exchange == Exchange.NSE.value}
    bse = {symbol for symbol, exchange in keys if exchange == Exchange.BSE.value}
    by_nse, by_bse = repository.listings_by_codes(session, provider, nse, bse)
    resolved: dict[SecurityKey, uuid.UUID] = {}
    excluded: list[ExcludedHoldingRead] = []
    for key in keys:
        symbol, exchange = key
        listing = by_nse.get(symbol) if exchange == Exchange.NSE.value else by_bse.get(symbol)
        if listing is None:
            excluded.append(
                ExcludedHoldingRead(symbol=symbol, exchange=Exchange(exchange), reason=ExcludedReason.LISTING_NOT_FOUND)
            )
        elif listing.nse_symbol is None:
            excluded.append(
                ExcludedHoldingRead(symbol=symbol, exchange=Exchange(exchange), reason=ExcludedReason.NO_NSE_LISTING)
            )
        else:
            resolved[key] = listing.id
    return resolved, excluded


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def value_holdings(
    session: Session,
    holdings: list,
    *,
    settings: Settings,
    now: datetime,
    start: date | None = None,
    end: date | None = None,
) -> LedgerValuation:
    """The same per-session structure for a portfolio with no ledger.

    Positions are constant and every flow is zero, which is exactly what the reconstruction
    basis assumes. This exists so attribution, and the explanations built on it, work for a
    portfolio that has holdings but no transactions - otherwise the most common portfolio in
    the application would have nothing to explain.

    The coverage rules mirror ``service._build_holdings_performance``: the window opens where
    every priceable holding has history, a session counts only when all of them are priced, and
    the window ends at the newest stored close. A test asserts the two agree.
    """
    calendar = settings.trading_calendar
    provider = settings.market_data_provider
    window_end_cap = min(end, latest_expected_session(now, calendar)) if end else latest_expected_session(now, calendar)

    keys = [(item.symbol, item.exchange) for item in holdings]
    quantities = {(item.symbol, item.exchange): item.quantity for item in holdings}
    listings, excluded = resolve_keys(session, provider, keys)

    # One query for every listing, not one per listing.
    closes: dict[SecurityKey, dict[date, Decimal]] = {}
    rows = (
        repository.price_series(session, list(listings.values()), Exchange.NSE, start=start, end=window_end_cap)
        if listings
        else {}
    )
    for key, listing_id in list(listings.items()):
        series = rows.get(listing_id, [])
        if not series:
            del listings[key]
            excluded.append(
                ExcludedHoldingRead(symbol=key[0], exchange=Exchange(key[1]), reason=ExcludedReason.NO_PRICE_DATA)
            )
            continue
        closes[key] = {row.trade_date: row.close_price for row in series}

    result = LedgerValuation(
        window_start=start or window_end_cap,
        window_end=window_end_cap,
        window_end_cap=window_end_cap,
        expected_sessions=[],
        excluded=excluded,
        closes=closes,
    )
    if not closes:
        return result

    result.window_start = start or max(min(dates) for dates in closes.values())
    result.window_end = min(window_end_cap, max(max(dates) for dates in closes.values()))
    if result.window_start > result.window_end:
        return result

    result.expected_sessions = [
        day for day in _days(result.window_start, result.window_end) if calendar.is_session_day(day)
    ]
    tracked = sorted(closes)
    result.values = {key: [] for key in tracked}
    result.security_flows = {key: [] for key in tracked}
    position_index: dict[date, int] = {}

    for index, day in enumerate(result.expected_sessions):
        prices = {key: closes[key].get(day) for key in tracked}
        if any(price is None for price in prices.values()):
            result.missing.append(day)
            if all(price is None for price in prices.values()):
                result.missing_without_any_price.append(day)
            continue
        total = Decimal(0)
        for key in tracked:
            value = Decimal(quantities[key]) * prices[key]
            result.values[key].append(value)
            result.security_flows[key].append(Decimal(0))
            total += value
        position_index[day] = index
        result.sessions.append(day)
        result.totals.append(total)
        result.flows.append(Decimal(0))
        result.positions.append({key: quantities[key] for key in tracked})
        result.events_on.append([])

    result.adjacent = (
        [False]
        + [
            position_index[result.sessions[i]] == position_index[result.sessions[i - 1]] + 1
            for i in range(1, len(result.sessions))
        ]
        if result.sessions
        else []
    )
    return result


@dataclass(slots=True)
class PerformanceContext:
    """The work one request should do once, shared by everything built from it.

    Deliberately small. It holds only what more than one consumer needs and what is expensive
    to repeat: the portfolio, its ledger, and the single valuation pass over it. Derived
    figures - returns, risk, attribution, P&L - stay in the functions that own them, because
    caching those here would turn this into a second, quieter copy of the engine.
    """

    portfolio: object
    events: list[LedgerEvent]
    valuation: LedgerValuation

    @property
    def has_ledger(self) -> bool:
        return bool(self.events)


def build_context(
    session: Session,
    portfolio_id: uuid.UUID,
    *,
    settings: Settings,
    now: datetime,
    start: date | None = None,
    end: date | None = None,
) -> PerformanceContext:
    """One pass: read the ledger, then value it (or value the holdings when there is none)."""
    from app.portfolios.service import get_portfolio
    from app.transactions.service import ledger_events, list_transactions

    portfolio = get_portfolio(session, portfolio_id)
    events = ledger_events(list_transactions(session, portfolio_id))
    valuation = (
        value_ledger(session, portfolio_id, events, settings=settings, now=now, start=start, end=end)
        if events
        else value_holdings(session, portfolio.holdings, settings=settings, now=now, start=start, end=end)
    )
    return PerformanceContext(portfolio=portfolio, events=events, valuation=valuation)
