"""Cost basis, realised and unrealised profit and loss from the transaction ledger.

**Methodology: FIFO.** Shares sold are matched against the earliest lots still open. FIFO is the
basis Indian income-tax law applies to listed equity shares, it is deterministic, and it needs no
extra data from the user. Average cost and LIFO are deliberately not offered: presenting a figure
whose basis the user did not choose, or silently switching basis, would make two runs of the same
ledger disagree.

Costs are carried on the lot. A buy's fees increase the cost of the shares it bought; when a lot is
partly sold, its remaining fees are allocated pro rata by quantity. A sale's fees reduce its
proceeds. Both therefore reduce realised profit, which is what they do in reality.

Realised P&L for one sale:

    proceeds = quantity x sale price - sale fees
    cost     = sum over matched lots of (quantity x lot price + allocated lot fees)
    realised = proceeds - cost

Unrealised P&L for an open position, once a market price exists:

    unrealised = quantity x market close - remaining cost

This is a **price** P&L: it excludes dividends, and it is not adjusted for corporate actions. A
split will show as a loss against an unadjusted cost basis, which is why the reconciliation and the
corporate-action warnings elsewhere in the application matter.
"""

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from app.performance.positions import BUY, SELL, LedgerEvent, SecurityKey

_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)

COST_BASIS_NOTE = (
    "Shares sold are matched against the earliest lots still open (FIFO), the basis Indian "
    "income-tax law applies to listed equity shares. Buy fees are added to the cost of the shares "
    "they bought and allocated pro rata when a lot is partly sold; sale fees reduce proceeds. "
    "Excludes dividends; not adjusted for corporate actions."
)


@dataclass(slots=True)
class Lot:
    """An open parcel of shares at the price and cost it was bought for."""

    trade_date: date
    quantity: int
    price: Decimal
    fees: Decimal

    @property
    def cost(self) -> Decimal:
        """What the remaining shares in this lot cost, including their share of the fees."""
        with localcontext(_CONTEXT):
            return Decimal(self.quantity) * self.price + self.fees


@dataclass(slots=True)
class Disposal:
    """One sale, matched against the lots it closed."""

    trade_date: date
    key: SecurityKey
    quantity: int
    proceeds: Decimal
    cost: Decimal
    matched_lots: int

    @property
    def realised(self) -> Decimal:
        with localcontext(_CONTEXT):
            return self.proceeds - self.cost


@dataclass(slots=True)
class SecurityPnl:
    key: SecurityKey
    quantity: int
    cost: Decimal  # cost of the shares still held
    realised: Decimal
    contributions: Decimal  # cash paid for buys, including fees
    withdrawals: Decimal  # cash received from sales, net of fees
    fees: Decimal
    first_trade: date | None = None
    last_trade: date | None = None

    @property
    def average_cost(self) -> Decimal | None:
        if self.quantity <= 0:
            return None
        with localcontext(_CONTEXT):
            return self.cost / Decimal(self.quantity)


@dataclass(slots=True)
class LedgerPnl:
    securities: dict[SecurityKey, SecurityPnl] = field(default_factory=dict)
    disposals: list[Disposal] = field(default_factory=list)
    oversold: list[tuple[date, SecurityKey, int]] = field(default_factory=list)

    @property
    def realised(self) -> Decimal:
        return sum((item.realised for item in self.securities.values()), Decimal(0))

    @property
    def contributions(self) -> Decimal:
        return sum((item.contributions for item in self.securities.values()), Decimal(0))

    @property
    def withdrawals(self) -> Decimal:
        return sum((item.withdrawals for item in self.securities.values()), Decimal(0))

    @property
    def fees(self) -> Decimal:
        return sum((item.fees for item in self.securities.values()), Decimal(0))

    @property
    def open_cost(self) -> Decimal:
        return sum((item.cost for item in self.securities.values()), Decimal(0))

    @property
    def net_invested(self) -> Decimal:
        """Money still in the portfolio: everything paid in, less everything taken out."""
        with localcontext(_CONTEXT):
            return self.contributions - self.withdrawals


