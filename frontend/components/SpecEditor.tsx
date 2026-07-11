"use client";

import { markdown } from "@codemirror/lang-markdown";
import { EditorView } from "@codemirror/view";
import dynamic from "next/dynamic";
import { useMemo } from "react";

// CodeMirror touches browser APIs at import time — load it browser-only.
const CodeMirror = dynamic(() => import("@uiw/react-codemirror"), {
  ssr: false,
  loading: () => (
    <div className="p-4 text-sm text-slate-400">Loading editor…</div>
  ),
});

export function SpecEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const extensions = useMemo(
    () => [markdown(), EditorView.lineWrapping],
    [],
  );
  return (
    <div className="h-full overflow-auto text-sm">
      <CodeMirror
        value={value}
        extensions={extensions}
        onChange={onChange}
        theme="none"
        basicSetup={{ lineNumbers: true, foldGutter: false }}
        style={{ height: "100%" }}
      />
    </div>
  );
}
