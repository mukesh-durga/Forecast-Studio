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

function confidenceTier(c: number): string {
  if (c >= 0.85) return "High";
  if (c >= 0.6) return "Medium";
  return "Low";
}

function ShieldCheck() {
  return (
    <svg viewBox="0 0 20 20" className="h-5 w-5" fill="currentColor" aria-hidden>
      <path d="M10 1.5l6.2 2.2v4.8c0 3.9-2.6 7.4-6.2 8.6-3.6-1.2-6.2-4.7-6.2-8.6V3.7L10 1.5z" opacity="0.16" />
      <path
        fillRule="evenodd"
        d="M13.7 7.7a1 1 0 00-1.4-1.4L9 9.6 7.7 8.3a1 1 0 10-1.4 1.4l2 2a1 1 0 001.4 0l4-4z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function ShieldAlert() {
  return (
    <svg viewBox="0 0 20 20" className="h-5 w-5" fill="currentColor" aria-hidden>
      <path d="M10 1.5l6.2 2.2v4.8c0 3.9-2.6 7.4-6.2 8.6-3.6-1.2-6.2-4.7-6.2-8.6V3.7L10 1.5z" opacity="0.16" />
      <path d="M10 6a1 1 0 00-1 1v3a1 1 0 102 0V7a1 1 0 00-1-1zm0 7.4a1.05 1.05 0 100-2.1 1.05 1.05 0 000 2.1z" />
    </svg>
  );
}

export default function AnswerCard({ result }: { result: QueryResponse }) {
  const v = result.verification;
  if (!v) return null; // nothing to show when no verification (e.g. unsupported)
  const { verified, confidence, explanation, failure_reason } = v;
  const pct = Math.round(confidence * 100);

  return (
    <div className="overflow-hidden rounded-2xl border border-hairline bg-white shadow-card">
      {/* Answer + quick status */}
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between sm:p-6">
        <div className="min-w-0">
          <p className="font-mono text-xs font-medium uppercase tracking-widest text-slate-400">Answer</p>
          <p className="mt-1.5 text-xl font-semibold leading-snug text-slate-900 sm:text-2xl">
            {summarize(result)}
          </p>
        </div>
        <VerificationBadge verification={v} />
      </div>

      {/* Verification panel — the product differentiator */}
      <div
        className={
          "border-t px-5 py-4 sm:px-6 " +
          (verified ? "border-emerald-100 bg-emerald-50/50" : "border-amber-100 bg-amber-50/50")
        }
      >
        <div className="flex items-start gap-3">
          <span
            className={
              "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full " +
              (verified ? "bg-emerald-100 text-emerald-600" : "bg-amber-100 text-amber-600")
            }
          >
            {verified ? <ShieldCheck /> : <ShieldAlert />}
          </span>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <p
                className={
                  "text-sm font-semibold " + (verified ? "text-emerald-800" : "text-amber-800")
                }
              >
                {verified ? "Answer verified against the question" : "Answer needs review"}
              </p>

              {/* Confidence meter */}
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-slate-500">{confidenceTier(confidence)}</span>
                <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200">
                  <div
                    className={"h-full rounded-full " + (verified ? "bg-emerald-500" : "bg-amber-500")}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-9 text-right text-sm font-semibold tabular-nums text-slate-700">
                  {pct}%
                </span>
              </div>
            </div>

            <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{explanation}</p>

            {failure_reason && (
              <div className="mt-2.5 inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-white/70 px-2.5 py-1">
                <span className="text-xs font-medium text-amber-700">Reason</span>
                <code className="font-mono text-xs text-slate-600">{failure_reason}</code>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
