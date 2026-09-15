type DataKind = "input" | "calculated" | "market";

const labels: Record<DataKind, string> = {
  input: "Your input",
  calculated: "Calculated",
  market: "Market data",
};

const styles: Record<DataKind, string> = {
  input: "border-line-strong bg-surface text-ink-muted",
  calculated: "border-accent/30 bg-accent-soft text-accent",
  market: "border-brand/25 bg-canvas text-brand",
};

/** Marks where a value comes from: the user, a calculation, or stored market data. */
export function DataBadge({ kind }: { kind: DataKind }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium ${styles[kind]}`}
    >
      {labels[kind]}
    </span>
  );
}

export function DataLegend() {
  return (
    <p className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-subtle">
      <span className="flex items-center gap-2">
        <DataBadge kind="input" /> Values you entered
      </span>
      <span className="flex items-center gap-2">
        <DataBadge kind="market" /> Dated NSE end-of-day closing prices
      </span>
      <span className="flex items-center gap-2">
        <DataBadge kind="calculated" /> Derived from your inputs and those prices
      </span>
    </p>
  );
}
