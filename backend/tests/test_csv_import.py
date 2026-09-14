"""Unit tests for the CSV parser (no database)."""

from decimal import Decimal

from app.portfolios.csv_import import parse_holdings_csv
from app.portfolios.rules import MAX_HOLDINGS_PER_PORTFOLIO, Exchange

VALID_CSV = b"""symbol,exchange,quantity,average_buy_price
HDFCBANK,NSE,20,1650
TCS,NSE,10,3200
RELIANCE,NSE,15,1400
"""


def messages(content: bytes) -> list[str]:
    return [issue.message for issue in parse_holdings_csv(content).errors]


def test_valid_csv_is_accepted() -> None:
    result = parse_holdings_csv(VALID_CSV)

    assert result.is_valid
    assert result.errors == []
    assert [(h.symbol, h.exchange, h.quantity, h.average_buy_price) for h in result.holdings] == [
        ("HDFCBANK", Exchange.NSE, 20, Decimal("1650.0000")),
        ("TCS", Exchange.NSE, 10, Decimal("3200.0000")),
        ("RELIANCE", Exchange.NSE, 15, Decimal("1400.0000")),
    ]


def test_normalizes_case_whitespace_bom_and_column_order() -> None:
    content = "﻿Exchange, SYMBOL ,Average_Buy_Price,quantity\r\n nse , hdfcbank ,1650.50, 20 \r\n\r\n".encode()

    result = parse_holdings_csv(content)

    assert result.is_valid
    assert result.holdings[0].symbol == "HDFCBANK"
    assert result.holdings[0].exchange is Exchange.NSE
    assert result.holdings[0].average_buy_price == Decimal("1650.5000")


def test_missing_header_column_is_rejected() -> None:
    result = parse_holdings_csv(b"symbol,exchange,quantity\nHDFCBANK,NSE,20\n")

    assert not result.is_valid
    assert result.holdings == []
    assert "Missing required column(s): average_buy_price" in result.errors[0].message
    assert result.errors[0].row == 1


def test_file_without_header_is_rejected() -> None:
    assert any("Missing required column(s)" in m for m in messages(b"HDFCBANK,NSE,20,1650\n"))


def test_extra_column_is_rejected() -> None:
    content = b"symbol,exchange,quantity,average_buy_price,notes\nHDFCBANK,NSE,20,1650,core\n"
    assert any("Unexpected column(s): notes" in m for m in messages(content))


def test_duplicate_header_column_is_rejected() -> None:
    content = b"symbol,exchange,quantity,average_buy_price,symbol\nHDFCBANK,NSE,20,1650,TCS\n"
    assert any("Duplicate column(s)" in m for m in messages(content))


def test_row_with_wrong_number_of_values_is_rejected() -> None:
    result = parse_holdings_csv(VALID_CSV + b"INFY,NSE,5\n")

    assert not result.is_valid
    assert result.errors[0].row == 5
    assert "Expected 4 values but found 3" in result.errors[0].message


def test_malformed_quoting_is_rejected() -> None:
    result = parse_holdings_csv(b'symbol,exchange,quantity,average_buy_price\n"HDFCBANK,NSE,20,1650\n')

    assert not result.is_valid
    assert "not a valid CSV file" in result.errors[0].message


def test_blank_values_are_rejected() -> None:
    result = parse_holdings_csv(b"symbol,exchange,quantity,average_buy_price\n,NSE,,1650\n")

    assert {(e.column, e.message) for e in result.errors} == {
        ("symbol", "Symbol is required."),
        ("quantity", "Quantity is required."),
    }


def test_invalid_numeric_values_are_rejected() -> None:
    content = b'symbol,exchange,quantity,average_buy_price\nHDFCBANK,NSE,twenty,1650\nTCS,NSE,10,"3,200"\n'
    result = parse_holdings_csv(content)

    assert [(e.row, e.column) for e in result.errors] == [(2, "quantity"), (3, "average_buy_price")]
    assert all("must be a number" in e.message for e in result.errors)


