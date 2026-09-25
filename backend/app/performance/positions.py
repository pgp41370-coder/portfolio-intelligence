"""Turn a transaction ledger into the position held at the close of each trading session.

Pure functions: no database, no clock. The rules are documented in docs/transactions.md.

* A transaction is recognised at the close of its trade date, or of the next session day when
  the trade date is not a session (a settlement date, or a year the calendar does not cover).
* Same-day transactions in one security are netted; only end-of-day prices exist, so intra-day
  sequencing is not modelled and is not pretended to be.
* A day's closing position may never be negative. Nothing is clamped: an oversold ledger is
  reported as a data error.
"""

import bisect
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)

BUY = "BUY"
SELL = "SELL"

# (symbol, exchange) — the same pair that identifies a holding.
SecurityKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """One transaction, reduced to what the engine needs."""

    trade_date: date
    symbol: str
    exchange: str
    kind: str
    quantity: int
    price: Decimal
    fees: Decimal = Decimal(0)

    @property
    def key(self) -> SecurityKey:
        return (self.symbol, self.exchange)

    @property
    def signed_quantity(self) -> int:
        return self.quantity if self.kind == BUY else -self.quantity

    @property
    def cash_flow(self) -> Decimal:
        """Money the investor put in (+) or took out (-), including costs.

        A buy costs quantity x price plus fees; a sell returns quantity x price less fees.
        Fees therefore reduce the return, which is what they do in reality.
        """
        with localcontext(_CONTEXT):
            gross = Decimal(self.quantity) * self.price
            return gross + self.fees if self.kind == BUY else -(gross - self.fees)


class OversoldLedgerError(ValueError):
    """A sell would take a security's closing position below zero."""

    def __init__(self, symbol: str, exchange: str, day: date, held: int, sold: int) -> None:
        self.symbol, self.exchange, self.day, self.held, self.sold = symbol, exchange, day, held, sold
        super().__init__(
            f"{symbol} on {exchange}: selling {sold} on {day:%d %b %Y} exceeds the {held} held. "
            "Short positions are not supported."
        )


@dataclass(slots=True)
class Timeline:
    """Positions and external cash flows across an ordered list of sessions."""

    sessions: list[date]
    opening: dict[SecurityKey, int]
    positions: list[dict[SecurityKey, int]] = field(default_factory=list)
    flows: list[Decimal] = field(default_factory=list)
    # The same flows split by security, which attribution needs to tell a price move apart
    # from a purchase.
    security_flows: list[dict[SecurityKey, Decimal]] = field(default_factory=list)
    # The transactions recognised at each session's close, for the portfolio timeline.
    events_on: list[list[LedgerEvent]] = field(default_factory=list)
    unrecognised: list[LedgerEvent] = field(default_factory=list)
    non_session_dates: list[date] = field(default_factory=list)

    def position_on(self, index: int) -> dict[SecurityKey, int]:
        return self.positions[index]

    @property
    def securities_ever_held(self) -> set[SecurityKey]:
        held = {key for key, quantity in self.opening.items() if quantity}
        for position in self.positions:
            held |= {key for key, quantity in position.items() if quantity}
        return held

    @property
    def first_funded_index(self) -> int | None:
        """The first session at whose close any security is held."""
        for index, position in enumerate(self.positions):
            if any(quantity > 0 for quantity in position.values()):
                return index
        return None


def validate_ledger(events: Iterable[LedgerEvent]) -> None:
    """Raise if any day's closing position would go negative. Order: trade date, then input order."""
    running: dict[SecurityKey, int] = {}
    for day, same_day in _group_by_day(events):
        deltas: dict[SecurityKey, int] = {}
        sold: dict[SecurityKey, int] = {}
        for event in same_day:
            deltas[event.key] = deltas.get(event.key, 0) + event.signed_quantity
            if event.kind == SELL:
                sold[event.key] = sold.get(event.key, 0) + event.quantity
        for key, delta in deltas.items():
            closing = running.get(key, 0) + delta
            if closing < 0:
                symbol, exchange = key
                raise OversoldLedgerError(symbol, exchange, day, running.get(key, 0), sold.get(key, 0))
            running[key] = closing


def build_timeline(
    events: Sequence[LedgerEvent], sessions: Sequence[date], *, opening_before: date | None = None
) -> Timeline:
    """Walk the sessions, applying each day's recognised transactions.

    ``opening_before`` is the first day the window measures, which defaults to the first
    session. Transactions dated before it form the opening position - a window starting
    mid-history is still valued against the position actually held, and their cash flows
    belong to a period this window does not measure. Transactions on or after it are
    recognised inside the window, including one dated on the weekend before it opens.
    """
    ordered = [event for _, group in _group_by_day(events) for event in group]
    session_list = list(sessions)
    cutoff = opening_before if opening_before is not None else (session_list[0] if session_list else None)
    timeline = Timeline(sessions=session_list, opening={})

    if not session_list:
        timeline.unrecognised = list(ordered)
        return timeline

    opening: dict[SecurityKey, int] = {}
    by_index: dict[int, list[LedgerEvent]] = {}
    for event in ordered:
        if cutoff is not None and event.trade_date < cutoff:
            opening[event.key] = opening.get(event.key, 0) + event.signed_quantity
            continue
        recognised = _recognise(event.trade_date, session_list)
        if recognised is None:
            timeline.unrecognised.append(event)  # dated after the window's last session
            continue
        if recognised != event.trade_date:
            timeline.non_session_dates.append(event.trade_date)
        by_index.setdefault(bisect.bisect_left(session_list, recognised), []).append(event)
    timeline.opening = opening

    running = dict(opening)
    with localcontext(_CONTEXT):
        for index in range(len(session_list)):
            flow = Decimal(0)
            per_security: dict[SecurityKey, Decimal] = {}
            for event in by_index.get(index, []):
                running[event.key] = running.get(event.key, 0) + event.signed_quantity
                flow += event.cash_flow
                per_security[event.key] = per_security.get(event.key, Decimal(0)) + event.cash_flow
            timeline.positions.append({key: quantity for key, quantity in running.items() if quantity})
            timeline.flows.append(flow)
            timeline.security_flows.append(per_security)
            timeline.events_on.append(list(by_index.get(index, [])))
    return timeline


def final_positions(events: Iterable[LedgerEvent]) -> dict[SecurityKey, int]:
    """Net position per security after every transaction, excluding closed positions."""
    running: dict[SecurityKey, int] = {}
    for event in events:
        running[event.key] = running.get(event.key, 0) + event.signed_quantity
    return {key: quantity for key, quantity in running.items() if quantity}


def _recognise(trade_date: date, sessions: Sequence[date]) -> date | None:
    """The session at whose close a trade is recognised: the trade date or the next session."""
    index = bisect.bisect_left(sessions, trade_date)
    return sessions[index] if index < len(sessions) else None


def _group_by_day(events: Iterable[LedgerEvent]) -> list[tuple[date, list[LedgerEvent]]]:
    grouped: dict[date, list[LedgerEvent]] = {}
    for event in events:
        grouped.setdefault(event.trade_date, []).append(event)
    return sorted(grouped.items())
