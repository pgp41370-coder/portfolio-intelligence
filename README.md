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
6. [Production hardening](#production-hardening)
7. [API endpoints](#api-endpoints)
8. [Database model](#database-model)
9. [Validation rules and CSV format](#validation-rules-and-csv-format)
10. [Local development](#local-development)
11. [Environment variables](#environment-variables)
12. [Tests and checks](#tests-and-checks)
13. [Limitations and non-goals](#limitations-and-non-goals)
14. [Project status](#project-status)

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
| Operations | A status endpoint reporting provider configuration, request usage, last syncs and held-security freshness — without credentials |

### 🔜 Next

Portfolio analytics on top of the existing valuation: allocation and concentration breakdowns, then risk and performance measures.

### 🔭 Future

BSE-sourced prices and ISIN-based matching, corporate-action data, user accounts, and price history charts.

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
| `GET` | `/api/v1/market-data/status` | Provider, configuration flag, request usage, last syncs, latest trade date, held-security freshness. Never returns credentials | `200` | `503` |
| `POST` | `/api/v1/portfolios` | Create a portfolio, optionally with holdings | `201` | `403` in production, `422`, `503` |
| `POST` | `/api/v1/portfolios/{portfolio_id}/holdings` | Add one holding | `201` | `403` in production, `404`, `409`, `422` |
| `DELETE` | `/api/v1/portfolios/{portfolio_id}/holdings/{holding_id}` | Delete one holding | `204` | `403` in production, `404` |
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
| Backend with PostgreSQL | 360 passed |
| Backend without a database | 253 passed, 107 skipped |
| Frontend unit tests | 8 passed |
| ESLint, TypeScript, production build | Clean |

Database tests rebuild the schema with the real migrations and assert that migrations match the ORM models. They cover portfolio creation and retrieval, holdings, deletion, validation, duplicate handling, CSV import without partial writes, market-data sync (idempotency, budget, rate limits, failures, locking, session and holiday rules), valuation arithmetic and the read-only production configuration.

Automated tests **never call the real Indian API**: parsing uses recorded fixtures in `backend/tests/fixtures/indian_api/`, HTTP behaviour uses a mocked transport, and sync tests use a fake provider.

## Limitations and non-goals

Deliberately **not** implemented:

- AI or automated investment recommendations, stock picking, or portfolio optimization
- Advanced risk analytics, benchmarks and performance attribution
- Real-time or intraday prices
- Realized P&L, taxes and dividends, or total-return measurement
- Automated corporate-action adjustment (large moves are flagged, not corrected)
- BSE-sourced prices; BSE-only securities cannot be valued
- User accounts and authentication

Operational limitations:

- The public deployment is read-only; visitors cannot create or import portfolios.
- Free-tier provider: roughly 20 held NSE securities can be kept current each month within the request budget, and the provider publishes no SLA.
- The NSE trading calendar is maintained by hand in `backend/app/market_data/nse_calendar.py`; each year's list must be added.
- Provider prices were spot-checked against NSE's official closes for five large-cap securities on 15 September 2026 and matched to the paisa. That is a small sample, not continuous assurance.
- ISIN is not populated; holdings cannot be edited in place; portfolios cannot be renamed or deleted from the interface.

## Project status

| Milestone | Scope | Status |
|---|---|---|
| 1. Live application skeleton | Frontend, backend, database configuration, tests, deployment | Done |
| 2. Portfolio input and data model | Manual entry, CSV import, validation, PostgreSQL storage, portfolio display | Done |
| 3A. Market data and valuation | Security master, NSE end-of-day prices, budget-protected sync, valuation API and UI | Done |
| 3P. Production deployment | API and database in production, scheduled sync, read-only public access, hardening, rate limiting in log mode | Done |
| 4. Analytics | Allocation, concentration, risk and performance | Planned |

"Production" here means deployed on production infrastructure as a read-only demonstration. It is not a regulated or commercially assured financial service.

---

Portfolio Intelligence is for information only and is not investment advice.
