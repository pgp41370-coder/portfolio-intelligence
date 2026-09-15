"""Indian API response validation against recorded fixtures (no network)."""

import copy
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.market_data.exceptions import ProviderGranularityError, ProviderResponseError
from app.market_data.providers.indian_api import parse_historical_prices, parse_security_master
from app.portfolios.rules import Exchange
from market_data_fakes import load_fixture

TODAY = date(2026, 9, 14)


def price_payload(values: list[Any], *, label: str = "Price on NSE", is_weekly: object = False) -> dict[str, Any]:
    return {"datasets": [{"metric": "Price", "label": label, "values": values, "meta": {"is_weekly": is_weekly}}]}


@pytest.mark.parametrize(
    ("fixture", "symbol", "last_close"),
    [
        ("historical_reliance.json", "RELIANCE", "2650.0000"),
        ("historical_tcs.json", "TCS", "3207.3500"),
        ("historical_infy.json", "INFY", "1627.5500"),
        ("historical_hdfcbank.json", "HDFCBANK", "1672.8500"),
        ("historical_mm.json", "M&M", "3094.6000"),
    ],
)
def test_valid_daily_nse_history_is_parsed(fixture: str, symbol: str, last_close: str) -> None:
    series = parse_historical_prices(load_fixture(fixture), symbol=symbol, today=TODAY)

    assert series.symbol == symbol
    assert series.exchange is Exchange.NSE
    assert len(series.bars) == 6
    assert [bar.trade_date for bar in series.bars] == sorted(bar.trade_date for bar in series.bars)
    assert series.bars[-1].trade_date == date(2026, 9, 14)
    assert str(series.bars[-1].close_price) == last_close
    assert all(isinstance(bar.close_price, Decimal) for bar in series.bars)
    assert all(isinstance(bar.volume, int) for bar in series.bars)
    assert series.skipped_points == 0


def test_moving_averages_are_never_used_as_prices() -> None:
    series = parse_historical_prices(load_fixture("historical_reliance.json"), symbol="RELIANCE", today=TODAY)

    assert Decimal("2557.4000") not in {bar.close_price for bar in series.bars}


def test_missing_prices_are_skipped_not_invented() -> None:
    series = parse_historical_prices(load_fixture("historical_missing_price.json"), symbol="RELIANCE", today=TODAY)

    assert series.skipped_points == 2
    assert [bar.trade_date for bar in series.bars] == [
        date(2026, 9, 7),
        date(2026, 9, 9),
        date(2026, 9, 11),
        date(2026, 9, 14),
    ]


def test_non_nse_prices_are_rejected() -> None:
    with pytest.raises(ProviderResponseError, match="not labelled as NSE"):
        parse_historical_prices(load_fixture("historical_non_nse.json"), symbol="TCS", today=TODAY)


def test_weekly_flagged_series_is_rejected() -> None:
    with pytest.raises(ProviderGranularityError):
        parse_historical_prices(load_fixture("historical_weekly.json"), symbol="INFY", today=TODAY)


def test_weekly_spacing_is_rejected_even_if_flagged_daily() -> None:
    payload = load_fixture("historical_weekly.json")
    payload["datasets"][0]["meta"]["is_weekly"] = False

    with pytest.raises(ProviderGranularityError, match="looks weekly"):
        parse_historical_prices(payload, symbol="INFY", today=TODAY)


@pytest.mark.parametrize("meta", [None, {}, {"is_weekly": None}, {"is_weekly": "false"}])
def test_unconfirmed_daily_granularity_is_rejected(meta: object) -> None:
    payload = copy.deepcopy(load_fixture("historical_reliance.json"))
    payload["datasets"][0]["meta"] = meta

    with pytest.raises(ProviderGranularityError):
        parse_historical_prices(payload, symbol="RELIANCE", today=TODAY)


