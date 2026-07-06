"use client";

import { useState } from "react";

export default function SqlPanel({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard may be unavailable; ignore
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Generated SQL
        </span>
        <button
          onClick={copy}
          className="rounded-md px-2 py-1 text-xs font-medium text-slate-300 transition hover:bg-slate-800 hover:text-white"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-3 text-sm leading-relaxed text-emerald-300">
        <code>{sql}</code>
      </pre>
    </div>
  );
}
