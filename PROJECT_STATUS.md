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
Production backend + first real price sync ✅ (delivered in 3A.1 and 3P)
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
Production deployment                     ✅  delivered in 3P (write protection and rate limiting in place)
```

```
MILESTONE 3P: PRODUCTION DEPLOYMENT (deployed)

Read-only public API (production)         ✅  every non-GET request -> 403 before the body is read
Production CORS / docs                    ✅  explicit https origins only; /docs disabled
Supabase transaction pooler support       ✅  NullPool, prepared statements disabled
Sync + migrations need session pooler     ✅  enforced
Row-level security on all tables          ✅  migration 20260915_0003
Vercel backend config                     ✅  sin1, .vercelignore keeps .env out of uploads
GitHub Actions scheduled sync             ✅  workflow on main; repository secrets configured
Rate limiting                             ✅  Vercel Firewall rules live in LOG-only mode
Supabase project + real migration         ✅  16 Sep 2026: Singapore, head 20260915_0003, RLS verified, no drift
Demo portfolio                            ✅  created and valued from synced prices
Deployment                                ✅  frontend and backend serving in production
```

```
MILESTONE 4.1: PERFORMANCE HISTORY (local only - NOT deployed)

Historical value series                  ✅  today's holdings at past NSE closes (labelled a reconstruction)
Daily + cumulative return                ✅  returns never linked across an unpriced session
Annualised volatility                    ✅  sample stdev x sqrt(252); withheld below 20 observations
Maximum drawdown                         ✅
Coverage reporting                       ✅  expected vs available sessions; missing sessions listed and classified
Missing-data handling                    ✅  no interpolation, no zero substitution, no carry-forward
Performance API (read-only)              ✅  GET /portfolios/{id}/performance, GET /benchmarks
Performance UI section                   ✅  chart, metrics, coverage notice on the existing portfolio page
Benchmark comparison                     🔜  interface built, registry empty - provider exposes no index endpoint
Sharpe ratio                             🔭  deferred: no risk-free rate configured
Time-weighted return                     🔭  needs the M4.2 transaction ledger

Status: implemented and tested locally. Not committed, not pushed, not deployed.
```

```
MILESTONE 4.2: TRANSACTION-AWARE ANALYTICS (local only - NOT deployed)

Transaction ledger                       ✅  dated BUY/SELL with quantity, price, fees, reference
Migration 20260924_0004                  ✅  additive; upgrade/downgrade tested; RLS enabled
Ledger validation                        ✅  no overselling, no future trade dates, non-session dates recognised next session
Portfolio state engine                   ✅  position and cash flow per session, partial sells, zero positions
Time-weighted return                     ✅  daily flow-adjusted returns chained; statistics from a growth index
Reconciliation vs holdings               ✅  differences reported, neither source overwritten
Benchmark proxy (NIFTY 50)               ✅  SETFNIF50 ETF synced (1 request, 247 closes); labelled ETF_PROXY
Risk measures                            ✅  downside volatility, beta, tracking error, information ratio
Sharpe ratio                             ✅  computed only when RISK_FREE_RATE_PCT is configured; unset by default
Allocation + concentration               ✅  weights, top 1/3/5, HHI, effective holdings
Sector allocation                        🔜  no classification data exists; abstraction reserved, nothing invented
Trading calendar 2025                    ✅  four holidays added; calendar now states the range it covers
Trading calendar 2027                    🔭  NSE publishes the current year only; no 2027 list exists yet
Transaction entry in the UI              🔜  API accepts transactions; no form yet
Money-weighted return (IRR)              🔭  deferred

Status: implemented and tested locally. Not committed, not pushed, not deployed.
```

```
MILESTONE 4.3: TRANSACTION INTELLIGENCE (local only - NOT deployed)

