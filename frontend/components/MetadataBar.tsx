import type { QueryResponse } from "@/lib/types";

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "hit" | "miss" | "muted";
}) {
  const valueClass =
    tone === "hit"
      ? "text-emerald-600"
      : tone === "miss" || tone === "muted"
        ? "text-slate-500"
        : "text-slate-800";
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className={"mt-0.5 truncate text-sm font-semibold " + valueClass}>{value}</p>
    </div>
  );
}

function formatCost(cost: number): string {
  return cost === 0 ? "Free" : `$${cost.toFixed(6)}`;
}

export default function MetadataBar({ result }: { result: QueryResponse }) {
  const cacheHit = result.cache_hit === true;
  const score = result.cache_match_score ?? 0;
  // "Hit (exact)" for an exact match, "Hit (0.92)" for a semantic near-duplicate.
  const cacheValue = cacheHit
    ? score >= 1
      ? "Hit (exact)"
      : `Hit (${score.toFixed(2)})`
    : "Miss";
  const t = result.telemetry ?? null;
  const provider = t?.provider ?? result.generator;
  const cost = t ? formatCost(t.estimated_cost_usd) : "—";

  // Self-check status from the sample execution loop.
  let selfCheck = "—";
  let selfCheckTone: "hit" | "miss" | "muted" | undefined = "muted";
  if (result.sample_checked) {
    if (result.repair_successful) {
      selfCheck = "Repaired";
      selfCheckTone = "hit";
    } else if (result.repair_attempted) {
      selfCheck = "Failed";
      selfCheckTone = "miss";
    } else {
      selfCheck = "Passed";
      selfCheckTone = "hit";
    }
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Stat label="Rows" value={result.row_count.toLocaleString()} />
      <Stat label="Runtime" value={`${result.runtime_ms.toFixed(2)} ms`} />
      <Stat label="Provider" value={provider} />
      <Stat label="Cache" value={cacheValue} tone={cacheHit ? "hit" : "miss"} />
      <Stat label="Est. cost" value={cost} tone={cost === "Free" ? "muted" : undefined} />
      <Stat label="Self-check" value={selfCheck} tone={selfCheckTone} />
      <Stat label="Intent" value={result.intent ?? "unmatched"} />
    </div>
  );
}
