import { EXAMPLE_QUESTIONS } from "@/lib/api";

interface SidebarProps {
  onPick: (question: string) => void;
  disabled: boolean;
  active: string;
}

function ListIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
      <path d="M4 5a1 1 0 100 2 1 1 0 000-2zm4 0a1 1 0 000 2h7a1 1 0 100-2H8zM4 9a1 1 0 100 2 1 1 0 000-2zm4 0a1 1 0 000 2h7a1 1 0 100-2H8zM4 13a1 1 0 100 2 1 1 0 000-2zm4 0a1 1 0 000 2h7a1 1 0 100-2H8z" />
    </svg>
  );
}

function DbIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <ellipse cx="10" cy="4.5" rx="6" ry="2.5" />
      <path d="M4 4.5v11c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-11M4 10c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
      <path d="M10 1.5l6.2 2.2v4.8c0 3.9-2.6 7.4-6.2 8.6-3.6-1.2-6.2-4.7-6.2-8.6V3.7L10 1.5z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" fill="currentColor" aria-hidden>
      <path
        fillRule="evenodd"
        d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.7-9.3a1 1 0 00-1.4-1.4L9 10.6 7.7 9.3a1 1 0 10-1.4 1.4l2 2a1 1 0 001.4 0l4-4z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function CardHeader({ icon, title, badge }: { icon: React.ReactNode; title: string; badge?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-slate-400">{icon}</span>
      <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
      {badge}
    </div>
  );
}

export default function Sidebar({ onPick, disabled, active }: SidebarProps) {
  const activeText = active.trim();

  return (
    <aside className="flex flex-col gap-5 lg:sticky lg:top-24 lg:self-start">
      {/* Example questions */}
      <section className="rounded-2xl border border-hairline bg-white p-5 shadow-card">
        <CardHeader
          icon={<ListIcon />}
          title="Example questions"
          badge={
            <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              {EXAMPLE_QUESTIONS.length}
            </span>
          }
        />
        <ul className="mt-3 space-y-1.5">
          {EXAMPLE_QUESTIONS.map((q, i) => {
            const isActive = activeText === q;
            const running = disabled && isActive;
            return (
              <li key={q}>
                <button
                  onClick={() => onPick(q)}
                  disabled={disabled}
                  aria-current={isActive ? "true" : undefined}
                  className={
                    "group flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left text-sm transition-colors disabled:cursor-not-allowed " +
                    (isActive
                      ? "border-primary/50 bg-blue-50 font-medium text-primary"
                      : "border-slate-200 text-slate-600 hover:border-primary/40 hover:bg-blue-50 hover:text-primary disabled:opacity-60")
                  }
                >
                  <span
                    className={
                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[11px] font-semibold tabular-nums " +
                      (isActive
                        ? "bg-primary text-white"
                        : "bg-slate-100 text-slate-500 group-hover:bg-primary/10 group-hover:text-primary")
                    }
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{q}</span>
                  {running ? (
                    <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                  ) : (
                    <span
                      className={
                        "shrink-0 transition-colors " +
                        (isActive ? "text-primary" : "text-slate-300 group-hover:text-primary")
                      }
                      aria-hidden
                    >
                      →
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Connection */}
      <section className="rounded-2xl border border-hairline bg-white p-5 shadow-card">
        <CardHeader icon={<DbIcon />} title="Connection" />
        <div className="mt-3 space-y-2.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 font-medium text-slate-700">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
              </span>
              Connected
            </span>
            <span className="rounded-full border border-hairline bg-canvas px-2 py-0.5 text-xs font-medium text-slate-500">
              read-only
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wide text-slate-400">Database</span>
            <span className="font-mono text-xs text-slate-600">demo</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wide text-slate-400">Engine</span>
            <span className="font-mono text-xs text-slate-600">SQLite</span>
          </div>
        </div>
      </section>

      {/* Safety */}
      <section className="rounded-2xl border border-hairline bg-white p-5 shadow-card">
        <CardHeader icon={<ShieldIcon />} title="Safety" />
        <ul className="mt-3 space-y-2.5 text-sm text-slate-600">
          {[
            "SELECT-only, single-statement guard",
            "Read-only connection, row limit & timeout",
            "Every answer is verified before display",
          ].map((item) => (
            <li key={item} className="flex items-start gap-2">
              <CheckIcon />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
