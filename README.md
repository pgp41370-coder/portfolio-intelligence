# Portfolio Intelligence

**Understand your portfolio. Measure your risk.**

Portfolio Intelligence is a portfolio analytics platform for Indian equities listed on NSE and BSE. It is being built to show investors how their holdings are allocated, where risk is concentrated and how their portfolio has performed.

> **Status: early build (Milestone 1).** The application skeleton is live. Portfolio analytics are **not implemented yet**. See [Roadmap](#roadmap).

**Live site:** _added after deployment_

---

## 1. What Portfolio Intelligence is

A web application that will take an investor's equity holdings and turn them into clear, standard portfolio analytics: allocation, concentration, risk and performance. It focuses on the Indian market (NSE and BSE, INR).

## 2. Problem being solved

Retail investors in Indian equities often hold stocks across several brokers and apps. Broker dashboards show prices and profit or loss, but rarely answer the questions that matter for managing a portfolio:

- Is too much of my money in one stock or sector?
- How volatile is my portfolio, and how badly could it fall?
- Has my portfolio actually done better than simply holding the market?

Portfolio Intelligence aims to answer these with transparent, well-established financial measures.

## 3. Current functionality

What exists **today**:

| Area | Implemented |
|---|---|
| Frontend | Homepage describing the product and its planned analysis areas; placeholder `/analyze` page; responsive layout; custom 404 page |
| Backend | FastAPI app with `GET /health`, `GET /api/v1` and `GET /health/db` (database connectivity check); consistent JSON error responses |
| Database | Environment-based configuration and a connectivity check against PostgreSQL. No tables yet. |
| Tests | Backend tests with Pytest; frontend lint and production build |
| Deployment | Frontend deployed on Vercel. The backend runs locally only. |

**Not implemented yet:** portfolio input, market data, any analytics calculations, user accounts, backend deployment.

## 4. Technology stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| Backend | Python 3.12, FastAPI, Pydantic, pydantic-settings |
| Database | PostgreSQL 16 locally (SQLAlchemy 2 + psycopg 3); Supabase PostgreSQL in production (planned) |
| Testing | Pytest, ESLint, Next.js production build |
| Tooling | uv (Python), npm (Node.js 24) |
| Hosting | Vercel (frontend) |
| Version control | Git, GitHub |

Planned additions when their milestones arrive: pandas, NumPy and SciPy for analytics; Recharts for charts.

## 5. Local setup

### Prerequisites

- Node.js 24 and npm
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 running locally (optional; only needed for the database check)

### Clone

```bash
git clone https://github.com/pgp41370-coder/portfolio-intelligence.git
cd portfolio-intelligence
```

### Create the local database (optional)

```bash
createdb portfolio_intelligence
```

## 6. Environment variables

The backend reads its configuration from environment variables or from `backend/.env`. Copy the example file and fill in your own values:

```bash
cp backend/.env.example backend/.env
```

| Variable | Required | Description |
|---|---|---|
| `APP_ENV` | No | `development`, `test` or `production`. Defaults to `development`. |
| `DATABASE_URL` | No | PostgreSQL connection string, e.g. `postgresql+psycopg://USER:PASSWORD@localhost:5432/portfolio_intelligence`. Without it, `/health/db` reports that the database is not configured. |
| `CORS_ALLOWED_ORIGINS` | No | JSON list of browser origins allowed to call the API. Defaults to `["http://localhost:3000"]`. |
| `TEST_DATABASE_URL` | No | Enables the test that connects to a real PostgreSQL database. |

Never commit `.env` files. They are listed in `.gitignore`.

The frontend needs no environment variables yet.

## 7. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

## 8. Run the backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

| URL | Response |
|---|---|
| http://localhost:8000/health | `{"status": "ok"}` |
| http://localhost:8000/api/v1 | API name, version and status |
| http://localhost:8000/health/db | Database connectivity (`200` connected, `503` not configured or unreachable) |
| http://localhost:8000/docs | Interactive API documentation |

## 9. Run the tests

Backend:

```bash
cd backend
uv run pytest
```

Include the real-database test:

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://USER@localhost:5432/portfolio_intelligence uv run pytest
```

Frontend (lint and production build):

```bash
cd frontend
npm run lint
npm run build
```

## 10. Project architecture

```
portfolio-intelligence/
  frontend/   Next.js application (deployed to Vercel)
  backend/    FastAPI application
  docs/       Architecture and project documentation
```

```
Browser → Next.js → FastAPI → PostgreSQL
```

The frontend does not call the backend yet. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## 11. Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 1. Live application skeleton | Frontend, backend, database configuration, tests, deployment | Done |
| 2. Portfolio input and data model | Enter holdings; database schema for portfolios | Planned |
| 3. Market data | End-of-day prices for NSE and BSE equities | Planned |
| 4. Analytics | Allocation, concentration, risk and performance | Planned |
| 5. Production backend | Deploy the API and connect Supabase PostgreSQL | Planned |

Everything marked **Planned** is not available yet.

---

Portfolio Intelligence is for information only and is not investment advice.
