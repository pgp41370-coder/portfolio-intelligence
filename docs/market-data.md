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

**Displayed weights are allocated after rounding.** Rounding each weight separately can make them sum to 100.01% or 99.99%. The displayed `weight_pct` values therefore use a largest-remainder allocation: every exact weight is rounded down to 0.01%, and the missing hundredths go one each to the weights with the largest discarded remainders (earlier position first on ties). Displayed weights sum to exactly 100.00%, and each differs from its exact value by less than 0.01%. Market value, P&L and returns are not affected.

## 5. Price semantics

- The only valuation price is the **latest dated NSE end-of-day close stored in `daily_prices`**.
- Never used for valuation: `/stock` `currentPrice`, live or delayed price endpoints, the live `close` field (which is the previous close), moving averages, technical indicators, scraped or unofficial sources.
- Every stored price has: listing, exchange (`NSE`), `trade_date` (a `DATE`, the exchange trading day), `close_price` (`NUMERIC(18,4)`), optional volume, `source`, `fetched_at` and the sync run that stored it.
- A provider response is accepted only if it contains exactly one "Price" dataset labelled NSE, `meta.is_weekly` is explicitly `false`, the dates are not spaced weekly, and every point has a `YYYY-MM-DD` date that is not in the future and a positive plain-decimal price with at most 4 decimal places. Points with a missing price are skipped (never filled in). Any other malformed point rejects the whole response, and nothing from it is stored.
- The portfolio page is never allowed to call the provider. Valuation reads the database only.

## 6. Freshness methodology

Implemented in `backend/app/market_data/calendar.py`; calendar data in `backend/app/market_data/nse_calendar.py`:

1. A day is an NSE session if it is a configured **special trading session**, or a Monday–Friday that is not a configured **trading holiday**.
2. A session's EOD price is expected to be available from **18:00 IST** that day (market close is 15:30 IST).
3. The **latest expected session** is today if today is a session and it is 18:00 IST or later; otherwise the most recent earlier session. It is the latest session whose close is treated as complete.
4. A holding is **VALUED** if its price's trade date is on or after the latest expected session, **STALE** if older, and **UNPRICED** if there is no price.

Examples: Monday 10:00 IST → Friday's close is current. Sunday → Friday's close is current. Tuesday 19:00 IST with only Monday's close → STALE. Monday 14 Sep 2026 (Ganesh Chaturthi, no session) at 19:00 IST → Friday 11 Sep's close is still VALUED; from Tuesday 15 Sep 18:00 IST it is STALE until Tuesday's close is stored.

### Trading calendar

| Setting | Default | Meaning |
|---|---|---|
| `NSE_TRADING_HOLIDAYS` | The 16 weekday trading holidays of 2026 below | Weekdays with no session |
| `NSE_SPECIAL_TRADING_SESSIONS` | `2026-02-01` | Sessions on days that are normally closed |

