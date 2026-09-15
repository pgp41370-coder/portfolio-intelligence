"""Indian API HTTP behaviour with a mocked transport: auth, throttling, retries and budget (no network)."""

import logging
from datetime import date

import httpx
import pytest

from app.market_data.exceptions import (
    ProviderAuthenticationError,
    ProviderNotConfiguredError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
    RequestBudgetExceededError,
)
from app.market_data.providers.indian_api import (
    MAX_ATTEMPTS,
    MAX_HISTORY_BYTES,
    RETRY_BACKOFF_SECONDS,
    IndianApiProvider,
)
from market_data_fakes import FIXTURES_DIR

TEST_KEY = "test-key-not-a-real-credential"
BASE_URL = "https://stock.indianapi.in"
MASTER_URL = "https://analyst.indianapi.in/static/all_stocks.json"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Responder:
    """MockTransport handler that returns queued (status, body) items; the last item repeats."""

    def __init__(self, *items: tuple[int, bytes] | type[Exception]) -> None:
        self.items = list(items)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("simulated failure", request=request)
        status, body = item
        return httpx.Response(status, content=body)


def fixture(name: str = "historical_reliance.json") -> tuple[int, bytes]:
    return 200, (FIXTURES_DIR / name).read_bytes()


def build(responder: Responder, *, key: str | None = TEST_KEY, **overrides: object) -> tuple[IndianApiProvider, FakeClock]:
    clock = FakeClock()
    provider = IndianApiProvider(
        api_key=key,
        base_url=BASE_URL,
        security_master_url=MASTER_URL,
        timeout_seconds=5,
        min_interval_seconds=1.1,
        transport=httpx.MockTransport(responder),
        clock=clock.monotonic,
        sleep=clock.sleep,
        today=lambda: date(2026, 9, 14),
        **overrides,  # type: ignore[arg-type]
    )
    return provider, clock


def test_historical_request_uses_documented_endpoint_parameters_and_header() -> None:
    responder = Responder(fixture("historical_mm.json"))
    provider, _ = build(responder)

    series = provider.get_daily_prices(" m&m ", "1m")

    [request] = responder.requests
    assert request.url.host == "stock.indianapi.in"
    assert request.url.path == "/historical_data"
    assert dict(request.url.params) == {"stock_name": "M&M", "period": "1m", "filter": "price"}
    assert b"stock_name=M%26M" in request.url.query
    assert request.headers["x-api-key"] == TEST_KEY
    assert series.symbol == "M&M"
    assert provider.metered_requests == 1


def test_requests_are_spaced_by_the_minimum_interval() -> None:
    responder = Responder(fixture())
    provider, clock = build(responder)

    provider.get_daily_prices("RELIANCE", "1m")
    provider.get_daily_prices("RELIANCE", "1m")

    assert len(responder.requests) == 2
    assert clock.sleeps == [pytest.approx(1.1)]


def test_missing_key_fails_before_any_request() -> None:
    responder = Responder(fixture())
    provider, _ = build(responder, key=None)

    with pytest.raises(ProviderNotConfiguredError):
        provider.get_daily_prices("RELIANCE", "1m")
    assert responder.requests == []


def test_invalid_symbol_is_rejected_without_a_request() -> None:
    responder = Responder(fixture())
    provider, _ = build(responder)

    with pytest.raises(ProviderRequestError):
        provider.get_daily_prices("HDFC BANK", "1m")
    assert responder.requests == []


@pytest.mark.parametrize(("status", "body"), [(400, b"Missing API key"), (401, b"Invalid API key"), (403, b"Forbidden")])
def test_authentication_errors_are_not_retried(status: int, body: bytes) -> None:
    responder = Responder((status, body))
    provider, clock = build(responder)

    with pytest.raises(ProviderAuthenticationError):
        provider.get_daily_prices("RELIANCE", "1m")
    assert len(responder.requests) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, ProviderNotFoundError), (422, ProviderRequestError), (302, ProviderRequestError)],
)
def test_request_errors_are_not_retried(status: int, error: type[Exception]) -> None:
    responder = Responder((status, b'{"error": "nope"}'))
    provider, _ = build(responder)

    with pytest.raises(error):
        provider.get_daily_prices("RELIANCE", "1m")
    assert len(responder.requests) == 1


