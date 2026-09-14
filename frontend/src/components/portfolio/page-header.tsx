import Link from "next/link";
import type { ReactNode } from "react";

type Breadcrumb = { label: string; href?: string };

type PageHeaderProps = {
  breadcrumbs: Breadcrumb[];
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
};

export function PageHeader({ breadcrumbs, title, description, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <nav aria-label="Breadcrumb">
          <ol className="flex flex-wrap items-center gap-1.5 text-sm text-ink-subtle">
            {breadcrumbs.map((crumb, index) => (
              <li key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-1.5">
                {index > 0 && <span aria-hidden="true">/</span>}
                {crumb.href ? (
                  <Link href={crumb.href} className="transition-colors hover:text-ink">
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page" className="truncate text-ink-muted">
                    {crumb.label}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </nav>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight [overflow-wrap:anywhere] sm:text-3xl">
          {title}
        </h1>
        {description && (
          <div className="mt-2 max-w-2xl text-sm leading-6 text-ink-muted sm:text-base sm:leading-7">
            {description}
          </div>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
