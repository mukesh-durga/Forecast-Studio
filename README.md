# Forecast Studio

**Natural-language analytics with verified SQL.**

Ask a plain-English business question and get a verified, SQL-backed answer from
a connected database. Forecast Studio turns questions into **SELECT-only** SQL,
runs it in a **read-only sandbox** with a row limit and timeout, and **verifies**
that the result actually answers the question before showing it.

---

## Architecture

```text
User → Next.js frontend → FastAPI backend
                              │
                              ├─ schema inspection        (compact schema context)
                              ├─ SQL generation           (local rules; optional Groq)
                              ├─ SQL safety guard         (SELECT-only, single statement)
                              ├─ schema grounding         (must reference real tables)
                              ├─ execution                (read-only, row limit, timeout)
                              └─ verification             (does the result fit the question?)
                              │
                              ▼
                           SQLite demo DB
```

- **SQL generation** defaults to a free, deterministic, offline **local** generator
  (no API key, no internet). An optional **Groq** provider can be enabled; it is
  guarded + schema-grounded and **falls back to local** on any error.
- Unsupported questions return an honest "not supported" response — never fake SQL.

## Project structure

```text
Forecast-Studio/
├── backend/                 # FastAPI application
│   ├── app/
│   │   ├── main.py          # app entrypoint (auto-seeds demo DB on startup) + CORS
│   │   ├── config.py        # env-driven settings
│   │   ├── api/             # routes: health, connections, query
│   │   ├── db/              # SQLite connector + seed script
│   │   ├── services/        # schema, sql_generator, sql_guard, schema_grounding,
│   │   │                    #   execution, verification
│   │   ├── models/          # Pydantic request/response models
│   │   └── tests/           # pytest suite
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .dockerignore
├── frontend/                # Next.js + TypeScript + Tailwind dashboard
│   ├── app/                 # layout, page, globals
│   ├── components/          # QueryBox, ResultTable, SqlPanel, VerificationBadge, …
│   └── lib/                 # api client + types
├── .env.example
└── README.md
```

---

## Local development

### Prerequisites
- Python 3.11+ (3.9+ works)
- Node.js 18+

### 1. Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
- The **demo SQLite database is seeded automatically on startup** if missing.
  (To seed/reset manually: `python -m app.db.sample_seed`.)
- Health: <http://localhost:8000/health> · Docs: <http://localhost:8000/docs>

### 2. Frontend
```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev                     # http://localhost:3000
```

### Build the frontend (production bundle)
```bash
cd frontend
npm run build        # type-checks + compiles
npm run start        # serve the production build locally
```

---

## Environment variables

| Variable | Where | Default | Purpose |
|---|---|---|---|
| `CORS_ORIGINS` | backend | `http://localhost:3000` | Comma-separated allowlist of frontend origins. Set to your deployed frontend URL in prod. |
| `SQL_GENERATOR_PROVIDER` | backend | `local` | `local` (free/offline) or `groq`. |
| `GROQ_API_KEY` | backend **only** | _(empty)_ | Groq secret — used only when provider is `groq`. **Never** exposed to the browser. |
| `GROQ_MODEL` | backend | `llama-3.3-70b-versatile` | Optional Groq model override. |
| `PORT` | backend | `8000` | Injected by most hosts; the container honors it. |
| `NEXT_PUBLIC_API_BASE_URL` | frontend | `http://localhost:8000` | Backend URL the browser calls. Set to your deployed backend URL in prod. |

> Default deployment uses `SQL_GENERATOR_PROVIDER=local`. Groq is optional; the
> key is read server-side only and never sent to the frontend.

---

## Deployment

### Backend (Docker → Render / Railway / Fly.io / any container host)
```bash
cd backend
docker build -t forecast-studio-api .
docker run -p 8000:8000 -e CORS_ORIGINS=https://your-frontend.example.com forecast-studio-api
```
On a PaaS: point it at `backend/` (the Dockerfile), and set env vars:
- `CORS_ORIGINS=https://<your-frontend-domain>`
- (optional) `SQL_GENERATOR_PROVIDER=groq` **and** `GROQ_API_KEY=...`

The container listens on `$PORT` (default 8000) and **auto-seeds the demo DB on
startup**, so demo mode works immediately with no extra step.

### Frontend (Vercel — recommended)
1. Import the repo, set the project root to `frontend/`.
2. Add env var **`NEXT_PUBLIC_API_BASE_URL`** = your deployed backend URL.
3. Deploy (build: `npm run build`).

After both are live, make sure the backend's `CORS_ORIGINS` includes the
frontend's deployed origin.

---

## Testing before deployment

```bash
# Backend: full test suite
cd backend && source .venv/bin/activate && pytest -q

# Frontend: type-check + production build
cd frontend && npx tsc --noEmit && npm run build

# End-to-end smoke (with backend running on :8000)
curl http://localhost:8000/health
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the top 5 products by revenue?"}'
```

## Example questions
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

## Safety
Read-only by design: SELECT-only guard, single-statement enforcement, blocked
dangerous keywords, query timeout, row limit, schema-grounding (generated SQL
must reference real tables), server-side credentials, and a CORS allowlist.
Secrets live in environment variables and are never logged or returned to the
frontend. No authentication (public demo).
