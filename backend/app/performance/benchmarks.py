"""Benchmark sources.

The market-data provider documents no index endpoint: there is no NIFTY 50, SENSEX or
NIFTY 500 series to fetch. Rather than invent one, a benchmark here is an **index ETF used as
a proxy** - an ordinary listed security whose closes flow through the existing sync, so no
separate price table and no new provider integration are needed.

An ETF is not its index, and the application says so everywhere it shows one:

* its market price can trade at a premium or discount to net asset value;
* it carries a total expense ratio, so it drifts below the index over time;
* its NAV reinvests dividends while a price index does not, which pushes the other way;
* it has its own liquidity, and a thin day's close is its own close, not the index's.

Those are disclosed, not corrected for: adjusting an ETF series to "reconstruct" the index
would be fabrication.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.market_data import repository
from app.portfolios.rules import Exchange


@dataclass(frozen=True, slots=True)
class BenchmarkDefinition:
    """A tracked security standing in for an index."""

    key: str
    display_name: str
    nse_symbol: str
    exchange: Exchange
    tracks: str  # the index this instrument aims to follow
    source: str  # where its prices come from
    is_proxy: bool
    methodology: str
    note: str

    @property
    def basis(self) -> str:
        return "ETF_PROXY" if self.is_proxy else "INDEX"


class BenchmarkStatus:
    AVAILABLE = "available"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN_KEY = "unknown_key"
    NO_DATA = "no_data"
    NOT_REQUESTED = "not_requested"


PROXY_DISCLOSURE = (
    "This is an index ETF used as a proxy, not the index itself. Its price can trade at a "
    "premium or discount to net asset value, it bears a total expense ratio, and its returns "
    "reflect the fund, not the published index. No adjustment is applied to make it look like "
    "the index."
)

# SETFNIF50 (SBI ETF Nifty 50) is the entry because it is what this architecture can actually
# price: it is in the provider's security master with an NSE symbol, so the existing sync can
# fetch its closes like any other security. Several other NIFTY 50 ETFs - NIFTYBEES among them -
# appear in the master with a BSE code but no NSE symbol, which the NSE-only price pipeline
# cannot use.
BENCHMARKS: dict[str, BenchmarkDefinition] = {
    "NIFTY50": BenchmarkDefinition(
        key="NIFTY50",
        display_name="NIFTY 50 (via SBI ETF Nifty 50)",
        nse_symbol="SETFNIF50",
        exchange=Exchange.NSE,
        tracks="NIFTY 50",
        source="Indian API end-of-day closes for SETFNIF50 on NSE",
        is_proxy=True,
        methodology=(
            "Daily end-of-day closes of the SETFNIF50 ETF, rebased to 100 at the first session "
            "of the window. Returns are measured between adjacent completed sessions, exactly "
            "as the portfolio's are."
        ),
        note=PROXY_DISCLOSURE,
    )
}

NOT_CONFIGURED_NOTE = (
    "No benchmark series is ingested yet. The market-data provider documents no index endpoint, "
    "so a benchmark requires syncing an index ETF as a tracked security; comparison is deferred "
    "rather than estimated."
)

NO_DATA_NOTE = (
    "This benchmark is configured but its price history has not been synced yet, so no "
    "comparison is shown. Nothing is estimated in its place."
)


def available_benchmarks() -> list[BenchmarkDefinition]:
    return sorted(BENCHMARKS.values(), key=lambda item: item.key)


def get_benchmark(key: str) -> BenchmarkDefinition | None:
    return BENCHMARKS.get(key.strip().upper())


def benchmark_listing_id(session: Session, provider: str, definition: BenchmarkDefinition) -> uuid.UUID | None:
    by_nse, _ = repository.listings_by_codes(session, provider, {definition.nse_symbol}, set())
    listing = by_nse.get(definition.nse_symbol)
    return listing.id if listing is not None else None


def benchmark_closes(
    session: Session,
    provider: str,
    definition: BenchmarkDefinition,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[date, Decimal]:
    """Stored closes for a benchmark, keyed by trade date. Empty when nothing is stored."""
    listing_id = benchmark_listing_id(session, provider, definition)
    if listing_id is None:
        return {}
    series = repository.price_series(session, [listing_id], Exchange.NSE, start=start, end=end)
    return {row.trade_date: row.close_price for row in series.get(listing_id, [])}
