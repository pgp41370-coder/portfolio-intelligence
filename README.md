# Portfolio Intelligence

**Know what your Indian equity portfolio is actually worth — and exactly where that number came from.**

Portfolio Intelligence turns a list of holdings into a valued portfolio: every position priced at a **dated NSE end-of-day close**, with invested capital, current value, unrealized P&L, return and weights — and the price date, source and exchange shown on every figure.

| | |
|---|---|
| **Live application** | https://portfolio-intelligence-bice.vercel.app |
| **Live API** | https://portfolio-intelligence-api.vercel.app |
| **Demo portfolio** | [Open the demo](https://portfolio-intelligence-bice.vercel.app/analyze) — five NSE large caps, valued at the latest completed session |
| **Status** | Deployed demo on production infrastructure. Public deployment is **read-only** |

```
portfolio data  →  market data  →  valuation  →  portfolio intelligence
 holdings you      NSE EOD closes   priced at a     allocation, risk and
 enter or import   synced daily     dated close     performance (planned)
```

The first three stages are built and live. The fourth is the roadmap.

This is a portfolio analytics and valuation tool. It is not a broker, adviser or asset manager, and it does not provide personalized investment advice.

---

## Contents

1. [Why it exists](#why-it-exists)
2. [What it does today](#what-it-does-today)
3. [Architecture](#architecture)
4. [Market data](#market-data)
5. [Market-data sync](#market-data-sync)
6. [Portfolio intelligence](#portfolio-intelligence)
7. [Performance and analytics](#performance-and-analytics)
8. [Production hardening](#production-hardening)
9. [API endpoints](#api-endpoints)
10. [Database model](#database-model)
11. [Validation rules and CSV format](#validation-rules-and-csv-format)
12. [Local development](#local-development)
13. [Environment variables](#environment-variables)
14. [Tests and checks](#tests-and-checks)
15. [Limitations and non-goals](#limitations-and-non-goals)
16. [Project status](#project-status)

---

## Why it exists

Retail investors in Indian equities hold stocks across several brokers and apps. Broker dashboards show a price and a profit figure, but rarely say *which* price, *from when*, or *from where* — and they quietly mix positions they can price with ones they cannot.

Portfolio Intelligence takes the opposite approach, because a valuation you cannot audit is not worth much:

- **Every number is sourced.** Each price carries its trade date, exchange and provider, and the basis is stated: an end-of-day close, never a live quote.
- **Staleness is visible.** A holding is VALUED, STALE or UNPRICED against the latest *completed* NSE session, judged by an exchange calendar rather than a 24-hour rule.
- **Missing data is never disguised.** An unpriced holding is reported as unpriced — excluded from current value, P&L, return and weights, still counted in invested capital, and never shown as ₹0.

That discipline is the foundation. Allocation, concentration and risk analytics only mean something once the valuation underneath them is trustworthy.

## What it does today

### ✅ Implemented and live

| Capability | Detail |
|---|---|
| Portfolio capture | Manual entry (add, remove, review, save) and CSV import with per-row validation; preview a file without saving anything |
| Storage | Portfolios and holdings in PostgreSQL through a service layer; schema managed by Alembic |
| Invested capital | Σ (quantity × average buy price), exact `Decimal` arithmetic, from user input only |
| Market data | Security master and dated NSE end-of-day closes synced into the database by a budget-protected job |
| Valuation | Per holding: EOD price with trade date, market value, unrealized P&L, return, weight. Portfolio: invested, current value, P&L, return |
| Price provenance | Trade date, source, exchange and basis ("end-of-day close, not a live price") shown on every price |
| Freshness | VALUED / STALE / UNPRICED against the latest completed NSE session, using a configured exchange calendar |
| Honest gaps | Unpriced holdings excluded from value, P&L, return and weights; still in invested capital; never ₹0 |
| Weights | Displayed weights allocated after rounding so they sum to exactly 100.00% |
| Performance history | Value series, cumulative return, annualised volatility and maximum drawdown over a chosen window, with explicit coverage reporting |
| Transaction ledger | Dated buys and sells per portfolio, entered in the interface or imported from CSV, validated against overselling and future dates, reconciled against the holdings on record |
| Transaction CSV import | Upload, validate, preview, confirm — with row-level errors and an all-or-nothing import |
| Realised and unrealised P&L | FIFO cost basis, per security and in total, with contributions and withdrawals shown apart from performance |
| Money-weighted return | XIRR alongside the time-weighted return, as a period figure and an annualised one, withheld rather than guessed when the cash flows admit several answers |
| Corporate-action disclosure | The whole window is scanned for price moves that may be splits, bonus issues or consolidations; the figures they affect are named, and nothing is adjusted |
| Portfolio timeline | Every recorded transaction with the position change, portfolio value and return it produced |
| Return attribution | Per-security contributions that sum to the portfolio's daily return, and the latest session's movers |
| Portfolio intelligence | A deterministic explanation of the measured numbers: what drove the return, how it compares with the benchmark proxy, how much of the value change was cash flow, the risk context, and what qualifies the answer |
| Time-weighted return | Daily flow-adjusted returns chained across the window, so money added or withdrawn is not counted as performance |
| Benchmark comparison | NIFTY 50 via a synced index ETF proxy, rebased for comparison and labelled a proxy everywhere it appears |
| Risk measures | Downside volatility, beta, tracking error and information ratio; Sharpe only when a risk-free rate is configured |
| Allocation | Position weights, top-1/3/5 concentration and a Herfindahl-Hirschman index |
| Operations | A status endpoint reporting provider configuration, request usage, last syncs and held-security freshness — without credentials |

### 🔜 Next

Sector allocation once a classification source exists, and editing a transaction in place.

### 🔭 Deliberately not built

Natural-language generation over these facts. The structured explanation is the source of truth; a
language layer on top of it would be a rendering choice, never the calculation engine.

### 🔭 Future

BSE-sourced prices and ISIN-based matching, corporate-action data, dividends and total return, tax-lot reporting, and user accounts.

Planned capabilities are **not** present in the running application. Anything not in the ✅ table is not implemented — see [Limitations and non-goals](#limitations-and-non-goals).

## Architecture

```mermaid
flowchart LR
    B[Browser] --> F["Next.js on Vercel<br/>portfolio-intelligence-bice"]
    F -- "/api/v1/* rewrite" --> A["FastAPI on Vercel, sin1<br/>portfolio-intelligence-api"]
    A -- "transaction pooler" --> D[("PostgreSQL<br/>Supabase, ap-southeast-1")]
    G["GitHub Actions<br/>weekdays 21:30 IST"] -- "session pooler" --> D
    G --> P[Indian API]
```

The application is the user-facing Next.js site; the API is a separate FastAPI service. The site forwards `/api/v1/*` server-side, so the browser only ever talks to its own origin. **No web request ever calls the market-data provider** — prices are synced into the database first, and valuation reads stored data only.

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 (psycopg 3) |
| Database | PostgreSQL (Supabase in production, PostgreSQL 16 locally), Alembic migrations |
| Market data | Indian API, httpx, `Decimal`, `zoneinfo` (Asia/Kolkata) |
| Scheduling | GitHub Actions (cron) |
| Hosting | Vercel (two projects: application and API) |
| Tooling | uv (Python), npm (Node.js 24), Pytest, Node test runner, ESLint |

```
portfolio-intelligence/
  frontend/   Next.js application
  backend/    FastAPI application, market-data sync, Alembic migrations
  docs/       Architecture, market-data methodology, deployment runbook
  .github/    Scheduled market-data sync workflow
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/deployment.md](docs/deployment.md).

## Market data

Full methodology, trading calendar and limitations: [docs/market-data.md](docs/market-data.md).

- **Provider:** Indian API is the V1 provider, reached only through a `MarketDataProvider` interface returning provider-neutral records — replacing it means adding one adapter. Valuation, the schema, the API and the frontend never see a vendor's response format.
- **NSE-first, end of day.** The only valuation price is the latest stored **dated NSE closing price**. Live, delayed and "current price" fields are never used. This is **not** real-time data.
- **Synced, not fetched per request.** A valuation request performs database reads only.
- **BSE:** a BSE holding of a security that also trades on NSE is valued at that security's **NSE** close and labelled as such. **BSE-only securities cannot be priced** and are reported as unpriced. No BSE price feed is implemented.
- **Adjustment:** whether provider history is adjusted for splits, bonuses or dividends **could not be established** from the provider's response or documentation, so the application claims neither. Prices are used as reported, a close-to-close move of 35% or more is flagged as a possible corporate action, and returns exclude dividends.
- **Freshness:** a session's close is expected from 18:00 IST that day; before then the previous session applies. Sessions come from a configured NSE calendar — weekdays, minus trading holidays, plus exchange-declared special sessions. Only completed session closes are stored: a bar for the current session before the cut-off, a future date or a non-session day is ignored.
- **Validation:** a provider response must contain exactly one NSE-labelled daily price series with valid dates and positive plain-decimal prices, or nothing from it is stored.

| Value | Definition |
|---|---|
| Market value | quantity × NSE end-of-day close |
| Unrealized P&L | market value − quantity × average buy price |
| Return | unrealized P&L ÷ invested value (portfolio: total P&L ÷ invested value of priced holdings) |
| Weight | market value ÷ current value of priced holdings |

Money and percentages are returned as decimal strings rounded to 2 places (ROUND_HALF_UP); unavailable values are `null`.

## Market-data sync

The sync is a CLI, run by a scheduled GitHub Actions workflow in production ([`.github/workflows/market-data-sync.yml`](.github/workflows/market-data-sync.yml)) or locally by an operator. These are operator commands, not public API endpoints.

| Concern | Behaviour |
|---|---|
| Security master | Loads the provider's security list into `listings` (unmetered); refreshed weekly on Mondays or on request |
| Daily prices | Requests NSE end-of-day history only for **held** NSE securities lacking the latest expected session |
| Schedule | Weekdays at 21:30 IST (`0 16 * * 1-5` UTC), after end-of-day availability |
| Budget | A monthly metered-request budget (default 450) counted per IST month from recorded runs; the request that would exceed it is never sent |
| Pacing and retries | At least 1.1 s between requests, bounded retries on timeouts and 5xx, immediate stop on rate limiting or authentication failure, and a stop after repeated rejected responses |
| Concurrency | A PostgreSQL advisory lock prevents overlapping syncs, so the sync needs a session-mode connection |
| Auditability | Every run is recorded in `market_data_sync_runs` with counters, status and details |

```bash
uv run python -m app.market_data.cli sync-listings
```

```bash
uv run python -m app.market_data.cli sync-prices --dry-run
```

```bash
uv run python -m app.market_data.cli sync-prices
```

```bash
uv run python -m app.market_data.cli status
```

## Portfolio intelligence

A single read-only endpoint, `GET /api/v1/portfolios/{id}/intelligence`, composes the performance,
attribution, profit-and-loss and allocation calculations into structured facts and template
sentences.

- **It explains; it does not calculate.** Every figure comes from a calculation documented
  elsewhere in this README, and every sentence is a template filled with one of those figures.
- **It states measurements, never judgements.** "HDFCBANK contributed −13.04 percentage points" is
  a fact the data supports. Whether a holding is good, bad, risky or worth buying is not, so the
  layer never says it. A test asserts that no response contains advice or forecast vocabulary.
- **It never explains past the data.** A contribution says which security moved the portfolio, not
  why that security moved — the application knows the first and not the second.
- **It leads with what qualifies the answer.** Stale prices, missing sessions, an unsynced
  benchmark and a ledger that disagrees with the holdings are reported before the figures they
  affect, and the response is marked `limited` rather than `available`.
- **There is no model here.** No LLM, no prediction, no scoring, no external service. The layer
  reads stored end-of-day closes through the existing services and nothing else.

Contributions are checkable rather than merely plausible: they sum to the portfolio's measured
return by construction, and the response carries `contributions_reconcile` to say so. Because each
day is weighed against the portfolio's size that day, a security's contribution can differ in sign
from its own price return — the response explains this rather than letting it look like an error.

**One valuation per request.** Performance, attribution, profit and loss, and the explanation all
read a single `PerformanceContext`: the portfolio, its ledger, and one pass over it. The same pass
serves both bases, so a card and the explanation of that card can never describe different
sessions. Adding `?trace=true` returns the provenance of each headline figure — which calculation
produced it, from which inputs, by which formula — for auditing; the ordinary response is
unchanged.

Two kinds of test protect the arithmetic from silent drift. **Golden tests** pin every published
figure for a fixed portfolio whose expected values were derived independently of the application.
**Invariant tests** assert the identities the engine must satisfy for any portfolio: contributions
sum to the measured return, value change equals net flow plus the performance-driven part, weights
sum to 100%, relative return is the difference of the two returns, and stale data is never
presented as current. Identities that do *not* hold — the arithmetic sum of contributions is not
the compounded return — are tested too, to confirm the difference is reported rather than hidden.

## Performance and analytics

Formulas, risk definitions and the benchmark's proxy status: [docs/performance.md](docs/performance.md).
The ledger model and the time-weighted return methodology: [docs/transactions.md](docs/transactions.md).

- **Two bases, always labelled.** With a transaction ledger the series is what the portfolio was actually worth and the return is **time-weighted** (`TRANSACTIONS`). Without one it values today's holdings at past closes — a reconstruction, labelled *Reconstructed* (`CURRENT_HOLDINGS`).
- **Time-weighted return.** Each day's external cash flow is removed before the return is measured: `R_t = (V_t − CF_t) ÷ V_(t−1) − 1`, chained across the window. Adding money is not performance. Volatility and drawdown read a growth index built from those returns, so a withdrawal is never mistaken for a loss.
- **Money-weighted return, beside it.** XIRR on the investor's own cash flows — actual/365, `Decimal`, bisection — reported as both a period figure and an annualised rate. TWR measures the portfolio, MWR measures the money; the application reports both and ranks neither. Where several rates fit the cash flows, no figure is published.
- **Ledger and holdings are reconciled, not merged.** If the two disagree the response names each difference; neither is overwritten.
- **Gaps are reported, never filled.** A session counts only when every security held that day has a close. Nothing is interpolated, substituted with ₹0 or carried forward, and returns are never linked across a gap. Staleness is reported separately from missing data.
- **The benchmark is a proxy and says so.** The provider exposes no index endpoint, so NIFTY 50 is tracked through the SETFNIF50 ETF, labelled `ETF_PROXY` with its limitations stated. Nothing is estimated: an unsynced benchmark returns `no_data`.
- **Measures state their own requirements.** Beta, tracking error and information ratio need 20 paired sessions; Sharpe needs `RISK_FREE_RATE_PCT`, unset by default. Each is withheld with its reason rather than estimated.
- **Sector allocation is unavailable** — the security master has no sector data, and guessing one would be fabrication.
- **Suspected corporate actions are flagged, not corrected.** A split arrives as a large fall and would silently invalidate returns, contributions and cost basis; the window is scanned for moves over 35%, or over 20% when they land on a ratio a corporate action would produce. Adjusting would need a corporate-action feed this application does not have.
- **Profit uses a FIFO cost basis**, the basis Indian income-tax law applies to listed equity shares. Buy fees join the cost of the lot they bought and are allocated pro rata on a partial sale; sale fees reduce proceeds. Without a ledger, realised profit is reported unavailable rather than as zero.
- **The money-weighted return is withheld, not guessed, when it is ambiguous.** A cash-flow series with several sign changes can satisfy the XIRR equation at several rates; the response says so instead of picking one. Annualisation is withheld below a 90-day window.
- **Contributions and withdrawals are shown apart from performance**, so money paid in never reads as a gain.
- **The intelligence layer gives no advice and makes no forecast.** It reports measurements and the limits on them; it does not rate, score or recommend securities.

## Production hardening

| Protection | Implementation |
|---|---|
| Read-only public API | With `APP_ENV=production`, middleware rejects every non-GET/HEAD/OPTIONS request with `403 read_only_demo` **before the body is read** — covering create, holding changes, CSV preview and import |
| API documentation | `/docs`, `/redoc` and `/openapi.json` are disabled in production |
| CORS | Restricted to the production application origin; wildcard, `http://` and localhost origins are rejected in production |
| Row-level security | Enabled on every table (migration `20260915_0003`), so a hosted database's REST data API can neither read nor write them; the application connects as the table owner |
| Provider key | The deployed API holds **no** provider key — it never calls the provider. The key exists only as a GitHub Actions secret used by the sync |
| Secrets | Configuration comes from environment variables; `.env` files are git-ignored and excluded from deployment uploads; credentials never appear in API responses, and database errors are reported by type only |
| Uploads | CSV uploads are capped at 1 MB and rejected before buffering |
| Rate limiting | Vercel Firewall rules on both projects — application `/api/v1/` at 60 requests/60 s per IP, API at 120 requests/60 s per IP |

**The firewall rules currently LOG; they do not BLOCK.** Both use a log-only action so traffic patterns can be observed before enforcement is considered.

There is no authentication: write access is disabled in production rather than protected by accounts.

## API endpoints

All application endpoints are under `/api/v1`. In production only the reads are available; write endpoints return `403 read_only_demo`.

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| `GET` | `/health` | Liveness check | `200` | |
| `GET` | `/health/db` | Database connectivity check | `200` | `503` |
| `GET` | `/api/v1` | API name, version and status | `200` | |
| `GET` | `/api/v1/portfolios` | List portfolios with holding count and invested capital | `200` | `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}` | One portfolio with its holdings | `200` | `404`, `422` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/valuation` | Value a portfolio at stored NSE end-of-day prices (never calls the provider) | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/performance` | Historical value series, returns, risk and benchmark comparison from stored closes (never calls the provider) | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/allocation` | Position weights and concentration at the latest stored closes | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/transactions` | The portfolio's transaction ledger, oldest first | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/pnl` | Realised and unrealised profit on a FIFO cost basis, with contributions and withdrawals | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/timeline` | Recorded transactions with the position change and value each produced | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/attribution` | Per-security contributions to the window's return | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/intelligence` | Deterministic explanation of the measured numbers, with the limitations that qualify them | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/benchmarks` | Benchmarks that can be requested for comparison, with their proxy status | `200` | |
| `GET` | `/api/v1/market-data/status` | Provider, configuration flag, request usage, last syncs, latest trade date, held-security freshness. Never returns credentials | `200` | `503` |
| `POST` | `/api/v1/portfolios` | Create a portfolio, optionally with holdings | `201` | `403` in production, `422`, `503` |
| `POST` | `/api/v1/portfolios/{portfolio_id}/holdings` | Add one holding | `201` | `403` in production, `404`, `409`, `422` |
| `DELETE` | `/api/v1/portfolios/{portfolio_id}/holdings/{holding_id}` | Delete one holding | `204` | `403` in production, `404` |
| `POST` | `/api/v1/portfolios/{portfolio_id}/transactions` | Append transactions, rejecting future dates and oversells | `201` | `403` in production, `404`, `422` |
| `DELETE` | `/api/v1/portfolios/{portfolio_id}/transactions/{transaction_id}` | Delete one transaction, refusing if the rest would be oversold | `204` | `403` in production, `404`, `422` |
| `POST` | `/api/v1/portfolios/{portfolio_id}/transactions/csv-preview` | Validate a transactions CSV against this ledger; saves nothing | `200` | `403` in production, `404`, `413`, `415` |
| `POST` | `/api/v1/portfolios/{portfolio_id}/transactions/csv-import` | Import a transactions CSV atomically | `201` | `403` in production, `404`, `413`, `415`, `422` |
| `POST` | `/api/v1/portfolios/csv-preview` | Validate a CSV file (multipart `file`); saves nothing | `200` | `403` in production, `413`, `415` |
| `POST` | `/api/v1/portfolios/csv-import` | Create a portfolio from a CSV file (multipart `name`, `file`) | `201` | `403` in production, `413`, `415`, `422` |

Valuation response (abridged):

```json
{
  "valued_at": "2026-09-16T00:06:23Z",
  "market_data_configured": false,
  "freshness": {"expected_session_date": "2026-09-15", "latest_price_date": "2026-09-15", "valued_count": 5, "stale_count": 0, "unpriced_count": 0},
  "totals": {"total_invested_value": "83000.00", "priced_invested_value": "83000.00", "total_market_value": "85881.50", "total_unrealized_pnl": "2881.50", "total_unrealized_return_pct": "3.47", "is_complete": true},
  "holdings": [
    {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 10, "average_buy_price": "1200.00", "status": "VALUED", "unpriced_reason": null,
     "price": {"close_price": "1235.30", "trade_date": "2026-09-15", "exchange": "NSE", "source": "indian_api", "source_name": "Indian API", "fetched_at": "…"},
     "invested_value": "12000.00", "market_value": "12353.00", "unrealized_pnl": "353.00", "unrealized_return_pct": "2.94", "weight_pct": "14.38", "warnings": []}
  ]
}
```

`market_data_configured` is `false` on the deployed API by design: it holds no provider key and reads prices the sync has already stored.

Errors share one shape, with `details` for validation problems:

```json
{"error": {"code": "duplicate_holding", "message": "HDFCBANK on NSE is already in this portfolio."}}
```

## Database model

```mermaid
erDiagram
    PORTFOLIOS ||--o{ HOLDINGS : contains
    LISTINGS ||--o{ DAILY_PRICES : "has closes"
    MARKET_DATA_SYNC_RUNS ||--o{ DAILY_PRICES : "stored by"
    HOLDINGS }o..o| LISTINGS : "matched by NSE symbol or BSE code"
```

| Table | Purpose | Key constraints |
|---|---|---|
| `portfolios` | Portfolio name and timestamps | Name not blank |
| `holdings` | Symbol, exchange, quantity, average buy price | FK to `portfolios` `ON DELETE CASCADE`; unique `(portfolio_id, symbol, exchange)`; quantity and price > 0; `NSE`/`BSE`; symbol format |
| `listings` | Security master: provider ID, name, NSE symbol, BSE scrip code, ISIN (nullable), active flag | Unique `(provider, provider_security_id)`, `(provider, nse_symbol)`, `(provider, bse_code)`; format checks |
| `daily_prices` | One reported close per security, exchange and `trade_date` (`DATE`): `close_price NUMERIC(18,4)`, volume, source, `fetched_at`, sync run | Unique `(listing_id, exchange, trade_date)`; close > 0 |
| `market_data_sync_runs` | Every sync: provider, kind, status, requests made, records attempted/inserted/updated, failures, error summary, details | Status and kind checks; non-negative counters |
| `alembic_version` | Migration state managed by Alembic | Current head: `20260915_0003` |

Holdings are matched to listings **at read time** by NSE symbol or BSE scrip code, not by foreign key, so market data can be added without touching user data.

**Nothing derived is stored.** Market value, invested value, P&L, returns and weights are calculated on every request from stored holdings and stored prices.

## Validation rules and CSV format

The same rules apply to manual entry, the JSON API and CSV import: the browser catches obvious mistakes, the API validates everything again, and database constraints are the final safeguard.

| Field | Rule |
|---|---|
| Portfolio name | Required, 1–100 characters after trimming; repeated spaces collapsed |
| Symbol | Required, trimmed and uppercased, at most 20 characters, starts with a letter or digit, then letters, digits, `&` or `-`. Format only: symbols are **not** checked against exchange listings at entry |
| Exchange | `NSE` or `BSE` (case-insensitive) |
| Quantity | Whole number, greater than 0, at most 1,000,000,000 |
| Average buy price | Greater than 0, at most 4 decimal places, at most 9,999,999,999.9999; no commas or currency symbols |
| Holdings per portfolio | At most 500; each symbol and exchange pair at most once |
| Request body | Unknown fields are rejected |

CSV header (case-insensitive, any order), with a sample at [`frontend/public/sample-portfolio.csv`](frontend/public/sample-portfolio.csv):

```csv
symbol,exchange,quantity,average_buy_price
HDFCBANK,NSE,20,1650
TCS,NSE,10,3200
RELIANCE,NSE,15,1400
```

Rejected: bad or duplicated headers, malformed rows, blank or non-numeric values, zero or negative values, fractional quantities, exchanges other than NSE/BSE, duplicate symbol-and-exchange rows (never merged), non-`.csv` files, files over 1 MB or not UTF-8, and more than 500 holdings.

## Local development

Writes are enabled by default outside production, so the full flow — manual entry, CSV import, valuation — works locally.

**Prerequisites:** Node.js 24 and npm, Python 3.12 and [uv](https://docs.astral.sh/uv/), PostgreSQL 16.

```bash
git clone https://github.com/pgp41370-coder/portfolio-intelligence.git
cd portfolio-intelligence
```

```bash
cd backend && uv sync
```

```bash
cd frontend && npm install
```

```bash
createdb portfolio_intelligence && createdb portfolio_intelligence_test
```

```bash
cp backend/.env.example backend/.env
```

Set `DATABASE_URL` in `backend/.env` — placeholders only, never real credentials — then create the tables:

```bash
cd backend && uv run alembic upgrade head
```

Run the backend from `backend/`:

```bash
uv run uvicorn app.main:app --reload
```

And the frontend from `frontend/`, in a second terminal:

```bash
npm run dev
```

Open http://localhost:3000 and choose **Analyze My Portfolio**. The frontend forwards `/api/v1/*` to http://127.0.0.1:8000, so no CORS setup is needed. Interactive API documentation is at http://localhost:8000/docs in development.

## Environment variables

Use placeholders in committed files. `.env` files are git-ignored and excluded from deployment uploads.

Backend (`backend/.env` or the environment):

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | For storage | PostgreSQL connection string, e.g. `postgresql+psycopg://USER:PASSWORD@localhost:5432/portfolio_intelligence`. Plain `postgresql://` URLs are converted to the psycopg driver. Without it, portfolio endpoints return `503 database_not_configured` |
| `DATABASE_POOL_MODE` | No | `session` (default: local PostgreSQL, migrations, market-data sync) or `transaction` (a transaction-mode pooler for a serverless API; disables client-side pooling and prepared statements) |
| `APP_ENV` | No | `development`, `test` or `production`. Defaults to `development`. `production` makes the API read-only, disables `/docs` and requires explicit `https://` CORS origins |
| `CORS_ALLOWED_ORIGINS` | No | JSON list of browser origins allowed to call the API directly. Defaults to `["http://localhost:3000"]` in development and test, and to none in production |
| `ENABLE_WRITE_API` | No | Enables write endpoints. Defaults to on, except in production |
| `INDIAN_API_KEY` | For price sync | Indian API key. **Sync only**; never set on the deployed API, never exposed to the frontend, never committed |
| `MARKET_DATA_MONTHLY_REQUEST_BUDGET` | No | Maximum metered provider requests per IST calendar month. Default `450`, maximum `500` |
| `MARKET_DATA_BACKFILL_PERIOD` | No | Initial price history period: `1m`, `6m` or `1yr` (default) |
| `NSE_TRADING_HOLIDAYS` | No | JSON list of NSE weekday trading holidays used by the freshness rule. Defaults to the published 2026 list; setting it replaces the list |
| `NSE_SPECIAL_TRADING_SESSIONS` | No | JSON list of exchange-declared sessions on normally closed days. Defaults to `["2026-02-01"]` (Union Budget, Sunday) |
| `TEST_DATABASE_URL` | For database tests | A separate database whose name must end in `_test`. The tests rebuild its schema |

Frontend:

| Variable | Required | Description |
|---|---|---|
| `API_BASE_URL` | No | Where the frontend forwards `/api/v1/*`. Read at **build** time. Defaults to `http://127.0.0.1:8000` in development; without it in a production build, no API is connected |

## Tests and checks

Backend, from `backend/`. Database tests run only when `TEST_DATABASE_URL` names a database ending in `_test`:

```bash
TEST_DATABASE_URL=postgresql+psycopg://USER@localhost:5432/portfolio_intelligence_test uv run pytest
```

```bash
uv run pytest
```

Frontend, from `frontend/`:

```bash
npm test
```

```bash
npm run lint
```

```bash
npm run build
```

Latest verified run on this commit:

| Check | Result |
|---|---|
| Backend with PostgreSQL | 619 passed |
| Backend without a database | 367 passed, 252 skipped |
| Frontend unit tests | 44 passed |
| ESLint, TypeScript, production build | Clean |

Database tests rebuild the schema with the real migrations and assert that migrations match the ORM models. They cover portfolio creation and retrieval, holdings, deletion, validation, duplicate handling, CSV import without partial writes, market-data sync (idempotency, budget, rate limits, failures, locking, session and holiday rules), valuation arithmetic, performance and coverage arithmetic, the transaction ledger and time-weighted return, transaction CSV validation and atomic import, FIFO cost basis and P&L, the timeline and attribution, the deterministic explanation layer with its golden and invariant suites, allocation and risk measures, and the read-only production configuration.

Automated tests **never call the real Indian API**: parsing uses recorded fixtures in `backend/tests/fixtures/indian_api/`, HTTP behaviour uses a mocked transport, and sync tests use a fake provider.

## Limitations and non-goals

Deliberately **not** implemented:

- AI or automated investment recommendations, stock picking, or portfolio optimization
- Money-weighted return (IRR), the Sortino ratio, and benchmark attribution by allocation and selection
- Real-time or intraday prices
- Realized P&L, taxes and dividends, or total-return measurement
- Automated corporate-action adjustment (large moves are flagged, not corrected)
- BSE-sourced prices; BSE-only securities cannot be valued
- User accounts and authentication

Operational limitations:

- The public deployment is read-only; visitors cannot create or import portfolios.
- Free-tier provider: roughly 20 held NSE securities can be kept current each month within the request budget, and the provider publishes no SLA.
- The NSE trading calendar is maintained by hand in `backend/app/market_data/nse_calendar.py`; each year's list must be added. It is known complete from 15 September 2025 to 31 December 2026, and says so when a window reaches outside that range — NSE publishes only the current year, so no 2025 archive or 2027 list was available.
- The benchmark is an **ETF proxy**, not the NIFTY 50 index: it carries an expense ratio and can trade away from net asset value.
- Transactions can be added and removed but not edited in place; remove and re-add instead.
- Tax reporting is not implemented: realised profit is computed FIFO, but holding-period rules and set-off are a separate problem.
- Provider prices were spot-checked against NSE's official closes for five large-cap securities on 15 September 2026 and matched to the paisa. That is a small sample, not continuous assurance.
- ISIN is not populated; holdings cannot be edited in place; portfolios cannot be renamed or deleted from the interface.

## Project status

| Milestone | Scope | Status |
|---|---|---|
| 1. Live application skeleton | Frontend, backend, database configuration, tests, deployment | Done |
| 2. Portfolio input and data model | Manual entry, CSV import, validation, PostgreSQL storage, portfolio display | Done |
| 3A. Market data and valuation | Security master, NSE end-of-day prices, budget-protected sync, valuation API and UI | Done |
| 3P. Production deployment | API and database in production, scheduled sync, read-only public access, hardening, rate limiting in log mode | Done |
| 4.1. Performance history | Historical value series, cumulative return, volatility, maximum drawdown, coverage reporting | Done locally, not deployed |
| 4.2. Transaction-aware analytics | Transaction ledger, time-weighted return, benchmark proxy, risk measures, allocation and concentration | Done locally, not deployed |
| 4.3. Transaction intelligence | Entry and CSV import workflows, reconciliation, FIFO P&L, timeline, return attribution | Done locally, not deployed |
| 5. Deterministic portfolio intelligence | Composed explanation of return drivers, benchmark comparison, cash-flow context, risk context and data quality | Done locally, not deployed |
| 5.1. Intelligence engine hardening | Shared calculation context, one valuation pass per request, golden and invariant test suites, explanation trace | Done locally, not deployed |
| 6.1. Money-weighted return | XIRR beside the time-weighted return, with ambiguous and short-window cases withheld rather than estimated | Done locally, not deployed |
| 6.2. Corporate-action disclosure | The whole price window scanned for moves that may be corporate actions, with the affected figures named and none adjusted | Done locally, not deployed |

"Production" here means deployed on production infrastructure as a read-only demonstration. It is not a regulated or commercially assured financial service.

---

Portfolio Intelligence is for information only and is not investment advice.
