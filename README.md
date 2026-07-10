# Forecast Studio

**Natural-language analytics with verified SQL.**

Ask a plain-English business question and get a verified, SQL-backed answer from a
connected database — the generated SQL is safety-checked, run in a read-only
sandbox, and the result is verified against the question before it's shown.

### 🔗 Links
- **Live demo:** https://forecast-studio-ten.vercel.app
- **Backend API:** https://forecast-studio-api-7kxg.onrender.com ( [`/health`](https://forecast-studio-api-7kxg.onrender.com/health) · [`/docs`](https://forecast-studio-api-7kxg.onrender.com/docs) )
- **Source:** https://github.com/mukesh-durga/Forecast-Studio

> The backend runs on a free tier and may take ~30–50s to wake on the first
> request (cold start), then responds instantly.

---

## Overview

Forecast Studio is a full-stack app that turns natural-language analytics
questions into **verified SQL** against a demo e-commerce database. It's built
around a safety-first pipeline: every query is generated from the real schema,
passed through a **SELECT-only guard**, checked for **schema grounding**,
executed **read-only** with a row limit and timeout, and finally **verified** —
does the result actually answer the question? — before the UI displays it.

It works with **no paid API and no internet**: the default SQL generator is a
free, deterministic, rule-based engine. An **optional Groq LLM provider** can be
enabled for open-ended questions, and it automatically **falls back to local** if
it errors, times out, or returns unsafe/ungrounded SQL.

## Screenshots

> Placeholder paths — add real images at these locations (see "Screenshots to
> take" in the notes) and they'll render here.

| Dashboard | Verified answer + result table |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Verified answer](docs/screenshots/answer.png) |

| Generated SQL panel | Unsupported question (honest) |
|---|---|
| ![SQL panel](docs/screenshots/sql.png) | ![Unsupported](docs/screenshots/unsupported.png) |

## Features

- **Natural-language → SQL** grounded in the live database schema.
- **Sample self-check loop** — the draft SQL is first run on a small `LIMIT 5`
  sample and checked against the plan (expected columns, shape, non-empty); if it
  fails, one plan-based repair is attempted, re-guarded, and re-checked before the
  final query runs.
- **Semantic-dedup cache** — repeat and paraphrased questions reuse a previously
  verified query. Lookup is exact-match on the normalized question, then Jaccard
  similarity on content tokens above a configurable threshold — reusing SQL only
  when the intent, connection, and schema signature match and the earlier result
  was verified.
- **Verification loop** — each answer shows a Verified / Not-verified badge, a
  confidence score, and a plain-English explanation.
- **Per-query telemetry & cost tracking** — every query records per-phase
  latency (planner, generation, sample execution, final execution, verification),
  cache-hit / repair flags, and estimated prompt/completion tokens with an
  **estimated cost** (always `$0` for the local provider; chars/4 estimate for
  Groq). Shown in a debug card when `show_debug=true`; always stored in history.
- **SELECT-only safety guard** with single-statement enforcement and blocked
  write/DDL keywords.
- **Schema grounding** — rejects SQL that doesn't reference real tables (no
  placeholder/constant queries).
- **Read-only execution** with a row limit and a wall-clock timeout.
- **Honest unsupported-question handling** — returns a helpful message +
  suggestions instead of a fabricated answer.
- **Optional Groq LLM provider** with automatic local fallback (free by default).
- **Polished, responsive dashboard** — result tables with formatted currency,
  syntax-highlighted SQL, example questions, and light micro-interactions.

## Architecture

