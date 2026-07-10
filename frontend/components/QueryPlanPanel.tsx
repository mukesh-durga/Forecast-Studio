import type { QueryPlan } from "@/lib/types";

function Chips({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((v) => (
        <span key={v} className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600">
          {v}
        </span>
      ))}
    </div>
  );
}

function Row({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="grid grid-cols-[7rem_1fr] items-start gap-3 py-1.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd>
        <Chips items={items} />
      </dd>
    </div>
  );
}

/** Collapsible, debug-only view of the structured query plan. */
export default function QueryPlanPanel({ plan }: { plan: QueryPlan }) {
  return (
    <details className="group overflow-hidden rounded-2xl border border-hairline bg-white shadow-card">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50">
        <span className="flex items-center gap-2">
          Query plan
          <span className="rounded-full bg-blue-50 px-2 py-0.5 font-mono text-xs font-medium text-primary">
            {plan.intent}
          </span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-xs font-medium text-slate-500">
            confidence {Math.round(plan.confidence * 100)}%
          </span>
        </span>
        <span className="text-slate-400 transition-transform group-open:rotate-180" aria-hidden>
          ▾
        </span>
      </summary>
      <dl className="border-t border-hairline px-5 py-3">
        <Row label="Connection" items={plan.target_connection ? [plan.target_connection] : []} />
        <Row label="Tables" items={plan.required_tables} />
        <Row label="Columns" items={plan.required_columns} />
        <Row label="Joins" items={plan.joins} />
        <Row label="Measures" items={plan.measures} />
        <Row label="Dimensions" items={plan.dimensions} />
        <Row label="Filters" items={plan.filters} />
        <Row label="Group by" items={plan.group_by} />
        <Row label="Order by" items={plan.order_by} />
        <Row label="Limit" items={plan.limit === null ? [] : [String(plan.limit)]} />
        <Row label="Result cols" items={plan.expected_result_columns} />
      </dl>
    </details>
  );
}