Transaction entry form                   ✅  type, security, date, quantity, price, fees, reference
Live gross value + cash movement         ✅  shown while typing, restated on a review step
Client-side validation                   ✅  mirrors the API; sells checked against the ledger position
Duplicate-submission guard               ✅  a double click cannot post the same trade twice
Transaction history                      ✅  newest first; filters by type, security and date range
Mobile history layout                    ✅  table on wide screens, cards below 640px
Transaction CSV import                   ✅  upload -> validate -> preview -> confirm -> import
Row-level CSV errors                     ✅  every problem at once, with row and column
Atomic import                            ✅  any blocking error imports nothing
Reconciliation                           ✅  RECONCILED / RECONCILIATION REQUIRED, neither source overwritten
Realised + unrealised P&L                ✅  FIFO cost basis; fees allocated pro rata
Contributions / withdrawals view         ✅  capital shown apart from the gain or loss on it
Portfolio timeline                       ✅  transaction -> position change -> value -> return
Return attribution                       ✅  per-security contributions that sum to the daily return
Intelligence foundation                  ✅  deterministic contributor data, latest-session movers, stale positions
Editing a transaction in place           🔜  remove and re-add for now
Money-weighted return (IRR)              🔭  deferred
Tax-lot reporting                        🔭  holding-period rules are a separate problem

Status: implemented and tested locally. Not committed, not pushed, not deployed.
```

```
MILESTONE 5: DETERMINISTIC PORTFOLIO INTELLIGENCE (local only - NOT deployed)

Single read-only endpoint                ✅  GET /portfolios/{id}/intelligence
Return explanation                       ✅  drivers ranked, contributions reconcile to the measured return
Benchmark explanation                    ✅  ETF proxy labelled as a proxy; unavailable is explained, never faked
Cash-flow context                        ✅  value change vs net flow vs time-weighted return
Risk context                             ✅  volatility, max and current drawdown, gaining/losing sessions, concentration
Data-quality disclosure                  ✅  coverage, staleness, benchmark status, reconciliation, limitations first
Attribution on the holdings basis        ✅  a portfolio with no ledger can now be explained too
Template sentences only                  ✅  no free-form text; a test forbids advice and forecast vocabulary
Frontend intelligence card               ✅  headline, drivers, contexts, data quality
LLM / natural-language layer             🔭  deliberately not built; the facts are the source of truth

Status: implemented and tested locally. Not committed, not pushed, not deployed.
```

```
MILESTONE 5.1: INTELLIGENCE ENGINE HARDENING (local only - NOT deployed)

Shared PerformanceContext                ✅  portfolio + ledger + one valuation pass, nothing more
Single valuation per request             ✅  2 passes -> 1; both bases now use one implementation
Duplicate holdings valuation removed     ✅  the M4.1 loop and its helpers deleted, not copied
N+1 price query removed                  ✅  holdings prices fetched in one query, not one per listing
Golden tests                             ✅  every published figure pinned, values derived independently
Invariant tests                          ✅  identities asserted; non-identities asserted as disclosed
Explanation trace                        ✅  ?trace=true returns metric -> source -> inputs -> formula
Wording review                           ✅  no causation, prediction or index/proxy conflation
UI: price return vs contribution         ✅  named separately, with one line on why they differ
Numerical output                         ✅  identical to M5, re-verified against raw SQL

Status: implemented and tested locally. Not committed, not pushed, not deployed.
```

```
MILESTONE 6.1: MONEY-WEIGHTED RETURN (local only - NOT deployed)

XIRR solver                              ✅  actual/365, Decimal, bisection, bounded search
Period + annualised figures              ✅  both published and labelled separately
Solved in period terms                   ✅  keeps short windows solvable; same roots
Ambiguous roots withheld                 ✅  ambiguous_multiple_roots, never a chosen root
No-solution / insufficient history       ✅  explicit statuses with reasons
Annualisation withheld below 90 days     ✅  period figure still published, reason attached
Sub-window opening position              ✅  valued at market, with an explicit disclosure
Reuses PerformanceContext                ✅  no extra valuation pass, no extra query
TWR unchanged                            ✅  golden values and invariants all still pass
Intelligence + UI                        ✅  both returns shown side by side, neither ranked

