"use client";

interface QueryBoxProps {
  question: string;
  onChange: (value: string) => void;
  onRun: () => void;
  loading: boolean;
}

function PromptIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 7l3 3-3 3M11 13h4" />
    </svg>
  );
}

function RunIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
      <path d="M5 3.5l11 6.5-11 6.5v-13z" />
    </svg>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[11px] font-medium text-slate-500 shadow-sm">
      {children}
    </kbd>
  );
}

export default function QueryBox({ question, onChange, onRun, loading }: QueryBoxProps) {
  const canRun = question.trim().length > 0 && !loading;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Cmd/Ctrl + Enter runs the query.
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canRun) {
      e.preventDefault();
      onRun();
    }
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-hairline bg-white shadow-card">
      {/* Command bar header */}
      <div className="flex items-center justify-between gap-3 border-b border-hairline/70 bg-gradient-to-b from-slate-50 to-white px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <PromptIcon />
          </span>
          <label htmlFor="question" className="text-sm font-semibold text-slate-800">
            Ask a question
          </label>
        </div>
        <span className="hidden font-mono text-[11px] uppercase tracking-wider text-slate-400 sm:block">
          natural language → SQL
        </span>
      </div>

      {/* Input */}
      <div className="p-5">
        <div className="relative">
          <span
            className="pointer-events-none absolute left-4 top-3 font-mono text-lg leading-none text-primary/50"
            aria-hidden
          >
            ›
          </span>
          <textarea
            id="question"
            value={question}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={3}
            placeholder="e.g. What are the top 5 products by revenue?"
            className="w-full resize-y rounded-xl border border-slate-200 bg-canvas/60 py-3 pl-9 pr-4 text-[15px] leading-relaxed text-slate-800 outline-none transition-colors placeholder:text-slate-400 focus:border-primary/50 focus:bg-white focus:ring-4 focus:ring-primary/10"
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <span>Run with</span>
            <Kbd>⌘</Kbd>
            <span className="text-slate-300">/</span>
            <Kbd>Ctrl</Kbd>
            <span>+</span>
            <Kbd>Enter</Kbd>
          </div>

          <div className="flex items-center gap-2">
            {question.length > 0 && !loading && (
              <button
                onClick={() => onChange("")}
                className="rounded-lg px-3 py-2 text-sm font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
              >
                Clear
              </button>
            )}
            <button
              onClick={onRun}
              disabled={!canRun}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white shadow-card transition-all hover:bg-primary-hover hover:shadow-card-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
            >
              {loading ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                  Running…
                </>
              ) : (
                <>
                  <RunIcon />
                  Run query
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
