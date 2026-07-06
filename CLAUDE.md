# CLAUDE.md — Forecast Studio

## Project Goal

Build **Forecast Studio**, a deployable full-stack web app that lets a user ask plain-English analytics questions and receive verified SQL-backed answers from a connected database.

The core product flow is:

1. User connects or selects a database.
2. User asks a natural-language question.
3. The system inspects the schema and creates a grounded SQL query.
4. The SQL is executed in a read-only sandbox with row limits and timeouts.
5. A verification step checks whether the result actually answers the user question.
6. The app returns the answer, SQL, result table, verification status, and explanation.

This project must be resume-quality, deployable, and understandable to recruiters.

---

## Product Positioning

**One-line description:**

Natural-language analytics platform that converts business questions into verified SQL with a safety loop.

**Resume angle:**

Built a full-stack natural-language analytics system that turns plain-English questions into SQL for Postgres/Snowflake-style databases, executes queries in a controlled read-only sandbox, and validates answer correctness before returning results.

---

## Recommended Stack

### Frontend
- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- Recharts for simple result visualizations

### Backend
- FastAPI
- Python
- SQLAlchemy
- Pydantic
- PostgreSQL as the app metadata database
- SQLite sample database for demo mode
- OpenAI/Anthropic-compatible LLM abstraction layer

### Database Support
Start with:
- SQLite demo database
- PostgreSQL connection support

Add later:
- Snowflake-compatible connector interface

### Deployment
- Frontend: Vercel
- Backend: Render, Railway, Fly.io, or a Docker-based host
- Metadata DB: Supabase Postgres / Neon / Render Postgres
- Demo DB: bundled SQLite or seeded Postgres database

---

## High-Level Architecture

```text
User
 |
 | asks question
 v
Next.js Frontend
 |
 | POST /api/query
 v
FastAPI Backend
 |
 | 1. Load connection metadata
 | 2. Inspect schema
 | 3. Retrieve relevant tables/columns
 | 4. Generate SQL plan
 | 5. Generate SQL
 | 6. Validate SQL safety
 | 7. Execute with timeout + row limit
 | 8. Verify result answers question
 | 9. Return answer package
 v
Database
```

---

## Core Backend Modules

Use this structure:

```text
backend/
  app/
    main.py
    config.py
    api/
      routes_health.py
      routes_connections.py
      routes_query.py
    core/
      llm.py
      security.py
      errors.py
    db/
      metadata.py
      sample_seed.py
      connectors/
        base.py
        sqlite_connector.py
        postgres_connector.py
    services/
      schema_service.py
      planner_service.py
      sql_generator.py
      sql_guard.py
      execution_service.py
      verification_service.py
      answer_service.py
    models/
      requests.py
      responses.py
    tests/
      test_sql_guard.py
      test_query_flow.py
  requirements.txt
  Dockerfile
```

Frontend:

```text
frontend/
  app/
    page.tsx
    layout.tsx
    demo/page.tsx
  components/
    QueryBox.tsx
    ResultTable.tsx
    SqlPanel.tsx
    VerificationBadge.tsx
    ConnectionPanel.tsx
  lib/
    api.ts
    types.ts
  package.json
```

---

## Main Features

### MVP Features

Build these first:

1. **Demo Mode**
   - Use a seeded SQLite database with realistic business data.
   - Example tables:
     - customers
     - orders
     - order_items
     - products
     - marketing_campaigns
     - support_tickets

2. **Natural Language Query Box**
   - User enters a question.
   - Example: “What were the top 5 products by revenue last month?”

3. **Schema Inspection**
   - Backend extracts table names, columns, types, primary keys, and sample rows.
   - Keep this schema context compact.

4. **SQL Generation**
   - Generate only SELECT queries.
   - Ground SQL in actual schema.
   - No hallucinated tables or columns.

5. **SQL Safety Guard**
   - Block:
     - INSERT
     - UPDATE
     - DELETE
     - DROP
     - ALTER
     - TRUNCATE
     - CREATE
     - MERGE
     - COPY
     - multiple statements
   - Enforce:
     - SELECT-only
     - row limit
     - timeout
     - read-only transaction where possible

6. **Query Execution**
   - Execute query safely.
   - Return rows, columns, runtime, and row count.

7. **Verification Loop**
   - Check:
     - Does the SQL match the user question?
     - Do the result columns support the answer?
     - Are there obvious mismatches?
   - Return:
     - verified: true/false
     - confidence: 0 to 1
     - explanation

8. **Answer UI**
   - Show:
     - final natural-language answer
     - result table
     - generated SQL
     - verification badge
     - explanation of how the answer was produced

---

## Future Advanced Features

Do not build these until the MVP works:

1. Semantic schema retrieval
2. Query cache
3. Cost tracking per query
4. Query history
5. User authentication
6. Snowflake connector
7. Spider benchmark evaluation harness
8. Accuracy dashboard
9. Multi-step agent planner
10. SQL repair loop after failed execution

---

## Coding Rules

1. Keep the first version simple and working.
2. Do not over-engineer the agent flow before the MVP is complete.
3. Every backend endpoint must use Pydantic request/response models.
4. Every SQL query must pass through `sql_guard.py` before execution.
5. Never execute write queries.
6. Never return raw secrets to the frontend.
7. Keep connection credentials server-side only.
8. Use environment variables for API keys and database URLs.
9. Add tests for safety-critical code.
10. Prefer readable code over clever abstractions.

---

## API Design

### Health Check

```http
GET /health
```

Response:

```json
{
  "status": "ok"
}
```

### Run Natural-Language Query

```http
POST /query
```

Request:

