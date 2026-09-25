"""Indian API adapter.

Two data sets are used, both documented by the provider:

* the public security list (``static/all_stocks.json``), which is not metered, and
* ``/historical_data?filter=price``, which returns dated NSE prices.

Live or "current" price fields are never read. Every response is validated before any
record is returned; anything that does not match the documented format raises
``ProviderResponseError`` so that nothing is stored from it.
"""

import json
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import Settings
from app.market_data.calendar import today_in_ist
from app.market_data.exceptions import (
    MarketDataError,
    ProviderAuthenticationError,
    ProviderGranularityError,
    ProviderNotConfiguredError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.market_data.records import (
    DailyPriceBar,
    DailyPriceSeries,
    HistoricalPeriod,
    SecurityMasterSnapshot,
    SecurityRecord,
)
from app.portfolios.rules import MAX_SYMBOL_LENGTH, SYMBOL_PATTERN, Exchange

logger = logging.getLogger(__name__)

PROVIDER_KEY = "indian_api"
PROVIDER_NAME = "Indian API"

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (2.0, 4.0)
MAX_HISTORY_BYTES = 2 * 1024 * 1024
MAX_SECURITY_MASTER_BYTES = 8 * 1024 * 1024
DIAGNOSTIC_SNIPPET_LIMIT = 200
DIAGNOSTIC_MAX_KEYS = 12
MIN_SECURITY_MASTER_ROWS = 100
MAX_CLOSE_PRICE = Decimal("99999999999999.9999")  # NUMERIC(18, 4)
MAX_VOLUME = 9_223_372_036_854_775_807  # BIGINT
PRICE_QUANTUM = Decimal("0.0001")
WEEKLY_SPACING_DAYS = 5
SUPPORTED_PERIODS: tuple[HistoricalPeriod, ...] = ("1m", "6m", "1yr")

_MISSING_VALUES = frozenset({"", "null", "none", "nan", "n/a", "-"})
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PLAIN_DECIMAL = re.compile(r"\d+(?:\.\d+)?")
_BSE_CODE = re.compile(r"\d{6}")
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}\d")
_NSE_LABEL = re.compile(r"\bNSE\b")
_DIGITS = re.compile(r"\d+")
_API_KEY_PROBLEM = re.compile(r"\bapi[\s_-]?key\b", re.IGNORECASE)
_REDACTED = "[redacted]"


