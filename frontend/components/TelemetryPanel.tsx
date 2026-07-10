import type { Telemetry } from "@/lib/types";

function ms(v: number) {
  return `${v.toFixed(2)} ms`;
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="grid grid-cols-[11rem_1fr] items-baseline gap-3 py-1">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className={"font-mono text-xs " + (strong ? "font-semibold text-slate-800" : "text-slate-600")}>
        {value}
      </dd>
    </div>
  );
}

/** Collapsible, debug-only per-query telemetry (latencies, tokens, est. cost). */
export default function TelemetryPanel({ telemetry }: { telemetry: Telemetry }) {
  const t = telemetry;
  const cost = t.estimated_cost_usd === 0 ? "Free ($0.00)" : `$${t.estimated_cost_usd.toFixed(6)}`;
  return (
    <details className="group overflow-hidden rounded-2xl border border-hairline bg-white shadow-card">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50">
        <span className="flex items-center gap-2">
          Telemetry
          <span className="rounded-full bg-blue-50 px-2 py-0.5 font-mono text-xs font-medium text-primary">
            {t.provider}
          </span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-xs font-medium text-slate-500">
            {ms(t.total_latency_ms)}
          </span>
        </span>
        <span className="text-slate-400 transition-transform group-open:rotate-180" aria-hidden>
          ▾
        </span>
      </summary>
      <div className="grid gap-6 border-t border-hairline px-5 py-3 sm:grid-cols-2">
        <dl>
          <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-slate-400">Latency</p>
          <Line label="Planner" value={ms(t.planner_latency_ms)} />
          <Line label="Generation" value={ms(t.generation_latency_ms)} />
          <Line label="Sample execution" value={ms(t.sample_execution_latency_ms)} />
          <Line label="Final execution" value={ms(t.final_execution_latency_ms)} />
          <Line label="Verification" value={ms(t.verification_latency_ms)} />
          <Line label="Total" value={ms(t.total_latency_ms)} strong />
        </dl>
        <dl>
          <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-slate-400">Tokens &amp; cost</p>
          <Line label="Cache hit" value={t.cache_hit ? "yes" : "no"} />
          <Line label="Repair attempted" value={t.repair_attempted ? "yes" : "no"} />
          <Line label="Est. prompt tokens" value={String(t.estimated_prompt_tokens)} />
          <Line label="Est. completion tokens" value={String(t.estimated_completion_tokens)} />
          <Line label="Est. total tokens" value={String(t.estimated_total_tokens)} />
          <Line label="Est. cost (USD)" value={cost} strong />
        </dl>
      </div>
    </details>
  );
}
