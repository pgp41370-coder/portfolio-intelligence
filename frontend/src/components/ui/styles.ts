const buttonBase =
  "inline-flex items-center justify-center gap-2 rounded-md text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50";

export const buttonStyles = {
  primary: `${buttonBase} h-10 bg-brand px-4 font-semibold text-white hover:bg-brand-hover`,
  secondary: `${buttonBase} h-10 border border-line-strong bg-surface px-4 font-medium text-ink hover:bg-canvas`,
  ghost: `${buttonBase} h-10 px-3 font-medium text-ink-muted hover:text-ink`,
  danger: `${buttonBase} h-8 px-2.5 font-medium text-negative hover:bg-negative-soft`,
  subtle: `${buttonBase} h-8 px-2.5 font-medium text-ink-muted hover:bg-canvas hover:text-ink`,
};

export const inputStyles =
  "block h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none aria-[invalid=true]:border-negative";

export const labelStyles = "block text-sm font-medium text-ink";

export const cardStyles = "rounded-lg border border-line bg-surface";

export const eyebrowStyles = "text-xs font-semibold uppercase tracking-[0.14em] text-ink-subtle";
