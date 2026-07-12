// Shapes mirror the backend Pydantic models (app/models/responses.py).

export interface Verification {
  verified: boolean;
  confidence: number; // 0.0 - 1.0
  explanation: string;
  failure_reason: string | null;
}

export interface QueryPlan {
  question: string;
  intent: string;
  matched: boolean;
  confidence: number; // 0.0 - 1.0 (deterministic planner score)
  target_connection: string;
  required_tables: string[];
  required_columns: string[];
  joins: string[];
  measures: string[];
  dimensions: string[];
  filters: string[];
  group_by: string[];
  order_by: string[];
  limit: number | null;
  expected_result_columns: string[];
}

export interface Telemetry {
  provider: string; // "local" | "groq" | "cache"
  planner_latency_ms: number;
  generation_latency_ms: number;
  sample_execution_latency_ms: number;
  final_execution_latency_ms: number;
  verification_latency_ms: number;
  total_latency_ms: number;
  cache_hit: boolean;
  repair_attempted: boolean;
  estimated_prompt_tokens: number;
  estimated_completion_tokens: number;
  estimated_total_tokens: number;
  estimated_cost_usd: number;
}

export type Row = Record<string, string | number | boolean | null>;

export interface QueryResponse {
  question: string;
  connection_id: string;
  dialect: string;
  generator: string;
  matched: boolean;
  intent: string | null;
  sql: string | null; // null for unsupported questions
  guard_passed: boolean;
  columns: string[];
  rows: Row[];
  row_count: number;
  runtime_ms: number;
  verification: Verification | null; // null when nothing was executed
  message?: string | null; // user-facing note for unsupported questions
  suggestions?: string[]; // example questions to try
  plan?: QueryPlan | null; // structured plan (present when show_debug=true)
  generic_mode_used?: boolean; // answered via the generic schema-aware path
  cache_hit?: boolean; // true when SQL was reused from the dedup cache
  cache_match_score?: number; // 1.0 exact, Jaccard for semantic, 0.0 on miss
  cached_from_question?: string | null; // source question (present when show_debug=true)
  sample_checked?: boolean; // draft was run + self-checked on a sample
  sample_row_count?: number; // rows the sample query returned
  repair_attempted?: boolean; // sample check failed and a repair ran
  repair_successful?: boolean; // a repaired query passed the sample check
  telemetry?: Telemetry | null; // per-query timing/cost (present when show_debug=true)
}