```json
{
  "question": "What are the top 5 products by revenue?",
  "connection_id": "demo",
  "show_sql": true
}
```

Response:

```json
{
  "question": "What are the top 5 products by revenue?",
  "sql": "SELECT ... LIMIT 5",
  "columns": ["product_name", "revenue"],
  "rows": [
    {
      "product_name": "Wireless Headphones",
      "revenue": 12500.75
    }
  ],
  "answer": "The top product by revenue is Wireless Headphones with $12,500.75.",
  "verification": {
    "verified": true,
    "confidence": 0.86,
    "explanation": "The SQL groups order items by product and sorts by revenue descending, which matches the question."
  },
  "metadata": {
    "runtime_ms": 130,
    "row_count": 5
  }
}
```

---

## Agent Flow

For the MVP, use this exact flow:

```text
question
  -> schema_service.get_schema_context()
  -> planner_service.create_plan()
  -> sql_generator.generate_sql()
  -> sql_guard.validate_sql()
  -> execution_service.execute()
  -> verification_service.verify()
  -> answer_service.generate_answer()
```

Do not let the LLM execute tools directly. The backend controls execution.

---

## LLM Prompting Rules

### SQL Generation Prompt Must Include

- User question
- Database dialect
- Schema context
- Rules:
  - Generate one SELECT statement only.
  - Use only listed tables and columns.
  - Include LIMIT unless aggregation returns few rows.
  - Do not use unsafe operations.
  - Return SQL only.

### Verification Prompt Must Include

- User question
- Generated SQL
- Result columns
- First few result rows
- Ask the model to return JSON:
  - verified
  - confidence
  - explanation
  - failure_reason

---

## Security Requirements

This project must be safe by default.

Minimum requirements:

1. Read-only database user for external Postgres connections.
2. SQL parser/guard before execution.
3. Query timeout.
4. Row limit.
5. Block multiple statements.
6. Block dangerous SQL keywords.
7. Do not allow arbitrary connection strings from frontend in production.
8. Do not log secrets.
9. Use CORS allowlist.
10. Use `.env.example`, never commit `.env`.

---

## Demo Dataset

Create a realistic e-commerce sample dataset.

Tables:

```sql
customers(
  id,
  name,
  email,
  city,
  signup_date
)

products(
  id,
  name,
  category,
  price
)

orders(
  id,
  customer_id,
  order_date,
  status
)

order_items(
  id,
  order_id,
  product_id,
  quantity,
  unit_price
)

marketing_campaigns(
  id,
  name,
  channel,
  start_date,
  end_date,
  spend
)

support_tickets(
  id,
  customer_id,
  created_at,
  issue_type,
  status,
  satisfaction_score
)
```

Seed enough rows to make queries interesting.

---

## Example Questions for Testing

Use these questions during development:

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

---

## Frontend UI Requirements

The UI should feel like a polished analytics tool, not a basic chatbot.

Sections:

1. Header
   - Forecast Studio
   - Natural-language analytics with verified SQL

2. Query Panel
   - Textarea for question
   - Demo database selected by default
   - Run button

3. Result Area
   - Answer summary card
   - Verification badge
   - Result table
   - SQL viewer
   - Metadata: runtime, row count, confidence

4. Sidebar
   - Example questions
   - Connection status
   - Safety notes

Style:
- Clean SaaS dashboard look.
- Use cards, spacing, and subtle borders.
- Avoid overusing animations.
- Mobile responsive enough, but desktop-first is okay.

---

## Testing Requirements

Minimum tests:

1. `test_sql_guard_allows_select`
2. `test_sql_guard_blocks_delete`
3. `test_sql_guard_blocks_drop`
4. `test_sql_guard_blocks_multiple_statements`
5. `test_sql_guard_adds_limit`
6. `test_demo_query_flow_returns_rows`

---

## Milestones

### Milestone 1 — Repo Setup
- Create frontend and backend folders.
- Add basic FastAPI app.
- Add basic Next.js app.
- Add README.
- Add `.env.example`.

### Milestone 2 — Demo Database
- Build SQLite connector.
- Add seed script.
- Add schema inspection.

### Milestone 3 — SQL Guard
- Add SELECT-only validation.
- Add timeout and row limit.
- Add tests.

### Milestone 4 — LLM SQL Generation
- Add LLM abstraction.
- Generate schema-grounded SQL.
- Return SQL only.

### Milestone 5 — Execution Loop
- Run generated SQL.
- Return rows, columns, runtime.

### Milestone 6 — Verification Loop
- Verify result against question.
- Return confidence and explanation.

### Milestone 7 — Frontend UI
- Query box.
- Result table.
- SQL panel.
- Verification badge.

### Milestone 8 — Deployment
- Dockerize backend.
- Deploy backend.
- Deploy frontend.
- Add environment variables.
- Confirm demo mode works live.

### Milestone 9 — Resume Polish
- Add query history.
- Add sample benchmark script.
- Add screenshots.
- Add final README architecture diagram.

---

## Definition of Done

The project is ready when:

1. The user can open the website.
2. The user can ask a question in plain English.
3. The backend generates SQL.
4. The SQL executes safely.
5. The result appears in a table.
6. The app gives a clear answer.
7. The verification status is shown.
8. The app can run locally and is deployable.
9. The README explains architecture, safety, setup, and demo examples.
10. There are tests for SQL safety.

---

## Important Instruction for Claude Code

When working on this project:

- Make minimal but complete changes per milestone.
- After every milestone, explain:
  - what changed
  - how to run it
  - how to test it
  - what files were created/modified
- Do not skip tests for safety-critical logic.
- Do not add unnecessary features early.
- If something is ambiguous, choose the simpler implementation and continue.
