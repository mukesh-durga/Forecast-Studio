# Forecast Studio — Evaluation Results

_Generated: 2026-07-10T06:15:55+00:00 · Dataset: 35 questions (27 supported, 8 unsupported) · Provider: local (deterministic)_

## Metrics

| Metric | Value |
|---|---|
| SQL generation success rate (supported) | 100.0% |
| Planner intent accuracy (all questions) | 100.0% |
| Avg planner confidence (supported) | 0.986 |
| Intent accuracy (supported) | 100.0% |
| Execution success rate (supported) | 100.0% |
| Result-column match rate | 100.0% |
| Row-count behavior correct | 100.0% |
| Verification pass rate (supported) | 100.0% |
| Unsupported rejection accuracy | 100.0% |
| Sample self-check pass rate (supported) | 100.0% |
| Sample-check failures / repairs attempted / successful | 0 / 0 / 0 |

## Mode comparison (average latency)

| Mode | Avg latency | Avg est. cost (USD) | Verification |
|---|---|---|---|
| Baseline (generate + execute) | 0.118 ms | — | — |
| Planner + verification (full) | 0.204 ms | $0.0 | 100.0% pass |

_Both modes use the same schema-grounded local generator; the full mode adds the verification loop. Numbers are measured by `scripts/run_eval.py`._