def test_rate_limit_stops_without_retrying() -> None:
    responder = Responder((429, b"Rate limit exceeded"))
    provider, clock = build(responder)

    with pytest.raises(ProviderRateLimitError):
        provider.get_daily_prices("RELIANCE", "1m")
    assert len(responder.requests) == 1
    assert clock.sleeps == []


def test_server_errors_retry_with_bounded_backoff() -> None:
    responder = Responder((503, b""), (502, b""), fixture())
    provider, clock = build(responder)

    series = provider.get_daily_prices("RELIANCE", "1m")

    assert len(series.bars) == 6
    assert len(responder.requests) == 3
    assert list(RETRY_BACKOFF_SECONDS) == [s for s in clock.sleeps if s in RETRY_BACKOFF_SECONDS]


def test_server_errors_give_up_after_max_attempts() -> None:
    responder = Responder((500, b"boom"))
    provider, _ = build(responder)

    with pytest.raises(ProviderUnavailableError):
        provider.get_daily_prices("RELIANCE", "1m")
    assert len(responder.requests) == MAX_ATTEMPTS


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError])
def test_timeouts_and_network_errors_retry_then_fail(failure: type[Exception]) -> None:
    responder = Responder(failure)
    provider, _ = build(responder)

    with pytest.raises(ProviderUnavailableError):
        provider.get_daily_prices("RELIANCE", "1m")
    assert len(responder.requests) == MAX_ATTEMPTS


def test_budget_guard_blocks_the_request_before_sending() -> None:
    responder = Responder(fixture())
    provider, _ = build(responder)

    def exhausted() -> None:
        raise RequestBudgetExceededError("budget used")

    provider.set_request_guard(exhausted)
    with pytest.raises(RequestBudgetExceededError):
        provider.get_daily_prices("RELIANCE", "1m")
    assert responder.requests == []


def test_budget_guard_counts_every_attempt_including_retries() -> None:
    responder = Responder((500, b""), (500, b""), fixture())
    provider, _ = build(responder)
    consumed: list[int] = []
    provider.set_request_guard(lambda: consumed.append(1))

    provider.get_daily_prices("RELIANCE", "1m")

    assert len(consumed) == 3 == len(responder.requests)


def test_invalid_json_is_not_retried_or_stored() -> None:
    responder = Responder((200, b"<html>not json</html>"))
    provider, _ = build(responder)

    with pytest.raises(ProviderResponseError, match="not valid JSON"):
        provider.get_daily_prices("RELIANCE", "1m")
    assert len(responder.requests) == 1


def test_oversized_responses_are_rejected() -> None:
    responder = Responder((200, b"x" * (MAX_HISTORY_BYTES + 1)))
    provider, _ = build(responder)

    with pytest.raises(ProviderResponseError, match="larger than"):
        provider.get_daily_prices("RELIANCE", "1m")


def test_security_master_is_unauthenticated_and_unmetered() -> None:
    responder = Responder(fixture("security_master.json"))
    provider, _ = build(responder, security_master_min_rows=1)

    def must_not_be_called() -> None:
        raise AssertionError("the security master must not consume request budget")

    provider.set_request_guard(must_not_be_called)
    snapshot = provider.get_security_master()

    [request] = responder.requests
    assert str(request.url) == MASTER_URL
    assert "x-api-key" not in request.headers
    assert provider.metered_requests == 0
    assert len(snapshot.records) == 12


def test_errors_and_logs_never_contain_the_api_key(caplog: pytest.LogCaptureFixture) -> None:
    echo = TEST_KEY.encode()
    responder = Responder((500, b"key " + echo), (500, b""), (418, b"echo " + echo))
    provider, _ = build(responder)

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderRequestError) as raised:
        provider.get_daily_prices("RELIANCE", "1m")

    assert TEST_KEY not in str(raised.value)
    assert "[redacted]" in str(raised.value)
    assert TEST_KEY not in caplog.text
