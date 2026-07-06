"use client";

interface QueryBoxProps {
  question: string;
  onChange: (value: string) => void;
  onRun: () => void;
  loading: boolean;
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
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <label htmlFor="question" className="text-sm font-semibold text-slate-700">
        Ask a question
      </label>
      <textarea
        id="question"
        value={question}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={3}
        placeholder="e.g. What are the top 5 products by revenue?"
        className="mt-2 w-full resize-y rounded-xl border border-slate-300 px-4 py-3 text-slate-800 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
      />
      <div className="mt-3 flex items-center justify-between">
        <span className="text-xs text-slate-400">Press ⌘/Ctrl + Enter to run</span>
        <button
          onClick={onRun}
          disabled={!canRun}
          className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {loading && (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
          )}
          {loading ? "Running…" : "Run query"}
        </button>
      </div>
    </div>
  );
}
