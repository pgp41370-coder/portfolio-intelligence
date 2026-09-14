type Step = { id: string; label: string };

export function StepIndicator({ steps, current }: { steps: Step[]; current: string }) {
  const currentIndex = steps.findIndex((step) => step.id === current);

  return (
    <ol className="flex flex-wrap items-center gap-3 text-sm">
      {steps.map((step, index) => {
        const isCurrent = index === currentIndex;
        const isDone = index < currentIndex;
        const markerStyles = isCurrent
          ? "bg-brand text-white"
          : isDone
            ? "bg-accent-soft text-accent"
            : "border border-line bg-surface text-ink-subtle";
        return (
          <li key={step.id} className="flex items-center gap-3">
            {index > 0 && <span aria-hidden="true" className="h-px w-6 bg-line-strong sm:w-10" />}
            <span
              aria-hidden="true"
              className={`flex size-6 items-center justify-center rounded-full text-xs font-semibold ${markerStyles}`}
            >
              {isDone ? "✓" : index + 1}
            </span>
            <span
              aria-current={isCurrent ? "step" : undefined}
              className={isCurrent ? "font-medium text-ink" : "text-ink-muted"}
            >
              {step.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
