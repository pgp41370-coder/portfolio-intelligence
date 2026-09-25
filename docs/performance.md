# Performance history and risk statistics

How the application turns stored end-of-day closes into a historical value series, risk statistics
and a benchmark comparison, and the rules it follows when the data is incomplete. Delivered in M4.1
and extended in M4.2.

- [What it computes](#what-it-computes)
- [Two bases](#two-bases)
- [Formulas](#formulas)
- [Risk measures](#risk-measures)
- [Coverage and missing data](#coverage-and-missing-data)
- [Suspected corporate actions](#suspected-corporate-actions)
- [Benchmark comparison](#benchmark-comparison)
- [Allocation and concentration](#allocation-and-concentration)
- [API](#api)
- [What is deliberately absent](#what-is-deliberately-absent)

---

## What it computes

For one portfolio, over a date window:

| Output | Meaning |
|---|---|
| Value series | Portfolio value at each fully priced NSE session |
| Daily return | Session-over-session return, only between consecutive sessions |
| Cumulative return | First valued session to last |
| Annualised volatility | Sample standard deviation of daily returns × √252 |
| Maximum drawdown | Largest peak-to-trough fall in value within the window |
| Coverage | How many expected sessions could be valued, and why the others could not |
| Excluded holdings | Holdings left out of the series, each with a reason |

Everything is derived from prices already stored by the market-data sync. The endpoint never calls
the market-data provider — a test asserts this by making any provider request raise.

## Two bases

The engine measures a portfolio on the best basis its stored data supports, and always says which:

| Basis | When | Headline return |
|---|---|---|
| `TRANSACTIONS` | The portfolio has a transaction ledger | **Time-weighted return**, chained from daily flow-adjusted returns (`TWR_DAILY_CHAINED`) |
| `CURRENT_HOLDINGS` | It has none | Price return between the window's endpoints (`PRICE_RETURN_ENDPOINTS`) |

**`CURRENT_HOLDINGS` is a reconstruction.** Holdings carry a symbol, a quantity and an average buy
price but **no acquisition date**, so the series values today's holdings at past closes. It answers
"how would the current basket have moved?", not "what was this portfolio worth?". The UI labels that
card **Reconstructed**.

**`TRANSACTIONS` is a record.** The position on each session comes from the ledger, so the series is
what the portfolio was actually worth, and returns are time-weighted. The UI labels it
**Transaction-aware**. The ledger, its rules and the TWR methodology are documented in
[docs/transactions.md](transactions.md).

Where the two disagree — a ledger whose closing position differs from the holdings on record — the
response reports a `reconciliation` block naming each difference. Neither source is changed
automatically: the series follows the ledger, valuation follows the holdings.

## Formulas

Let `S = [s₀, s₁, …, s_T]` be the sessions that could be fully valued, in date order.

**Portfolio value**

```
V_t = Σ_h (quantity_h × close_{h,t})
```

Summed over every holding that has a close on session `t`, in exact `Decimal` arithmetic.

**Daily return** — computed only when `s_t` and `s_{t-1}` are *consecutive expected sessions*:

```
R_t = V_t / V_{t-1} − 1
```

If any expected session between them could not be valued, the pair is skipped and counted in
`returns_skipped_across_gaps`.

**Cumulative return** — endpoints only, so an interior gap does not invalidate it:

```
cumulative = V_T / V_0 − 1
```

**Annualised volatility** — sample standard deviation (n−1) of the daily returns actually used:

```
σ_annual = stdev(R) × √252
```

Withheld, with a note, when fewer than **20** daily returns are available; a standard deviation over
a handful of observations is noise presented as a statistic.

**Maximum drawdown** — over the valued series:

```
peak_t = max(V_0 … V_t)
MDD = min_t (V_t / peak_t − 1)
```

Reported as a non-positive percentage.

**Sharpe ratio** is computed **only** when a risk-free rate is configured through
`RISK_FREE_RATE_PCT`. It is unset by default, and the response then says so rather than assuming a
rate (6%? the 91-day T-bill? zero?) and manufacturing precision.

Under the transaction basis, `R_t` is the flow-adjusted return and the statistics are taken from a
**growth index** built by chaining those returns, never from raw portfolio value — otherwise a
withdrawal would register as a drawdown. See [docs/transactions.md](transactions.md).

Percentages are serialized as 2-decimal strings, money as 2-decimal strings, `ROUND_HALF_UP`.

## Risk measures

Each measure states its minimum data requirement and is withheld, with the reason, when the data
does not meet it. None of them is estimated, and none is shown as zero when it is unknown.

| Measure | Definition | Needs |
|---|---|---|
| Annualised volatility | sample stdev of daily returns × √252 | ≥ 20 daily returns |
| Downside volatility | √(Σ squared returns below 0 ÷ all observations) × √252 | ≥ 20 returns, ≥ 5 below the threshold |
| Maximum drawdown | worst peak-to-trough fall of the growth index | ≥ 2 valued sessions |
| Beta | cov(portfolio, benchmark) ÷ var(benchmark) on paired daily returns | ≥ 20 **paired** returns |
| Tracking error | annualised stdev of the daily return difference | ≥ 20 paired returns |
| Information ratio | excess cumulative return ÷ tracking error | both of the above |
| Sharpe ratio | (annualised return − risk-free rate) ÷ volatility | a configured risk-free rate |

"Paired" means both series priced the same session. A day either side missed produces no pair; it is
never filled in.

## Coverage and missing data

The expected sessions come from the configured NSE trading calendar, not from whatever happens to be
in the database. A session is valued **only if every priceable holding has a close for it**.

The alternative — valuing the holdings that do have prices — would produce a value series that
silently changes composition, showing a "drop" that is really a missing security. That is the single
most misleading failure mode available here, so it is not done.

Rules, all enforced in code and tested:

- Missing prices are never interpolated.
- A missing price is never treated as ₹0.
- A price is never carried forward from an earlier session.
- Returns are never computed across a gap.

`coverage.status` is one of:

| Status | Meaning |
|---|---|
| `complete` | Every expected session in the window was fully priced |
| `partial` | Some sessions could not be valued; they are listed and counted |
| `insufficient` | Fewer than two valued sessions — no return can be measured |

Coverage is about the window that was measured; **staleness is reported separately**. The window
always ends at the newest stored close, so a portfolio whose prices are a week old reports complete
coverage of what it could measure, plus `sessions_behind_latest` naming how far behind the latest
completed NSE session that leaves it. Both bases do this identically.

Missing sessions are reported in two kinds, because they mean different things:

- **`missing_no_prices_at_all_count`** — no holding had a close. Usually the exchange was closed on a
  day the configured calendar does not list; it can also mean a sync that failed for every security.
  The two cannot be told apart from stored prices alone, so the response describes both readings
  rather than asserting one.
- **`missing_some_prices_count`** — some holdings were priced and others were not: a genuine
  per-security gap.

A holding is excluded from the series entirely, with a reason, when it is not in the security master
(`LISTING_NOT_FOUND`), has no NSE listing (`NO_NSE_LISTING`, e.g. BSE-only securities), or has no
stored prices at all (`NO_PRICE_DATA`). Excluded holdings are named in the response and shown in the
UI — they are not silently dropped.

The window starts, by default, at the latest first-available date across the holdings, so the series
begins where every holding has history rather than showing a basket that grows a member partway
through.

### Trading-calendar coverage

The 2025 holidays that M4.1 mis-reported as data gaps are now configured, and a one-year window over
the development data reads `complete`. The calendar also states the range it is known to be complete
for (`complete_from` / `complete_to`, currently 15 Sep 2025 to 31 Dec 2026). A window reaching
outside that range is flagged in `coverage.note` rather than silently assuming every weekday outside
it was a trading session.

NSE publishes only the current calendar year on its holidays page: no 2025 archive and no 2027 list
were available when this was written. Rather than invent dates, the application names the boundary of
what it knows.

## Suspected corporate actions

A split, a bonus issue or a consolidation changes the share count and the price together. The
provider reports the price; nothing reports the share change to this application. So a 1-for-2
split arrives as a 50% overnight fall, and every figure built on that series — daily return,
contribution, drawdown, cost basis, time- and money-weighted return — silently becomes wrong for
that security.

The valuation card has always warned when the **latest** two closes move like that. Nothing
looked at the rest of the window, which is what the analytics are actually built from. Now the
whole window is scanned.

**A move is flagged when either:**

| Trigger | Rule |
|---|---|
| `large_move` | The move is at least 35% — the project's existing large-move threshold, shared with the valuation card so the two cannot drift apart |
| `corporate_action_ratio` | The move is at least 20% **and** lands within 2% of a ratio a corporate action would produce |

The second rule exists because a 1:2 bonus issue moves the price by a third — under the generic
threshold, and just as damaging. Recognised ratios cover 1-for-2 through 1-for-10 splits, 1:1 to
1:3 bonus issues, and 2-for-1 to 10-for-1 consolidations.

**It discloses; it never adjusts.** Correcting a split needs the ratio and the effective date from
a corporate-action feed this application does not have, and guessing them would silently rewrite
the user's history. So the figures stay exactly as measured, and the response says which ones may
be wrong and why. A test asserts that a 1-for-2 split still reports a −50% return, because the
alternative is a number nobody can check.

`consistent_with` is arithmetic, not a claim: a fall of almost exactly one half is what a 1-for-2
split produces, and saying so helps a reader tell a corporate action from a crash. The response
states in words that it is unconfirmed, and an explanation resting on a flagged price is marked
`limited` rather than `available`.

**Limits.** A genuine 50% crash and a 1-for-2 split are indistinguishable from price data alone,
so a real crash will be flagged. A corporate action smaller than 20% is not detected at all. The
scan reads the closes the valuation already loaded, so it costs no extra query.

## Benchmark comparison

**The benchmark is an index ETF used as a proxy, and the application never calls it the index.**

The market-data provider documents a `/historical_data` endpoint for equities and no index endpoint:
there is no NIFTY 50 series to fetch. Rather than invent one or scrape an unvetted source, a
benchmark here is an ordinary listed security whose closes flow through the existing sync.

The registered benchmark is **`NIFTY50` → SETFNIF50 (SBI ETF Nifty 50)**. It was chosen because it is
what this architecture can actually price: it appears in the provider's security master *with an NSE
symbol*, so the NSE-only price pipeline can fetch it. Several other NIFTY 50 ETFs — NIFTYBEES among
them — appear in the master with a BSE code and no NSE symbol, and cannot be priced at all.

What the proxy is not, stated in the API response and on screen wherever it appears:

- an ETF's market price can trade at a premium or discount to net asset value;
- it bears a total expense ratio, so it drifts below its index over time;
- its NAV reinvests dividends while a price index does not, which pushes the other way;
- a thin day's close is the fund's close, not the index's.

**No adjustment is applied to make the ETF look like the index.** `basis` is `ETF_PROXY`, `is_proxy`
is `true`, and the note spells this out.

Mechanics:

- The benchmark series is rebased to 100 at the first session both it and the portfolio priced, so
  the two are comparable on one axis.
- Only shared sessions are compared; `sessions_compared` reports how many. A day either series missed
  yields no return and no point — never an interpolated one.
- Benchmark securities are included in the price sync automatically, so a comparison is not drawn
  against a stale index.
- Statuses are `available`, `not_requested`, `not_configured`, `unknown_key` and `no_data`. A
  benchmark that is registered but not yet synced returns `no_data` with an explanation, never an
  estimated series.

## Allocation and concentration

`GET /api/v1/portfolios/{id}/allocation` reports position weights at the latest stored closes, taken
from the same valuation the rest of the application uses, so the two can never disagree.

- Weights are shares of the **priced** total. An unpriced holding is listed separately and given no
  weight: a position of unknown value cannot be sized, and calling it zero would understate
  concentration exactly when concentration matters.
- Concentration reports the largest position, the top 3 and top 5 shares, the Herfindahl-Hirschman
  Index on the 0–10,000 scale, and its reciprocal form — the number of equally sized positions the
  portfolio behaves like.
- **Sector allocation is unavailable.** The security master carries a name, an NSE symbol, a BSE code
  and an ISIN, and no sector classification. The field is present and reports itself unavailable so a
  real classification source can be added later; guessing a sector from a company name would be
  fabrication.

## API

```
GET /api/v1/portfolios/{portfolio_id}/performance?start_date=&end_date=&benchmark=
GET /api/v1/portfolios/{portfolio_id}/allocation
GET /api/v1/portfolios/{portfolio_id}/pnl
GET /api/v1/portfolios/{portfolio_id}/timeline
GET /api/v1/portfolios/{portfolio_id}/attribution?start_date=&end_date=&benchmark=
GET /api/v1/benchmarks
GET /api/v1/portfolios/{portfolio_id}/transactions
```

`pnl`, `timeline` and `attribution` need a transaction ledger and report themselves unavailable
without one; their methodology is in [docs/transactions.md](transactions.md).

Both are read-only and add no write surface; production write protection is unchanged. Invalid
windows (`start_date` after `end_date`) return `422 invalid_date_range`.

Response (abridged):

```json
{
  "portfolio_id": "…",
  "currency": "INR",
  "history_basis": "CURRENT_HOLDINGS",
  "period": {"start": "2025-09-15", "end": "2026-09-15"},
  "coverage": {
    "status": "partial",
    "sessions_expected": 252, "sessions_available": 248,
    "missing_sessions": ["2025-10-02", "2025-10-22", "2025-11-05", "2025-12-25"],
    "missing_session_count": 4,
    "missing_no_prices_at_all_count": 4,
    "missing_some_prices_count": 0,
    "coverage_pct": "98.41",
    "note": "Sessions without a complete set of closes are excluded; returns are not linked across them. …"
  },
  "summary": {
    "start_value": "71449.50", "end_value": "55370.50",
    "cumulative_return_pct": "-22.50", "volatility_pct": "17.22", "max_drawdown_pct": "-28.22",
    "returns_used": 243, "returns_skipped_across_gaps": 4, "volatility_note": null
  },
  "series": [{"trade_date": "2025-09-15", "value": "71449.50", "daily_return_pct": null, "cumulative_return_pct": "0.00"}],
  "benchmark": {"status": "not_configured", "key": null, "display_name": null, "note": "…", "series": []},
  "excluded_holdings": [],
  "methodology": {"note": "…", "sharpe_note": "Deferred: no risk-free rate is configured…"}
}
```

## What is deliberately absent

| Not implemented | Why |
|---|---|
| Money-weighted return (IRR / XIRR) | Needs an iterative solver and a product decision about which figure headlines |
| Sortino ratio | Not implemented; downside volatility, its input, is |
| Benchmark attribution (allocation vs selection) | Needs the benchmark's own constituent weights, which an ETF price series does not provide |
| Alpha | Needs a risk-free rate as well as a benchmark |
| Sector allocation | The security master carries no sector classification |
| Dividends and total return | No corporate-action data |
| Corporate-action adjustment | Closes are used as the provider reports them; a split shows as a price move |
| Intraday or real-time series | Only completed-session end-of-day closes are stored |