Sources, checked 15 Sep 2026: NSE [Holidays for the calendar year 2026 – Equities](https://www.nseindia.com/resources/exchange-communication-holidays) and NSE circular [CMTR72349](https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf).

| Date | Day | Trading holiday |
|---|---|---|
| 15 Jan 2026 | Thursday | Municipal Corporation Election – Maharashtra |
| 26 Jan 2026 | Monday | Republic Day |
| 3 Mar 2026 | Tuesday | Holi |
| 26 Mar 2026 | Thursday | Shri Ram Navami |
| 31 Mar 2026 | Tuesday | Shri Mahavir Jayanti |
| 3 Apr 2026 | Friday | Good Friday |
| 14 Apr 2026 | Tuesday | Dr. Baba Saheb Ambedkar Jayanti |
| 1 May 2026 | Friday | Maharashtra Day |
| 28 May 2026 | Thursday | Bakri Id |
| 26 Jun 2026 | Friday | Muharram |
| 14 Sep 2026 | Monday | Ganesh Chaturthi |
| 2 Oct 2026 | Friday | Mahatma Gandhi Jayanti |
| 20 Oct 2026 | Tuesday | Dussehra |
| 10 Nov 2026 | Tuesday | Diwali – Balipratipada |
| 24 Nov 2026 | Tuesday | Prakash Gurpurb Sri Guru Nanak Dev |
| 25 Dec 2026 | Friday | Christmas |

Special trading session: **Sunday 1 Feb 2026**, Union Budget live trading session at normal market hours.

- Holidays on a Saturday or Sunday (15 Feb, 21 Mar, 15 Aug and 8 Nov 2026) need no entry.
- **Muhurat Trading on Sunday 8 Nov 2026 is not configured.** NSE had not notified its timings, and a short evening session does not fit the 18:00 IST availability rule. Its bar is ignored and the next regular session is used.
- **Updating the calendar:** add the next year's dates to `nse_calendar.py` when NSE publishes them, or set the variables as JSON lists of ISO dates. Setting a variable replaces that default list. A date cannot be both a holiday and a special session. If the calendar is out of date, the day after an unlisted holiday can show STALE prices and a bar from an unlisted special session is ignored: the system errs towards warning rather than claiming freshness.

### Only completed session closes are stored

Before storing, the price sync keeps a provider bar only if its trade date is a session in the configured calendar **and** is not after the latest expected session at the start of the sync. As a result:

- a bar for **today before 18:00 IST** is ignored, even when the provider already shows one (observed at 16:39 IST on 15 Sep 2026); the security is requested again after 18:00 IST;
- **future-dated** bars, and bars dated on a **holiday or an unlisted weekend day**, are ignored;
- an ignored bar is never stored and never overwrites an earlier close. Ignored bars are listed in the run details under `ignored_bars` with the reason `session_not_complete` or `not_a_session_day`.

## 7. Corporate-action limitation

Valuation uses the **latest reported closing price**. It is **not** adjusted for splits, bonus issues, rights issues or mergers, and it is **not a total return**: dividends, taxes and charges are excluded. Realized P&L is not calculated.

After a split or bonus issue, a user's pre-event quantity and average buy price make P&L misleading. As a safeguard, a day-over-day close move of 35% or more between the two latest stored prices adds a `LARGE_PRICE_MOVE` warning to the holding, and price syncs record such moves in the run details. The system never silently claims adjusted performance.

## 8. Free-tier request protection

- Prices are fetched only for **held NSE securities** that do not already have the latest expected session.
- A security that was already requested after that session's 18:00 IST availability is not requested again that session.
- Initial history uses `MARKET_DATA_BACKFILL_PERIOD` (default `1yr`). If that series is not confirmed daily, the sync falls back to `1m` rather than storing weekly data. Existing history is topped up with `1m` requests.
- At least 1.1 seconds between provider requests; request timeout of 20 seconds; no redirects.
- **HTTP 401/403** (authentication or authorization failure), or an **HTTP 400** whose message reports an API key problem: no retry; the sync stops. HTTP 400 is context-dependent: observed on 15 Sep 2026, a request without a key returns `400 Missing API key` and an unknown key returns `401 Invalid API key`; the key is checked before request parameters.
- **HTTP 422** (provider validation error for invalid parameters, observed for an unsupported period), any other **HTTP 400** (bad request), **404** (no data) and other 4xx: no retry; that security is recorded as failed and the sync continues.
- **Three consecutive rejected or invalid responses** (HTTP 404 excluded) stop the sync with status `failed`, so a provider-wide fault, such as an error body returned with HTTP 200, cannot spend the monthly budget.
- HTTP 429: no retry; the sync stops with status `rate_limited`.
- HTTP 5xx, timeouts and network errors: at most 3 attempts with 2 s and 4 s backoff; then the sync stops.
- **Monthly budget:** `MARKET_DATA_MONTHLY_REQUEST_BUDGET` (default **450**, maximum 500) counts every metered request, including retries, per IST calendar month from `market_data_sync_runs`. The request that would exceed it is never sent; the sync stops with status `budget_exhausted`.
- **The budget ledger covers sync requests only.** Ad-hoc provider probes made outside the sync (for example the single malformed-request check during the 15 Sep 2026 validation) are not recorded in `market_data_sync_runs` and are not counted. The 50-request margin between the 450 budget and the provider's 500-request tier absorbs such occasional probes; keep them rare.
- A PostgreSQL advisory lock prevents two syncs from running at the same time.
- Every run is recorded in `market_data_sync_runs` with requests made, records attempted/inserted/updated, failures, an error summary and details.

## 9. Environment variable

Set in `backend/.env` (never in the frontend, never committed):

```
INDIAN_API_KEY=
```

The key is read into a secret value, sent only in the `X-Api-Key` header to `stock.indianapi.in`, redacted from error messages and never logged or returned by any endpoint. If it is absent, the application still starts, valuation still works from stored prices, and `GET /api/v1/market-data/status` reports `"configured": false`.

Optional settings: `MARKET_DATA_MONTHLY_REQUEST_BUDGET`, `MARKET_DATA_BACKFILL_PERIOD` (`1m`, `6m`, `1yr`), `MARKET_DATA_MIN_REQUEST_INTERVAL_SECONDS` (≥ 1.1), `MARKET_DATA_REQUEST_TIMEOUT_SECONDS`, `NSE_TRADING_HOLIDAYS` and `NSE_SPECIAL_TRADING_SESSIONS` (JSON lists of ISO dates; default to the 2026 NSE calendar, see [Trading calendar](#trading-calendar)). Provider URLs must use `https://`.

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

- **Real-provider validation was local and small.** On 15 Sep 2026, `1yr` requests for RELIANCE, TCS, INFY, HDFCBANK and M&M parsed as daily NSE prices (248 points each, `is_weekly: false`), and every latest close matched NSE's official quote and Yahoo Finance to the paisa. The weekly-to-`1m` fallback is verified only with recorded fixtures. Provider volumes were about 8% higher than NSE's figure; volume is not used for valuation.
- **Adjustment methodology could not be independently established from the provider response/documentation.** The provider's documentation does not state whether `/historical_data` prices are adjusted for splits, bonuses or dividends, nor when longer periods switch to weekly data. The application therefore makes no claim either way and flags large day-over-day moves.
- **Sync database connection** must support session-level advisory locks: use a direct or session-mode connection for the sync, not a transaction-mode pooler.
- A security already requested after a session's 18:00 IST availability is not requested again that session, even if the provider published late; it shows as STALE until the next run on a later session or a `--force` run.
- **Data provenance and exchange licensing** are not stated by the provider. Suitable for a non-commercial demonstration; confirm in writing before any commercial use.
- **No SLA.** The provider may change or withdraw endpoints without notice.
- **BSE-only securities cannot be valued.** No BSE end-of-day source is used.
- **ISIN is not populated.** The bulk security list does not include it.
- **The trading calendar must be updated each year.** The 2026 NSE holidays and special session are built in; later years need NSE's published list. Evening-only sessions such as Muhurat Trading are not supported.
- **Not adjusted for corporate actions; not total return;** dividends, taxes and charges are excluded.
- **End of day only.** Not real-time or intraday.
- **Free tier:** about 20 held NSE securities can be kept current each month within the 450-request budget.
