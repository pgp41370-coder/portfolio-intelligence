# Portfolio Intelligence

**Understand your portfolio. Measure your risk.**

Portfolio Intelligence is a portfolio analytics platform for Indian equities listed on NSE and BSE. It is being built to show investors how their holdings are allocated, where risk is concentrated and how their portfolio has performed.

> **Status: Milestone 3A (market data and portfolio valuation).** Enter a portfolio manually or from CSV, store it in PostgreSQL, and value it at **dated NSE end-of-day closing prices** with unrealized P&L, return and weights. **Risk and performance analytics are not implemented yet.** See [Roadmap](#roadmap).

**Live site:** https://portfolio-intelligence-bice.vercel.app. The live site shows the interface only; portfolio storage and valuation are not connected there yet (see [Current limitations](#current-limitations)). The full flow runs locally.

This system is a portfolio analytics and valuation tool. It does not provide personalized investment advice.

---

## Contents

1. [What Portfolio Intelligence is](#what-portfolio-intelligence-is)
2. [Problem being solved](#problem-being-solved)
3. [Current functionality](#current-functionality)
4. [Technology stack](#technology-stack)
5. [Local setup](#5-local-setup)
6. [Environment variables](#environment-variables)
7. [Running the app](#running-the-app)
8. [Entering a portfolio manually](#entering-a-portfolio-manually)
9. [Importing a portfolio from CSV](#importing-a-portfolio-from-csv)
10. [Market data and valuation](#market-data-and-valuation)
11. [API endpoints](#api-endpoints)
12. [Database model](#database-model)
13. [Validation rules](#validation-rules)
14. [Running the tests](#running-the-tests)
15. [Project architecture](#project-architecture)
16. [Current limitations](#current-limitations)
17. [Roadmap](#roadmap)
18. [Future work](#future-work)

---

## What Portfolio Intelligence is

A web application that takes an investor's equity holdings and, in later milestones, turns them into clear, standard portfolio analytics: allocation, concentration, risk and performance. It focuses on the Indian market (NSE and BSE, INR).

## Problem being solved

Retail investors in Indian equities often hold stocks across several brokers and apps. Broker dashboards show prices and profit or loss, but rarely answer the questions that matter for managing a portfolio:

- Is too much of my money in one stock or sector?
- How volatile is my portfolio, and how badly could it fall?
- Has my portfolio actually done better than simply holding the market?

Portfolio Intelligence aims to answer these with transparent, well-established financial measures. The first step, built in this milestone, is capturing the portfolio accurately.

## Current functionality

| Area | Implemented |
|---|---|
| Portfolio input | Manual entry (add and remove holdings, review, save) and CSV import (upload, validate every row, review, save) |
| Storage | Portfolios and holdings stored in PostgreSQL through a service layer; schema managed by Alembic migrations |
| Retrieval and display | Saved portfolios list; portfolio page with holdings table and total invested capital; remove a holding from a saved portfolio |
| Calculation | **Total invested capital** = Σ (quantity × average buy price). Exact decimal arithmetic, based only on user input |
| Market data | Security master from Indian API; dated NSE end-of-day closing prices ingested by a rate-limited, budget-protected sync CLI; every sync recorded |
| Valuation | Per holding: EOD price and date, market value, unrealized P&L, return and weight. Portfolio: current value, P&L and return. Each holding is VALUED, STALE or UNPRICED; missing prices are never shown as zero |
| Validation | Client-side checks for obvious errors; full server-side validation plus database constraints; strict validation of provider responses |
| API | REST endpoints for portfolios, holdings, CSV import, valuation and market-data status (see [API endpoints](#api-endpoints)) |
| Tests | Backend: Pytest suite covering rules, CSV parsing, API, persistence, migrations, provider parsing and HTTP behaviour (mocked), sync, freshness and valuation. Frontend: valuation display unit tests, ESLint, TypeScript and production build |
| Deployment | Frontend on Vercel. The backend, database and market-data sync run locally only |

**Not implemented:** real-time prices, corporate-action adjustment, dividends and total return, realized P&L, risk metrics, benchmarks, any investment recommendation, user accounts and a production backend.

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| Backend | Python 3.12, FastAPI, Pydantic 2 |
| Database | PostgreSQL 16, SQLAlchemy 2 (psycopg 3), Alembic migrations |
| Market data | Indian API (NSE end-of-day prices), httpx, Python `Decimal`, `zoneinfo` (Asia/Kolkata) |
| Testing | Pytest (with recorded provider fixtures and mocked HTTP), Node test runner, ESLint, Next.js production build |
| Tooling | uv (Python), npm (Node.js 24) |
| Hosting | Vercel (frontend) |
| Version control | Git, GitHub |

Planned for later milestones: pandas, NumPy and SciPy for analytics; Recharts for charts; Supabase PostgreSQL in production.

## 5. Local setup

### Prerequisites

- Node.js 24 and npm
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 running locally

### Clone and install

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

### Create the databases

```bash
createdb portfolio_intelligence
```

```bash
createdb portfolio_intelligence_test
```

### Configure and migrate

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set `DATABASE_URL`, then create the tables:

```bash
cd backend && uv run alembic upgrade head
```

Migrations are reproducible: `uv run alembic downgrade base` removes the tables and `uv run alembic upgrade head` recreates them on any empty PostgreSQL database. `uv run alembic upgrade head --sql` prints the SQL without running it.

## Environment variables

Backend (`backend/.env` or the environment):

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | For storage | PostgreSQL connection string, e.g. `postgresql+psycopg://USER:PASSWORD@localhost:5432/portfolio_intelligence`. Plain `postgresql://` URLs are converted to the psycopg driver automatically. Without it, portfolio endpoints return `503 database_not_configured`. |
| `APP_ENV` | No | `development`, `test` or `production`. Defaults to `development`. |
| `CORS_ALLOWED_ORIGINS` | No | JSON list of browser origins allowed to call the API directly. Defaults to `["http://localhost:3000"]`. |
| `INDIAN_API_KEY` | For price sync | Indian API key. **Backend only**; never exposed to the frontend or committed. Without it the app runs and valuation uses already-stored prices. |
| `MARKET_DATA_MONTHLY_REQUEST_BUDGET` | No | Maximum metered provider requests per IST calendar month. Default `450`, maximum `500`. |
| `MARKET_DATA_BACKFILL_PERIOD` | No | Initial price history period: `1m`, `6m` or `1yr` (default). |
| `NSE_TRADING_HOLIDAYS` | No | JSON list of NSE holiday dates used by the price-freshness rule, e.g. `["2026-10-02"]`. |
| `TEST_DATABASE_URL` | For database tests | A separate database whose name must end in `_test`. The tests rebuild its schema. |

Frontend:

| Variable | Required | Description |
|---|---|---|
| `API_BASE_URL` | No | Where the frontend forwards `/api/v1/*` requests. Read when the app is built. Defaults to `http://127.0.0.1:8000` in development; in production builds without it, no API is connected. |

Never commit `.env` files. They are listed in `.gitignore`.

## Running the app

Backend (from `backend/`):

```bash
uv run uvicorn app.main:app --reload
```

Frontend (from `frontend/`, in a second terminal):

```bash
npm run dev
```

Open http://localhost:3000 and choose **Analyze My Portfolio**. The frontend forwards `/api/v1/*` to the backend at http://127.0.0.1:8000, so no CORS setup is needed. Interactive API documentation is at http://localhost:8000/docs.

## Entering a portfolio manually

1. Go to **Analyze My Portfolio → Enter holdings manually**.
2. Enter a **portfolio name**.
3. For each position, enter **Stock Symbol**, **Exchange** (NSE or BSE), **Quantity** and **Average Buy Price (₹)**, then choose **Add Holding**. For example: `HDFCBANK`, `NSE`, `20`, `1650`.
4. Repeat for every holding. Use **Remove Holding** to take one out. The running **Total Invested Capital** is shown below the list.
5. Choose **Review Portfolio** to check everything, then **Save Portfolio**. **Cancel** leaves without saving.

Nothing is stored until you save. The whole portfolio is saved in one database transaction.

## Importing a portfolio from CSV

1. Go to **Analyze My Portfolio → Upload a CSV file**.
2. Enter a portfolio name and choose a `.csv` file.
3. The file is checked immediately. Any problems are listed by row and column, and nothing is saved.
4. If the file is valid, review the holdings and total invested capital, then choose **Save Portfolio**.

The server validates the file again when saving. If any row is invalid, **nothing** is written to the database.

### CSV format

The first line must be this header (column names are case-insensitive and may be in any order):

```
symbol,exchange,quantity,average_buy_price
```

| Column | Content |
|---|---|
| `symbol` | NSE or BSE symbol, e.g. `HDFCBANK`, `M&M`, `BAJAJ-AUTO` or a BSE scrip code such as `500180` |
| `exchange` | `NSE` or `BSE` |
| `quantity` | Whole number of shares, greater than 0 |
| `average_buy_price` | Price per share in rupees, greater than 0, up to 4 decimal places |

### Example CSV

```csv
symbol,exchange,quantity,average_buy_price
HDFCBANK,NSE,20,1650
TCS,NSE,10,3200
RELIANCE,NSE,15,1400
```

A copy is available at [`frontend/public/sample-portfolio.csv`](frontend/public/sample-portfolio.csv) and from the import page.

### What is rejected

- Missing, extra, blank or duplicated header columns
- Rows with too few or too many values, and malformed CSV (for example an unclosed quote)
- Blank values, non-numeric values (including commas like `1,000` or `₹`), zero or negative values, fractional quantities
- Exchanges other than NSE or BSE
- **Duplicate holdings**: the same symbol and exchange on more than one row. Duplicates are never merged; the row is identified so you can correct the file.
- Files that are not `.csv`, larger than 1 MB, not UTF-8 text, empty, or with more than 500 holdings

## Market data and valuation

Portfolios are valued at the **latest available dated NSE end-of-day closing price**, never a live price. Full methodology, freshness rules and limitations: [docs/market-data.md](docs/market-data.md).

| Value | Definition |
|---|---|
| Market value | quantity × NSE end-of-day close |
| Unrealized P&L | market value − quantity × average buy price |
| Return | unrealized P&L ÷ invested value (portfolio: total P&L ÷ invested value of priced holdings) |
| Weight | market value ÷ current value of priced holdings |

- **VALUED:** priced at the close of the latest expected NSE session (after 18:00 IST on a session day, that day; otherwise the previous session).
- **STALE:** priced at an older close; the date is always shown.
- **UNPRICED:** no NSE listing (e.g. BSE-only), unknown symbol or no stored price. Excluded from current value, P&L, return and weights; still included in total invested. Never shown as ₹0.
- BSE holdings of securities that also trade on NSE are valued at the NSE close, and labelled as such.
- A close-to-close move of 35% or more is flagged as a possible split or bonus issue. Prices are not adjusted for corporate actions; returns exclude dividends.

### Running the sync

Set `INDIAN_API_KEY` in `backend/.env`, then from `backend/`:

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

`sync-listings` loads the security master (not metered). `sync-prices` fetches prices only for held NSE securities that are not up to date, at most one request per 1.1 seconds, and stops on authentication errors, HTTP 429, provider outages or when the monthly request budget is reached.

## API endpoints

All portfolio endpoints are under `/api/v1`. Amounts are returned as decimal strings (for example `"1650.00"`) so no precision is lost.

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| `GET` | `/health` | Liveness check | `200` | |
| `GET` | `/health/db` | Database connectivity check | `200` | `503` |
| `GET` | `/api/v1` | API name, version and status | `200` | |
| `POST` | `/api/v1/portfolios` | Create a portfolio, optionally with its holdings | `201` | `422`, `503` |
| `GET` | `/api/v1/portfolios` | List portfolios with holding count and invested capital | `200` | `503` |
| `GET` | `/api/v1/portfolios/{portfolio_id}` | Retrieve one portfolio with its holdings | `200` | `404`, `422` |
| `POST` | `/api/v1/portfolios/{portfolio_id}/holdings` | Add one holding | `201` | `404`, `409` duplicate, `422` |
| `DELETE` | `/api/v1/portfolios/{portfolio_id}/holdings/{holding_id}` | Delete one holding | `204` | `404` |
| `POST` | `/api/v1/portfolios/csv-preview` | Validate a CSV file (multipart `file`). Saves nothing | `200` | `413`, `415` |
| `POST` | `/api/v1/portfolios/csv-import` | Create a portfolio from a CSV file (multipart `name`, `file`) | `201` | `413`, `415`, `422` |
| `GET` | `/api/v1/portfolios/{portfolio_id}/valuation` | Value a portfolio at stored NSE end-of-day prices (never calls the provider) | `200` | `404`, `422`, `503` |
| `GET` | `/api/v1/market-data/status` | Provider, configuration flag, request usage, last syncs, latest trade date, held-security freshness. Never returns credentials | `200` | `503` |

Valuation response (abridged):

```json
{
  "valued_at": "2026-09-14T13:00:00Z",
  "market_data_configured": true,
  "freshness": {"expected_session_date": "2026-09-14", "latest_price_date": "2026-09-14", "valued_count": 1, "stale_count": 0, "unpriced_count": 0},
  "totals": {"total_invested_value": "24000.00", "priced_invested_value": "24000.00", "total_market_value": "26500.00", "total_unrealized_pnl": "2500.00", "total_unrealized_return_pct": "10.42", "is_complete": true},
  "holdings": [
    {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 10, "average_buy_price": "2400.00", "status": "VALUED", "unpriced_reason": null,
     "price": {"close_price": "2650.00", "trade_date": "2026-09-14", "exchange": "NSE", "source": "indian_api", "source_name": "Indian API", "fetched_at": "…"},
     "invested_value": "24000.00", "market_value": "26500.00", "unrealized_pnl": "2500.00", "unrealized_return_pct": "10.42", "weight_pct": "100.00", "warnings": []}
  ]
}
```

Money and percentages are decimal strings rounded to 2 places (ROUND_HALF_UP); unavailable values are `null`.

Create a portfolio:

```http
POST /api/v1/portfolios
Content-Type: application/json

{
  "name": "Long-term equity",
  "holdings": [
    {"symbol": "HDFCBANK", "exchange": "NSE", "quantity": 20, "average_buy_price": "1650"},
    {"symbol": "TCS", "exchange": "NSE", "quantity": 10, "average_buy_price": "3200"}
  ]
}
```

Response `201`:

```json
{
  "id": "0c3f…",
  "name": "Long-term equity",
  "created_at": "2026-09-15T05:10:00Z",
  "updated_at": "2026-09-15T05:10:00Z",
  "holdings": [
    {"id": "…", "symbol": "HDFCBANK", "exchange": "NSE", "quantity": 20, "average_buy_price": "1650.00", "created_at": "…", "updated_at": "…"},
    {"id": "…", "symbol": "TCS", "exchange": "NSE", "quantity": 10, "average_buy_price": "3200.00", "created_at": "…", "updated_at": "…"}
  ],
  "total_invested_capital": "65000.00"
}
```

Every error has the same shape, with `details` for validation problems:

```json
{"error": {"code": "duplicate_holding", "message": "HDFCBANK on NSE is already in this portfolio."}}
```

## Database model

```mermaid
erDiagram
    PORTFOLIOS ||--o{ HOLDINGS : contains
    PORTFOLIOS {
        uuid id PK
        varchar name
        timestamptz created_at
        timestamptz updated_at
    }
    HOLDINGS {
        uuid id PK
        uuid portfolio_id FK
        varchar symbol
        varchar exchange
        bigint quantity
        numeric average_buy_price
        timestamptz created_at
        timestamptz updated_at
    }
```

**portfolios**

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | Primary key |
| `name` | `VARCHAR(100)` | Not null; must not be blank |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Not null; default `now()` |

**holdings**

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | Primary key |
| `portfolio_id` | `UUID` | Foreign key to `portfolios.id`, `ON DELETE CASCADE` |
| `symbol` | `VARCHAR(20)` | Uppercase letters, digits, `&` and `-` (check constraint) |
| `exchange` | `VARCHAR(3)` | `NSE` or `BSE` (check constraint) |
| `quantity` | `BIGINT` | Greater than 0 |
| `average_buy_price` | `NUMERIC(14,4)` | Greater than 0 |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Not null; default `now()` |

A holding is unique per portfolio, symbol and exchange (`uq_holdings_portfolio_id_symbol_exchange`).

**Market-data tables** (migration `20260915_0002`, additive; portfolios and holdings are unchanged):

| Table | Purpose | Key constraints |
|---|---|---|
| `listings` | Security master: provider ID, name, NSE symbol, BSE scrip code, ISIN (nullable), active flag | Unique `(provider, provider_security_id)`, `(provider, nse_symbol)`, `(provider, bse_code)`; format checks |
| `daily_prices` | One reported close per security, exchange and `trade_date` (`DATE`): `close_price NUMERIC(18,4)`, volume, source, `fetched_at`, sync run | Unique `(listing_id, exchange, trade_date)`; close > 0 |
| `market_data_sync_runs` | Every sync: provider, kind, status, requests made, records attempted/inserted/updated, failures, error summary, details | Status and kind checks; non-negative counters |

Holdings are matched to listings at read time (NSE symbol or BSE scrip code), not by foreign key.

**Nothing derived is stored.** Market value, invested value, profit or loss, returns and weights are always calculated from stored holdings and stored prices.

## Validation rules

The same rules apply to manual entry, the JSON API and CSV import. The browser catches obvious mistakes first; the API validates everything again; the database constraints are a final safeguard.

| Field | Rule |
|---|---|
| Portfolio name | Required, 1–100 characters after trimming; repeated spaces collapsed |
| Symbol | Required, trimmed and uppercased, at most 20 characters, starts with a letter or digit, then letters, digits, `&` or `-`. Format only: symbols are **not** checked against NSE or BSE listings yet |
| Exchange | `NSE` or `BSE` (case-insensitive) |
| Quantity | Whole number, greater than 0, at most 1,000,000,000 |
| Average buy price | Number greater than 0, at most 4 decimal places, at most 9,999,999,999.9999; no commas or currency symbols |
| Holdings per portfolio | At most 500; each symbol and exchange pair at most once |
| Request body | Unknown fields are rejected |

## Running the tests

Backend (from `backend/`). Tests that need a database run only when `TEST_DATABASE_URL` points at a database whose name ends in `_test`:

```bash
TEST_DATABASE_URL=postgresql+psycopg://USER@localhost:5432/portfolio_intelligence_test uv run pytest
```

Without `TEST_DATABASE_URL`, the database tests are skipped and the rest still run:

```bash
uv run pytest
```

The database tests rebuild the schema with the real Alembic migrations, check that the migrations match the ORM models, and cover portfolio creation and retrieval, holdings, deletion, validation, duplicate handling, CSV import without partial writes, constraint enforcement, total invested capital, market-data sync (idempotency, duplicates, budget, rate limits, failures, locking) and the valuation and status APIs.

Automated tests **never call the real Indian API**: provider parsing uses recorded-format fixtures in `backend/tests/fixtures/indian_api/`, HTTP behaviour uses a mocked transport, and sync tests use a fake provider.

Frontend (from `frontend/`):

```bash
npm test
```

```bash
npm run lint
```

```bash
npm run build
```

## Project architecture

```
portfolio-intelligence/
  frontend/   Next.js application (deployed to Vercel)
  backend/    FastAPI application, portfolio service, Alembic migrations
  docs/       Architecture documentation
```

```
Frontend (Next.js) → FastAPI → Portfolio / Valuation services → PostgreSQL ← Market-data sync (CLI) ← Indian API
```

No web request calls the market-data provider.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Current limitations

- **The live site has no backend or database.** Portfolio pages on Vercel explain that storage and valuation are unavailable. The complete flow works locally. Deploying the API, the database (Supabase) and a scheduled sync is a separate, planned step.
- **No real price sync has run yet.** The Indian API adapter is built from the provider's documentation and tested with recorded-format fixtures; the first sync with a real key must confirm the response format and that recent closes are unadjusted daily prices.
- **End-of-day, NSE only.** Not real-time. BSE-only securities cannot be valued. ISIN is not populated.
- **Not adjusted for corporate actions and not a total return.** Dividends, taxes and charges are excluded; large moves are flagged but not corrected.
- **NSE holidays** must be configured (`NSE_TRADING_HOLIDAYS`) for exact freshness around exchange holidays.
- **Free-tier provider.** About 20 held NSE securities can be kept current each month within the request budget; the provider publishes no SLA.
- **No user accounts.** Anyone who can reach a running backend can see and change every portfolio. This is a demonstration MVP, not a production financial service.
- Holdings cannot be edited in place; remove and add again. Portfolios cannot be renamed or deleted from the interface yet.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 1. Live application skeleton | Frontend, backend, database configuration, tests, deployment | Done |
| 2. Portfolio input and data model | Manual entry, CSV import, validation, PostgreSQL storage, portfolio display | Done |
| 3A. Market data and valuation | Security master, NSE end-of-day prices, sync with request budget, portfolio valuation API and UI | Done (local; first real price sync pending an API key) |
| 3B. Production backend | Deploy the API, connect Supabase PostgreSQL, scheduled price sync | Planned |
| 4. Analytics | Allocation, concentration, risk and performance | Planned |

## Future work

Ideas noted during Milestone 2 and deliberately not built, to keep the scope focused:

- Edit a holding's quantity or average buy price (`PATCH`) and add holdings to a saved portfolio from the interface
- Rename and delete portfolios from the interface
- Show invested amount per holding
- Verify symbols against an NSE/BSE security master
- Import broker export formats (for example Zerodha or Groww holdings files)
- User accounts so each investor sees only their own portfolios
- Rate limiting and pagination for the API
- Export a portfolio to CSV
- BSE end-of-day prices and ISIN-based security matching
- Corporate-action data to adjust quantities and flag affected holdings precisely
- An NSE holiday calendar sourced from the exchange rather than configuration
- Price history charts

---

Portfolio Intelligence is for information only and is not investment advice.