Status: implemented and tested locally. Not committed, not pushed, not deployed.
```

```
MILESTONE 6.2: CORPORATE-ACTION DISCLOSURE (local only - NOT deployed)

Whole-window price scan                  ✅  every held security, every session pair in the window
Generic large-move trigger               ✅  35%, the threshold the valuation card already uses
Corporate-action ratio trigger           ✅  >=20% and within 2% of a split/bonus/consolidation ratio
Ratio hypothesis                         ✅  arithmetic only, explicitly unconfirmed
Consequence stated                       ✅  names the figures that become unreliable
Never adjusts                            ✅  a 1-for-2 split still reports -50%; a test asserts it
Intelligence + UI disclosure             ✅  leads the data-quality section; status drops to "limited"
No extra query or valuation pass         ✅  reads closes the valuation already loaded

Status: implemented and tested locally. Not committed, not pushed, not deployed.
```

## Milestone 6.2 details

| Item | Result |
|---|---|
| Completed | 25 September 2026 (local working tree) |
| Migration | None |
| New endpoints | None. `price_anomalies` added to the performance response and the intelligence data-quality block |
| Gap closed | `app/valuation/service.py` warned on the latest two closes only; the analytics are built from the whole window, which nothing scanned |
| Backend tests | 619 passed with PostgreSQL (367 passed, 252 skipped without `TEST_DATABASE_URL`); baseline before M6.2 was 587 |
| Frontend checks | 44 unit tests pass; ESLint clean; TypeScript clean; production build succeeds |
| Real-data validation | The development history contains no qualifying move - largest single-session change is 8.39% - and the detector correctly reports zero. A close was then temporarily halved to confirm the disclosure renders, and the database restored to its exact prior value |
| Performance | SQL and valuation passes unchanged (7/11 and 1). Intelligence median 40 ms -> 44 ms after short-circuiting the ratio test below the 20% floor |

## Milestone 6.1 details

| Item | Result |
|---|---|
| Completed | 25 September 2026 (local working tree) |
| Migration | None |
| New endpoints | None. The existing performance and intelligence responses gained a `money_weighted` block |
| Method | XIRR, actual/365, `Decimal` bisection; float scan locates brackets, `Decimal` confirms and solves them |
| Backend tests | 587 passed with PostgreSQL (344 passed, 243 skipped without `TEST_DATABASE_URL`); baseline before M6.1 was 551 |
| Frontend checks | 43 unit tests pass; ESLint clean; TypeScript clean; production build succeeds |
| Real-data validation | Independent XIRR from raw SQL matched the API exactly: period -28.91%, annualised -30.02%, 349 days, contributions 105,156.00, withdrawals 84,089.70, terminal 73,161.10 |
| Interpretation | TWR -19.69% against MWR -28.91% over the same window: money was added before further falls, so the investor's return was 9.23 points worse than the portfolio's |
| Performance | SQL and valuation passes unchanged (11 and 1 for the ledger basis); intelligence median 30 ms -> 40 ms, the difference being the root solve |

## Milestone 5.1 details

| Item | Result |
|---|---|
| Completed | 25 September 2026 (local working tree) |
| Migration | None |
| Valuation passes per request | 2 -> 1 (transaction basis); the holdings basis also consolidated onto the same implementation |
| SQL statements per request | 15 -> 11 (transaction basis), 13 -> 9 (holdings basis) |
| Median latency | 45 ms -> 30 ms (transaction), 37 ms -> 29 ms (holdings), local dev database |
| Backend tests | 551 passed with PostgreSQL (319 passed, 232 skipped without `TEST_DATABASE_URL`); baseline before M5.1 was 524 |
| Frontend checks | 37 unit tests pass; ESLint clean; TypeScript clean; production build succeeds |
| Real-data validation | All 13 metrics re-checked against an independent SQL recomputation after the refactor: TWR, benchmark, relative, contribution sum, per-security contributions, drawdowns, start and end value, net flow, sessions - every one identical to M5 |
| Code removed | `_Priced`, `_resolve_listings`, `_excluded` and the duplicated holdings valuation loop |

## Milestone 5 details

| Item | Result |
|---|---|
| Completed | 25 September 2026 (local working tree) |
| Migration | None. M5 adds no tables or columns; it composes existing measurements |
| Backend tests | 524 passed with PostgreSQL (319 passed, 205 skipped without `TEST_DATABASE_URL`); baseline before M5 was 498 |
| Frontend checks | 36 unit tests pass; ESLint clean; TypeScript clean; production build succeeds |
| Provider requests | None |
| External services | None. No LLM, no paid API, no network call of any kind in this layer |
| Real-data validation | Contributions recomputed from raw SQL matched the API exactly: RELIANCE +4.80, HDFCBANK -13.04, TCS -12.10, summing to -20.34 percentage points against a compounded TWR of -19.69% |
| Notable finding | RELIANCE's price fell 9.75% over the window yet contributed +4.80 points, because contributions are weighed by the portfolio's size each day and the portfolio grew from about 27k to 73k. The response explains this rather than leaving it to look like an error |
| Browser verification | Both bases exercised against the local API - transaction ledger and holdings-only - with no console errors and no horizontal overflow at 375px |

## Milestone 4.3 details

| Item | Result |
|---|---|
| Completed | 25 September 2026 (local working tree) |
| Migration | None. M4.3 adds no tables or columns; the M4.2 ledger already carried what it needed |
| Cost basis | FIFO, the basis Indian income-tax law applies to listed equity shares |
| Backend tests | 498 passed with PostgreSQL (319 passed, 179 skipped without `TEST_DATABASE_URL`); baseline before M4.3 was 452 |
| Frontend checks | 30 unit tests pass; ESLint clean; TypeScript clean; production build succeeds |
| Provider requests | None |
| Real-data validation | FIFO P&L on the dev ledger checked by hand: RELIANCE cost basis ₹16,439.40, realised -₹31.00, contributions ₹1,05,156.00 less withdrawals ₹10,928.60 = ₹94,227.40 net, matching the independently computed TWR cash flow |
| Attribution check | Per-security contributions summed to -20.34%, exactly the sum of daily returns, against a compounded TWR of -19.69%; the 0.66pp difference is reported, not hidden |
| Browser verification | Entry, review, save, delete, CSV preview (valid and invalid) and reconciliation all exercised against the local API; no console errors; no horizontal overflow at 375px |

## Milestone 4.2 details

| Item | Result |
|---|---|
| Completed | 24 September 2026 (local working tree) |
| Migration | `20260924_0004` adds `transactions`; additive, downgrade and re-upgrade verified, RLS enabled |
| Backend tests | 452 passed with PostgreSQL (295 passed, 157 skipped without `TEST_DATABASE_URL`); baseline before M4.2 was 400 |
| Frontend checks | 19 unit tests pass; ESLint clean; TypeScript clean; production build succeeds |
| Provider requests | 1 - the benchmark ETF backfill (SETFNIF50, 247 closes). Budget 6 of 450 used this month |
| Real-data validation | Transaction portfolio recomputed from raw SQL: 236 sessions, TWR -19.69%, volatility 18.36%, max drawdown -31.64%, net flow ₹94,227.40 - every figure matched the API exactly |
| Benchmark validation | Portfolio -19.69% vs NIFTY 50 proxy -5.74%, beta 1.06, tracking error 12.69%, information ratio -1.10 |
| Calendar fix verified | The M4.1 window that read "partial, 4 missing" now reads complete 248/248, and volatility corrects from 17.22% to 17.13% |

## Milestone 4.1 details

| Item | Result |
|---|---|
| Completed | 24 September 2026 (local working tree) |
| Migration | None. Holdings carry no dates, so history is reconstructed from existing tables |
| Basis | `CURRENT_HOLDINGS` - today's holdings valued at past closes, labelled as such in API and UI |
| Backend tests | 400 passed with PostgreSQL (275 passed, 125 skipped without `TEST_DATABASE_URL`); baseline before M4.1 was 360 |
| Frontend checks | 14 unit tests pass; ESLint clean; TypeScript clean; production build succeeds |
| Real-data verification | Dev database, 3-holding portfolio: 248 of 252 sessions priced, cumulative -22.50%, volatility 17.22%, max drawdown -28.22%, 243 returns used, 4 skipped across gaps. Single-holding portfolio independently recomputed from raw SQL: -25.90%, 21.62%, -31.94% - all matched |
| Provider requests | None. The performance endpoint reads stored prices only, asserted by test |

## Milestone 3A details

| Item | Result |
|---|---|
| Completed | 15 September 2026 (local) |
| Migration | `20260915_0002` adds `listings`, `daily_prices`, `market_data_sync_runs`; M2 tables unchanged |
| Methodology | Latest dated NSE end-of-day close; Decimal arithmetic; 2-dp ROUND_HALF_UP on output; VALUED / STALE / UNPRICED |
| Backend tests | 290 passed with PostgreSQL (202 run and 88 skip without `TEST_DATABASE_URL`) |
| Frontend checks | ESLint clean; TypeScript clean; 8 valuation display unit tests pass; production build succeeds |
| Manual testing | Valuation verified in the browser with fixture prices: fresh, stale, BSE via NSE, BSE-only, no data, unknown symbol, large move, partial totals, valuation failure fallback; no horizontal overflow at 375 px |

## Milestone 3P details

| Item | Result |
|---|---|
| Deployed | 16 September 2026, from commit `90cbf69865d7626ec2eb8d41a6bc06239aae2460` |
| Application | https://portfolio-intelligence-bice.vercel.app (deployment `jrreby823`) |
| API | https://portfolio-intelligence-api.vercel.app (deployment `grz4d3nis`) |
| Database | Supabase production PostgreSQL connected; NSE EOD market data synchronized |
| Valuation | Working end to end in production from synced prices |
| Public API | Read-only; API documentation endpoints disabled; CORS restricted to the production frontend |
| Row-level security | Enabled on all tables |
| Rate limiting | Vercel Firewall rules live in LOG-only mode (logging, not blocking) |
| Scheduled sync | GitHub Actions market-data synchronization configured |

## Known limitations

- **Performance history is a reconstruction.** No transaction history is stored, so the series shows how the current holdings would have moved, not what was actually held. Time-weighted return is not available.
- **The benchmark is an ETF proxy, not the index.** The provider exposes no index endpoint, so NIFTY 50 is tracked through SETFNIF50; it carries an expense ratio and can trade away from net asset value. Labelled `ETF_PROXY` everywhere.
- **Trading calendar is known complete from 15 Sep 2025 to 31 Dec 2026** and says so when a window reaches outside that range. NSE publishes the current year only, so no 2025 archive or 2027 list was available.
- **Transactions can be added and removed but not edited in place.** Remove and re-add instead: an edit that changes a quantity has to re-validate every later sale.
- **Profit uses a FIFO cost basis** and is a price P&L: it excludes dividends and is not adjusted for corporate actions.
- **Suspected corporate actions are disclosed, never corrected.** A genuine crash and a split are indistinguishable from price data alone, so a real crash will be flagged; an action smaller than 20% is not detected at all.
- **The money-weighted return is withheld when ambiguous.** Several rates can satisfy one cash-flow series; the response reports that rather than choosing one. Annualisation is withheld below 90 days, and a sub-window discloses that pre-window costs are not attributed to it.
- **The intelligence layer is deterministic and gives no advice.** It renders measured numbers into template sentences; it contains no model, makes no forecast, and rates no security.
- **Sector allocation is unavailable** — the security master carries no sector classification.
- **Real provider validated locally (M3A.1).** Adjustment methodology could not be independently established from the provider response/documentation.
- **The public deployment is read-only.** Visitors cannot create or import portfolios; write endpoints are disabled in production.
- BSE-only securities are unpriced; ISIN is not populated; the NSE trading calendar must be updated each year.
- Not adjusted for corporate actions; not a total return; not real-time.
- No user accounts: this is a demonstration MVP.
