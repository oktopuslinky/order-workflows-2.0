"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";

/** Header chip for the signed-in user with a small sign-out dropdown. */
export function UserMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!user) return null;

  const initials = user.display_name
    .split(/\s+/)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .slice(0, 2)
    .join("");

  return (
    <div ref={root} className="relative">
      <button
        ref={trigger}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account: ${user.display_name}`}
        className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-full bg-[var(--accent-soft)] text-xs font-semibold text-[var(--accent)] transition hover:opacity-80"
      >
        {initials || "?"}
      </button>
      {open && (
        <div
          role="menu"
          className="card absolute right-0 top-9 z-30 w-52 p-2 text-sm shadow-[var(--shadow)]"
        >
          <p className="px-2 py-1 font-medium text-[var(--ink)]">
            {user.display_name}
          </p>
          <p className="truncate px-2 pb-2 text-xs text-[var(--muted)]">
            {user.email}
          </p>
          <button
            role="menuitem"
            onClick={async () => {
              setOpen(false);
              await logout();
              router.replace("/login");
            }}
            className="w-full cursor-pointer rounded-md border-t border-[var(--border)] px-2 py-1.5 text-left text-[var(--muted)] transition hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
