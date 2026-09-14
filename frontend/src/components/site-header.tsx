import Link from "next/link";
import { LogoMark } from "@/components/logo-mark";

export function SiteHeader() {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-8">
        <Link href="/" className="flex items-center gap-2.5 rounded-md">
          <LogoMark className="size-7" />
          <span className="text-[15px] font-semibold tracking-tight">
            Portfolio Intelligence
          </span>
        </Link>
        <nav aria-label="Primary" className="flex items-center gap-6 text-sm">
          <Link
            href="/#what-we-analyze"
            className="hidden text-ink-muted transition-colors hover:text-ink sm:inline"
          >
            What we analyze
          </Link>
          <Link
            href="/analyze"
            className="rounded-md border border-line-strong px-3.5 py-2 font-medium transition-colors hover:bg-canvas"
          >
            Analyze
          </Link>
        </nav>
      </div>
    </header>
  );
}
