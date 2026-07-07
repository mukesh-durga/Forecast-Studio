import type { Row } from "@/lib/types";

function isNumeric(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

// Columns whose numeric values represent money → format as currency.
const CURRENCY_RE = /revenue|spend|price|cost|amount|value/i;

const currencyFmt = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

/** Human-readable header: "product_name" → "Product Name". */
function humanize(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function formatCell(v: string | number | boolean | null, currency: boolean): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (currency) return currencyFmt.format(v);
    return Number.isInteger(v)
      ? v.toLocaleString()
      : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(v);
}

export default function ResultTable({ columns, rows }: { columns: string[]; rows: Row[] }) {
  if (columns.length === 0 || rows.length === 0) {
    return (
      <div className="rounded-2xl border border-hairline bg-white p-8 text-center text-sm text-slate-500 shadow-card">
        No rows returned.
      </div>
    );
  }

  // Per-column metadata (computed once): is it numeric? currency?
  const meta = columns.map((key) => {
    const numeric = rows.every((r) => isNumeric(r[key]));
    return { key, numeric, currency: numeric && CURRENCY_RE.test(key) };
  });

  // Inline bar on the last column when it is fully numeric.
  const metricIndex = columns.length - 1;
  const metricNumeric = meta[metricIndex].numeric;
  const maxVal = metricNumeric
    ? Math.max(...rows.map((r) => Math.abs(Number(r[columns[metricIndex]]))), 0)
    : 0;

  return (
    <div className="overflow-hidden rounded-2xl border border-hairline shadow-card">
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="border-b border-hairline bg-gradient-to-b from-slate-50 to-white">
            <tr>
              {meta.map((m) => (
                <th
                  key={m.key}
                  className={
                    "whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 " +
                    (m.numeric ? "text-right" : "text-left")
                  }
                >
                  {humanize(m.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row, i) => (
              <tr
                key={i}
                className={(i % 2 === 1 ? "bg-slate-50/40 " : "bg-white ") + "transition-colors hover:bg-blue-50/60"}
              >
                {meta.map((m, ci) => {
                  const val = row[m.key];
                  const isMetric = ci === metricIndex && metricNumeric;
                  const width = isMetric && maxVal > 0 ? `${(Math.abs(Number(val)) / maxVal) * 100}%` : "0%";

                  if (isMetric) {
                    return (
                      <td key={m.key} className="whitespace-nowrap px-4 py-2.5">
                        <div className="flex items-center justify-end gap-2.5">
                          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100 sm:w-28">
                            <div
                              className="h-full rounded-full bg-secondary"
                              style={{ width }}
                            />
                          </div>
                          <span className="font-mono text-[13px] font-medium tabular-nums text-slate-900">
                            {formatCell(val, m.currency)}
                          </span>
                        </div>
                      </td>
                    );
                  }

                  return (
                    <td
                      key={m.key}
                      className={
                        "whitespace-nowrap px-4 py-2.5 " +
                        (m.numeric
                          ? "text-right font-mono text-[13px] tabular-nums text-slate-800"
                          : "text-left text-slate-700")
                      }
                    >
                      {formatCell(val, m.currency)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
