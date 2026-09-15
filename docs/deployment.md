# Production deployment

**Status: prepared, not deployed.** This document is the plan and runbook for the first public deployment: a **read-only demo** at ₹0.

```
Browser ──> Vercel: frontend (Next.js) ── /api/v1/* rewrite ──> Vercel: backend (FastAPI, sin1)
                                                                   │  transaction pooler :6543
                                                                   ▼
GitHub Actions (weekdays 21:30 IST) ── session pooler :5432 ──> Supabase PostgreSQL (Singapore)
        │
        └──> Indian API (NSE end-of-day prices)
```

No web request calls the market-data provider. Only the scheduled GitHub Actions job holds `INDIAN_API_KEY`.

## 1. Platforms and cost

| Component | Platform | Plan | Cost |
|---|---|---|---|
| Frontend | Vercel (existing project `portfolio-intelligence`) | Hobby | ₹0 |
| Backend API | Vercel (new project, root directory `backend`) | Hobby: one function region (`sin1`, Singapore, matching the database), 1 WAF rate-limit rule per project | ₹0 |
| Database | Supabase (project created, region `ap-southeast-1`, Singapore) | Free: 500 MB, 5 GB egress, 2 projects, paused after 1 week of inactivity, no backups | ₹0 |
| Scheduled sync | GitHub Actions | Free for public repositories | ₹0 |
| Market data | Indian API | Free tier: 500 requests per month | ₹0 |

No card, trial or paid add-on is needed. Vercel Hobby is for personal, non-commercial use, which fits this project.

**Why Vercel for the backend:** Vercel runs FastAPI natively (it detects `app` in `app/main.py`, installs from `pyproject.toml` and `uv.lock`, and uses Python 3.12 by default). The API is short, stateless, database-only requests, which suit serverless functions. It keeps both apps on one platform and one CLI. The serverless constraints are handled in code: `DATABASE_POOL_MODE=transaction` disables client-side pooling and psycopg prepared statements for Supabase's transaction pooler, and the functions run in Singapore (`sin1`), the region of the database.

## 2. Supabase configuration

1. **Done (16 Sep 2026):** a project exists on the **Free** plan in region **Singapore (ap-southeast-1)**, so Vercel functions use `sin1`. Keep the database password in a password manager; never paste it into chat or a committed file.
2. From **Connect**, copy two connection strings and append `?sslmode=require`:

| Connection | Port | Used by | `DATABASE_POOL_MODE` |
|---|---|---|---|
| Transaction pooler (Supavisor) | 6543 | Vercel backend API | `transaction` |
| Session pooler (Supavisor) | 5432 | Alembic migrations, GitHub Actions sync, one-off admin tasks | `session` |

