import type { QueryResponse } from "@/lib/types";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-slate-800">{value}</p>
    </div>
  );
}

export default function MetadataBar({ result }: { result: QueryResponse }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat label="Rows" value={result.row_count.toLocaleString()} />
      <Stat label="Runtime" value={`${result.runtime_ms.toFixed(2)} ms`} />
      <Stat label="Dialect" value={result.dialect} />
      <Stat label="Intent" value={result.intent ?? "unmatched"} />
    </div>
  );
}
