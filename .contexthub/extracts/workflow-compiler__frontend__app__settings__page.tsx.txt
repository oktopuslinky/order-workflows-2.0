"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Skeleton } from "@/components/Skeleton";
import type { UserPreferences } from "@/lib/types";

type Theme = "light" | "dark";

// Labels + one-line help for each time-saved baseline category. Keys mirror the
// metric buckets in metrics.py / config.py Settings.baseline_hours.
const CATEGORY_META: Record<string, { label: string; help: string }> = {
  discovery: { label: "Discovery", help: "Document analysis + workflow discovery, per project." },
  spec: { label: "Spec drafting", help: "Fact extraction + spec drafting, per workflow." },
  validate: { label: "Validate", help: "Review + consistency check, per validate pass." },
  compile: { label: "Compile", help: "Graph + CVPA + Temporal design + code, per workflow." },
  edit: { label: "Edit", help: "Analysis + re-spec + re-review, per edit section." },
};

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

export default function SettingsPage() {
  const { user, setUser } = useAuth();
  const defaults = useQuery({
    queryKey: ["settings-defaults"],
    queryFn: () => api.settingsDefaults(),
  });

  // Local form state, seeded from the signed-in user (present on this guarded route).
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [pageSize, setPageSize] = useState<number>(
    user?.preferences.projects_page_size ?? 10,
  );
  // Baseline overrides as raw strings: "" means "inherit the org default".
  const [overrides, setOverrides] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(user?.preferences.baseline_hours ?? {}).map(([k, v]) => [
        k,
        String(v),
      ]),
    ),
  );
  const [theme, setTheme] = useState<Theme>("light");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    // Sync the toggle to the theme the pre-paint script already applied to
    // <html>. Done post-mount (not during render) so it can't cause a
    // hydration mismatch — matching ThemeToggle's approach.
    const current = document.documentElement.dataset.theme;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(current === "dark" ? "dark" : "light");
  }, []);

  const baselineKeys = useMemo(
    () => Object.keys(defaults.data?.baseline_hours ?? {}),
    [defaults.data],
  );

  function applyTheme(next: Theme) {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* ignore storage failures (private mode, etc.) */
    }
    setTheme(next);
  }

  const save = useMutation({
    mutationFn: () => {
      // Keep only well-formed positive overrides; blanks inherit the default.
      const baseline_hours: Record<string, number> = {};
      for (const [key, raw] of Object.entries(overrides)) {
        const trimmed = raw.trim();
        if (trimmed === "") continue;
        const n = Number(trimmed);
        if (Number.isFinite(n) && n >= 0) baseline_hours[key] = n;
      }
      const preferences: UserPreferences = {
        baseline_hours,
        projects_page_size: pageSize,
      };
      return api.updateProfile({
        display_name: displayName.trim() || undefined,
        preferences,
      });
    },
    onSuccess: (updated) => {
      setUser(updated);
      setSaved(true);
    },
  });

  function resetBaselines() {
    setOverrides({});
    setSaved(false);
  }

  const nameInvalid = displayName.trim().length === 0;

  return (
    <div className="mx-auto max-w-2xl p-6">
      <header className="mb-6">
        <p className="eyebrow mb-2">Settings</p>
        <h1 className="text-2xl font-[650] tracking-[-0.02em]">
          Profile &amp; preferences
        </h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Personalize your account and tune how the time-saved metric is
          calculated for your team.
        </p>
      </header>

      {/* Profile */}
      <section className="card mb-5 p-5">
        <h2 className="text-base font-semibold">Profile</h2>
        <div className="mt-4 grid gap-4">
          <label className="grid gap-1.5">
            <span className="text-sm text-[var(--muted)]">Display name</span>
            <input
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                setSaved(false);
              }}
              className="rounded-md border border-[var(--border-strong)] bg-transparent px-3 py-1.5 text-sm outline-none focus:border-[var(--accent)]"
            />
            {nameInvalid && (
              <span className="text-xs text-[var(--block)]">
                Display name can’t be empty.
              </span>
            )}
            <span className="text-xs text-[var(--faint)]">
              Shown in the UI and recorded as author/reviewer on your work.
            </span>
          </label>

          <div className="grid gap-1.5">
            <span className="text-sm text-[var(--muted)]">Theme</span>
            <div className="seg w-fit" role="group" aria-label="Theme">
              <button
                type="button"
                className={theme === "light" ? "seg-active" : ""}
                aria-pressed={theme === "light"}
                onClick={() => applyTheme("light")}
              >
                ☾ Light
              </button>
              <button
                type="button"
                className={theme === "dark" ? "seg-active" : ""}
                aria-pressed={theme === "dark"}
                onClick={() => applyTheme("dark")}
              >
                ☀ Dark
              </button>
            </div>
            <span className="text-xs text-[var(--faint)]">
              Applies instantly and is remembered on this browser.
            </span>
          </div>
        </div>
      </section>

      {/* Time-saved baselines */}
      <section className="card mb-5 p-5">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold">Time-saved baselines</h2>
          <button
            type="button"
            onClick={resetBaselines}
            className="btn btn-ghost px-2 py-1 text-xs"
          >
            Reset to defaults
          </button>
        </div>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Estimated hours a human team would spend per pipeline step. The
          time-saved figure compares your measured pipeline runs against these.
          Leave a field blank to inherit the default; enter your own for a more
          realistic estimate.
        </p>

        {defaults.isLoading && (
          <div className="mt-4 grid gap-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        )}

        {defaults.error && (
          <p className="mt-3 text-sm text-[var(--block)]">
            {(defaults.error as ApiError).message}
          </p>
        )}

        {defaults.data && (
          <div className="mt-4 grid gap-2.5">
            {baselineKeys.map((key) => {
              const meta = CATEGORY_META[key];
              const def = defaults.data!.baseline_hours[key];
              return (
                <div
                  key={key}
                  className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-lg border border-[var(--border)] px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-[var(--ink)]">
                      {meta?.label ?? key}
                    </p>
                    <p className="text-xs text-[var(--faint)]">
                      {meta?.help ?? key}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min={0}
                      step="0.5"
                      inputMode="decimal"
                      value={overrides[key] ?? ""}
                      placeholder={String(def)}
                      aria-label={`${meta?.label ?? key} baseline hours (default ${def})`}
                      onChange={(e) => {
                        setOverrides((o) => ({ ...o, [key]: e.target.value }));
                        setSaved(false);
                      }}
                      className="w-20 rounded-md border border-[var(--border-strong)] bg-transparent px-2 py-1 text-right text-sm [font-variant-numeric:tabular-nums] outline-none focus:border-[var(--accent)]"
                    />
                    <span className="w-20 shrink-0 text-xs text-[var(--faint)]">
                      hrs · def {def}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Projects list */}
      <section className="card mb-5 p-5">
        <h2 className="text-base font-semibold">Projects list</h2>
        <label className="mt-3 flex items-center justify-between gap-3">
          <span className="text-sm text-[var(--muted)]">
            Projects shown per page
          </span>
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setSaved(false);
            }}
            className="cursor-pointer rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-sm outline-none focus:border-[var(--accent)]"
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </section>

      {/* Save bar */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={save.isPending || nameInvalid}
          onClick={() => save.mutate()}
          className="btn btn-primary px-4 py-2"
        >
          {save.isPending ? "Saving…" : "Save changes"}
        </button>
        {saved && !save.isPending && (
          <span className="text-sm text-[var(--pass)]">Saved ✓</span>
        )}
        {save.error && (
          <span className="text-sm text-[var(--block)]">
            {(save.error as ApiError).message}
          </span>
        )}
        <Link href="/" className="link-accent ml-auto text-sm">
          ← Back to projects
        </Link>
      </div>
    </div>
  );
}