- The **direct connection** is IPv6-only on the Free plan, and GitHub-hosted runners use IPv4, so it is not used.
- **Transaction pooler:** prepared statements are not supported and session state is not kept. The API therefore uses `NullPool` and `prepare_threshold=None`.
- **Session pooler:** the market-data sync takes a session-level PostgreSQL advisory lock, which a transaction pooler would silently lose. The sync CLI and migrations refuse to run with `DATABASE_POOL_MODE=transaction`.
- **Data API exposure:** Supabase exposes tables in the `public` schema through its REST Data API. Migration `20260915_0003` enables row-level security on every table with no policies, so Data API roles can read and write nothing. The application connects as the table owner and is unaffected. Optionally, also turn off the Data API in the project settings; the application never uses it.
- **Percent-encode the password** in both connection strings. libpq splits the credentials at the **first** `@`, so an unencoded `@`, `#`, `/`, `:` or `%` in the password produces a "failed to resolve host" error (Python's URL parser hides this, since it splits at the last `@`).
- **Inactivity pause:** the weekday sync job queries the database, which keeps the free project active.
- **No backups on Free:** production holds only the demo portfolio (re-creatable) and market data (re-syncable).

## 3. Environment variables

`NEXT_PUBLIC_` is never used. Classification: **PUBLIC** is safe to disclose; **SERVER-ONLY** is not secret but must never be sent to the browser; **SECRET** must stay in a secret store.

### Frontend: Vercel project `portfolio-intelligence`

| Variable | Value | Class | Notes |
|---|---|---|---|
| `API_BASE_URL` | `https://<backend project>.vercel.app` | SERVER-ONLY | Read at build time by `next.config.ts` for the `/api/v1/*` rewrite. Set it for Production before deploying. |

### Backend: new Vercel project

| Variable | Value | Class | Notes |
|---|---|---|---|
| `APP_ENV` | `production` | PUBLIC | Read-only API, `/docs` disabled, strict CORS validation |
| `DATABASE_URL` | Supabase **transaction** pooler URL | **SECRET** | |
| `DATABASE_POOL_MODE` | `transaction` | PUBLIC | |
| `CORS_ALLOWED_ORIGINS` | `["https://portfolio-intelligence-bice.vercel.app"]` | PUBLIC | Only the production frontend; `*`, `http://` and localhost are rejected |
| `ENABLE_WRITE_API` | not set | PUBLIC | Unset means writes are disabled in production. Never set it to `true` on Vercel. |
| `INDIAN_API_KEY` | **not set** | — | The API never calls the provider |
| `NSE_TRADING_HOLIDAYS`, `NSE_SPECIAL_TRADING_SESSIONS` | not set | PUBLIC | Defaults are the published 2026 NSE calendar |

`backend/.vercelignore` stops `backend/.env` from being uploaded; the settings loader would otherwise read it.

### GitHub Actions: repository secrets

| Name | Value | Class |
|---|---|---|
| `DATABASE_URL` | Supabase **session** pooler URL | **SECRET** |
| `INDIAN_API_KEY` | Indian API key | **SECRET** |

`APP_ENV=production`, `DATABASE_POOL_MODE=session` and `MARKET_DATA_MONTHLY_REQUEST_BUDGET=450` are set in the workflow file (PUBLIC).

## 4. Endpoint matrix

In production (`APP_ENV=production`, `ENABLE_WRITE_API` unset), `ReadOnlyApiMiddleware` answers **every** request other than GET, HEAD or OPTIONS with `403 read_only_demo` before routing and before the body is read. This also covers future write routes.

| Method | Path | Class | Production behaviour |
|---|---|---|---|
| GET | `/health` | PUBLIC READ | `{"status": "ok"}` |
| GET | `/health/db` | PUBLIC READ | `connected`, or `503` with a generic message |
| GET | `/api/v1` | PUBLIC READ | API name and version |
| GET | `/api/v1/portfolios` | PUBLIC READ | Lists every portfolio in the production database (demo data only, by policy) |
| GET | `/api/v1/portfolios/{id}` | PUBLIC READ | |
| GET | `/api/v1/portfolios/{id}/valuation` | PUBLIC READ | Stored prices only; never calls the provider |
| GET | `/api/v1/market-data/status` | PUBLIC READ | Operational counts and sync summaries; no credentials |
| POST | `/api/v1/portfolios` | PROTECTED WRITE | `403 read_only_demo` |
| POST | `/api/v1/portfolios/csv-preview` | PROTECTED WRITE (upload) | `403`; the file is never read |
| POST | `/api/v1/portfolios/csv-import` | PROTECTED WRITE (upload) | `403`; the file is never read |
| POST | `/api/v1/portfolios/{id}/holdings` | PROTECTED WRITE | `403` |
| DELETE | `/api/v1/portfolios/{id}/holdings/{holding_id}` | PROTECTED WRITE | `403` |
| Any PUT, PATCH, POST, DELETE | any path | PROTECTED WRITE | `403` |
| GET | `/docs`, `/redoc`, `/openapi.json` | Disabled | `404` |
| — | `python -m app.market_data.cli sync-listings` / `sync-prices` | INTERNAL SYNC | GitHub Actions only; not reachable over HTTP |

"Protected" means disabled on the public deployment. The operator makes writes (the demo portfolio) from their own machine, running the backend locally against the production database with `ENABLE_WRITE_API=true`. No password or admin token is added.

The frontend already shows API error messages. On the demo, the create, import and remove-holding actions display the read-only message, and the M2 service-unavailable and valuation-unavailable states are unchanged.

## 5. Rate limiting

- **Writes and uploads** (portfolio creation, holding changes, CSV) are disabled in production, so they are rejected without touching the body or the database.
- **Application-level rate limiting is not used.** Serverless instances do not share memory, so an in-process limiter would be unreliable, and Redis or a paid service is out of scope.
- **Platform control: Vercel WAF rate limiting** (Hobby: 1 rule per project, fixed window, keyed by IP, 1,000,000 allowed requests included). Configure it in the dashboard (**Firewall → Configure → New Rule**):

| Project | Condition | Limit | Action |
|---|---|---|---|
| Frontend | Request path starts with `/api/v1/` | 60 requests per 60 s per IP | Start with **Log** for a day, then **Default (429)** |
| Backend | All requests | 120 requests per 60 s per IP | **Log** first; enforce only after checking the keys |

The frontend rule sees real visitor IPs. Requests the frontend proxies to the backend may arrive at the backend from Vercel's proxy addresses, so the backend rule stays in Log mode until the Firewall view confirms it will not throttle every visitor at once. Vercel's automatic DDoS mitigation applies to both projects on all plans.

If limits are exceeded on the free plans, services are paused or throttled rather than billed.

## 6. Scheduled sync (GitHub Actions)

Workflow: [`.github/workflows/market-data-sync.yml`](../.github/workflows/market-data-sync.yml).

| Requirement | How |
|---|---|
| Weekday evening, about 21:30 IST | `cron: "0 16 * * 1-5"` (16:00 UTC; IST has no daylight saving). GitHub may start scheduled runs late under load. |
| Weekly security list | `sync-listings` runs when the scheduled run falls on a Monday in IST, or on manual request |
| Daily prices | `sync-prices` on every run |
| Secrets | `DATABASE_URL` (session pooler) and `INDIAN_API_KEY` as repository secrets; never printed. The CLI reports database errors by type only because public-repository logs are public. |
| Failure fails the workflow | CLI exit codes: 1 failed or partial, 2 configuration, 3 rate limit or budget, 4 lock held |
| No overlapping syncs | `concurrency: market-data-sync` (queued, not cancelled), plus the PostgreSQL advisory lock over the session pooler |
| Budget 450 | `MARKET_DATA_MONTHLY_REQUEST_BUDGET: "450"`, enforced before every request |
| No provider calls from pages | The API has no key and never calls the provider |
| Supply chain | Actions pinned to commit SHAs; `permissions: contents: read`; `persist-credentials: false`; only `schedule` and `workflow_dispatch` triggers, so pull requests from forks cannot reach the secrets |

Manual run options: `sync_listings` (refresh the security list first) and `dry_run` (plan without calling the provider).

**Budget:** five demo securities need about 5 requests for the first one-year backfill and then about 5 per weekday (roughly 110 per month). **The provider's 500-request limit is per key, while the 450 budget is counted per database.** Once production is live, do not run local price syncs with the same key, or set a small local budget (for example `MARKET_DATA_MONTHLY_REQUEST_BUDGET=40` in `backend/.env`).

**Inactivity:** GitHub disables scheduled workflows in a public repository after 60 days without repository activity. Re-enable it from the Actions tab if that happens; stale prices then show as STALE.

## 7. Database migrations

Always Alembic, over the **session** pooler, from the operator's machine. All migrations are additive; nothing drops or rewrites M2 data.

```bash
cd backend
read -rs DATABASE_URL && export DATABASE_URL   # paste the session pooler URL; it is not echoed
DATABASE_POOL_MODE=session uv run alembic upgrade head
uv run alembic current
uv run alembic check
unset DATABASE_URL
```

Expected: `current` shows `20260915_0003 (head)` and `check` reports no new upgrade operations. Environment variables override `backend/.env`, so the local database is not touched.

## 8. Demo data

The production database starts empty. It holds **only** a clearly named demo portfolio; no private portfolio is ever loaded into it, because `GET /api/v1/portfolios` is public.

Create it from your machine with writes enabled locally only:

```bash
cd backend
read -rs DATABASE_URL && export DATABASE_URL   # session pooler URL
ENABLE_WRITE_API=true DATABASE_POOL_MODE=session uv run uvicorn app.main:app --port 8001
```

Then, in another terminal:

```bash
curl -sS -X POST http://127.0.0.1:8001/api/v1/portfolios -H 'Content-Type: application/json' -d @demo-portfolio.json
```

`demo-portfolio.json` is written at deployment time with the approved name and holdings, for example `"DEMO – Sample NSE portfolio (illustrative)"`. Stop the local server afterwards and `unset DATABASE_URL`.

## 9. Deployment sequence

Nothing below has been run. Each step needs approval; secrets are typed only into Supabase, Vercel or GitHub prompts, never into chat.

1. **Approve** the platform choices and the open decisions (section 11).
2. ~~**Supabase:** create the Free project.~~ **Done (16 Sep 2026):** Singapore, `ap-southeast-1`.
3. ~~**Migrate** (section 7).~~ **Done (16 Sep 2026):** `20260915_0003 (head)`, no drift, row-level security verified on all six tables, database empty, and both poolers checked from the application.
4. **Demo portfolio** (section 8).
5. **Push** the commits to GitHub (approval required).
6. **GitHub secrets:** `gh secret set DATABASE_URL` and `gh secret set INDIAN_API_KEY` (each prompts for the value without echoing it).
7. **First sync:** Actions → Market data sync → Run workflow with `sync_listings: true`, `dry_run: true`; review the plan, then run again with `dry_run: false`. Expect about 5 metered requests.
8. **Backend project:** from `backend/`, run `vercel link` and create a new project in scope `lakh-datar` (for example `portfolio-intelligence-api`). Add `APP_ENV`, `DATABASE_URL` (transaction pooler), `DATABASE_POOL_MODE` and `CORS_ALLOWED_ORIGINS` for Production with `vercel env add <NAME> production`, then run `vercel deploy --prod`.
9. **Backend smoke test:**
   - `GET /health` returns `{"status":"ok"}`;
   - `GET /health/db` returns `connected`;
   - `GET /api/v1/market-data/status` shows `configured: false`, recent sync runs and no credentials;
   - `POST /api/v1/portfolios` returns `403 read_only_demo`;
   - `GET /docs` returns `404`;
   - the demo valuation returns 200 with dated NSE closes.
10. **Frontend:** from `frontend/`, run `vercel env add API_BASE_URL production` with the backend URL, then `vercel deploy --prod`.
11. **Frontend smoke test:** open the demo portfolio through the live URL: valuation, price dates, freshness and the read-only message on create, import and remove.
12. **Firewall:** add the rate-limit rules (section 5) in Log mode; enforce the frontend rule after reviewing traffic.
13. **Docs:** update the README status and live URLs.

**Rollback:** `vercel rollback` (per project), `gh workflow disable "Market data sync"`, or remove `API_BASE_URL` and redeploy the frontend to return to the M2 "service unavailable" state.

## 10. Known limitations of this deployment

- Read-only demo: visitors cannot create portfolios. There are no user accounts.
- `GET /api/v1/portfolios` lists every portfolio in the production database; safety depends on keeping only demo data there.
- Rate limits are per region and per IP; the backend rule's behaviour behind the frontend proxy must be confirmed after deploying.
- Supabase Free has no backups and pauses after a week without activity.
- Scheduled workflows can start late and are disabled after 60 days without repository activity.
- The NSE calendar must be extended for 2027.

## 11. Decisions required before deploying

1. **Backend platform:** Vercel Hobby (recommended).
2. **Demo portfolio:** its name and holdings.
3. **Push** the local commits to the public repository.
4. ~~**Supabase:** create the free project.~~ Done: Singapore (`ap-southeast-1`); Vercel functions therefore use `sin1`.
5. **Request budget split** between production (450) and local development, since both share one provider key.
6. **Backend project name** (for example `portfolio-intelligence-api`), which determines `API_BASE_URL`.
