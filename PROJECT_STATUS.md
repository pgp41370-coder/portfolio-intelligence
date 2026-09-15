# Project Status

```
PROJECT: Portfolio Intelligence

MILESTONE 1: LIVE APPLICATION SKELETON

Environment        ✅
Frontend           ✅
Backend            ✅
Database config    ✅
Tests              ✅
Git                ✅
GitHub             ✅
Vercel             ✅
Live URL           https://portfolio-intelligence-bice.vercel.app
```

```
MILESTONE 2: PORTFOLIO INPUT + DATA MODEL

Portfolio data model       ✅
Database migration         ✅
Portfolio API              ✅
Manual entry               ✅
CSV upload                 ✅
Validation                 ✅
Portfolio display          ✅
Tests                      ✅
Security review            ✅
Production build           ✅
```

```
MILESTONE 3A: MARKET DATA + PORTFOLIO VALUATION

Provider abstraction                 ✅
Indian API adapter + validation      ✅  (verified against documented formats and fixtures)
Security master                      ✅  (real provider list loaded locally: 5,540 securities)
daily_prices + sync run tracking     ✅
NSE EOD price ingestion              ✅  (validated with real provider data in M3A.1)
Rate limits + request budget         ✅
Freshness rules                      ✅
Valuation engine (Decimal)           ✅
Valuation + status API               ✅
Valuation UI                         ✅
Tests                                ✅
Security audit                       ✅
Documentation                        ✅

NEXT MILESTONE:
Production backend + first real price sync (not started)
```

```
MILESTONE 3A.1: REAL PROVIDER VALIDATION + HARDENING

Real provider validation (5 NSE symbols)  ✅  latest closes matched NSE official figures to the paisa
1yr history granularity                   ✅  daily (248 points per symbol)
Real-data end-to-end valuation            ✅  API and UI, independently recalculated
HTTP status handling                      ✅  401/403 auth, 400 context-dependent, 422 validation, 429 rate limit
Stop after repeated rejections            ✅
2026 NSE trading calendar                 ✅  16 holidays + Sunday 1 Feb 2026 special session
Completed-session-only price storage      ✅
Displayed weights sum to 100.00%          ✅
Production deployment                     ⛔  not started (write protection + rate limiting required first)
```

```
MILESTONE 3P: PRODUCTION DEPLOYMENT PREPARATION (prepared, not deployed)

Read-only public API (production)         ✅  every non-GET request -> 403 before the body is read
Production CORS / docs                    ✅  explicit https origins only; /docs disabled
Supabase transaction pooler support       ✅  NullPool, prepared statements disabled
Sync + migrations need session pooler     ✅  enforced
Row-level security on all tables          ✅  migration 20260915_0003
Vercel backend config                     ✅  sin1, .vercelignore keeps .env out of uploads
GitHub Actions scheduled sync             ✅  workflow file prepared, not yet on GitHub
Rate limiting                             ✅  plan: Vercel WAF rules (dashboard, at deploy time)
Supabase project + real migration         ✅  16 Sep 2026: Singapore, head 20260915_0003, RLS verified, no drift
Demo portfolio                            ⛔  awaiting approval
Deployment                                ⛔  awaiting approval
```

## Milestone 3A details

| Item | Result |
|---|---|
| Completed | 15 September 2026 (local) |
| Migration | `20260915_0002` adds `listings`, `daily_prices`, `market_data_sync_runs`; M2 tables unchanged |
| Methodology | Latest dated NSE end-of-day close; Decimal arithmetic; 2-dp ROUND_HALF_UP on output; VALUED / STALE / UNPRICED |
| Backend tests | 290 passed with PostgreSQL (202 run and 88 skip without `TEST_DATABASE_URL`) |
| Frontend checks | ESLint clean; TypeScript clean; 8 valuation display unit tests pass; production build succeeds |
| Manual testing | Valuation verified in the browser with fixture prices: fresh, stale, BSE via NSE, BSE-only, no data, unknown symbol, large move, partial totals, valuation failure fallback; no horizontal overflow at 375 px |

## Known limitations

- **Real provider validated locally (M3A.1).** Adjustment methodology could not be independently established from the provider response/documentation.
- **Production has no backend or database.** Valuation works locally only.
- BSE-only securities are unpriced; ISIN is not populated; the NSE trading calendar must be updated each year.
- Not adjusted for corporate actions; not a total return; not real-time.
- No user accounts: this is a demonstration MVP.
