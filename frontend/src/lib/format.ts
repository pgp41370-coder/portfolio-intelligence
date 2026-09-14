const inrFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const quantityFormatter = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

const dateTimeFormatter = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Kolkata",
});

/** Format a decimal string as Indian rupees with lakh/crore grouping, e.g. "₹1,23,456.50". */
export function formatInr(amount: string): string {
  // Passing the string (not a Number) keeps the exact decimal value.
  return inrFormatter.format(amount as Intl.StringNumericLiteral);
}

export function formatQuantity(quantity: number): string {
  return quantityFormatter.format(quantity);
}

export function formatDateTime(isoTimestamp: string): string {
  return `${dateTimeFormatter.format(new Date(isoTimestamp))} IST`;
}
