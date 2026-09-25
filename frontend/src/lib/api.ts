export type Exchange = "NSE" | "BSE";

export const EXCHANGES: readonly Exchange[] = ["NSE", "BSE"];

/** Amounts are decimal strings (e.g. "1650.00") to avoid floating-point rounding. */
export type HoldingInput = {
  symbol: string;
  exchange: Exchange;
  quantity: number;
  average_buy_price: string;
};

export type Holding = HoldingInput & {
  id: string;
  created_at: string;
  updated_at: string;
};

export type PortfolioDetail = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  holdings: Holding[];
  total_invested_capital: string;
};

export type PortfolioSummary = {
  id: string;
  name: string;
  holding_count: number;
  total_invested_capital: string;
  created_at: string;
  updated_at: string;
};

export type CsvIssue = {
  row: number | null;
  column: string | null;
  message: string;
};

export type CsvPreview = {
  is_valid: boolean;
  holding_count: number;
  holdings: HoldingInput[];
  total_invested_capital: string | null;
  errors: CsvIssue[];
};

type ErrorDetail = {
  loc?: (string | number)[];
  row?: number | null;
  column?: string | null;
  message: string;
};

type ErrorBody = {
  error?: { code?: string; message?: string; details?: ErrorDetail[] };
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: ErrorDetail[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The portfolio API or its database cannot be reached from this deployment. */
export class ServiceUnavailableError extends Error {
  constructor(message = "The portfolio service is not available.") {
    super(message);
    this.name = "ServiceUnavailableError";
  }
}

type RequestOptions = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      cache: "no-store",
      headers: { Accept: "application/json", ...options.headers },
    });
  } catch {
    throw new ServiceUnavailableError();
  }

  if (response.status === 204) {
    return undefined as T;
  }

  // Without a connected backend the request reaches Next.js itself and gets an HTML page.
  const isJson = response.headers.get("content-type")?.includes("application/json") ?? false;
  if (!isJson) {
    throw new ServiceUnavailableError();
  }

  const body: unknown = await response.json();
  if (response.ok) {
    return body as T;
  }

  const error = (body as ErrorBody).error;
  if (response.status === 503) {
    throw new ServiceUnavailableError(error?.message);
  }
  throw new ApiError(
    response.status,
    error?.code ?? "unknown_error",
    error?.message ?? "Something went wrong.",
    error?.details ?? [],
  );
}

export function listPortfolios(): Promise<PortfolioSummary[]> {
  return request("/portfolios");
}

export function getPortfolio(portfolioId: string): Promise<PortfolioDetail> {
  return request(`/portfolios/${encodeURIComponent(portfolioId)}`);
}

