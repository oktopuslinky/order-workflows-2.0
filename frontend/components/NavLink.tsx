"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** Header nav link that highlights when its route (or a sub-route) is active. */
export function NavLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-md px-2.5 py-1 transition ${
        active
          ? "bg-[var(--surface-2)] font-medium text-[var(--ink)]"
          : "text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
      }`}
    >
      {children}
    </Link>
  );
}
