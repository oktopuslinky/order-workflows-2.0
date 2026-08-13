"use client";

import type { SuggestedOption } from "@/lib/types";

/**
 * Candidate answers, offered as a starting point rather than a menu.
 *
 * Shared by both doors to the spec gate — the guided dialogue's questions and
 * the free-form chat's clarifying questions — for the same reason their spec
 * bookkeeping is shared: the two must not be able to drift on how a suggestion
 * behaves.
 *
 * Picking one fills the answer box; it does not send. That keeps a stray click
 * from patching the specification, and leaves the suggestion editable — which
 * matters, because these come from the model and the user is the one with the
 * authority here.
 */
export function SuggestedAnswers({
  options,
  picked,
  disabled,
  hint = "Some likely answers — pick one to edit and send, or just write your own.",
  onPick,
}: {
  options: SuggestedOption[];
  /** Label of the option currently loaded in the box, if it is still unedited. */
  picked: string | null;
  disabled: boolean;
  hint?: string;
  onPick: (option: SuggestedOption) => void;
}) {
  if (options.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs text-[var(--faint)]">{hint}</p>
      <div className="flex flex-col gap-1.5" data-testid="dialogue-options">
        {options.map((option) => {
          const active = option.label === picked;
          return (
            <button
              key={option.label}
              type="button"
              onClick={() => onPick(option)}
              disabled={disabled}
              aria-pressed={active}
              className={`rounded-md border px-2.5 py-1.5 text-left text-sm transition-colors disabled:opacity-60 ${
                active
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-strong)]"
              }`}
            >
              <span className="text-[var(--ink)]">{option.label}</span>
              {option.detail && (
                <span className="mt-0.5 block text-xs text-[var(--muted)]">
                  {option.detail}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