export function createPortfolio(payload: {
  name: string;
  holdings: HoldingInput[];
}): Promise<PortfolioDetail> {
  return request("/portfolios", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteHolding(portfolioId: string, holdingId: string): Promise<void> {
  return request(
    `/portfolios/${encodeURIComponent(portfolioId)}/holdings/${encodeURIComponent(holdingId)}`,
    { method: "DELETE" },
  );
}

export function previewCsv(file: File): Promise<CsvPreview> {
  const form = new FormData();
  form.append("file", file);
  return request("/portfolios/csv-preview", { method: "POST", body: form });
}

export function importCsv(name: string, file: File): Promise<PortfolioDetail> {
  const form = new FormData();
  form.append("name", name);
  form.append("file", file);
  return request("/portfolios/csv-import", { method: "POST", body: form });
}

export type ValuationStatus = "VALUED" | "STALE" | "UNPRICED";
export type UnpricedReason = "LISTING_NOT_FOUND" | "NO_NSE_LISTING" | "NO_PRICE_DATA";
export type HoldingWarning = "LARGE_PRICE_MOVE";

/** A dated NSE end-of-day closing price. Never a live price. */
export type ValuationPrice = {
  close_price: string;
  trade_date: string;
  exchange: Exchange;
  source: string;
  source_name: string;
  fetched_at: string;
};

/** Monetary and percentage values are decimal strings; null means unavailable, never zero. */
export type HoldingValuation = {
  holding_id: string;
  symbol: string;
  exchange: Exchange;
  quantity: number;
  average_buy_price: string;
  status: ValuationStatus;
  unpriced_reason: UnpricedReason | null;
  price: ValuationPrice | null;
  invested_value: string;
  market_value: string | null;
  unrealized_pnl: string | null;
  unrealized_return_pct: string | null;
  weight_pct: string | null;
  warnings: HoldingWarning[];
};

export type PortfolioValuation = {
  portfolio_id: string;
  portfolio_name: string;
  valued_at: string;
  market_data_configured: boolean;
  methodology: { price_basis: "NSE_EOD_CLOSE"; currency: "INR"; rounding: string; note: string };
  freshness: {
    expected_session_date: string;
    latest_price_date: string | null;
    oldest_price_date: string | null;
    valued_count: number;
    stale_count: number;
    unpriced_count: number;
  };
  totals: {
    total_invested_value: string;
    priced_invested_value: string;
    total_market_value: string | null;
    total_unrealized_pnl: string | null;
    total_unrealized_return_pct: string | null;
    is_complete: boolean;
  };
  holdings: HoldingValuation[];
};

export function getPortfolioValuation(portfolioId: string): Promise<PortfolioValuation> {
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/valuation`);
}

export type CoverageStatus = "complete" | "partial" | "insufficient";

export type PerformancePoint = {
  trade_date: string;
  value: string;
  daily_return_pct: string | null;
  cumulative_return_pct: string;
};

export type BenchmarkPoint = { trade_date: string; index: string };

/** A statistic, or the reason it is being withheld. */
export type Measure = { value: string | null; available: boolean; note: string | null };

/** The investor's money-weighted return, or the reason there is not one. */
export type MoneyWeighted = {
  status:
    | "available"
    | "not_applicable"
    | "insufficient_history"
    | "no_solution"
    | "ambiguous_multiple_roots";
  annualised_pct: string | null;
  period_pct: string | null;
  period_days: number;
  annualisation_available: boolean;
  contributions: string | null;
  withdrawals: string | null;
  terminal_value: string | null;
  roots_found: number;
  opening_position_valued: boolean;
  note: string;
  annualisation_note: string | null;
  disclosure: string | null;
  method: string;
};

/** A price move large enough that figures built on it should not be trusted. */
export type PriceAnomaly = {
  symbol: string;
  exchange: Exchange;
  previous_date: string;
  trade_date: string;
  previous_close: string;
  close: string;
  change_pct: string;
  consistent_with: string | null;
  trigger: "large_move" | "corporate_action_ratio";
  description: string;
};

export type PriceAnomalies = {
  detected: number;
  threshold_pct: string;
  anomalies: PriceAnomaly[];
  note: string | null;
};

export type PerformanceRisk = {
  volatility_pct: string | null;
  downside_volatility: Measure;
  max_drawdown_pct: string | null;
  beta: Measure;
  tracking_error_pct: Measure;
  information_ratio: Measure;
  sharpe_ratio: Measure;
  observations: number;
  note: string;
};

export type PositionDifference = {
  symbol: string;
  exchange: Exchange;
  ledger_quantity: number;
  holdings_quantity: number;
};

export type Reconciliation = {
  status: "not_applicable" | "matches" | "differs";
  differences: PositionDifference[];
  note: string | null;
};

export type Weight = {
  symbol: string;
  exchange: Exchange;
  market_value: string;
  weight_pct: string;
};

/** Point-in-time allocation and concentration at the latest stored closes. */
export type PortfolioAllocation = {
  portfolio_id: string;
  portfolio_name: string;
  currency: "INR";
  as_of: string;
  data_as_of: string | null;
  priced_market_value: string | null;
  holdings: Weight[];
  concentration: {
    holdings_counted: number;
    top_holding: Weight | null;
    top_1_pct: string | null;
    top_3_pct: string | null;
    top_5_pct: string | null;
    hhi: string | null;
    hhi_band: string | null;
    effective_holdings: string | null;
  };
  sectors: { available: boolean; note: string; weights: Weight[] };
  unpriced_positions: { symbol: string; exchange: Exchange; quantity: number; reason: string | null }[];
  note: string;
};

/** Historical value and risk statistics, derived from stored end-of-day closes only. */
export type PortfolioPerformance = {
  portfolio_id: string;
  portfolio_name: string;
  currency: "INR";
  as_of: string;
  basis: "CURRENT_HOLDINGS" | "TRANSACTIONS";
  period: { start: string | null; end: string | null };
  coverage: {
    status: CoverageStatus;
    sessions_expected: number;
    sessions_available: number;
    missing_sessions: string[];
    missing_session_count: number;
    missing_no_prices_at_all_count: number;
    missing_some_prices_count: number;
    coverage_pct: string | null;
    sessions_behind_latest: number;
    latest_expected_session: string | null;
    note: string | null;
  };
  summary: {
    start_value: string | null;
    end_value: string | null;
    cumulative_return_pct: string | null;
    volatility_pct: string | null;
    max_drawdown_pct: string | null;
    returns_used: number;
    returns_skipped_across_gaps: number;
    volatility_note: string | null;
    returns_skipped_zero_base: number;
    net_external_flow: string | null;
  };
  series: PerformancePoint[];
  benchmark: {
    requested: string | null;
    status: string;
    display_name: string | null;
    basis: string | null;
    tracks: string | null;
    source: string | null;
    is_proxy: boolean;
    cumulative_return_pct: string | null;
    excess_return_pct: string | null;
    sessions_compared: number;
    series: BenchmarkPoint[];
    methodology: string | null;
    note: string;
  };
  money_weighted: MoneyWeighted | null;
  price_anomalies: PriceAnomalies | null;
  risk: PerformanceRisk;
  excluded_holdings: { symbol: string; exchange: Exchange; reason: UnpricedReason }[];
  reconciliation: Reconciliation;
  methodology: {
    basis: string;
    calculation_method: "PRICE_RETURN_ENDPOINTS" | "TWR_DAILY_CHAINED";
    price_basis: "NSE_EOD_CLOSE";
    trading_days_per_year: number;
    returns: string;
    sharpe: string;
    note: string;
  };
};

export function getPortfolioPerformance(
  portfolioId: string,
  options: { startDate?: string; benchmark?: string } = {},
): Promise<PortfolioPerformance> {
  const query = new URLSearchParams();
  if (options.startDate) query.set("start_date", options.startDate);
  if (options.benchmark) query.set("benchmark", options.benchmark);
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/performance${suffix}`);
}

/** Position weights and concentration at the latest stored closes. */
export function getPortfolioAllocation(portfolioId: string): Promise<PortfolioAllocation> {
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/allocation`);
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const messages = error.details.map((detail) => detail.message).filter(Boolean);
    if (error.code === "validation_error" && messages.length > 0) {
      return messages.join(" ");
    }
    return error.message;
  }
  if (error instanceof ServiceUnavailableError) {
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

// --- Transaction ledger (M4.3) -------------------------------------------------------------

export type TransactionKind = "BUY" | "SELL";

export type TransactionInput = {
  symbol: string;
  exchange: Exchange;
  kind: TransactionKind;
  trade_date: string;
  quantity: number;
  price: string;
  fees?: string;
  reference?: string | null;
};

export type Transaction = {
  id: string;
  symbol: string;
  exchange: Exchange;
  kind: TransactionKind;
  trade_date: string;
  quantity: number;
  price: string;
  fees: string;
  reference: string | null;
  created_at: string;
};

export type TransactionList = {
  portfolio_id: string;
  portfolio_name: string;
  count: number;
  transactions: Transaction[];
};

export type TransactionCsvPreview = {
  is_valid: boolean;
  transaction_count: number;
  transactions: TransactionInput[];
  net_cash_flow: string | null;
  errors: CsvIssue[];
};

export function getTransactions(portfolioId: string): Promise<TransactionList> {
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/transactions`);
}

