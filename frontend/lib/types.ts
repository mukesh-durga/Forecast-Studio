// Shapes mirror the backend Pydantic models (app/models/responses.py).

export interface Verification {
  verified: boolean;
  confidence: number; // 0.0 - 1.0
  explanation: string;
  failure_reason: string | null;
}

export type Row = Record<string, string | number | boolean | null>;

export interface QueryResponse {
  question: string;
  connection_id: string;
  dialect: string;
  generator: string;
  matched: boolean;
  intent: string | null;
  sql: string;
  guard_passed: boolean;
  columns: string[];
  rows: Row[];
  row_count: number;
  runtime_ms: number;
  verification: Verification;
}
