// Central place for talking to the Forecast Studio backend.

import type { QueryResponse } from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Run a natural-language question through the backend agent flow. */
export async function runQuery(
  question: string,
  connectionId = "demo",
): Promise<QueryResponse> {
  const res = await fetch(`${API_BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, connection_id: connectionId, show_debug: true }),
    cache: "no-store",
  });

  if (!res.ok) {
    // FastAPI returns { detail: "..." } on errors.
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore non-JSON error bodies
    }
    throw new Error(detail);
  }

  return res.json();
}

export const EXAMPLE_QUESTIONS: string[] = [
  "What are the top 5 products by revenue?",
  "Which city has the most customers?",
  "What was the total revenue by month?",
  "Which product category generated the highest revenue?",
  "What is the average order value?",
  "Which customers placed the most orders?",
  "How many support tickets are still open?",
  "Which issue type has the lowest satisfaction score?",
  "What marketing channel had the highest spend?",
  "Show monthly revenue trend.",
];