class IndianApiProvider:
    """HTTP adapter for Indian API with throttling, bounded retries and response validation."""

    name = PROVIDER_KEY
    display_name = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        security_master_url: str,
        timeout_seconds: float,
        min_interval_seconds: float,
        security_master_min_rows: int = MIN_SECURITY_MASTER_ROWS,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], date] = today_in_ist,
    ) -> None:
        self._api_key = api_key or None
        self._base_url = base_url.rstrip("/")
        self._security_master_url = security_master_url
        self._min_interval = min_interval_seconds
        self._security_master_min_rows = security_master_min_rows
        self._clock = clock
        self._sleep = sleep
        self._today = today
        self._guard: Callable[[], None] | None = None
        self._last_request_started: float | None = None
        self.metered_requests = 0
        # No redirects: a redirect could send the API key to another host.
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "PortfolioIntelligence/0.1 (market-data sync)"},
        )

    @classmethod
    def from_settings(cls, settings: Settings, **overrides: Any) -> "IndianApiProvider":
        key = settings.indian_api_key.get_secret_value() if settings.indian_api_key else None
        options: dict[str, Any] = {
            "api_key": key,
            "base_url": settings.indian_api_base_url,
            "security_master_url": settings.indian_api_security_master_url,
            "timeout_seconds": settings.market_data_request_timeout_seconds,
            "min_interval_seconds": settings.market_data_min_request_interval_seconds,
        }
        options.update(overrides)
        return cls(**options)

    def set_request_guard(self, guard: Callable[[], None] | None) -> None:
        self._guard = guard

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "IndianApiProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_security_master(self) -> SecurityMasterSnapshot:
        payload, _ = self._request_json(
            self._security_master_url,
            params=None,
            metered=False,
            max_bytes=MAX_SECURITY_MASTER_BYTES,
            context="security master",
        )
        return parse_security_master(payload, min_rows=self._security_master_min_rows)

    def get_daily_prices(self, nse_symbol: str, period: HistoricalPeriod) -> DailyPriceSeries:
        if self._api_key is None:
            raise ProviderNotConfiguredError("INDIAN_API_KEY is not configured; historical prices cannot be requested.")
        if period not in SUPPORTED_PERIODS:
            raise ValueError(f"Unsupported history period {period!r}.")
        symbol = nse_symbol.strip().upper()
        if len(symbol) > MAX_SYMBOL_LENGTH or not SYMBOL_PATTERN.fullmatch(symbol):
            raise ProviderRequestError(f"{nse_symbol!r} is not a valid NSE symbol.")
        context = f"historical prices for {symbol}"
        payload, meta = self._request_json(
            f"{self._base_url}/historical_data",
            params={"stock_name": symbol, "period": period, "filter": "price"},
            metered=True,
            max_bytes=MAX_HISTORY_BYTES,
            context=context,
        )
        try:
            return parse_historical_prices(payload, symbol=symbol, today=self._today(), context=context, meta=meta)
        except MarketDataError as exc:  # the key must never survive into a diagnostic
            raise self._redacted(exc) from None

    # --- HTTP ------------------------------------------------------------------------

    def _request_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None,
        metered: bool,
        max_bytes: int,
        context: str,
    ) -> tuple[Any, str]:
        headers = {"X-Api-Key": self._api_key} if metered and self._api_key else {}
        last_error: MarketDataError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if metered and self._guard is not None:
                self._guard()  # raises RequestBudgetExceededError before anything is sent
            self._wait_for_rate_limit()
            if metered:
                self.metered_requests += 1
            try:
                status, body, content_type = self._send(
                    url, params=params, headers=headers, max_bytes=max_bytes, context=context
                )
            except httpx.TimeoutException:
                last_error = ProviderUnavailableError(f"{context}: the request timed out.")
            except httpx.TransportError as exc:
                last_error = ProviderUnavailableError(f"{context}: network error ({type(exc).__name__}).")
            else:
                if status == 200:
                    meta = response_meta(status, content_type, len(body))
                    return _decode_json(body, context, meta), meta
                error = _error_for_status(status, body, context)
                if not isinstance(error, ProviderUnavailableError):
                    raise self._redacted(error)
                last_error = error
            if attempt < MAX_ATTEMPTS:
                delay = RETRY_BACKOFF_SECONDS[attempt - 1]
                logger.warning(
                    "%s (attempt %d of %d); retrying in %.0f s.",
                    self._redact(str(last_error)),
                    attempt,
                    MAX_ATTEMPTS,
                    delay,
                )
                self._sleep(delay)
        assert last_error is not None
        raise self._redacted(last_error)

    def _send(
        self,
        url: str,
        *,
        params: dict[str, str] | None,
        headers: dict[str, str],
        max_bytes: int,
        context: str,
    ) -> tuple[int, bytes, str | None]:
        with self._client.stream("GET", url, params=params, headers=headers) as response:
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise ProviderResponseError(f"{context}: response is larger than {max_bytes} bytes.")
            received = bytearray()
            for chunk in response.iter_bytes():
                received.extend(chunk)
                if len(received) > max_bytes:
                    raise ProviderResponseError(f"{context}: response is larger than {max_bytes} bytes.")
            return response.status_code, bytes(received), response.headers.get("content-type")

    def _wait_for_rate_limit(self) -> None:
        now = self._clock()
        if self._last_request_started is not None:
            wait = self._min_interval - (now - self._last_request_started)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request_started = now

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, _REDACTED) if self._api_key else text

    def _redacted(self, error: MarketDataError) -> MarketDataError:
        return type(error)(self._redact(str(error)))


def _decode_json(body: bytes, context: str, meta: str | None = None) -> Any:
    try:
        return json.loads(body, parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):
        detail = f" ({meta}; snippet={_bounded(body.decode('utf-8', errors='replace'), DIAGNOSTIC_SNIPPET_LIMIT)})" if meta else ""
        raise ProviderResponseError(f"{context}: response was not valid JSON.{detail}") from None


def _snippet(body: bytes, limit: int = 120) -> str:
    text = body.decode("utf-8", errors="replace")
    text = "".join(character for character in text if character.isprintable() or character.isspace())
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or "empty body"


