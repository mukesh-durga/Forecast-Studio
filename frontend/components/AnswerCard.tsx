import type { QueryResponse } from "@/lib/types";
import VerificationBadge from "./VerificationBadge";

/** Build a short, human-readable answer from the result rows (UI-only, no LLM). */
function summarize(res: QueryResponse): string {
  const { columns, rows, row_count } = res;
  if (row_count === 0 || rows.length === 0) return "The query returned no rows.";

  const first = rows[0];

  // Single value (e.g. a count or average).
  if (columns.length === 1) {
    const c = columns[0];
    return `${c.replace(/_/g, " ")}: ${format(first[c])}`;
  }

  // Label + metric (e.g. product_name + revenue).
  const label = columns[0];
  const metric = columns[columns.length - 1];
  const lead = `${format(first[label])} — ${metric.replace(/_/g, " ")}: ${format(first[metric])}`;
  return row_count > 1 ? `Top result: ${lead}` : lead;
}

function format(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(v);
}

export default function AnswerCard({ result }: { result: QueryResponse }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Answer</p>
          <p className="mt-1 text-lg font-semibold text-slate-900">{summarize(result)}</p>
        </div>
        <VerificationBadge verification={result.verification} />
      </div>
      <p className="mt-3 border-t border-slate-100 pt-3 text-sm text-slate-500">
        {result.verification.explanation}
        {result.verification.failure_reason ? (
          <span className="ml-1 text-amber-600">({result.verification.failure_reason})</span>
        ) : null}
      </p>
    </div>
  );
}