export function addTransactions(portfolioId: string, transactions: TransactionInput[]): Promise<Transaction[]> {
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/transactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(transactions),
  });
}

export function deleteTransaction(portfolioId: string, transactionId: string): Promise<void> {
  return request(
    `/portfolios/${encodeURIComponent(portfolioId)}/transactions/${encodeURIComponent(transactionId)}`,
    { method: "DELETE" },
  );
}

export function previewTransactionCsv(portfolioId: string, file: File): Promise<TransactionCsvPreview> {
  const form = new FormData();
  form.append("file", file);
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/transactions/csv-preview`, {
    method: "POST",
    body: form,
  });
}

export function importTransactionCsv(portfolioId: string, file: File): Promise<Transaction[]> {
  const form = new FormData();
  form.append("file", file);
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/transactions/csv-import`, {
    method: "POST",
    body: form,
  });
}

// --- P&L, timeline and attribution ------------------------------------------------------------

export type SecurityPnl = {
  symbol: string;
  exchange: Exchange;
  quantity: number;
  cost_basis: string | null;
  average_cost: string | null;
  market_value: string | null;
  realised_pnl: string;
  unrealised_pnl: string | null;
  total_pnl: string | null;
  contributions: string;
  withdrawals: string;
  fees: string;
  price_date: string | null;
  price_note: string | null;
};

