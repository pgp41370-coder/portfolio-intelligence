"""P&L, timeline and attribution, all built from one pass over the ledger.

Each view answers a different question about the same facts:

* **P&L** — what did it cost, what is it worth, what was actually banked.
* **Timeline** — what happened, when, and what it did to the portfolio.
* **Attribution** — which securities moved the portfolio, and by how much.

All three require a transaction ledger. A portfolio without one keeps the M4.1 reconstruction
for performance, but it cannot support realised P&L or a timeline: there is no record of what
was sold or when anything was bought, and inventing one is out of the question. Those views say
so explicitly instead of returning zeros.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.market_data import repository
from app.market_data.calendar import PriceFreshness, classify_freshness, latest_expected_session
from app.performance import attribution as attribution_engine
from app.performance import pnl as pnl_engine
from app.performance.calculations import ValuePoint, as_percent, chain, flow_adjusted_returns, growth_index
from app.performance.ledger_analysis import PerformanceContext, resolve_keys, value_holdings, value_ledger
from app.performance.positions import LedgerEvent, SecurityKey
from app.performance.schemas import (
    AttributionRead,
    BenchmarkRead,
    ContributionRead,
    DailyContributionRead,
    HistoryBasis,
    PeriodRead,
    PnlMethodologyRead,
    PnlTotalsRead,
    PortfolioPnlRead,
    PortfolioTimelineRead,
    SecurityPnlRead,
    TimelineEntryRead,
    TimelineTransactionRead,
)
from app.portfolios.rules import Exchange
from app.portfolios.service import get_portfolio
from app.transactions.service import ledger_events, list_transactions

NO_LEDGER_NOTE = (
    "This portfolio has no transaction ledger. Realised profit and cost basis need a record of "
    "what was bought and sold and when; the holdings on record carry an average buy price but no "
    "dates or disposals. Add transactions to enable this view."
)
TIMELINE_NOTE = (
    "Every entry comes from a recorded transaction. Transactions dated on a non-trading day are "
    "shown on the session at whose close they are recognised. Nothing is inferred."
)
RECONSTRUCTED_ATTRIBUTION_NOTE = (
    "This portfolio has no transaction ledger, so the contributions describe how today's "
    "holdings would have moved, not what was actually held."
)
ATTRIBUTION_NOTE = (
    "A security's contribution is its value change with its own cash flow removed, divided by the "
    "portfolio's opening value that session. Contributions sum to the portfolio's daily return by "
    "construction. The window total is the arithmetic sum of daily contributions, which differs "
    "from the compounded time-weighted return; both are shown."
)


def build_pnl(
    session: Session,
    portfolio_id: uuid.UUID,
    *,
    settings: Settings,
    now: datetime,
    context: PerformanceContext | None = None,
) -> PortfolioPnlRead:
    """Realised and unrealised profit, by security and in total, on a FIFO cost basis.

    ``context`` lets a caller that has already read this portfolio's ledger pass it in.
    """
    portfolio = context.portfolio if context else get_portfolio(session, portfolio_id)
    events = context.events if context else ledger_events(list_transactions(session, portfolio_id))
    if not events:
        return PortfolioPnlRead(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.name,
            as_of=now,
            data_as_of=None,
            totals=None,
            securities=[],
            methodology=PnlMethodologyRead(
                note=NO_LEDGER_NOTE, basis=HistoryBasis.CURRENT_HOLDINGS, available=False
            ),
        )

    ledger = pnl_engine.build_pnl(events)
    keys = sorted({event.key for event in events})
    listings, _ = resolve_keys(session, settings.market_data_provider, keys)
    closes = _latest_closes(session, listings)
    expected_session = latest_expected_session(now, settings.trading_calendar)

    securities: list[SecurityPnlRead] = []
    market_total = Decimal(0)
    unrealised_total = Decimal(0)
    complete = True
    data_as_of: date | None = None

    for key in keys:
        entry = ledger.securities.get(key)
        if entry is None:  # pragma: no cover - every key comes from an event
            continue
        symbol, exchange = key
        priced = closes.get(key)
        close, trade_date = (priced if priced else (None, None))
        if trade_date is not None:
            data_as_of = max(data_as_of, trade_date) if data_as_of else trade_date
        market_value = Decimal(entry.quantity) * close if (close is not None and entry.quantity > 0) else None
        gain = pnl_engine.unrealised(entry.quantity, entry.cost, close)
        if entry.quantity > 0 and market_value is None:
            complete = False
        if market_value is not None:
            market_total += market_value
        if gain is not None:
            unrealised_total += gain

        note = None
        if entry.quantity > 0 and close is None:
            note = "No stored close for this security, so its unrealised profit cannot be measured."
        elif trade_date is not None and classify_freshness(trade_date, expected_session) is PriceFreshness.STALE:
            note = "Priced at an older NSE close; the latest session's price has not been loaded."

        securities.append(
            SecurityPnlRead(
                symbol=symbol,
                exchange=Exchange(exchange),
                quantity=entry.quantity,
                cost_basis=entry.cost if entry.quantity > 0 else Decimal(0),
                average_cost=entry.average_cost,
                market_value=market_value,
                realised_pnl=entry.realised,
                unrealised_pnl=gain,
                total_pnl=(entry.realised + gain) if gain is not None else None,
                contributions=entry.contributions,
                withdrawals=entry.withdrawals,
                fees=entry.fees,
                price_date=trade_date,
                price_note=note,
            )
        )

    securities.sort(key=lambda item: item.symbol)
    totals = PnlTotalsRead(
        realised_pnl=ledger.realised,
        unrealised_pnl=unrealised_total if complete else (unrealised_total if unrealised_total else None),
        total_pnl=(ledger.realised + unrealised_total) if complete else None,
        contributions=ledger.contributions,
        withdrawals=ledger.withdrawals,
        net_invested=ledger.net_invested,
        fees=ledger.fees,
        open_cost_basis=ledger.open_cost,
        market_value=market_total if complete else None,
        is_complete=complete,
    )
    return PortfolioPnlRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        as_of=now,
        data_as_of=data_as_of,
        totals=totals,
        securities=securities,
        unmatched_sales=[f"{symbol} on {exchange}: {quantity} share(s) on {day:%d %b %Y}"
                         for day, (symbol, exchange), quantity in ledger.oversold],
        methodology=PnlMethodologyRead(
            note=pnl_engine.COST_BASIS_NOTE, basis=HistoryBasis.TRANSACTIONS, available=True
        ),
    )


def build_timeline(
    session: Session, portfolio_id: uuid.UUID, *, settings: Settings, now: datetime, limit: int = 200
) -> PortfolioTimelineRead:
    """What happened and what it did, newest first, from the ledger alone."""
    portfolio = get_portfolio(session, portfolio_id)
    rows = list_transactions(session, portfolio_id)
    events = ledger_events(rows)
    if not events:
        return PortfolioTimelineRead(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.name,
            as_of=now,
            basis=HistoryBasis.CURRENT_HOLDINGS,
            entries=[],
            transaction_count=0,
            note=NO_LEDGER_NOTE,
        )

    reference_by_event = {
        (row.trade_date, row.symbol, row.exchange, row.kind, row.quantity): row.reference for row in rows
    }
    valued = value_ledger(session, portfolio_id, events, settings=settings, now=now)
    points = [ValuePoint(day, total) for day, total in zip(valued.sessions, valued.totals, strict=True)]
    measured = flow_adjusted_returns(points, adjacent=valued.adjacent, flows=valued.flows)
    index = growth_index(points, measured.returns)
    base = index[0].value if index else None

    entries: list[TimelineEntryRead] = []
    previous: dict[SecurityKey, int] = {}
    for position, day in enumerate(valued.sessions):
        day_events = valued.events_on[position]
        current = valued.positions[position]
        if day_events:
            entries.append(
                TimelineEntryRead(
                    trade_date=day,
                    transactions=[
                        _timeline_transaction(event, reference_by_event) for event in day_events
                    ],
                    position_changes=_describe_changes(previous, current, day_events),
                    portfolio_value=valued.totals[position],
                    net_cash_flow=valued.flows[position],
                    daily_return_pct=as_percent(measured.returns[position]),
                    cumulative_return_pct=(
                        as_percent(index[position].value / base - 1) if base and base > 0 else None
                    ),
                )
            )
        previous = current

    entries.reverse()  # newest first
    return PortfolioTimelineRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        as_of=now,
        basis=HistoryBasis.TRANSACTIONS,
        entries=entries[:limit],
        transaction_count=len(events),
        note=TIMELINE_NOTE,
    )


def build_attribution(
    session: Session,
    portfolio_id: uuid.UUID,
    *,
    settings: Settings,
    now: datetime,
    start: date | None = None,
    end: date | None = None,
    benchmark: str | None = None,
    top: int = 5,
) -> AttributionRead:
    """Per-security contributions to the window's return, plus the latest session's movers."""
    from app.performance.service import _benchmark  # local import: the service imports this module

    portfolio = get_portfolio(session, portfolio_id)
    events = ledger_events(list_transactions(session, portfolio_id))
    # Without a ledger the positions are today's holdings held constant, with no cash flows.
    # That is the M4.1 reconstruction, and it decomposes just as well - it is simply a weaker
    # claim about what was held, which the basis already states.
    basis = HistoryBasis.TRANSACTIONS if events else HistoryBasis.CURRENT_HOLDINGS
    valued = (
        value_ledger(session, portfolio_id, events, settings=settings, now=now, start=start, end=end)
        if events
        else value_holdings(session, portfolio.holdings, settings=settings, now=now, start=start, end=end)
    )
    if valued.is_empty:
        return AttributionRead(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.name,
            as_of=now,
            basis=basis,
            period=PeriodRead(start=valued.window_start, end=valued.window_end),
            sessions_counted=0,
            twr_pct=None,
            sum_of_daily_returns_pct=None,
            compounding_difference_pct=None,
            contributors=[],
            detractors=[],
            latest_session=None,
            latest_contributions=[],
            note=(
                "No session in this window could be valued, so nothing can be attributed."
                if events
                else f"{NO_LEDGER_NOTE} No session in this window could be valued either."
            ),
        )

    result = attribution_engine.attribute(
        sessions=valued.sessions,
        totals=valued.totals,
        values=valued.values,
        flows=valued.security_flows,
        adjacent=valued.adjacent,
    )
    points = [ValuePoint(day, total) for day, total in zip(valued.sessions, valued.totals, strict=True)]
    measured = flow_adjusted_returns(points, adjacent=valued.adjacent, flows=valued.flows)
    twr = chain(measured.returns)
    difference = (
        twr - result.sum_of_daily_returns
        if (twr is not None and result.sum_of_daily_returns is not None)
        else None
    )

    benchmark_read: BenchmarkRead | None = None
    gap = None
    if benchmark:
        benchmark_read, _ = _benchmark(session, settings, benchmark, points, twr)
        if benchmark_read.cumulative_return_pct is not None and twr is not None:
            gap = attribution_engine.benchmark_gap(twr, benchmark_read.cumulative_return_pct / Decimal(100))

    expected_session = latest_expected_session(now, settings.trading_calendar)
    stale = [
        f"{key[0]} on {key[1]}"
        for key, series in valued.closes.items()
        if series and classify_freshness(max(series), expected_session) is PriceFreshness.STALE
    ]

    return AttributionRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        as_of=now,
        basis=basis,
        period=PeriodRead(start=valued.sessions[0], end=valued.sessions[-1]),
        sessions_counted=result.sessions_counted,
        twr_pct=as_percent(twr),
        sum_of_daily_returns_pct=as_percent(result.sum_of_daily_returns),
        compounding_difference_pct=as_percent(difference),
        contributors=[_contribution(item, valued) for item in result.positive[:top]],
        detractors=[_contribution(item, valued) for item in reversed(result.negative[-top:])],
        latest_session=result.latest_date,
        latest_contributions=[
            DailyContributionRead(
                symbol=item.key[0],
                exchange=Exchange(item.key[1]),
                contribution_pct=as_percent(item.contribution) or Decimal(0),
                value_change=item.value_change,
                cash_flow=item.cash_flow,
            )
            for item in result.latest
        ],
        benchmark=benchmark_read,
        benchmark_gap_pct=as_percent(gap),
        stale_positions=sorted(stale),
        note=ATTRIBUTION_NOTE if events else f"{ATTRIBUTION_NOTE} {RECONSTRUCTED_ATTRIBUTION_NOTE}",
    )


def _contribution(item: attribution_engine.SecurityContribution, valued) -> ContributionRead:
    return ContributionRead(
        symbol=item.key[0],
        exchange=Exchange(item.key[1]),
        contribution_pct=as_percent(item.contribution) or Decimal(0),
        start_value=item.start_value,
        end_value=item.end_value,
        start_weight_pct=as_percent(item.start_weight),
        end_weight_pct=as_percent(item.end_weight),
        sessions_counted=item.sessions_counted,
    )


def _timeline_transaction(event: LedgerEvent, references: dict) -> TimelineTransactionRead:
    gross = Decimal(event.quantity) * event.price
    return TimelineTransactionRead(
        kind=event.kind,  # type: ignore[arg-type]
        symbol=event.symbol,
        exchange=Exchange(event.exchange),
        quantity=event.quantity,
        price=event.price,
        fees=event.fees,
        gross_value=gross,
        cash_flow=event.cash_flow,
        reference=references.get((event.trade_date, event.symbol, event.exchange, event.kind, event.quantity)),
        trade_date=event.trade_date,
    )


def _describe_changes(
    previous: dict[SecurityKey, int], current: dict[SecurityKey, int], events: list[LedgerEvent]
) -> list[str]:
    """Plain descriptions of what each traded security's position became."""
    changes: list[str] = []
    for key in sorted({event.key for event in events}):
        before, after = previous.get(key, 0), current.get(key, 0)
        delta = after - before
        sign = "+" if delta >= 0 else ""
        changes.append(f"{key[0]} {sign}{delta} → {after}")
    return changes


def _latest_closes(session: Session, listings: dict[SecurityKey, uuid.UUID]) -> dict[SecurityKey, tuple[Decimal, date]]:
    """The newest stored close per security, with its trade date."""
    if not listings:
        return {}
    rows = repository.recent_prices(session, list(listings.values()), Exchange.NSE, per_listing=1)
    by_listing = {
        listing_id: (prices[0].close_price, prices[0].trade_date)
        for listing_id, prices in rows.items()
        if prices
    }
    return {key: by_listing[listing_id] for key, listing_id in listings.items() if listing_id in by_listing}
