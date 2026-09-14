"""Unit tests for validation rules and deterministic calculations (no database)."""

from dataclasses import dataclass
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.portfolios.calculations import format_amount, total_invested_capital
from app.portfolios.rules import (
    Exchange,
    normalize_exchange,
    normalize_portfolio_name,
    normalize_symbol,
    parse_average_buy_price,
    parse_quantity,
)
from app.portfolios.schemas import HoldingInput, PortfolioCreate


@dataclass
class _Position:
    quantity: int
    average_buy_price: Decimal


class TestTotalInvestedCapital:
    def test_is_sum_of_quantity_times_average_buy_price(self) -> None:
        positions = [
            _Position(20, Decimal("1650")),
            _Position(10, Decimal("3200")),
            _Position(15, Decimal("1400.5")),
        ]
        # 20 × 1650 + 10 × 3200 + 15 × 1400.5 = 33000 + 32000 + 21007.5
        assert total_invested_capital(positions) == Decimal("86007.5")

    def test_is_exact_with_four_decimal_places(self) -> None:
        positions = [_Position(3, Decimal("123.4567")), _Position(7, Decimal("0.0001"))]
        assert total_invested_capital(positions) == Decimal("370.3708")

    def test_is_zero_without_holdings(self) -> None:
        assert total_invested_capital([]) == Decimal("0")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0"), "0.00"),
        (Decimal("1650"), "1650.00"),
        (Decimal("1650.5000"), "1650.50"),
        (Decimal("1650.3333"), "1650.3333"),
        (Decimal("86007.5"), "86007.50"),
    ],
)
def test_format_amount(value: Decimal, expected: str) -> None:
    assert format_amount(value) == expected


class TestSymbol:
    @pytest.mark.parametrize("symbol", ["HDFCBANK", "M&M", "BAJAJ-AUTO", "500180", "L&TFH"])
    def test_accepts_real_symbol_formats(self, symbol: str) -> None:
        assert normalize_symbol(symbol) == symbol

    def test_trims_and_uppercases(self) -> None:
        assert normalize_symbol("  hdfcbank ") == "HDFCBANK"

    @pytest.mark.parametrize("symbol", ["", "   ", "HDFC BANK", "-TCS", "=CMD()", "TCS.NS", "ABCDEFGHIJKLMNOPQRSTU"])
    def test_rejects_invalid_symbols(self, symbol: str) -> None:
        with pytest.raises(ValueError):
            normalize_symbol(symbol)


class TestExchange:
    def test_normalizes_case(self) -> None:
        assert normalize_exchange(" nse ") is Exchange.NSE

    @pytest.mark.parametrize("exchange", ["", "NYSE", "NSEI", 1])
    def test_rejects_unsupported_exchanges(self, exchange: object) -> None:
        with pytest.raises(ValueError):
            normalize_exchange(exchange)


class TestQuantity:
    @pytest.mark.parametrize(("value", "expected"), [("20", 20), (20, 20), ("20.0", 20), (" 5 ", 5)])
    def test_accepts_whole_positive_numbers(self, value: object, expected: int) -> None:
        assert parse_quantity(value) == expected

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            ("0", "greater than 0"),
            ("-5", "greater than 0"),
            ("2.5", "whole number"),
            ("abc", "must be a number"),
            ("1,000", "must be a number"),
            ("", "required"),
            (True, "must be a number"),
            ("1000000001", "at most"),
        ],
    )
    def test_rejects_invalid_quantities(self, value: object, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_quantity(value)


class TestAverageBuyPrice:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1650", Decimal("1650.0000")), (1650.5, Decimal("1650.5000")), ("0.05", Decimal("0.0500"))],
    )
    def test_accepts_positive_prices(self, value: object, expected: Decimal) -> None:
        assert parse_average_buy_price(value) == expected

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            ("0", "greater than 0"),
            ("-1650", "greater than 0"),
            ("1650.12345", "4 decimal places"),
            ("₹1650", "must be a number"),
            ("NaN", "must be a number"),
            (float("inf"), "finite"),
            ("", "required"),
        ],
    )
    def test_rejects_invalid_prices(self, value: object, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_average_buy_price(value)


class TestPortfolioName:
    def test_collapses_whitespace(self) -> None:
        assert normalize_portfolio_name("  Long   term  ") == "Long term"

    @pytest.mark.parametrize("name", ["", "   ", "x" * 101, "bad\x00name"])
    def test_rejects_invalid_names(self, name: str) -> None:
        with pytest.raises(ValueError):
            normalize_portfolio_name(name)


class TestSchemas:
    def test_holding_input_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            HoldingInput.model_validate(
                {"symbol": "TCS", "exchange": "NSE", "quantity": 1, "average_buy_price": "1", "current_price": "5"}
            )

    def test_portfolio_create_rejects_duplicate_holdings(self) -> None:
        holding = {"symbol": "TCS", "exchange": "NSE", "quantity": 1, "average_buy_price": "1"}
        with pytest.raises(ValidationError, match="more than once"):
            PortfolioCreate.model_validate({"name": "Test", "holdings": [holding, {**holding, "symbol": "tcs"}]})
