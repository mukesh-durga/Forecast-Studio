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

function LogoMark() {
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-white shadow-card">
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
        <path d="M5 20v-6M11 20v-12M17 20v-8" />
      </svg>
    </span>
  );
}

function Check() {
  return (
    <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 text-primary" fill="currentColor" aria-hidden>
      <path d="M8 13.2 4.8 10l-1.15 1.15L8 15.5l8-8-1.15-1.15z" />
    </svg>
  );
}

function FeatureChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-white/70 px-3 py-1 text-xs font-medium text-slate-600">
      <Check />
      {label}
    </span>
  );
}

/** Loading placeholder that mirrors the result layout. */
function ResultSkeleton() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-live="polite">
      <span className="sr-only">Running query…</span>
      <div className="rounded-2xl border border-hairline bg-white p-5 shadow-card sm:p-6">
        <div className="h-3 w-16 animate-pulse rounded bg-slate-200" />
        <div className="mt-3 h-6 w-2/3 animate-pulse rounded bg-slate-200" />
        <div className="mt-4 h-14 animate-pulse rounded-xl bg-slate-100" />
      </div>
      <div className="overflow-hidden rounded-2xl border border-hairline shadow-card">
        <div className="h-10 animate-pulse bg-slate-100" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-9 animate-pulse border-t border-slate-100 bg-white" />
        ))}
      </div>
    </div>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 shadow-card">
      <svg viewBox="0 0 20 20" className="mt-0.5 h-5 w-5 shrink-0 text-red-500" fill="currentColor" aria-hidden>
        <path fillRule="evenodd" d="M8.3 2.9c.75-1.3 2.65-1.3 3.4 0l6.1 10.6c.75 1.3-.2 2.9-1.7 2.9H3.9c-1.5 0-2.45-1.6-1.7-2.9L8.3 2.9zM10 7a1 1 0 00-1 1v3a1 1 0 102 0V8a1 1 0 00-1-1zm0 7.5a1.1 1.1 0 100-2.2 1.1 1.1 0 000 2.2z" clipRule="evenodd" />
      </svg>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-red-800">Query failed</p>
        <p className="mt-0.5 break-words text-sm text-red-600">{message}</p>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-hairline bg-white/60 p-12 text-center shadow-card">
      <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-blue-50 text-primary">
        <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <circle cx="9" cy="9" r="6" />
          <path d="M14 14l3 3" strokeLinecap="round" />
        </svg>
      </span>
      <p className="mt-3 text-sm font-semibold text-slate-700">No results yet</p>
      <p className="mt-1 text-sm text-slate-400">
        Ask a question or pick an example to see verified, SQL-backed results.
      </p>
    </div>
  );
}

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
    <div className="min-h-dvh">
      {/* Top app bar */}
      <header className="sticky top-0 z-40 border-b border-hairline/70 bg-white/75 backdrop-blur-md supports-[backdrop-filter]:bg-white/70">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex items-center gap-2.5">
            <LogoMark />
            <span className="text-sm font-semibold tracking-tight text-slate-900">Forecast Studio</span>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-canvas px-3 py-1 text-xs font-medium text-slate-600">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Demo · SQLite
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Hero */}
        <section className="mb-8 animate-fade-up">
          <span className="font-mono text-xs font-medium uppercase tracking-widest text-primary">
            Natural-language analytics
          </span>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            Forecast Studio
          </h1>
          <p className="mt-2 max-w-2xl text-base text-slate-600 sm:text-lg">
            Natural-language analytics with verified SQL.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <FeatureChip label="Verified answers" />
            <FeatureChip label="Read-only sandbox" />
            <FeatureChip label="SELECT-only guard" />
          </div>
        </section>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:gap-8 xl:grid-cols-[minmax(0,1fr)_20rem]">
          {/* Main column */}
          <div className="flex min-w-0 flex-col gap-6">
            <QueryBox
              question={question}
              onChange={setQuestion}
              onRun={() => execute(question)}
              loading={loading}
            />

            {/* Dynamic result area (announced to assistive tech) */}
            <div className="flex min-w-0 flex-col gap-6" aria-live="polite">
              {error && <ErrorCard message={error} />}

              {loading && !result && <ResultSkeleton />}

              {result && (
                <div className="flex min-w-0 animate-fade-in flex-col gap-6">
                  <AnswerCard result={result} />
                  <MetadataBar result={result} />
                  <section className="min-w-0">
                    <h3 className="mb-2 text-sm font-semibold text-slate-700">Result</h3>
                    <ResultTable columns={result.columns} rows={result.rows} />
                  </section>
                  <SqlPanel sql={result.sql} />
                </div>
              )}

              {!result && !loading && !error && <EmptyState />}
            </div>
          </div>

          <Sidebar onPick={pickExample} disabled={loading} active={question} />
        </div>

        <footer className="mt-12 border-t border-hairline/70 pt-6 text-center text-xs text-slate-400">
          Forecast Studio · demo mode · read-only SQLite
        </footer>
      </main>
    </div>
  );
}
