# Market data and portfolio valuation

This system is a portfolio analytics and valuation tool. It does not provide personalized investment advice.

It values user-entered holdings at **dated NSE end-of-day closing prices**. It does not provide real-time prices, guaranteed accuracy or total-return performance, and it is not a regulated advisory service.

## 1. Provider

| | |
|---|---|
| Provider | [Indian API](https://indianapi.in/indian-stock-market) |
| Price endpoint | `GET https://stock.indianapi.in/historical_data?stock_name=<NSE symbol>&period=<1m\|6m\|1yr>&filter=price` |
| Security list | `https://analyst.indianapi.in/static/all_stocks.json` (public, not metered) |
| Authentication | `X-Api-Key` header, backend only |
| Code | `backend/app/market_data/providers/indian_api.py` |

## 2. Why Indian API is currently used

- It covers NSE and BSE listed equities and publishes a bulk security list with NSE symbols and BSE scrip codes.
- It offers a dated NSE price history through a documented endpoint.
- It has a free tier (500 requests/month, 1 request/second at the time of writing) that fits a small, NSE-first MVP.
- Its terms, as published, allow commercial and non-commercial use.

Known weaknesses are recorded in [Known limitations](#12-known-limitations). The provider is isolated behind an interface so it can be replaced.

## 3. NSE-first scope

- Holdings on **NSE** are matched by NSE symbol.
- Holdings on **BSE** are matched by BSE scrip code. When that security also has an NSE listing, it is valued at the **NSE** closing price of the same security, and the response says so (`price.exchange = "NSE"`).
- **BSE-only** securities have no supported end-of-day source and are shown as **UNPRICED** (`NO_NSE_LISTING`). No price is invented for them.
- A holding whose symbol is not in the security master is **UNPRICED** (`LISTING_NOT_FOUND`).

## 4. End-of-day (EOD) methodology

For each holding:

| Value | Formula |
|---|---|
| Invested value | quantity × average buy price |
| Market value | quantity × latest available NSE closing price |
| Unrealized P&L | market value − invested value |
| Unrealized return % | unrealized P&L ÷ invested value × 100 |
| Weight % | market value ÷ total market value of priced holdings × 100 |

For the portfolio:

| Value | Formula |
|---|---|
| Total invested | sum of invested value over **all** holdings |
| Priced invested | sum of invested value over holdings that have a price |
| Current value | sum of market value over priced holdings |
| Unrealized P&L | current value − priced invested |
| Return % | unrealized P&L ÷ priced invested × 100 (not an average of holding returns) |

Example: 10 RELIANCE shares bought at ₹2,400, valued at the ₹2,650 NSE close dated 14 Sep 2026 → invested ₹24,000, value ₹26,500, P&L ₹2,500, return 10.42%.

All arithmetic uses Python `Decimal` (34 significant digits); floats are rejected. Values are rounded only when returned by the API: money and percentages to **2 decimal places with ROUND_HALF_UP**; prices exactly as stored (up to 4 decimal places). Totals are computed from unrounded values, so a displayed total can differ by ₹0.01 from the sum of displayed rows. JSON carries these values as decimal strings.

## 5. Price semantics

- The only valuation price is the **latest dated NSE end-of-day close stored in `daily_prices`**.
- Never used for valuation: `/stock` `currentPrice`, live or delayed price endpoints, the live `close` field (which is the previous close), moving averages, technical indicators, scraped or unofficial sources.
- Every stored price has: listing, exchange (`NSE`), `trade_date` (a `DATE`, the exchange trading day), `close_price` (`NUMERIC(18,4)`), optional volume, `source`, `fetched_at` and the sync run that stored it.
- A provider response is accepted only if it contains exactly one "Price" dataset labelled NSE, `meta.is_weekly` is explicitly `false`, the dates are not spaced weekly, and every point has a `YYYY-MM-DD` date that is not in the future and a positive plain-decimal price with at most 4 decimal places. Points with a missing price are skipped (never filled in). Any other malformed point rejects the whole response, and nothing from it is stored.
- The portfolio page is never allowed to call the provider. Valuation reads the database only.

## 6. Freshness methodology

Implemented in `backend/app/market_data/calendar.py`:

1. NSE sessions are Monday–Friday, excluding holidays configured in `NSE_TRADING_HOLIDAYS`.
2. A session's EOD price is expected to be available from **18:00 IST** that day (market close is 15:30 IST).
3. The **latest expected session** is today if today is a session and it is 18:00 IST or later; otherwise the most recent earlier session.
4. A holding is **VALUED** if its price's trade date is on or after the latest expected session, **STALE** if older, and **UNPRICED** if there is no price.

Examples: Monday 10:00 IST → Friday's close is current. Sunday → Friday's close is current. Tuesday 19:00 IST with only Monday's close → STALE.

Without a configured holiday list, prices on the day after an exchange holiday can be marked STALE even though no newer price exists. The system errs towards warning rather than claiming freshness.

## 7. Corporate-action limitation

Valuation uses the **latest reported closing price**. It is **not** adjusted for splits, bonus issues, rights issues or mergers, and it is **not a total return**: dividends, taxes and charges are excluded. Realized P&L is not calculated.

After a split or bonus issue, a user's pre-event quantity and average buy price make P&L misleading. As a safeguard, a day-over-day close move of 35% or more between the two latest stored prices adds a `LARGE_PRICE_MOVE` warning to the holding, and price syncs record such moves in the run details. The system never silently claims adjusted performance.

## 8. Free-tier request protection

- Prices are fetched only for **held NSE securities** that do not already have the latest expected session.
- A security that was already requested after that session's 18:00 IST availability is not requested again that session.
- Initial history uses `MARKET_DATA_BACKFILL_PERIOD` (default `1yr`). If that series is not confirmed daily, the sync falls back to `1m` rather than storing weekly data. Existing history is topped up with `1m` requests.
- At least 1.1 seconds between provider requests; request timeout of 20 seconds; no redirects.
- HTTP 400/401/403 (missing or invalid key): no retry; the sync stops.
- HTTP 429: no retry; the sync stops with status `rate_limited`.
- HTTP 5xx, timeouts and network errors: at most 3 attempts with 2 s and 4 s backoff; then the sync stops.
- **Monthly budget:** `MARKET_DATA_MONTHLY_REQUEST_BUDGET` (default **450**, maximum 500) counts every metered request, including retries, per IST calendar month from `market_data_sync_runs`. The request that would exceed it is never sent; the sync stops with status `budget_exhausted`.
- A PostgreSQL advisory lock prevents two syncs from running at the same time.
- Every run is recorded in `market_data_sync_runs` with requests made, records attempted/inserted/updated, failures, an error summary and details.

## 9. Environment variable

Set in `backend/.env` (never in the frontend, never committed):

```
INDIAN_API_KEY=
```

The key is read into a secret value, sent only in the `X-Api-Key` header to `stock.indianapi.in`, redacted from error messages and never logged or returned by any endpoint. If it is absent, the application still starts, valuation still works from stored prices, and `GET /api/v1/market-data/status` reports `"configured": false`.

Optional settings: `MARKET_DATA_MONTHLY_REQUEST_BUDGET`, `MARKET_DATA_BACKFILL_PERIOD` (`1m`, `6m`, `1yr`), `MARKET_DATA_MIN_REQUEST_INTERVAL_SECONDS` (≥ 1.1), `MARKET_DATA_REQUEST_TIMEOUT_SECONDS`, `NSE_TRADING_HOLIDAYS` (JSON list of dates). Provider URLs must use `https://`.

## 10. How to run the sync

From `backend/`, with the database migrated (`uv run alembic upgrade head`):

```bash
uv run python -m app.market_data.cli sync-listings
```

Loads the security master (one unmetered request). Run it first and occasionally afterwards.

```bash
uv run python -m app.market_data.cli sync-prices --dry-run
```

Shows which securities would be requested and with which period, without calling the provider.

```bash
uv run python -m app.market_data.cli sync-prices
```

Fetches NSE EOD prices for held securities. Options: `--portfolio-id <uuid>` limits it to one portfolio; `--force` requests securities even if they look up to date (uses budget).

```bash
uv run python -m app.market_data.cli status
```

Prints the same information as `GET /api/v1/market-data/status`.

Exit codes: `0` success, `1` failed or partial, `2` configuration error, `3` rate limited or budget exhausted, `4` another sync is running.

## 11. How to add another provider

1. Create `backend/app/market_data/providers/<name>.py` with a class implementing `MarketDataProvider` (`providers/base.py`): `name`, `display_name`, `set_request_guard`, `get_security_master()`, `get_daily_prices(nse_symbol, period)` and `close()`. Return only the records in `app/market_data/records.py`, and validate responses before returning them.
2. Call the request guard before every metered request.
3. Register it in `build_provider` and `PROVIDER_DISPLAY_NAMES` (`providers/__init__.py`) and add its key to `market_data_provider` in `app/core/config.py`.
4. Add fixture-based parsing and HTTP tests like `tests/test_indian_api_parsing.py` and `tests/test_indian_api_client.py`.

Valuation, the database schema, the API and the frontend do not change: they only see provider-neutral records and stored prices.

## 12. Known limitations

- **No real-provider verification yet.** Response handling follows the provider's published documentation and is tested against recorded-format fixtures. The first real sync with an API key must confirm the response shape, that recent closes are unadjusted, and that `1yr` history is daily.
- **Data provenance and exchange licensing** are not stated by the provider. Suitable for a non-commercial demonstration; confirm in writing before any commercial use.
- **No SLA.** The provider may change or withdraw endpoints without notice.
- **BSE-only securities cannot be valued.** No BSE end-of-day source is used.
- **ISIN is not populated.** The bulk security list does not include it.
- **Holidays** must be configured manually for exact freshness around exchange holidays.
- **Not adjusted for corporate actions; not total return;** dividends, taxes and charges are excluded.
- **End of day only.** Not real-time or intraday.
- **Free tier:** about 20 held NSE securities can be kept current each month within the 450-request budget.
