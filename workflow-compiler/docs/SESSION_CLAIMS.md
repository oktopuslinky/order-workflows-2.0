# Session claims — two Claude Code sessions running concurrently

**Written:** 2026-08-11 · **Author:** the *run-workflows* session

Two sessions are working on this codebase at the same time. This file records who owns
what, so neither clobbers the other. It is deliberately short — read it once, act on it,
ignore it afterwards.

| | Session A — **pipeline** | Session B — **run-workflows** |
|---|---|---|
| Handoff | `docs/PIPELINE_HANDOFF.md` | `docs/RUN_WORKFLOWS_HANDOFF.md` |
| Worktree | `order-workflows-dialogue` (this one) | `order-workflows-run` (sibling) |
| Branch | `feat/spec-dialogue` | `feat/run-workflows` (off `f74b9de`) |
| Backend / frontend / Temporal | `:8000` / `:3000` / `:7233` | `:8001` / `:3001` / `:7234` |

**Session B works in a separate worktree, so it is not editing the files in this
directory at all.** The claims below are about the *merge* at the end, and about not
starting fresh work on the same lines in the meantime.

---

## Files claimed by Session B (run-workflows)

Please don't edit these on `feat/spec-dialogue` without saying so — Session B has changes
landing in them.

**Modified:**

- `src/workflow_compiler/codegen/temporal/generator.py` — extends `_workflow_input_fields`
  to feed sample values into the starter (RUN_WORKFLOWS §7). **This is the one real
  overlap:** commit `ed5d0e7` fixed §6.1 in that same function.
- `src/workflow_compiler/codegen/temporal/templates/starter.py.jinja`
- `src/workflow_compiler/api/app.py` — **additive only**, a new block of `/runs` routes
  appended inside `create_app()`. No edits to existing routes.
- `src/workflow_compiler/api/schemas.py`, `src/workflow_compiler/config.py` — additive.
- `frontend/components/ResultsView.tsx` — the Run control mounts here.
- `frontend/lib/api.ts`, `frontend/lib/types.ts` — additive.
- `frontend/app/projects/[id]/page.tsx` — **at most one line**, and only if unavoidable.

**New files** (no conflict possible):

- `src/workflow_compiler/interfaces/executor.py`, `src/workflow_compiler/execution/**`
- `frontend/components/RunPanel.tsx`
- `tests/test_executor.py`, `tests/test_api_runs.py`, `tests/test_codegen_starter.py`

## Files Session B will not touch

Everything else — in particular `dialogue/**`, `agents/dialogue.py`, `agents/spec_chat.py`,
`models/**`, `spec/**`, `project_compiler.py`, `frontend/components/DialoguePanel.tsx`,
`frontend/components/SpecChatPanel.tsx`, `demo/capture2/**`, `docs/PIPELINE_HANDOFF.md`,
and `docs/PIPELINE_RUN_LOG.md`.

## Runtime

Session B runs its **own** Temporal server on `:7234` and never touches the `:7233`
server, its namespace, or the `worker.py` processes currently attached to it. Likewise it
will not start or stop anything on `:8000` or `:3000`.

## Merge

Session B merges `feat/run-workflows` into `feat/spec-dialogue` **after** Session A has
finished committing, so conflicts are resolved against a settled tree rather than a moving
one. Session A does not need to do anything.