def test_negative_values_are_rejected() -> None:
    content = b"symbol,exchange,quantity,average_buy_price\nHDFCBANK,NSE,-20,1650\nTCS,NSE,10,-3200\n"
    result = parse_holdings_csv(content)

    assert [e.message for e in result.errors] == [
        "Quantity must be greater than 0.",
        "Average buy price must be greater than 0.",
    ]


def test_zero_values_are_rejected() -> None:
    content = b"symbol,exchange,quantity,average_buy_price\nHDFCBANK,NSE,0,1650\nTCS,NSE,10,0\n"
    assert messages(content) == [
        "Quantity must be greater than 0.",
        "Average buy price must be greater than 0.",
    ]


def test_fractional_quantity_is_rejected() -> None:
    content = b"symbol,exchange,quantity,average_buy_price\nHDFCBANK,NSE,2.5,1650\n"
    assert messages(content) == ["Quantity must be a whole number of shares."]


def test_invalid_exchange_is_rejected() -> None:
    content = b"symbol,exchange,quantity,average_buy_price\nAAPL,NASDAQ,5,180\n"
    assert messages(content) == ["Exchange must be NSE or BSE."]


def test_duplicate_holding_is_rejected_not_merged() -> None:
    content = VALID_CSV + b"hdfcbank,nse,5,1700\n"
    result = parse_holdings_csv(content)

    assert not result.is_valid
    assert len(result.errors) == 1
    assert result.errors[0].row == 5
    assert "Duplicate holding: HDFCBANK on NSE is also listed on row 2" in result.errors[0].message
    hdfc = [h for h in result.holdings if h.symbol == "HDFCBANK"]
    assert len(hdfc) == 1 and hdfc[0].quantity == 20


def test_same_symbol_on_different_exchanges_is_not_a_duplicate() -> None:
    content = b"symbol,exchange,quantity,average_buy_price\nHDFCBANK,NSE,20,1650\nHDFCBANK,BSE,5,1655\n"
    assert parse_holdings_csv(content).is_valid


def test_every_invalid_row_is_reported() -> None:
    content = b"symbol,exchange,quantity,average_buy_price\nA,NSE,0,1\nB,XYZ,1,1\nC,NSE,1,-1\nD,NSE,1,1\n"
    result = parse_holdings_csv(content)

    assert [e.row for e in result.errors] == [2, 3, 4]
    assert not result.is_valid


def test_empty_file_is_rejected() -> None:
    assert "The file is empty" in messages(b"")[0]
    assert "The file is empty" in messages(b"\n\n  \n")[0]


def test_header_without_rows_is_rejected() -> None:
    assert messages(b"symbol,exchange,quantity,average_buy_price\n") == ["The file has a header but no holdings."]


def test_non_utf8_file_is_rejected() -> None:
    assert "not UTF-8" in messages("symbol,exchange\nMÜLLER,NSE\n".encode("latin-1"))[0]


def test_binary_file_is_rejected() -> None:
    assert "not UTF-8" in messages(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")[0]
    assert "binary data" in messages(b"symbol,exchange\x00\x00\x00,quantity\n")[0]


def test_too_many_rows_is_rejected() -> None:
    rows = "".join(f"S{i},NSE,1,1\n" for i in range(MAX_HOLDINGS_PER_PORTFOLIO + 1))
    content = ("symbol,exchange,quantity,average_buy_price\n" + rows).encode()

    assert messages(content) == [f"The file contains {MAX_HOLDINGS_PER_PORTFOLIO + 1} holdings; the maximum is 500."]


def test_formula_like_values_are_treated_as_plain_invalid_text() -> None:
    content = b"symbol,exchange,quantity,average_buy_price\n=HYPERLINK(\"x\"),NSE,1,1\n"
    result = parse_holdings_csv(content)

    assert not result.is_valid
    assert result.errors[0].column == "symbol"
