"use client";

import { useState } from "react";

const KEYWORDS = new Set([
  "select", "from", "where", "group", "by", "order", "on", "as", "and", "or",
  "not", "in", "is", "null", "limit", "offset", "desc", "asc", "distinct",
  "having", "join", "left", "right", "inner", "outer", "case", "when", "then",
  "else", "end", "union", "all",
]);

const FUNCTIONS = new Set([
  "sum", "count", "avg", "min", "max", "strftime", "round", "coalesce",
  "cast", "abs", "length", "upper", "lower",
]);

/** Tokenize SQL into colored React nodes (no HTML injection). */
function highlight(sql: string): React.ReactNode[] {
  const re = /('(?:[^']|'')*')|(\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(\s+)|([^\sA-Za-z0-9_'])/g;
  const nodes: React.ReactNode[] = [];
  let m: RegExpExecArray | null;
  let i = 0;

  while ((m = re.exec(sql)) !== null) {
    const [, str, num, word, ws, punct] = m;
    const key = i++;
    if (str) {
      nodes.push(<span key={key} className="text-amber-300">{str}</span>);
    } else if (num) {
      nodes.push(<span key={key} className="text-orange-300">{num}</span>);
    } else if (word) {
      const lw = word.toLowerCase();
      if (KEYWORDS.has(lw)) nodes.push(<span key={key} className="font-medium text-sky-300">{word}</span>);
      else if (FUNCTIONS.has(lw)) nodes.push(<span key={key} className="text-violet-300">{word}</span>);
      else nodes.push(<span key={key} className="text-slate-200">{word}</span>);
    } else if (ws) {
      nodes.push(ws);
    } else {
      nodes.push(<span key={key} className="text-slate-500">{punct}</span>);
    }
  }
  return nodes;
}

function DbIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <ellipse cx="10" cy="4.5" rx="6" ry="2.5" />
      <path d="M4 4.5v11c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-11M4 10c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" />
    </svg>
  );
}

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
    <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-card">
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/80 px-4 py-2.5">
        <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          <DbIcon />
          Generated SQL
        </span>
        <button
          onClick={copy}
          className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-slate-300 transition-colors hover:bg-slate-800 hover:text-white"
        >
          {copied ? (
            <>
              <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 text-emerald-400" fill="currentColor" aria-hidden>
                <path fillRule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 011.4-1.4l3.3 3.3 6.8-6.8a1 1 0 011.4 0z" clipRule="evenodd" />
              </svg>
              Copied
            </>
          ) : (
            <>
              <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor" aria-hidden>
                <path d="M7 3a2 2 0 00-2 2v8a2 2 0 002 2h6a2 2 0 002-2V7.8a2 2 0 00-.6-1.4l-2.8-2.8A2 2 0 0010.2 3H7z" opacity="0.4" />
                <path d="M4 6a2 2 0 012-2v10a2 2 0 002 2h5a2 2 0 01-2 2H6a2 2 0 01-2-2V6z" />
              </svg>
              Copy
            </>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words px-4 py-3.5 text-[13px] leading-relaxed text-slate-200">
        <code>{highlight(sql)}</code>
      </pre>
    </div>
  );
}
