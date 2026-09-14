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