```text
User → Next.js frontend → FastAPI backend
                              │
                              ├─ schema inspection     (compact schema context)
                              ├─ query planner         (intent, tables, joins, measures,
                              │                          filters, group/order, confidence)
                              ├─ semantic-dedup cache   (reuse verified SQL for repeat /
                              │                          paraphrased questions)
                              ├─ SQL generation        (rendered from the plan; optional Groq)
                              ├─ SQL safety guard      (SELECT-only, single statement)
                              ├─ schema grounding      (must reference real tables)
                              ├─ sample self-check     (run on LIMIT 5, check vs plan;
                              │                          one plan-based repair on failure)
                              ├─ execution             (read-only, row limit, timeout)
                              └─ verification          (does the result fit the question?)
                              │
                              ▼
                           SQLite demo DB
```

The LLM never executes anything — the backend controls every step of the flow.

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | Next.js (App Router), React, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python, Pydantic, Uvicorn |
| Database | SQLite (read-only demo, auto-seeded) · optional PostgreSQL/Neon (`psycopg`) |
| SQL generation | Deterministic local rules (default) · optional Groq API |
| Testing | pytest |
| Deployment | Docker · Render (backend) · Vercel (frontend) |

## Project structure

```text
Forecast-Studio/
├── backend/                 # FastAPI application (Dockerized)
│   ├── app/
│   │   ├── main.py          # entrypoint; auto-seeds demo DB on startup; CORS
│   │   ├── config.py        # env-driven settings
│   │   ├── api/             # routes: health, connections, query
│   │   ├── db/              # SQLite connector + seed script
│   │   ├── services/        # schema, sql_generator, sql_guard, schema_grounding,
│   │   │                    #   execution, verification
│   │   ├── models/          # Pydantic request/response models
│   │   └── tests/           # pytest suite
│   ├── requirements.txt · Dockerfile · .dockerignore
├── frontend/                # Next.js + TypeScript + Tailwind dashboard
│   ├── app/  components/  lib/
├── render.yaml              # backend deploy blueprint (local mode)
├── .env.example
└── README.md
```

## Local setup

**Prerequisites:** Python 3.11+ (3.9+ works), Node.js 18+.

### Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
The demo SQLite database is **seeded automatically on startup** if missing
(manual reset: `python -m app.db.sample_seed`).
Health: <http://localhost:8000/health> · Docs: <http://localhost:8000/docs>

### Frontend
```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev            # http://localhost:3000
```

## Deployment

- **Backend (Docker → Render):** `render.yaml` provisions a Docker web service
  with `rootDir: backend`, `SQL_GENERATOR_PROVIDER=local`, `CORS_ORIGINS`, and a
  `/health` check. Manual build/run:
  ```bash
  cd backend
  docker build -t forecast-studio-api .
  docker run -p 8000:8000 -e CORS_ORIGINS=https://your-frontend.example.com forecast-studio-api
  ```
  The container listens on `$PORT` and auto-seeds the demo DB, so demo mode works
  immediately.
- **Frontend (Vercel):** set project root to `frontend/`, add
  `NEXT_PUBLIC_API_BASE_URL=<backend URL>`, deploy. Then set the backend's
  `CORS_ORIGINS` to the frontend's deployed origin.

See the environment-variable table in [`.env.example`](.env.example).

## Connect a real Postgres database (Neon)

The app ships with two demo connections. SQLite is always available; Postgres is
enabled by a single environment variable, so the same pipeline (guard → grounding
→ read-only execution → verification) runs against a real, hosted database.

| `connection_id` | Backend | Availability |
|---|---|---|
| `demo` / `demo_sqlite` | Bundled SQLite (read-only) | Always on |
| `demo_postgres` | PostgreSQL via `psycopg` | On when a Postgres URL is set |

**Steps (Neon free tier):**

1. Create a free Postgres database at <https://neon.tech> and copy its connection
   string (it looks like `postgresql://user:pass@ep-xxx.neon.tech/dbname?sslmode=require`).
2. Set it as an environment variable (backend only — never `NEXT_PUBLIC`):
   ```bash
   export POSTGRES_DATABASE_URL="postgresql://user:pass@ep-xxx.neon.tech/dbname?sslmode=require"
   ```
   `DATABASE_URL` is also accepted; `POSTGRES_DATABASE_URL` wins if both are set.
