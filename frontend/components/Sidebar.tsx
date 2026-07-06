import { EXAMPLE_QUESTIONS } from "@/lib/api";

interface SidebarProps {
  onPick: (question: string) => void;
  disabled: boolean;
}

export default function Sidebar({ onPick, disabled }: SidebarProps) {
  return (
    <aside className="flex flex-col gap-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">Example questions</h2>
        <ul className="mt-3 space-y-2">
          {EXAMPLE_QUESTIONS.map((q) => (
            <li key={q}>
              <button
                onClick={() => onPick(q)}
                disabled={disabled}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-sm text-slate-600 transition hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {q}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">Connection</h2>
        <div className="mt-3 flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-sm text-slate-600">Demo · SQLite (read-only)</span>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">Safety</h2>
        <ul className="mt-3 space-y-1.5 text-sm text-slate-500">
          <li>• SELECT-only, single-statement guard</li>
          <li>• Read-only connection, row limit &amp; timeout</li>
          <li>• Every answer is verified before display</li>
        </ul>
      </section>
    </aside>
  );
}
