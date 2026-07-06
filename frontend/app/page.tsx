"use client";

import { useState } from "react";
import { runQuery } from "@/lib/api";
import type { QueryResponse } from "@/lib/types";
import QueryBox from "@/components/QueryBox";
import Sidebar from "@/components/Sidebar";
import AnswerCard from "@/components/AnswerCard";
import MetadataBar from "@/components/MetadataBar";
import SqlPanel from "@/components/SqlPanel";
import ResultTable from "@/components/ResultTable";

export default function Home() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);

  async function execute(q: string) {
    const trimmed = q.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await runQuery(trimmed);
      setResult(res);
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  function pickExample(q: string) {
    setQuestion(q);
    execute(q);
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Forecast Studio</h1>
        <p className="mt-1 text-slate-600">Natural-language analytics with verified SQL</p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_20rem]">
        {/* Main column */}
        <div className="flex flex-col gap-6">
          <QueryBox
            question={question}
            onChange={setQuestion}
            onRun={() => execute(question)}
            loading={loading}
          />

          {error && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <span className="font-semibold">Error:</span> {error}
            </div>
          )}

          {loading && !result && (
            <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-400 shadow-sm">
              Running query…
            </div>
          )}

          {result && (
            <div className="flex flex-col gap-6">
              <AnswerCard result={result} />
              <MetadataBar result={result} />
              <section>
                <h3 className="mb-2 text-sm font-semibold text-slate-700">Result</h3>
                <ResultTable columns={result.columns} rows={result.rows} />
              </section>
              <SqlPanel sql={result.sql} />
            </div>
          )}

          {!result && !loading && !error && (
            <div className="rounded-2xl border border-dashed border-slate-300 bg-white/60 p-10 text-center text-slate-400">
              Ask a question or pick an example to see verified, SQL-backed results.
            </div>
          )}
        </div>

        <Sidebar onPick={pickExample} disabled={loading} />
      </div>

      <footer className="mt-10 text-center text-xs text-slate-400">
        Forecast Studio · demo mode · read-only SQLite
      </footer>
    </main>
  );
}
