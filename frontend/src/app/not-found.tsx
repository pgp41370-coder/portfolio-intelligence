import Link from "next/link";

export default function NotFound() {
  return (
    <section className="mx-auto w-full max-w-3xl px-5 py-24 sm:px-8">
      <p className="font-mono text-sm text-ink-subtle">404</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-4 text-base leading-7 text-ink-muted">
        The page you are looking for does not exist.
      </p>
      <Link
        href="/"
        className="mt-8 inline-flex h-11 items-center rounded-md bg-brand px-5 text-sm font-semibold text-white transition-colors hover:bg-brand-hover"
      >
        Go to home
      </Link>
    </section>
  );
}
