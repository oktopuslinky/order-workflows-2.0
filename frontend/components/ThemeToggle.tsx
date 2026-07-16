"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

/** Header button that flips the light/dark theme and persists the choice.
 *
 * The active theme lives as a `data-theme` attribute on <html>, set before
 * first paint by the inline script in the layout. This component reads that
 * attribute on mount and toggles it, writing the choice to localStorage. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const current = document.documentElement.dataset.theme;
    setTheme(current === "dark" ? "dark" : "light");
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* ignore storage failures (private mode, etc.) */
    }
    setTheme(next);
  }

  const isDark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title="Toggle light / dark"
      className="rounded-md px-2.5 py-1 text-[var(--muted)] transition hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
    >
      {isDark ? "☀ Light" : "☾ Dark"}
    </button>
  );
}