export type PortfolioPnl = {
  portfolio_id: string;
  portfolio_name: string;
  currency: "INR";
  as_of: string;
  data_as_of: string | null;
  totals: {
    realised_pnl: string;
    unrealised_pnl: string | null;
    total_pnl: string | null;
    contributions: string;
    withdrawals: string;
    net_invested: string;
    fees: string;
    open_cost_basis: string;
    market_value: string | null;
    is_complete: boolean;
  } | null;
  securities: SecurityPnl[];
  unmatched_sales: string[];
  methodology: { cost_basis: "FIFO"; note: string; basis: string; available: boolean };
};

export type TimelineEntry = {
  trade_date: string;
  transactions: {
    kind: TransactionKind;
    symbol: string;
    exchange: Exchange;
    quantity: number;
    price: string;
    fees: string;
    gross_value: string;
    cash_flow: string;
    reference: string | null;
    trade_date: string;
  }[];
  position_changes: string[];
  portfolio_value: string | null;
  net_cash_flow: string;
  daily_return_pct: string | null;
  cumulative_return_pct: string | null;
};

export type PortfolioTimeline = {
  portfolio_id: string;
  portfolio_name: string;
  currency: "INR";
  as_of: string;
  basis: string;
  entries: TimelineEntry[];
  transaction_count: number;
  note: string;
};

export type Contribution = {
  symbol: string;
  exchange: Exchange;
  contribution_pct: string;
  start_value: string | null;
  end_value: string | null;
  start_weight_pct: string | null;
  end_weight_pct: string | null;
  sessions_counted: number;
};

export type PortfolioAttribution = {
  portfolio_id: string;
  portfolio_name: string;
  currency: "INR";
  as_of: string;
  basis: string;
  period: { start: string | null; end: string | null };
  sessions_counted: number;
  twr_pct: string | null;
  sum_of_daily_returns_pct: string | null;
  compounding_difference_pct: string | null;
  contributors: Contribution[];
  detractors: Contribution[];
  latest_session: string | null;
  latest_contributions: {
    symbol: string;
    exchange: Exchange;
    contribution_pct: string;
    value_change: string;
    cash_flow: string;
  }[];
  benchmark: PortfolioPerformance["benchmark"] | null;
  benchmark_gap_pct: string | null;
  stale_positions: string[];
  note: string;
};

