"""Test helpers for market data: recorded Indian API fixtures and a fake provider (no network)."""

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.market_data.records import DailyPriceSeries, HistoricalPeriod, SecurityMasterSnapshot

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "indian_api"


def load_fixture(name: str) -> Any:
    """Decode a fixture the same way the provider decodes responses (floats as Decimal)."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"), parse_float=Decimal)


class FakeProvider:
    """Implements MarketDataProvider with canned data and records every call."""

    name = "indian_api"
    display_name = "Indian API"

    def __init__(
        self,
        *,
        snapshot: SecurityMasterSnapshot | Exception | None = None,
        series: dict[str, DailyPriceSeries] | None = None,
        errors: dict[Any, Exception] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.series = dict(series or {})
        self.errors = dict(errors or {})
        self.calls: list[tuple[str, str]] = []
        self.guard: Callable[[], None] | None = None
        self.closed = False

    def set_request_guard(self, guard: Callable[[], None] | None) -> None:
        self.guard = guard

    def get_security_master(self) -> SecurityMasterSnapshot:
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        assert self.snapshot is not None, "FakeProvider has no security master snapshot"
        return self.snapshot

    def get_daily_prices(self, nse_symbol: str, period: HistoricalPeriod) -> DailyPriceSeries:
        if self.guard is not None:
            self.guard()
        self.calls.append((nse_symbol, period))
        error = self.errors.get((nse_symbol, period), self.errors.get(nse_symbol))
        if error is not None:
            raise error
        return self.series[nse_symbol]

    def close(self) -> None:
        self.closed = True