# Diagnostics may reach public CI logs and the sync-run record, so anything that looks like a
# credential is removed before a snippet is kept, and the snippet itself is bounded.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'(?i)("?(?:api[_-]?key|authorization|auth|token|password|passwd|secret|access[_-]?key)"?\s*[:=]\s*"?)[^",}\s]+'), r"\1[redacted]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]+"), r"\1 [redacted]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*)://[^\s:/@]+:[^\s@]+@"), r"\1://[redacted]@"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "[redacted]"),
)


def scrub_secrets(text: str) -> str:
    """Remove credential-shaped substrings from text that may be logged or stored."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _bounded(text: str, limit: int) -> str:
    text = "".join(character for character in text if character.isprintable() or character.isspace())
    text = scrub_secrets(re.sub(r"\s+", " ", text).strip())
    return text[:limit] + "…" if len(text) > limit else text


def describe_payload(payload: Any, *, meta: str | None = None, limit: int = DIAGNOSTIC_SNIPPET_LIMIT) -> str:
    """Structure-first, secret-free description of an unexpected response.

    Reports the transport facts and the shape before any content, and includes a bounded,
    scrubbed snippet only because the shape alone rarely identifies which response it was.
    """
    parts = [meta] if meta else []
    parts.append(f"top-level {type(payload).__name__}")
    if isinstance(payload, dict):
        keys = list(payload)[:DIAGNOSTIC_MAX_KEYS]
        parts.append("keys=" + ", ".join(repr(str(key)) for key in keys) + ("…" if len(payload) > DIAGNOSTIC_MAX_KEYS else ""))
    elif isinstance(payload, list):
        parts.append(f"{len(payload)} items")
    try:
        rendered = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        rendered = str(payload)
    snippet = _bounded(rendered, limit)
    if snippet:
        parts.append(f"snippet={snippet}")
    return "; ".join(part for part in parts if part)


def response_meta(status: int, content_type: str | None, byte_length: int) -> str:
    kind = (content_type or "unknown").split(";")[0].strip() or "unknown"
    return f"HTTP {status}; content-type={kind}; {byte_length} bytes"


def _error_for_status(status: int, body: bytes, context: str) -> MarketDataError:
    snippet = _snippet(body)
    if status in (401, 403):
        return ProviderAuthenticationError(
            f"{context}: provider authentication or authorization failed (HTTP {status}: {snippet})."
        )
    if status == 400:
        # Context-dependent. Indian API answers a request without a key with HTTP 400 "Missing API
        # key" (observed 15 Sep 2026); any other 400 is a bad request and does not stop the sync.
        if _API_KEY_PROBLEM.search(snippet):
            return ProviderAuthenticationError(f"{context}: the provider reported an API key problem (HTTP 400: {snippet}).")
        return ProviderRequestError(f"{context}: the provider rejected the request (HTTP 400 bad request: {snippet}).")
    if status == 404:
        return ProviderNotFoundError(f"{context}: no data found (HTTP 404).")
    if status == 422:
        # Returned for invalid query parameters, e.g. an unsupported period (observed 15 Sep 2026).
        return ProviderRequestError(
            f"{context}: the provider rejected the request parameters (HTTP 422 validation error: {snippet})."
        )
    if status == 429:
        return ProviderRateLimitError(f"{context}: rate limit reached or monthly credits exhausted (HTTP 429).")
    if 500 <= status < 600:
        return ProviderUnavailableError(f"{context}: provider error (HTTP {status}).")
    if 300 <= status < 400:
        return ProviderRequestError(f"{context}: the provider answered with a redirect (HTTP {status}), which is not followed.")
    if 400 <= status < 500:
        return ProviderRequestError(f"{context}: the provider rejected the request (HTTP {status}: {snippet}).")
    return ProviderResponseError(f"{context}: the provider returned HTTP {status} instead of 200 ({snippet}).")


# --- Security master ------------------------------------------------------------------


def parse_security_master(payload: Any, *, min_rows: int = MIN_SECURITY_MASTER_ROWS) -> SecurityMasterSnapshot:
    """Validate the provider's security list.

    Missing codes may appear as empty strings or the text "null". A symbol or code shared
    by more than one security is ambiguous and is not mapped at all, rather than guessed.
    """
    if not isinstance(payload, list):
        raise ProviderResponseError("security master: expected a JSON list of securities.")
    if len(payload) < min_rows:
        raise ProviderResponseError(
            f"security master: only {len(payload)} rows received; refusing a suspiciously small list."
        )

    candidates: list[SecurityRecord] = []
    seen_ids: set[str] = set()
    dropped = 0
    for row in payload:
        record = _parse_security_row(row)
        if record is None or record.provider_security_id in seen_ids:
            dropped += 1
            continue
        seen_ids.add(record.provider_security_id)
        candidates.append(record)

    nse_counts = Counter(record.nse_symbol for record in candidates if record.nse_symbol)
    bse_counts = Counter(record.bse_code for record in candidates if record.bse_code)
    ambiguous_nse = {symbol for symbol, count in nse_counts.items() if count > 1}
    ambiguous_bse = {code for code, count in bse_counts.items() if count > 1}

    records: list[SecurityRecord] = []
    for record in candidates:
        nse = None if record.nse_symbol in ambiguous_nse else record.nse_symbol
        bse = None if record.bse_code in ambiguous_bse else record.bse_code
        if nse is None and bse is None:
            dropped += 1
            continue
        records.append(SecurityRecord(record.provider_security_id, record.name, nse, bse, record.isin))

    return SecurityMasterSnapshot(
        records=tuple(records),
        dropped_rows=dropped,
        ambiguous_nse_symbols=tuple(sorted(ambiguous_nse)),
        ambiguous_bse_codes=tuple(sorted(ambiguous_bse)),
    )


def _parse_security_row(row: Any) -> SecurityRecord | None:
    if not isinstance(row, dict):
        return None
    provider_id = _clean_text(row.get("id"))
    name = _clean_text(row.get("name"))
    if not provider_id or len(provider_id) > 64 or not name:
        return None

    nse = _clean_text(row.get("nse-code"))
    nse = nse.upper() if nse else None
    if nse is not None and (len(nse) > MAX_SYMBOL_LENGTH or not SYMBOL_PATTERN.fullmatch(nse)):
        nse = None

    bse = _clean_text(row.get("bse-code"))
    if bse is not None and not _BSE_CODE.fullmatch(bse):
        bse = None

    isin = _clean_text(row.get("isin"))
    isin = isin.upper() if isin and _ISIN.fullmatch(isin.upper()) else None

    if nse is None and bse is None:
        return None
    return SecurityRecord(provider_id, name[:255], nse, bse, isin)


def _clean_text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return None if text.casefold() in _MISSING_VALUES else text


# --- Historical prices -----------------------------------------------------------------


def parse_historical_prices(
    payload: Any,
    *,
    symbol: str,
    today: date,
    context: str | None = None,
    meta: str | None = None,
) -> DailyPriceSeries:
    """Validate a ``/historical_data?filter=price`` response and return dated NSE closes.

    Accepted only if there is exactly one "Price" dataset, it is labelled NSE, it is
    explicitly daily (``meta.is_weekly`` is false and dates are not spaced weekly), and
    every point has an ISO date and a positive plain decimal price. Points with a missing
    price are skipped; any other malformed point rejects the whole response.
    """
    context = context or f"historical prices for {symbol}"
    if not isinstance(payload, dict) or not isinstance(payload.get("datasets"), list):
        raise ProviderResponseError(
            f"{context}: expected an object with a 'datasets' list. Received: {describe_payload(payload, meta=meta)}"
        )
    datasets = payload["datasets"]

    price_sets = [dataset for dataset in datasets if _metric(dataset) == "price"]
    if not price_sets:
        raise ProviderResponseError(f"{context}: the response has no 'Price' dataset.")
    if len(price_sets) > 1:
        raise ProviderResponseError(f"{context}: the response has more than one 'Price' dataset.")
    price_set = price_sets[0]

    label = price_set.get("label")
    if not isinstance(label, str) or not _NSE_LABEL.search(label):
        raise ProviderResponseError(f"{context}: the price dataset is not labelled as NSE prices.")

    meta = price_set.get("meta")
    if not isinstance(meta, dict) or meta.get("is_weekly") is not False:
        raise ProviderGranularityError(f"{context}: the price dataset is not confirmed as daily.")

    values = price_set.get("values")
    if not isinstance(values, list):
        raise ProviderResponseError(f"{context}: the price dataset has no list of values.")

    volumes = _parse_volumes(datasets)
    bars: list[DailyPriceBar] = []
    seen_dates: set[date] = set()
    skipped = 0
    for index, point in enumerate(values):
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ProviderResponseError(f"{context}: price point {index} is malformed.")
        trade_date = _parse_trade_date(point[0], context, index)
        if trade_date > today:
            raise ProviderResponseError(f"{context}: price point {index} is dated in the future ({trade_date}).")
        if trade_date in seen_dates:
            raise ProviderResponseError(f"{context}: more than one price for {trade_date}.")
        seen_dates.add(trade_date)
        raw_price = point[1]
        if raw_price is None or (isinstance(raw_price, str) and raw_price.strip().casefold() in _MISSING_VALUES):
            skipped += 1
            continue
        close = _parse_close_price(raw_price, context, trade_date)
        bars.append(DailyPriceBar(trade_date=trade_date, close_price=close, volume=volumes.get(trade_date)))

    bars.sort(key=lambda bar: bar.trade_date)
    _reject_weekly_spacing(bars, context)
    return DailyPriceSeries(symbol=symbol, exchange=Exchange.NSE, bars=tuple(bars), skipped_points=skipped)


def _metric(dataset: Any) -> str:
    if not isinstance(dataset, dict) or not isinstance(dataset.get("metric"), str):
        return ""
    return dataset["metric"].strip().casefold()


def _parse_trade_date(raw: Any, context: str, index: int) -> date:
    if not isinstance(raw, str) or not _ISO_DATE.fullmatch(raw):
        raise ProviderResponseError(f"{context}: price point {index} does not have a YYYY-MM-DD date.")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ProviderResponseError(f"{context}: price point {index} has an invalid date.") from None


def _parse_close_price(raw: Any, context: str, trade_date: date) -> Decimal:
    if isinstance(raw, bool):
        raise ProviderResponseError(f"{context}: price on {trade_date} is not a number.")
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, int):
        value = Decimal(raw)
    elif isinstance(raw, float):
        value = Decimal(repr(raw))
    elif isinstance(raw, str):
        text = raw.strip()
        if not _PLAIN_DECIMAL.fullmatch(text):
            raise ProviderResponseError(f"{context}: price on {trade_date} is not a plain decimal number.")
        value = Decimal(text)
    else:
        raise ProviderResponseError(f"{context}: price on {trade_date} is not a number.")

    if not value.is_finite() or value <= 0:
        raise ProviderResponseError(f"{context}: price on {trade_date} must be a positive number.")
    if value > MAX_CLOSE_PRICE:
        raise ProviderResponseError(f"{context}: price on {trade_date} is out of range.")
    exponent = value.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -4:
        raise ProviderResponseError(f"{context}: price on {trade_date} has more than 4 decimal places.")
    return value.quantize(PRICE_QUANTUM)


def _parse_volumes(datasets: list[Any]) -> dict[date, int]:
    """Volume is optional: unusable volume values are ignored rather than rejected."""
    volume_sets = [dataset for dataset in datasets if _metric(dataset) == "volume"]
    if len(volume_sets) != 1 or not isinstance(volume_sets[0].get("values"), list):
        return {}
    volumes: dict[date, int] = {}
    for point in volume_sets[0]["values"]:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        if not isinstance(point[0], str) or not _ISO_DATE.fullmatch(point[0]):
            continue
        try:
            day = date.fromisoformat(point[0])
        except ValueError:
            continue
        raw = point[1]
        volume: int | None = None
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            volume = raw
        elif isinstance(raw, Decimal) and raw.is_finite() and raw == raw.to_integral_value():
            volume = int(raw)
        elif isinstance(raw, str) and _DIGITS.fullmatch(raw.strip()):
            volume = int(raw.strip())
        if volume is not None and 0 <= volume <= MAX_VOLUME:
            volumes[day] = volume
    return volumes


def _reject_weekly_spacing(bars: list[DailyPriceBar], context: str) -> None:
    if len(bars) < 3:
        return
    gaps = [(later.trade_date - earlier.trade_date).days for earlier, later in zip(bars, bars[1:], strict=False)]
    if min(gaps) >= WEEKLY_SPACING_DAYS:
        raise ProviderGranularityError(
            f"{context}: price dates are at least {WEEKLY_SPACING_DAYS} days apart; the series looks weekly, not daily."
        )