export function getPortfolioPnl(portfolioId: string): Promise<PortfolioPnl> {
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/pnl`);
}

export function getPortfolioTimeline(portfolioId: string): Promise<PortfolioTimeline> {
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/timeline`);
}

export function getPortfolioAttribution(
  portfolioId: string,
  options: { benchmark?: string } = {},
): Promise<PortfolioAttribution> {
  const query = options.benchmark ? `?benchmark=${encodeURIComponent(options.benchmark)}` : "";
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/attribution${query}`);
}

// --- Deterministic portfolio intelligence (M5) ---------------------------------------------

export type IntelligenceStatus = "available" | "limited" | "unavailable";

export type Contributor = {
  rank: number;
  symbol: string;
  exchange: Exchange;
  contribution_pct: string;
  security_return_pct: string | null;
  start_value: string | null;
  end_value: string | null;
  net_flow: string;
  start_weight_pct: string | null;
  end_weight_pct: string | null;
  sessions_counted: number;
};

export type PortfolioIntelligence = {
  portfolio_id: string;
  portfolio_name: string;
  currency: "INR";
  as_of: string;
  status: IntelligenceStatus;
  period: { start: string | null; end: string | null };
  headline: string;
  findings: string[];
  returns: {
    portfolio_return_pct: string | null;
    benchmark_return_pct: string | null;
    relative_return_pct: string | null;
    calculation_method: "PRICE_RETURN_ENDPOINTS" | "TWR_DAILY_CHAINED";
    basis: string;
    sum_of_contributions_pct: string | null;
    compounding_difference_pct: string | null;
    contributions_reconcile: boolean;
    top_positive: Contributor[];
    top_negative: Contributor[];
    latest_session: string | null;
    latest_session_movers: Contributor[];
    note: string;
  } | null;
  money_weighted: MoneyWeighted | null;
  cash_flow: {
    start_value: string | null;
    end_value: string | null;
    value_change: string | null;
    contributions: string | null;
    withdrawals: string | null;
    net_external_flow: string | null;
    return_driven_change: string | null;
    flow_share_of_change_pct: string | null;
    twr_pct: string | null;
    available: boolean;
    note: string;
  } | null;
  risk: {
    volatility_pct: string | null;
    downside_volatility_pct: string | null;
    max_drawdown_pct: string | null;
    current_drawdown_pct: string | null;
    positive_sessions: number;
    negative_sessions: number;
    flat_sessions: number;
    beta: string | null;
    largest_position_symbol: string | null;
    largest_position_weight_pct: string | null;
    top_3_weight_pct: string | null;
    hhi: string | null;
    concentration_band: string | null;
    effective_holdings: string | null;
    note: string;
  } | null;
  /** Provenance for each headline figure. Present only when requested with ?trace=true. */
  trace:
    | {
        metric: string;
        value: string | null;
        source: string;
        inputs: Record<string, string>;
        formula: string;
      }[]
    | null;
  data_quality: {
    status: IntelligenceStatus;
    coverage_status: CoverageStatus;
    sessions_available: number;
    sessions_expected: number;
    sessions_behind_latest: number;
    latest_expected_session: string | null;
    missing_session_count: number;
    stale_securities: string[];
    excluded_securities: string[];
    benchmark_status: string;
    benchmark_basis: string | null;
    reconciliation_status: string;
    price_anomalies: PriceAnomalies | null;
    limitations: string[];
    note: string;
  };
  methodology: string;
};

export function getPortfolioIntelligence(
  portfolioId: string,
  options: { benchmark?: string } = {},
): Promise<PortfolioIntelligence> {
  const query = options.benchmark ? `?benchmark=${encodeURIComponent(options.benchmark)}` : "";
  return request(`/portfolios/${encodeURIComponent(portfolioId)}/intelligence${query}`);
}
