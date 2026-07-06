import type { Row } from "@/lib/types";

function isNumeric(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function formatCell(v: string | number | boolean | null): string {
  if (v === null) return "—";
  if (typeof v === "number") {
    // Show up to 2 decimals for non-integers, keep integers clean.
    return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(v);
}

export default function ResultTable({ columns, rows }: { columns: string[]; rows: Row[] }) {
  if (columns.length === 0 || rows.length === 0) {
    return <p className="text-sm text-slate-500">No rows returned.</p>;
  }

  // Highlight the last column with an inline bar when it is fully numeric.
  const metricCol = columns[columns.length - 1];
  const numericMetric = rows.every((r) => isNumeric(r[metricCol]));
  const maxVal = numericMetric
    ? Math.max(...rows.map((r) => Math.abs(Number(r[metricCol]))), 0)
    : 0;

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((c) => (
              <th
                key={c}
                className="px-4 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-slate-50">
              {columns.map((c) => {
                const val = row[c];
                const isMetric = c === metricCol && numericMetric;
                const width = isMetric && maxVal > 0 ? `${(Math.abs(Number(val)) / maxVal) * 100}%` : "0%";
                return (
                  <td key={c} className="px-4 py-2.5 align-middle whitespace-nowrap text-slate-700">
                    {isMetric ? (
                      <div className="flex items-center justify-end gap-2">
                        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
                          <div className="h-full rounded-full bg-indigo-400" style={{ width }} />
                        </div>
                        <span className="tabular-nums font-medium">{formatCell(val)}</span>
                      </div>
                    ) : (
                      <span className={isNumeric(val) ? "tabular-nums" : ""}>{formatCell(val)}</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