def build_pnl(events: Sequence[LedgerEvent], *, until: date | None = None) -> LedgerPnl:
    """Walk the ledger in date order, matching sales against the oldest open lots.

    ``until`` measures the ledger as it stood at the end of that day, which is what a historical
    window needs. An oversell cannot normally reach this point - the service rejects it on entry -
    but if one exists it is recorded rather than allowed to produce a negative position.
    """
    result = LedgerPnl()
    open_lots: dict[SecurityKey, deque[Lot]] = {}

    for event in sorted(events, key=lambda item: (item.trade_date, item.kind == SELL)):
        if until is not None and event.trade_date > until:
            continue
        entry = result.securities.setdefault(
            event.key,
            SecurityPnl(
                key=event.key,
                quantity=0,
                cost=Decimal(0),
                realised=Decimal(0),
                contributions=Decimal(0),
                withdrawals=Decimal(0),
                fees=Decimal(0),
            ),
        )
        entry.first_trade = entry.first_trade or event.trade_date
        entry.last_trade = event.trade_date
        with localcontext(_CONTEXT):
            entry.fees += event.fees

        if event.kind == BUY:
            lot = Lot(event.trade_date, event.quantity, event.price, event.fees)
            open_lots.setdefault(event.key, deque()).append(lot)
            with localcontext(_CONTEXT):
                entry.quantity += event.quantity
                entry.cost += lot.cost
                entry.contributions += event.cash_flow  # quantity x price + fees
            continue

        remaining, cost, matched = event.quantity, Decimal(0), 0
        lots = open_lots.setdefault(event.key, deque())
        while remaining > 0 and lots:
            lot = lots[0]
            take = min(remaining, lot.quantity)
            with localcontext(_CONTEXT):
                # Fees travel with the shares they were paid for.
                fee_share = lot.fees * Decimal(take) / Decimal(lot.quantity)
                cost += Decimal(take) * lot.price + fee_share
                lot.fees -= fee_share
            lot.quantity -= take
            remaining -= take
            matched += 1
            if lot.quantity == 0:
                lots.popleft()

        if remaining > 0:
            # Nothing is invented to cover the shortfall; the sale is recorded for what could be
            # matched and the gap is reported.
            result.oversold.append((event.trade_date, event.key, remaining))

        sold = event.quantity - remaining
        with localcontext(_CONTEXT):
            proceeds = Decimal(sold) * event.price - (event.fees if sold else Decimal(0))
            entry.quantity -= sold
            entry.cost -= cost
            entry.realised += proceeds - cost
            entry.withdrawals += proceeds
        result.disposals.append(
            Disposal(event.trade_date, event.key, sold, proceeds, cost, matched)
        )

    return result


def unrealised(quantity: int, cost: Decimal, close: Decimal | None) -> Decimal | None:
    """Market value of an open position less what it cost. None without a price."""
    if close is None or quantity <= 0:
        return None
    with localcontext(_CONTEXT):
        return Decimal(quantity) * close - cost


def open_lots_for(events: Iterable[LedgerEvent], key: SecurityKey) -> list[Lot]:
    """The lots still open for one security, oldest first - the detail behind its cost basis."""
    pnl_events = [event for event in events if event.key == key]
    lots: deque[Lot] = deque()
    for event in sorted(pnl_events, key=lambda item: (item.trade_date, item.kind == SELL)):
        if event.kind == BUY:
            lots.append(Lot(event.trade_date, event.quantity, event.price, event.fees))
            continue
        remaining = event.quantity
        while remaining > 0 and lots:
            lot = lots[0]
            take = min(remaining, lot.quantity)
            with localcontext(_CONTEXT):
                lot.fees -= lot.fees * Decimal(take) / Decimal(lot.quantity)
            lot.quantity -= take
            remaining -= take
            if lot.quantity == 0:
                lots.popleft()
    return list(lots)
