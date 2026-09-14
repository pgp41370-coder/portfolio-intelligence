/**
 * Exact decimal arithmetic for user-entered amounts with up to 4 decimal places.
 * Values are held as bigint counts of 0.0001 so totals never suffer float rounding.
 */

const SCALE = 4;
const FACTOR = BigInt(10 ** SCALE);
const ZERO = BigInt(0);

/** Parse a validated, non-negative decimal string such as "1650", "1650.5" or ".25". */
export function toUnits(value: string): bigint {
  const [whole = "", fraction = ""] = value.trim().replace(/^\+/, "").split(".");
  const paddedFraction = `${fraction}${"0".repeat(SCALE)}`.slice(0, SCALE);
  return BigInt(whole || "0") * FACTOR + BigInt(paddedFraction);
}

/** Format units as a plain decimal string with 4 decimal places, e.g. "33000.0000". */
export function unitsToDecimalString(units: bigint): string {
  const whole = units / FACTOR;
  const fraction = (units % FACTOR).toString().padStart(SCALE, "0");
  return `${whole}.${fraction}`;
}

/** SUM(quantity × average_buy_price), computed exactly. */
export function investedCapital(
  holdings: readonly { quantity: number; average_buy_price: string }[],
): string {
  const total = holdings.reduce(
    (sum, holding) => sum + BigInt(holding.quantity) * toUnits(holding.average_buy_price),
    ZERO,
  );
  return unitsToDecimalString(total);
}
