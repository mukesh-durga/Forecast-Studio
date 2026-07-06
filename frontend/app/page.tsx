export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <header className="mb-10">
        <h1 className="text-4xl font-bold tracking-tight text-slate-900">
          Forecast Studio
        </h1>
        <p className="mt-3 text-lg text-slate-600">
          Natural-language analytics with verified SQL.
        </p>
      </header>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Milestone 1 — Repo Setup
        </h2>
        <p className="mt-3 text-slate-700">
          The project scaffold is in place. The query box, schema inspection, SQL
          generation, safety guard, and verification loop arrive in later
          milestones.
        </p>
        <ul className="mt-4 space-y-2 text-sm text-slate-600">
          <li>• Ask plain-English analytics questions</li>
          <li>• Get grounded, SELECT-only SQL</li>
          <li>• Run it safely in a read-only sandbox</li>
          <li>• Verify the answer before you trust it</li>
        </ul>
      </section>

      <footer className="mt-8 text-sm text-slate-400">
        Backend API base:{" "}
        <code className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
          {process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}
        </code>
      </footer>
    </main>
  );
}
