# Forecast Studio

**Natural-language analytics with verified SQL.**

Forecast Studio turns plain-English business questions into grounded, SELECT-only
SQL, runs it in a read-only sandbox, and verifies that the result actually answers
the question before returning it.

> **Status:** Milestone 1 (Repo Setup). The scaffold, a FastAPI health endpoint,
> and a Next.js landing page are in place. Database, SQL generation, the safety
> guard, and the verification loop arrive in later milestones.

---

## Architecture (target)

```text
User → Next.js frontend → FastAPI backend
                              │
                              ├─ schema inspection
                              ├─ SQL plan + generation (grounded in schema)
                              ├─ SQL safety guard (SELECT-only, single statement)
                              ├─ execution (read-only, row limit, timeout)
                              └─ verification (does the result answer the question?)
                              │
                              ▼
                           Database
```

The LLM never executes anything directly — the backend controls every step.

## Project structure

```text
Forecast-Studio/
├── backend/                 # FastAPI application
│   ├── app/
│   │   ├── main.py          # App entrypoint + CORS
│   │   ├── config.py        # Env-driven settings
│   │   └── api/
│   │       └── routes_health.py
│   └── requirements.txt
├── frontend/                # Next.js + TypeScript + Tailwind
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx         # Landing page
│   │   └── globals.css
│   ├── lib/api.ts           # Backend client
│   └── package.json
├── .env.example
├── .gitignore
└── README.md
```

## Getting started

### Prerequisites
- Python 3.9+
- Node.js 18+

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- Health check: <http://localhost:8000/health> → `{"status":"ok"}`
- Interactive docs: <http://localhost:8000/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev
```

- App: <http://localhost:3000>

### Environment

```bash
cp .env.example backend/.env
cp .env.example frontend/.env.local
```

Fill in values as later milestones require them. Never commit `.env` files.

## Testing the health endpoint

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## Roadmap

| Milestone | Focus |
|-----------|-------|
| 1 ✅ | Repo setup, health endpoint, landing page |
| 2 | SQLite demo DB, seed script, schema inspection |
| 3 | SQL safety guard (SELECT-only, timeout, row limit) + tests |
| 4 | LLM SQL generation |
| 5 | Execution loop |
| 6 | Verification loop |
| 7 | Frontend query UI |
| 8 | Deployment |
| 9 | Resume polish |

## Safety

Read-only by design: SELECT-only guard, single-statement enforcement, blocked
dangerous keywords, query timeouts, row limits, server-side credentials, and a
CORS allowlist. Secrets live in environment variables and are never logged or
returned to the frontend.
