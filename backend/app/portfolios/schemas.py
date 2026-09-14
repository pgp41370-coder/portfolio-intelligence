"""Request and response models for the portfolio API.

Amounts are serialised as decimal strings (e.g. "1650.00") so no precision is
lost to floating point on the way to the client.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.portfolios.calculations import format_amount
from app.portfolios.rules import (
    MAX_HOLDINGS_PER_PORTFOLIO,
    Exchange,
    normalize_exchange,
    normalize_portfolio_name,
    normalize_symbol,
    parse_average_buy_price,
    parse_quantity,
)

Amount = Annotated[Decimal, PlainSerializer(format_amount, return_type=str)]


class HoldingInput(BaseModel):
    """One holding exactly as the user entered it (after normalisation)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(examples=["HDFCBANK"])
    exchange: Exchange = Field(examples=["NSE"])
    quantity: int = Field(examples=[20])
    average_buy_price: Amount = Field(examples=["1650.00"])

    @field_validator("symbol", mode="before")
    @classmethod
    def _validate_symbol(cls, value: object) -> str:
        return normalize_symbol(value)

    @field_validator("exchange", mode="before")
    @classmethod
    def _validate_exchange(cls, value: object) -> Exchange:
        return normalize_exchange(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def _validate_quantity(cls, value: object) -> int:
        return parse_quantity(value)

    @field_validator("average_buy_price", mode="before")
    @classmethod
    def _validate_average_buy_price(cls, value: object) -> Decimal:
        return parse_average_buy_price(value)


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(examples=["Long-term portfolio"])
    holdings: list[HoldingInput] = Field(default_factory=list, max_length=MAX_HOLDINGS_PER_PORTFOLIO)

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        return normalize_portfolio_name(value)

    @model_validator(mode="after")
    def _reject_duplicate_holdings(self) -> Self:
        seen: set[tuple[str, Exchange]] = set()
        for holding in self.holdings:
            key = (holding.symbol, holding.exchange)
            if key in seen:
                raise ValueError(
                    f"{holding.symbol} on {holding.exchange} is listed more than once. "
                    "Each holding can appear only once in a portfolio."
                )
            seen.add(key)
        return self


class HoldingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    symbol: str
    exchange: Exchange
    quantity: int
    average_buy_price: Amount
    created_at: datetime
    updated_at: datetime


class PortfolioSummary(BaseModel):
    id: UUID
    name: str
    holding_count: int
    total_invested_capital: Amount
    created_at: datetime
    updated_at: datetime


class PortfolioDetail(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    holdings: list[HoldingRead]
    total_invested_capital: Amount


class CsvIssueRead(BaseModel):
    row: int | None
    column: str | None
    message: str


class CsvPreviewResponse(BaseModel):
    is_valid: bool
    holding_count: int
    holdings: list[HoldingInput]
    total_invested_capital: Amount | None
    errors: list[CsvIssueRead]