3. Seed the same e-commerce dataset used by the SQLite demo:
   ```bash
   cd backend && .venv/bin/python -m app.db.postgres_seed
   ```
4. Inspect the live Postgres schema:
   ```bash
   curl http://localhost:8000/connections/demo_postgres/schema
   ```
5. Ask a question against Postgres:
   ```bash
   curl -s -X POST http://localhost:8000/query \
     -H 'Content-Type: application/json' \
     -d '{"question":"Which city has the most customers?","connection_id":"demo_postgres"}'
   ```

Postgres queries pass through the **same SELECT-only guard and schema grounding**
as SQLite, and run in a **read-only transaction with a server-side
`statement_timeout`**. Credentials stay server-side; the browser only ever sends a
`connection_id`, never a connection string.

## Query history & semantic-dedup cache

Every executed query is recorded in a small metadata store (a SQLite
`query_history` table, kept separate from the read-only demo databases), with its
question, normalized question, intent, generated SQL, verification result,
confidence, runtime, provider, schema signature, and cache-hit flag.

On each request the backend first tries the cache:

1. **Exact match** — the question is normalized (lowercased, punctuation
   stripped, whitespace collapsed) and looked up directly.
2. **Semantic near-duplicate** — the question is tokenized, stopwords are
   removed, and **Jaccard similarity** is computed against prior questions. If the
   best match is at or above `SEMANTIC_CACHE_THRESHOLD` (default **0.85**), its SQL
   is reused.

A cached entry is reused **only** when it shares the same **intent**,
**connection_id**, and **schema signature** as the incoming question **and** its
earlier result was **verified** — so a schema change, a different intent, or an
unverified prior answer all correctly miss. The response exposes `cache_hit` and
`cache_match_score` (and `cached_from_question` when `show_debug=true`). Set
`CACHE_ENABLED=false` to disable reuse entirely.

## Supported demo questions

1. What are the top 5 products by revenue?
2. Which city has the most customers?
3. What was the total revenue by month?
4. Which product category generated the highest revenue?
5. What is the average order value?
6. Which customers placed the most orders?
7. How many support tickets are still open?
8. Which issue type has the lowest satisfaction score?
9. What marketing channel had the highest spend?
10. Show monthly revenue trend.

Anything outside these (with the default local provider) returns an honest
"not supported yet" response with suggestions — never a fabricated answer.

## Security & safety

Safety is the core design goal of this project:

