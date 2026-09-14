import { DataBadge } from "@/components/ui/data-badge";
import { formatInr } from "@/lib/format";

type InvestedCapitalCardProps = {
  amount: string;
  holdingCount: number;
};

export function InvestedCapitalCard({ amount, holdingCount }: InvestedCapitalCardProps) {
  return (
    <section
      aria-labelledby="invested-capital-heading"
      className="rounded-lg border border-accent/25 bg-surface p-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="invested-capital-heading" className="text-sm font-medium text-ink-muted">
          Total Invested Capital
        </h2>
        <DataBadge kind="calculated" />
      </div>
      <p className="mt-2 font-mono text-2xl font-semibold tracking-tight tabular-nums [overflow-wrap:anywhere] sm:text-3xl">
        {formatInr(amount)}
      </p>
      <p className="mt-3 text-xs leading-5 text-ink-subtle">
        Sum of quantity × average buy price across {holdingCount}{" "}
        {holdingCount === 1 ? "holding" : "holdings"}. Based only on your inputs; this is not
        the current market value.
      </p>
    </section>
  );
}
