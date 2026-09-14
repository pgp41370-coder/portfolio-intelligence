type DataKind = "input" | "calculated";

const labels: Record<DataKind, string> = {
  input: "Your input",
  calculated: "Calculated",
};

const styles: Record<DataKind, string> = {
  input: "border-line-strong bg-surface text-ink-muted",
  calculated: "border-accent/30 bg-accent-soft text-accent",
};

/** Marks a value as either entered by the user or derived from their inputs. */
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
        <DataBadge kind="calculated" /> Derived from your inputs. No market data is used.
      </span>
    </p>
  );
}
