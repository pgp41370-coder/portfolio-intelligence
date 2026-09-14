# Portfolio Intelligence

**Understand your portfolio. Measure your risk.**

Portfolio Intelligence is a portfolio analytics platform for Indian equities listed on NSE and BSE. It is being built to show investors how their holdings are allocated, where risk is concentrated and how their portfolio has performed.

> **Status: Milestone 2 (portfolio input and data model).** You can enter a portfolio manually or import it from CSV, store it in PostgreSQL and view it. **Portfolio analytics are not implemented yet.** See [Roadmap](#roadmap).

**Live site:** https://portfolio-intelligence-bice.vercel.app. The live site shows the interface only; portfolio storage is not connected there yet (see [Current limitations](#current-limitations)). The full flow runs locally.

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
10. [API endpoints](#api-endpoints)
11. [Database model](#database-model)
12. [Validation rules](#validation-rules)
13. [Running the tests](#running-the-tests)
14. [Project architecture](#project-architecture)
15. [Current limitations](#current-limitations)
16. [Roadmap](#roadmap)
17. [Future work](#future-work)

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
| Validation | Client-side checks for obvious errors; full server-side validation plus database constraints |
| API | REST endpoints for portfolios, holdings and CSV import (see [API endpoints](#api-endpoints)) |
| Tests | Backend: Pytest suite covering rules, CSV parsing, API, persistence and migrations. Frontend: ESLint and production build |
| Deployment | Frontend on Vercel. The backend and database run locally only |

**Not implemented:** live or historical market prices, market value, returns, profit or loss, risk metrics, any investment recommendation, user accounts and a production backend.

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| Backend | Python 3.12, FastAPI, Pydantic 2 |
| Database | PostgreSQL 16, SQLAlchemy 2 (psycopg 3), Alembic migrations |
| Testing | Pytest, ESLint, Next.js production build |
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

**Only user-provided data is stored.** Current price, market value, returns, profit or loss and portfolio weights are deliberately not stored; they depend on market data and will be calculated in later milestones.

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

The database tests rebuild the schema with the real Alembic migrations, check that the migration matches the ORM models, and cover portfolio creation and retrieval, holdings, deletion, validation, duplicate handling, CSV import without partial writes, constraint enforcement and total invested capital.

Frontend (from `frontend/`):

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
Frontend (Next.js) → FastAPI → Portfolio service → PostgreSQL
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Current limitations

- **The live site has no backend or database.** Portfolio pages on Vercel explain that storage is unavailable. The complete flow works locally. Connecting a production database (Supabase) and deploying the API is a separate, planned step.
- **No user accounts.** Anyone who can reach a running backend can see and change every portfolio. This is a demonstration MVP, not a production financial service.
- **Symbols are not verified** against NSE or BSE listings; only their format is checked.
- **No market data.** Total invested capital is the only calculated value, and it is not a market value.
- Holdings cannot be edited in place; remove and add again. Portfolios cannot be renamed or deleted from the interface yet.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 1. Live application skeleton | Frontend, backend, database configuration, tests, deployment | Done |
| 2. Portfolio input and data model | Manual entry, CSV import, validation, PostgreSQL storage, portfolio display | Done |
| 3. Market data | End-of-day prices for NSE and BSE equities | Planned |
| 4. Analytics | Allocation, concentration, risk and performance | Planned |
| 5. Production backend | Deploy the API and connect Supabase PostgreSQL | Planned |

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

---

Portfolio Intelligence is for information only and is not investment advice.
