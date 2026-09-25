# Transaction ledger and time-weighted return

The ledger, how transactions get into it, and everything measured from them: time-weighted
return, FIFO cost basis, profit, the timeline and per-security attribution. Designed in M4.2 and
completed as a user-facing workflow in M4.3. Companion to
[docs/performance.md](performance.md), which covers the M4.1 reconstruction basis.

- [Why a ledger](#why-a-ledger)
- [The model](#the-model)
- [Decisions and their reasons](#decisions-and-their-reasons)
- [Relationship to holdings](#relationship-to-holdings)
- [Entering transactions](#entering-transactions)
- [CSV import](#csv-import)
- [Portfolio state engine](#portfolio-state-engine)
- [Time-weighted return](#time-weighted-return)
- [Money-weighted return](#money-weighted-return)
- [Cost basis and profit](#cost-basis-and-profit)
- [Timeline and attribution](#timeline-and-attribution)
- [What is still not supported](#what-is-still-not-supported)

---

## Why a ledger

M4.1 can only value **today's** holdings at past closes, because a holding records a symbol, a
quantity and an average buy price — no dates. That reconstruction is labelled honestly, but it
cannot answer "what was this portfolio actually worth in March?" and it cannot produce a correct
return when money was added or removed.

A normalized transaction ledger is preferred over adding more columns to `holdings`: dated events
are naturally many-per-security, and squeezing them into a position row (a `first_bought_at`, a
`lots` JSON blob) would encode the same data less precisely and make partial sells unrepresentable.

## The model

```
transactions
  id              uuid        primary key
  portfolio_id    uuid        -> portfolios(id) ON DELETE CASCADE
  symbol          varchar(20) same normalisation as holdings
  exchange        varchar(3)  NSE | BSE
  kind            varchar(8)  BUY | SELL
  trade_date      date
  quantity        bigint      > 0 always; direction comes from kind
  price           numeric(14,4) > 0, per share, in the trade's currency (INR)
  fees            numeric(14,4) >= 0, total charges for the transaction
  reference       varchar(64) optional, e.g. a broker order id
  created_at      timestamptz
  updated_at      timestamptz
```

Constraints: `quantity > 0`, `price > 0`, `fees >= 0`, `kind IN ('BUY','SELL')`,
`exchange IN ('NSE','BSE')`, and the same symbol-format check the `holdings` table uses.

Indexes: `(portfolio_id, trade_date)` for the timeline scan, and
`(portfolio_id, symbol, exchange, trade_date)` for per-security lot questions.

## Decisions and their reasons

| Question | Decision | Reason |
|---|---|---|
| Negative quantities | Forbidden; direction is `kind` | One representation of a sell, enforceable by a check constraint |
| Partial sells | Natural — a SELL of any quantity ≤ position | No lot-closing bookkeeping needed for position tracking |
| Multiple buys of one security | Natural — many rows per security | This is exactly what the ledger is for |
| Transaction ordering | `(trade_date, created_at, id)` | Deterministic and stable across re-reads |
| Same-day transactions | Netted at that day's close | Only end-of-day prices exist; intra-day sequencing is not modelled, and the doc says so |
| Oversell | Rejected when a **day's closing position** would go negative | Detectable without intra-day times; reported as a data error, never silently clamped |
| Future trade dates | Rejected | A trade cannot have happened after the latest completed session |
| Non-session trade dates | Accepted, recognised on the next session, counted | A user's date may be a settlement date, or fall in a calendar year the app does not yet cover; rejecting would lose real data |
| Transaction costs | One `fees` total per transaction | Brokerage, STT, stamp duty and GST are not separable from typical broker statements; splitting them would invite fabricated detail |
| Dividends | Not supported | No dividend data source exists. A `DIVIDEND` kind with no amounts would be fiction; the `kind` column is extensible by migration when data exists |
| Deposits / withdrawals | Not a separate entity | See below — with no cash account, every buy is a contribution and every sell a withdrawal, which is sufficient for TWR |
| Currency | INR only, implicit | The whole application is INR-only; a currency column would imply FX support that does not exist |

## Relationship to holdings

Two sources of position data now exist, so the rule is explicit:

- **`holdings` stays the user's declared current position** and remains the sole input to valuation
  and to the M4.1 reconstruction. Nothing about M4.1 changes.
- **`transactions` is an optional ledger.** A portfolio with no transactions behaves exactly as
  before.
- When a ledger exists, the engine derives the final position from it and **reconciles** it against
  `holdings`, reporting `matches` or `differs` with the per-security differences.

The engine does not silently prefer one source. Deriving holdings from transactions automatically
would overwrite data the user entered by hand; ignoring the difference would hide a real error in
someone's records. Reporting it is the only honest option.

## Entering transactions

Two routes, both validated by the same rules and both refused in production, where the demo is
read-only:

| Route | Endpoint |
|---|---|
| One at a time, from the portfolio page | `POST /api/v1/portfolios/{id}/transactions` |
| A file | `POST …/transactions/csv-preview` then `…/csv-import` |

The form takes type, security, exchange, trade date, quantity, price, optional fees and an
optional reference. It shows the gross value and the resulting cash movement as they are typed,
then a review step restates the whole transaction before anything is sent — a trade is easy to
mistype and expensive to get wrong. Submitting is guarded against a double click, because two
identical trades on one day are legitimate and the API cannot tell an accident from a repeat.

Client-side checks mirror the API's and never decide anything: quantity a whole number above
zero, price above zero, at most four decimal places, a date that is neither before NSE began
trading nor after the latest completed session, and a sale no larger than the position the
ledger shows. The API validates all of it again.

## CSV import

```
trade_date,symbol,exchange,type,quantity,price,fees,reference
2026-09-14,HDFCBANK,NSE,BUY,20,1650,25,ORD-1
2026-09-16,HDFCBANK,NSE,SELL,5,1700,20,ORD-3
```

`fees` and `reference` are optional; column order and case are free. Rows must be oldest first,
because each sale is checked against the position the earlier rows produce.

**Upload → parse → validate → preview → confirm → import.** Nothing is written until the preview
is confirmed, and **an import is all-or-nothing**. A partly imported ledger is worse than a
rejected one: it produces a wrong cost basis and a wrong return, and says nothing about it.

Validation reports every problem at once, with the row and column, rather than one per upload:

| Reported | Example |
|---|---|
| Missing or unsupported columns | `Missing columns: type, quantity` |
| Malformed file, wrong encoding, wrong cell count | `Expected 8 values but found 5` |
| Invalid date, type, quantity, price or fees | `Trade date must be a date in YYYY-MM-DD format.` |
| Future trade dates | `… is after the latest completed NSE session (18 Sep 2026)` |
| Duplicate rows, and rows duplicating stored transactions | `Duplicate transaction: BUY 10 RELIANCE on 14 Sep 2026 matches row 2` |
| Sales larger than the position held at that point | `Sell quantity exceeds available quantity: selling 100 INFY on 15 Sep 2026 but only 60 held at that point.` |
| Rows out of date order | `Sort the file oldest first …` |

Files are capped at 1 MB and must be `.csv`. Cells are never evaluated: the standard library's
CSV reader is used on decoded text, so a cell beginning with `=` is simply an invalid symbol.

## Portfolio state engine

Given a portfolio, its ordered transactions and the trading calendar:

1. Recognise each transaction on its trade date, or the next session day if that date is not a
   session.
2. Walk the expected sessions in order, applying that day's net quantity change per security.
3. Emit, for each session, the position held at that day's close and the day's net external cash
   flow.

A security enters the timeline on its first buy and leaves when its position reaches zero; a zero
position contributes nothing and is not an error. The engine reports one of four states:

| State | Meaning |
|---|---|
| `NO_TRANSACTIONS` | No ledger; the M4.1 reconstruction basis applies |
| `INSUFFICIENT_PRICES` | A ledger exists, but stored prices cannot value it |
| `COMPLETE` | Every expected session in the window was fully priced |
| `PARTIAL` | Some sessions could not be valued; they are listed and counted |

The existing coverage methodology is reused unchanged: a session is valued only when **every**
security held that day has a stored close, nothing is interpolated or carried forward, and returns
are never linked across a missing session.

## Time-weighted return

**Convention:** a transaction is recognised at the close of its (recognised) session, so the day's
closing position includes it and the day's cash flow is the amount the investor actually paid or
received.

For each session `t` with a valued predecessor:

```
V_t  = Σ_s (position_s,t × close_s,t)
CF_t = Σ buys (quantity × price + fees) − Σ sells (quantity × price − fees)
R_t  = (V_t − CF_t) / V_(t−1) − 1
TWR  = Π (1 + R_t) − 1
```

Subtracting the flow before dividing removes the effect of the contribution or withdrawal, which is
precisely what makes the result time-weighted rather than money-weighted. Because the portfolio is
valued **every** session, each sub-period is one day long and the chained product is exact TWR — no
Modified Dietz approximation is involved, and no assumption about when during the day money arrived.

Execution price matters and is preserved: buying below that day's close makes `V_t − CF_t` exceed
`V_(t−1)`, which is a genuine same-day gain. Fees reduce the return, as they should.

**A growth index carries the statistics.** From the chained returns,
`I_t = I_(t−1) × (1 + R_t)` with `I_0 = 100`. Volatility and maximum drawdown are computed on this
index, never on raw portfolio value — otherwise a ₹1,00,000 withdrawal would register as a 30%
drawdown. With no transactions the index is proportional to value, so M4.1's numbers are unchanged.

**Days that cannot produce a return** are excluded and counted, never guessed:

| Situation | Treatment |
|---|---|
| Previous session missing from the calendar window | Skipped (`returns_skipped_across_gaps`) |
| Previous session not fully priced | Skipped — the existing gap rule |
| `V_(t−1) = 0` (portfolio empty, or first buy) | Skipped (`returns_skipped_zero_base`) — no capital was at risk |
| `V_t − CF_t < 0` | Skipped and flagged — implies a flow larger than the resulting value, which means bad input data |

**Is a separate cash-flow entity required?** No, not for correct TWR. The application models a
portfolio of securities with no idle cash, so the set of external flows is exactly the set of buys
and sells, and each one's amount is known to the paisa. A cash entity becomes necessary only when
the portfolio can hold uninvested cash, earn interest on it, or receive dividends — none of which
this application represents. That is a documented boundary, not an oversight.

## Money-weighted return

The time-weighted return measures the portfolio; the money-weighted return measures the
investor. Two people holding the same fund over the same year have the same TWR and different
MWRs, because one of them added money before a fall and the other did not. **Both are reported,
neither replaces the other, and the application does not rank them.**

**Method:** XIRR — solve `Σ CFᵢ × (1 + r)^(−dᵢ/365) = 0`, actual/365 day count, `Decimal`
arithmetic, **bisection** rather than Newton-Raphson, because bisection cannot diverge and
converges in a fixed number of steps. The plausible range is scanned in floating point to locate
every crossing (a search, 400× cheaper than the same scan in `Decimal`, measured at 85 ms against
0.2 ms); each bracket is then confirmed and solved in `Decimal`, so every published figure comes
from exact decimal arithmetic.

The equation is solved for the **period** rate and the annual rate derived from it
(`1 + r = (1 + g)^(365/D)`). The forms have identical roots, but solving in period terms keeps the
search well behaved: a 21% gain over two days is an ordinary period return and an absurd annual
one.

**Cash flows**, from the investor's side — money paid in is negative:

```
CF₀  = −(opening position valued at t₀ + that session's flow)
CFₜ  = −flowₜ                for later sessions
CF_N += terminal portfolio value
```

The ledger's flows are portfolio-inward positive, so they are negated exactly once. A trade dated
on a non-trading day is dated at the session it is recognised on, exactly as for TWR, so the two
measures never disagree about when money moved.

**Two figures are published:** the period return, directly comparable with the cumulative TWR, and
the annualised rate. They are labelled separately because they are different quantities.

**What is withheld, and why:**

| Situation | Behaviour |
|---|---|
| Several rates satisfy the cash flows | `ambiguous_multiple_roots`, no figure. Choosing one — the smallest, the nearest zero — would be a judgement the data does not support |
| No rate satisfies them in range | `no_solution` with the reason |
| Nothing was ever paid in, or one dated flow | `insufficient_history` |
| No transaction ledger | `not_applicable` |
| Window shorter than 90 days | The period figure stands; the **annualised** figure is withheld, because projecting a fortnight onto a year invents precision |

**Sub-windows.** A window starting after the first transaction values the position carried into it
at its market price on the first session, rather than at cost. The response says so: transaction
costs paid before the window are not attributed to it.

## Cost basis and profit

**FIFO.** Shares sold are matched against the earliest lots still open. FIFO is the basis Indian
income-tax law applies to listed equity shares, it is deterministic, and it needs nothing from
the user. Average cost and LIFO are deliberately not offered: a figure whose basis the user did
not choose, or a basis that changes silently, would make two runs of the same ledger disagree.

```
proceeds  = quantity × sale price − sale fees
cost      = Σ over matched lots (quantity × lot price + allocated lot fees)
realised  = proceeds − cost
unrealised = quantity held × market close − remaining cost
```

Fees travel with the shares they were paid for: a buy's fees join the cost of that lot and are
allocated pro rata when it is partly sold, and a sale's fees reduce its proceeds. Both therefore
reduce profit, as they do in reality.

`GET /api/v1/portfolios/{id}/pnl` reports this per security and in total, alongside
**contributions** (cash paid in, fees included) and **withdrawals** (cash taken out, net of fees).
Their difference is the net capital still invested, which the UI shows beside the gain or loss on
it — money added is not a return, and the two are never drawn as one number.

Without a ledger the view reports itself unavailable rather than returning zeros: holdings carry
an average buy price but no disposals, so realised profit is unknowable. Where an open position
has no stored price, its unrealised profit and the portfolio total are withheld with the reason.

## Timeline and attribution

`GET …/timeline` lists each session on which something happened, newest first, with the
transactions, the position each produced, the portfolio's value and its return that session.
Every entry comes from a recorded transaction; a trade dated on a non-trading day appears on the
session at whose close it is recognised, with its entered date shown.

`GET …/attribution` decomposes the return by security:

```
c(i,t) = (V(i,t) − V(i,t−1) − CF(i,t)) / V(t−1)
```

Summed across securities this is exactly the portfolio's flow-adjusted daily return, which makes
the decomposition checkable rather than merely plausible — a test asserts it. Over a window the
daily contributions are added, and that arithmetic sum is **not** the compounded time-weighted
return; both are reported with the difference named. This is the deterministic groundwork for
later portfolio intelligence: the numbers behind "why did it fall today?" exist as data before
anything tries to narrate them.

## What is still not supported

| Not implemented | Why |
|---|---|
| Money-weighted return (IRR / XIRR) | Needs an iterative solver and a clear product decision about which figure headlines; TWR is the comparable measure and is delivered first |
| Tax reporting (short/long-term gains) | Realised profit is computed FIFO, but holding-period rules, grandfathering and set-off are a separate problem |
| Editing a transaction in place | Remove and re-add; an edit that changes a quantity has to re-validate every later sale |
| Dividends and total return | No dividend data source |
| Corporate-action adjustment | Closes are used as reported; a split shows as a price move and as a position mismatch against the ledger |
| Cash balances, interest, deposits/withdrawals | No cash account is modelled |
| Short positions | A day's closing position may not be negative |