- **SELECT-only SQL guard** — every query must pass a guard that allows only a
  single `SELECT`/`WITH…SELECT` statement and blocks `INSERT`, `UPDATE`,
  `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `MERGE`, `COPY`, comments, and
  multiple statements.
- **Read-only SQLite demo database** — the connector opens the database in
  read-only mode, so even a write that slipped past the guard cannot mutate data.
- **Row limits & timeout** — a default `LIMIT` is enforced (and over-large limits
  clamped), and queries run under a wall-clock timeout.
- **Schema grounding** — generated SQL must reference real schema tables; safe
  but meaningless placeholder queries (e.g. `SELECT NULL … WHERE 1=0`) are
  rejected.
- **Unsupported-question handling** — questions the generator can't confidently
  answer return `matched: false`, no SQL, and a helpful message + examples,
  instead of guessing.
- **Optional Groq provider with local fallback** — the LLM is off by default; its
  output must pass **both** the safety guard **and** schema grounding, and any
  error/timeout/rate-limit/invalid output falls back to the local generator. The
  `GROQ_API_KEY` is read server-side only and is **never** exposed to the browser.
- Secrets live in environment variables and are never logged or returned to the
  frontend. CORS is restricted to an allowlist.

## Limitations

- The default demo runs against a **bundled SQLite dataset**. A real
  **PostgreSQL (Neon)** connection is supported (`demo_postgres`, seeded with the
  same dataset) but is opt-in via an environment variable — see "Connect a real
  Postgres database" above.
- The **default (local) generator answers a fixed set of predefined analytics
  questions** — it is deterministic rules, not a general text-to-SQL model.
- The **optional Groq provider** can handle open-ended questions, but its answers
  are shown as *unverified* (the verification loop only recognizes the predefined
  intents), and it depends on an external API key.
- **No authentication** — it's a public demo.
- The eval set below measures the app on its **own supported question set**, not
  a standard text-to-SQL benchmark (see Evaluation).

## Evaluation

An in-process harness ([`scripts/run_eval.py`](scripts/run_eval.py)) runs a
35-question set ([`eval/questions.json`](eval/questions.json)) — 27 supported
analytics questions (with paraphrases) and 8 unsupported ones — through the
backend pipeline and records real metrics. Latest run (local provider):

| Metric | Value |
|---|---|
| SQL generation success rate (supported) | 100.0% |
| Planner intent accuracy (all questions) | 100.0% |
| Intent accuracy (supported) | 100.0% |
| Execution success rate (supported) | 100.0% |
| Result-column match rate | 100.0% |
| Row-count behavior correct | 100.0% |
| Verification pass rate (supported) | 100.0% |
| Unsupported rejection accuracy | 100.0% |
| Sample self-check pass rate (supported) | 100.0% |
| Sample-check failures / repairs attempted / successful | 0 / 0 / 0 |

The harness also reports the **baseline vs. full** average latency (full adds the
sample self-check + verification, ~0.1–0.2 ms) and the **average estimated cost
per query**, which is **$0** with the local provider. These are measured numbers
on the app's own supported set (the deterministic local generator is built to
answer exactly these questions); this is **not** a standard benchmark like
Spider. Reproduce:

```bash
backend/.venv/bin/python scripts/run_eval.py   # writes eval/results.json + eval/results.md
```

### Spider-subset benchmark

A separate harness evaluates the pipeline on a configurable **subset of the
official Spider dev set** (Yale) — a standard text-to-SQL benchmark. It is a
**subset** harness (default 50 examples, `--limit N`); it does **not** run the
full Spider benchmark, and **no full-Spider accuracy is claimed anywhere in this
project**. Spider is Yale-licensed and downloaded manually — it is not committed
here, and no results are checked in.

```bash
backend/.venv/bin/python scripts/download_spider.py            # checks / prints setup
export SPIDER_DIR=/path/to/spider                              # dev.json + database/
backend/.venv/bin/python scripts/run_spider_subset.py --limit 50   # or --limit 10 / 25
```

For each example the harness loads the example's database schema, generates SQL
in **baseline** mode (single-shot, schema-grounded) and **full** mode (planner +
guard + sample self-check + verification + optional repair), executes both the
predicted and gold SQL, and compares result sets. It writes timestamped
`spider/results.json` and `spider/results.md` recording the provider and, per
mode: **execution accuracy, generation validity, unsafe-rejection count,
wrong-answer-caught count, and latency**. Numbers are measured on the examples
run — never hardcoded. Note: the default local generator is tuned to the demo
schema, so meaningful Spider accuracy requires an LLM provider (`SQL_GENERATOR_PROVIDER=groq`).

## Future improvements

- A general text-to-SQL model path with verification templates for arbitrary
  questions.
- Snowflake connector and user-supplied read-only connections (PostgreSQL/Neon
  is already supported — see above).
- Semantic schema retrieval for larger schemas.
- Extend generation beyond the demo intents so the Spider-subset harness (above)
  produces meaningful accuracy on arbitrary databases.
- Result charts and CSV export.

## Testing

```bash
cd backend && source .venv/bin/activate && pytest -q     # backend suite
cd frontend && npx tsc --noEmit && npm run build         # frontend type-check + build
```

---

*Built as a portfolio project to demonstrate full-stack engineering with a
safety-first, verifiable AI-analytics pipeline.*
