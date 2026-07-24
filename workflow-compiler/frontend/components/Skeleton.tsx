// Content-shaped loading placeholders. A pulsing neutral block that stands in
// for text/rows while data loads, so the layout doesn't jump and the app reads
// as "loading this" rather than "blank/slow". Respects prefers-reduced-motion
// (the pulse is a Tailwind utility that the global reduced-motion rules quiet).

/** A single pulsing placeholder bar. Size it with `className` (h-*, w-*). */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`animate-pulse rounded-md bg-[var(--surface-2)] ${className}`}
    />
  );
}

/** N stacked skeleton rows shaped like the Projects list items. */
export function ProjectRowsSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <ul className="mt-3 flex flex-col gap-2" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <li
          key={i}
          className="flex items-center justify-between rounded-lg border border-[var(--border)] px-3 py-2.5"
        >
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-40" />
            <Skeleton className="h-2.5 w-24" />
          </div>
          <Skeleton className="h-5 w-16 rounded-full" />
        </li>
      ))}
    </ul>
  );
}

/*
 * Page-shaped skeletons, one per route, rendered by each route's loading.tsx
 * (and reused for in-page data loading where the shapes match). Each mirrors
 * its page's real container/grid so the swap-in doesn't shift the layout.
 */

/** Home page: hero header + two-column new-project / projects grid. */
export function HomePageSkeleton() {
  return (
    <div className="mx-auto max-w-5xl p-6" aria-hidden>
      <div className="mb-6 flex flex-col gap-2.5">
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-8 w-full max-w-lg" />
        <Skeleton className="h-4 w-full max-w-md" />
      </div>
      <Skeleton className="mb-6 h-16 w-full max-w-sm" />
      <div className="grid gap-8 lg:grid-cols-[1.3fr_1fr]">
        <div className="card flex flex-col gap-3 p-5">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-full max-w-sm" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
        <div className="card flex flex-col gap-3 p-5">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-8 w-full" />
          <ProjectRowsSkeleton />
        </div>
      </div>
    </div>
  );
}

/** Project workspace: action bar + three-pane spec layout. */
export function WorkspaceSkeleton() {
  return (
    <div className="flex h-full min-h-0 flex-col" aria-hidden>
      <div className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-2">
        <Skeleton className="h-6 w-6" />
        <Skeleton className="h-5 w-36" />
        <Skeleton className="h-5 w-20 rounded-full" />
        <div className="ml-auto flex items-center gap-2">
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-7 w-16" />
          <Skeleton className="h-7 w-20" />
          <Skeleton className="h-7 w-20" />
        </div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[180px_1fr_320px]">
        <div className="flex flex-col gap-2 border-r border-[var(--border)] p-3">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-full" />
          <Skeleton className="h-7 w-full" />
        </div>
        <div className="flex flex-col gap-3 bg-[var(--surface)] p-4">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-full min-h-40 w-full flex-1" />
        </div>
        <div className="flex flex-col gap-3 border-l border-[var(--border)] p-3">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </div>
    </div>
  );
}

/** Settings page: narrow column of preference cards. */
export function SettingsSkeleton() {
  return (
    <div className="mx-auto max-w-2xl p-6" aria-hidden>
      <div className="mb-6 flex flex-col gap-2.5">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-4 w-full max-w-sm" />
      </div>
      <div className="card mb-6 flex flex-col gap-3 p-5">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
      <div className="card flex flex-col gap-3 p-5">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    </div>
  );
}

/** Guide pages: sidebar nav + long-form article column. */
export function GuideSkeleton() {
  return (
    <div
      className="mx-auto grid max-w-6xl grid-cols-1 gap-10 px-6 py-10 lg:grid-cols-[200px_1fr]"
      aria-hidden
    >
      <div className="hidden flex-col gap-2.5 lg:flex">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-4 w-32" />
        ))}
      </div>
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-full max-w-md" />
        <Skeleton className="h-4 w-full max-w-xl" />
        <Skeleton className="h-4 w-full max-w-lg" />
        <Skeleton className="mt-4 h-40 w-full" />
        <Skeleton className="h-4 w-full max-w-xl" />
        <Skeleton className="h-4 w-full max-w-md" />
      </div>
    </div>
  );
}

/** Login page: centered auth card. */
export function LoginSkeleton() {
  return (
    <div className="flex h-full items-center justify-center p-6" aria-hidden>
      <div className="card flex w-full max-w-sm flex-col gap-3 p-6">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="mt-2 h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="mt-2 h-9 w-full" />
      </div>
    </div>
  );
}
