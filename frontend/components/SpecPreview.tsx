"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function SpecPreview({ markdown }: { markdown: string }) {
  return (
    <div className="prose-spec h-full overflow-auto p-4 text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  );
}
