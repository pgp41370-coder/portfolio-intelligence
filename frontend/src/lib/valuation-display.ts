/**
 * Display rules for portfolio valuation. Pure functions with no runtime imports, so they
 * can be unit-tested with `node --test`.
 *
 * Values arrive as decimal strings from the API. Missing values are null and are shown as
 * unavailable; they are never replaced with zero.
 */

import type { PortfolioValuation, UnpricedReason, ValuationStatus } from "@/lib/api";

export type Tone = "positive" | "negative" | "neutral";

export type ValuationSummaryKind = "complete" | "partial" | "unpriced" | "empty";

export type ValuationNotice = {
  tone: "warning" | "info";
  title: string;
  body: string;
};

const signedInrFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const signedPercentFormatter = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const percentFormatter = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const tradeDateFormatter = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export const STATUS_TEXT: Record<ValuationStatus, { label: string; description: string }> = {
  VALUED: {
    label: "Valued",
    description: "Priced at the close of the latest expected NSE session.",
  },
  STALE: {
    label: "Stale",
    description: "Priced at an older NSE close; the latest session's price has not been loaded.",
  },
  UNPRICED: {
    label: "Unpriced",
    description: "No supported NSE end-of-day price is available.",
  },
};

export function toneOf(value: string): Tone {
  const number = Number(value);
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "neutral";
}

/** "+₹2,500.00", "-₹3,000.00" or "₹0.00". The sign is always shown in text, not only colour. */
export function formatSignedInr(value: string): string {
  return signedInrFormatter.format(value as Intl.StringNumericLiteral);
}

export function formatSignedPercent(value: string): string {
  return `${signedPercentFormatter.format(value as Intl.StringNumericLiteral)}%`;
}

export function formatPercent(value: string): string {
  return `${percentFormatter.format(value as Intl.StringNumericLiteral)}%`;
}

/** Formats an exchange trade date (YYYY-MM-DD) without shifting it across time zones. */
export function formatTradeDate(isoDate: string): string {
  return tradeDateFormatter.format(new Date(`${isoDate}T00:00:00Z`));
}

export function summarizeValuation(valuation: PortfolioValuation): ValuationSummaryKind {
  if (valuation.holdings.length === 0) return "empty";
  if (valuation.totals.total_market_value === null) return "unpriced";
  if (!valuation.totals.is_complete) return "partial";
  return "complete";
}

export function describePriceBasis(valuation: PortfolioValuation): string | null {
  const { latest_price_date: latest, oldest_price_date: oldest } = valuation.freshness;
  if (!latest || !oldest) return null;
  if (latest === oldest) {
    return `Valuation based on NSE EOD closing prices dated ${formatTradeDate(latest)}.`;
  }
  return `Valuation based on NSE EOD closing prices dated between ${formatTradeDate(oldest)} and ${formatTradeDate(latest)}.`;
}

export function unpricedReasonText(reason: UnpricedReason | null): string {
  switch (reason) {
    case "LISTING_NOT_FOUND":
      return "Price unavailable — this symbol was not found in the security master.";
    case "NO_NSE_LISTING":
      return "Price unavailable — this security has no NSE listing, and only NSE end-of-day prices are supported.";
    default:
      return "Price unavailable — this holding cannot currently be valued from the supported NSE EOD dataset.";
  }
}

export function valuationNotices(valuation: PortfolioValuation): ValuationNotice[] {
  const notices: ValuationNotice[] = [];
  const { stale_count: stale, unpriced_count: unpriced, expected_session_date: expected } = valuation.freshness;

  if (stale > 0) {
    notices.push({
      tone: "warning",
      title: `${count(stale, "holding uses", "holdings use")} an older closing price`,
      body: `The latest expected NSE session is ${formatTradeDate(expected)}, but its closing price has not been loaded yet. Each holding shows the date of the price used.`,
    });
  }

  if (unpriced > 0) {
    notices.push({
      tone: "warning",
      title: `${count(unpriced, "holding", "holdings")} could not be valued`,
      body: "Unpriced holdings are excluded from Current Value, Unrealized P&L, Return and weights. They are still included in Total Invested.",
    });
  }

  const moved = valuation.holdings
    .filter((holding) => holding.warnings.includes("LARGE_PRICE_MOVE"))
    .map((holding) => holding.symbol);
  if (moved.length > 0) {
    notices.push({
      tone: "warning",
      title: "Large price move detected",
      body: `${moved.join(", ")} moved 35% or more between the last two closes, which can indicate a stock split or bonus issue. Prices are not adjusted for corporate actions, so check the quantity and average buy price.`,
    });
  }

  if (!valuation.market_data_configured && (stale > 0 || unpriced > 0)) {
    notices.push({
      tone: "info",
      title: "Market-data sync is not configured",
      body: "This server has no market-data key, so prices cannot be refreshed. Values use prices that are already stored.",
    });
  }

  return notices;
}

function count(value: number, singular: string, plural: string): string {
  return `${value} ${value === 1 ? singular : plural}`;
}