@pytest.mark.parametrize(
    "payload",
    [
        "historical_malformed.json",
        [],
        "not json object",
        {"datasets": []},
        {"data": []},
        {"datasets": [{"metric": "Volume", "label": "Volume", "values": []}]},
    ],
)
def test_malformed_responses_are_rejected(payload: Any) -> None:
    if isinstance(payload, str) and payload.endswith(".json"):
        payload = load_fixture(payload)
    with pytest.raises(ProviderResponseError):
        parse_historical_prices(payload, symbol="RELIANCE", today=TODAY)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ([["2026/09/14", "2650.00"]], "YYYY-MM-DD"),
        ([["2026-13-40", "2650.00"]], "invalid date"),
        ([["2026-09-14", "-2650.00"]], "plain decimal"),
        ([["2026-09-14", "0"]], "positive"),
        ([["2026-09-14", "2,650.00"]], "plain decimal"),
        ([["2026-09-14", "₹2650"]], "plain decimal"),
        ([["2026-09-14", True]], "not a number"),
        ([["2026-09-14", "2650.123456"]], "4 decimal places"),
        ([["2026-09-15", "2650.00"]], "future"),
        ([["2026-09-14", "2650.00"], ["2026-09-14", "2651.00"]], "more than one price"),
        ([["2026-09-14"]], "malformed"),
        (["2026-09-14"], "malformed"),
    ],
)
def test_invalid_price_points_reject_the_whole_response(values: list[Any], message: str) -> None:
    with pytest.raises(ProviderResponseError, match=message):
        parse_historical_prices(price_payload(values), symbol="RELIANCE", today=TODAY)


def test_numeric_json_prices_are_converted_exactly() -> None:
    payload = price_payload([["2026-09-11", Decimal("2637.8")], ["2026-09-14", 2650]])

    series = parse_historical_prices(payload, symbol="RELIANCE", today=TODAY)

    assert [str(bar.close_price) for bar in series.bars] == ["2637.8000", "2650.0000"]


def test_multiple_price_datasets_are_ambiguous() -> None:
    payload = price_payload([["2026-09-14", "2650.00"]])
    payload["datasets"].append(copy.deepcopy(payload["datasets"][0]))

    with pytest.raises(ProviderResponseError, match="more than one"):
        parse_historical_prices(payload, symbol="RELIANCE", today=TODAY)


def test_security_master_is_normalised_and_ambiguous_codes_are_not_guessed() -> None:
    snapshot = parse_security_master(load_fixture("security_master.json"), min_rows=1)
    by_id = {record.provider_security_id: record for record in snapshot.records}

    assert by_id["S0003018"].nse_symbol == "RELIANCE" and by_id["S0003018"].bse_code == "500325"
    assert by_id["S0003018"].name == "Reliance Industries"
    assert by_id["S0003059"].nse_symbol == "M&M"
    assert by_id["S0003076"].nse_symbol == "M&MFIN"
    assert by_id["S0000064"].nse_symbol is None and by_id["S0000064"].bse_code == "539097"
    assert by_id["S0000105"].nse_symbol is None
    assert by_id["S0004774"].bse_code is None and by_id["S0004774"].nse_symbol == "KOTARISUG"
    assert by_id["S0005722"].bse_code is None
    assert by_id["T0000001"].nse_symbol is None and by_id["T0000001"].bse_code == "111111"
    assert by_id["T0000002"].nse_symbol is None and by_id["T0000002"].bse_code == "222222"
    assert all(record.isin is None for record in snapshot.records)
    assert len(snapshot.records) == 12
    assert snapshot.dropped_rows == 5
    assert snapshot.ambiguous_nse_symbols == ("DUPSYM",)


def test_security_master_rejects_non_lists_and_suspiciously_small_lists() -> None:
    with pytest.raises(ProviderResponseError):
        parse_security_master({"stocks": []})
    with pytest.raises(ProviderResponseError, match="suspiciously small"):
        parse_security_master(load_fixture("security_master.json"))
