import type { ReactNode } from "react";
import type { Exchange } from "@/lib/api";
import { formatInr, formatQuantity } from "@/lib/format";

export type HoldingRow = {
  key: string;
  symbol: string;
  exchange: Exchange;
  quantity: number;
  average_buy_price: string;
};

type HoldingsTableProps = {
  rows: readonly HoldingRow[];
  caption: string;
  emptyMessage?: string;
  renderAction?: (row: HoldingRow) => ReactNode;
};

const edgeCell = "px-3 first:pl-5 last:pr-5 sm:px-4 sm:first:pl-6 sm:last:pr-6";

export function HoldingsTable({ rows, caption, emptyMessage, renderAction }: HoldingsTableProps) {
  if (rows.length === 0) {
    return (
      <p className="px-5 py-10 text-center text-sm text-ink-subtle">
        {emptyMessage ?? "No holdings."}
      </p>
    );
  }

  return (
    // `relative` keeps the absolutely positioned sr-only label inside the scroll area on narrow screens.
    <div className="relative overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line text-left align-bottom text-xs uppercase tracking-wide text-ink-subtle">
            <th scope="col" className={`${edgeCell} py-3 font-medium`}>
              Symbol
            </th>
            <th scope="col" className={`${edgeCell} py-3 font-medium`}>
              Exchange
            </th>
            <th scope="col" className={`${edgeCell} py-3 text-right font-medium`}>
              Quantity
            </th>
            <th scope="col" className={`${edgeCell} py-3 text-right font-medium`}>
              Average Buy Price
            </th>
            {renderAction && (
              <th scope="col" className={`${edgeCell} py-3`}>
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={row.key}>
              <td className={`${edgeCell} py-3 font-semibold [overflow-wrap:anywhere]`}>{row.symbol}</td>
              <td className={`${edgeCell} py-3 text-ink-muted`}>{row.exchange}</td>
              <td className={`${edgeCell} py-3 text-right font-mono tabular-nums`}>
                {formatQuantity(row.quantity)}
              </td>
              <td className={`${edgeCell} whitespace-nowrap py-3 text-right font-mono tabular-nums`}>
                {formatInr(row.average_buy_price)}
              </td>
              {renderAction && <td className={`${edgeCell} py-2 text-right`}>{renderAction(row)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
