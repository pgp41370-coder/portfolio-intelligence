import type { ReactNode } from "react";

type Tone = "info" | "error" | "success" | "warning";

const toneStyles: Record<Tone, string> = {
  info: "border-line bg-canvas text-ink",
  error: "border-negative/25 bg-negative-soft text-negative",
  success: "border-positive/25 bg-positive-soft text-positive",
  warning: "border-caution/30 bg-caution-soft text-ink",
};

type AlertProps = {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
};

export function Alert({ tone = "info", title, children }: AlertProps) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-md border px-4 py-3 text-sm leading-6 ${toneStyles[tone]}`}
    >
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? "mt-1" : undefined}>{children}</div>}
    </div>
  );
}
