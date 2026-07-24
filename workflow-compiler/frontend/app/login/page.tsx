"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Mode = "signin" | "register";

export default function LoginPage() {
  const router = useRouter();
  const { setUser } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function validateEmail(): boolean {
    const ok = /.+@.+\..+/.test(email.trim());
    setFieldErrors((e) => ({
      ...e,
      email: ok || email === "" ? "" : "Enter a valid email address.",
    }));
    return ok;
  }

  function validatePassword(): boolean {
    const ok = mode === "signin" || password.length >= 8;
    setFieldErrors((e) => ({
      ...e,
      password:
        ok || password === "" ? "" : "Use at least 8 characters.",
    }));
    return ok;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!validateEmail() || !validatePassword()) {
      const invalid = document.querySelector<HTMLInputElement>(
        "input[aria-invalid='true']",
      );
      invalid?.focus();
      return;
    }
    setBusy(true);
    try {
      const user =
        mode === "signin"
          ? await api.login(email.trim(), password)
          : await api.register(email.trim(), password, displayName.trim());
      setUser(user);
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next && next.startsWith("/") ? next : "/");
    } catch (err) {
      setFormError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setFormError(null);
    setFieldErrors({});
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-[var(--paper)] p-6">
      <div className="w-full max-w-sm">
        <p className="mb-6 text-center font-semibold tracking-tight">
          workflow<span className="text-[var(--accent)]">·</span>compiler
        </p>
        <div className="card p-5">
          <div className="seg mb-4 grid grid-cols-2 text-sm">
            <button
              onClick={() => switchMode("signin")}
              className={mode === "signin" ? "seg-active" : ""}
              type="button"
            >
              Sign in
            </button>
            <button
              onClick={() => switchMode("register")}
              className={mode === "register" ? "seg-active" : ""}
              type="button"
            >
              Create account
            </button>
          </div>

          <form onSubmit={submit} noValidate className="flex flex-col gap-3">
            <div>
              <label htmlFor="login-email" className="mb-1 block text-xs font-medium text-[var(--muted)]">
                Email
              </label>
              <input
                id="login-email"
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onBlur={validateEmail}
                aria-invalid={Boolean(fieldErrors.email) || undefined}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1.5 text-sm"
              />
              {fieldErrors.email && (
                <p role="alert" className="mt-1 text-xs text-[var(--block)]">
                  {fieldErrors.email}
                </p>
              )}
            </div>

            {mode === "register" && (
              <div>
                <label htmlFor="login-name" className="mb-1 block text-xs font-medium text-[var(--muted)]">
                  Display name{" "}
                  <span className="font-normal text-[var(--faint)]">
                    (shown as author on edits)
                  </span>
                </label>
                <input
                  id="login-name"
                  autoComplete="name"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="defaults to your email name"
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1.5 text-sm"
                />
              </div>
            )}

            <div>
              <label htmlFor="login-password" className="mb-1 block text-xs font-medium text-[var(--muted)]">
                Password
                {mode === "register" && (
                  <span className="font-normal text-[var(--faint)]"> — at least 8 characters</span>
                )}
              </label>
              <div className="relative">
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={mode === "signin" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onBlur={validatePassword}
                  aria-invalid={Boolean(fieldErrors.password) || undefined}
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1.5 pr-14 text-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute inset-y-0 right-2 cursor-pointer text-xs text-[var(--faint)] hover:text-[var(--accent)]"
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              {fieldErrors.password && (
                <p role="alert" className="mt-1 text-xs text-[var(--block)]">
                  {fieldErrors.password}
                </p>
              )}
            </div>

            {formError && (
              <p role="alert" className="tone-block rounded-md border p-2 text-xs">
                {formError}
              </p>
            )}

            <button type="submit" disabled={busy} className="btn btn-gate mt-1 w-full">
              {busy
                ? mode === "signin"
                  ? "Signing in…"
                  : "Creating account…"
                : mode === "signin"
                  ? "Sign in"
                  : "Create account"}
            </button>
          </form>
        </div>
        <p className="mt-4 text-center text-xs text-[var(--faint)]">
          Local accounts — stored on this machine, no external services.
        </p>
      </div>
    </div>
  );
}
