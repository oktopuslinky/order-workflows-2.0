"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { COMPILE_STEPS, shortId } from "@/lib/format";
import { RunningOverlay } from "@/components/RunningOverlay";

export default function HomePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
  });

  const compile = useMutation({
    mutationFn: () => (file ? api.compileUpload(file) : api.compileText(text)),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${data.project.project_id}`);
    },
  });

  const canCompile =
    (file !== null || text.trim().length > 0) && !compile.isPending;

  return (
    <div className="mx-auto max-w-5xl p-6">
      <header className="mb-6">
        <p className="eyebrow mb-2">Workflow compiler</p>
        <h1 className="text-3xl font-[650] tracking-[-0.02em]">
          Turn a workflow doc into runnable Temporal code
        </h1>
        <p className="mt-2 max-w-2xl text-[var(--muted)]">
          Upload a document, edit the extracted specs at the human gate, then
          approve to generate code.{" "}
          <Link href="/guide" className="link-accent">
            Read the spec guide →
          </Link>
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[1.3fr_1fr]">
        {/* New project */}
        <section className="card relative p-5">
          {compile.isPending && (
            <RunningOverlay title="Compiling document" steps={COMPILE_STEPS} />
          )}
          <h2 className="text-lg font-semibold">New project</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            .docx / .pdf / .md / .html / .txt, or paste text. The compiler
            segments it into one editable spec per workflow.
          </p>

        <label
          className="mt-4 flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-[var(--border-strong)] px-4 py-6 text-center text-sm transition hover:border-[var(--accent)] hover:bg-[var(--accent-soft)]/40"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files?.[0];
            if (f) {
              setFile(f);
              setText("");
            }
          }}
        >
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            accept=".docx,.pdf,.md,.markdown,.html,.htm,.txt"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f) setText("");
            }}
          />
          {file ? (
            <span className="font-medium text-[var(--accent)]">{file.name}</span>
          ) : (
            <span className="text-[var(--muted)]">
              Drag a file here, or click to choose
            </span>
          )}
        </label>

        <div className="my-3 flex items-center gap-3 text-xs text-[var(--faint)]">
          <span className="h-px flex-1 bg-[var(--border)]" /> or paste
          text <span className="h-px flex-1 bg-[var(--border)]" />
        </div>

        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            if (e.target.value) {
              setFile(null);
              if (fileInput.current) fileInput.current.value = "";
            }
          }}
          placeholder="When a customer submits an order, validate payment, then ship it…"
          className="h-32 w-full resize-y rounded-lg border border-[var(--border-strong)] bg-transparent p-3 font-mono text-sm outline-none focus:border-[var(--accent)]"
        />

        {compile.error && (
          <p className="mt-2 text-sm text-[var(--block)]">
            {(compile.error as ApiError).message}
          </p>
        )}

          <button
            disabled={!canCompile}
            onClick={() => compile.mutate()}
            className="btn btn-primary mt-4 w-full justify-center py-2"
          >
            Compile
          </button>
        </section>

        {/* Existing projects */}
        <section className="card p-5">
          <h2 className="text-lg font-semibold">Projects</h2>
          {projects.isLoading && (
            <p className="mt-3 text-sm text-[var(--muted)]">Loading…</p>
          )}
          {projects.error && (
            <p className="mt-3 text-sm text-[var(--block)]">
              {(projects.error as ApiError).message}
            </p>
          )}
          {projects.data && projects.data.project_ids.length === 0 && (
            <p className="mt-3 text-sm text-[var(--muted)]">
              No projects yet. Compile a document to begin.
            </p>
          )}
          <ul className="mt-3 flex flex-col gap-2">
            {projects.data?.project_ids.map((id) => (
              <li key={id}>
                <Link
                  href={`/projects/${id}`}
                  className="block rounded-lg border border-[var(--border)] px-3 py-2 font-mono text-sm text-[var(--muted)] transition hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--ink)]"
                >
                  {shortId(id)}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
