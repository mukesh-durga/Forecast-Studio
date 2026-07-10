# Spider-subset evaluation

This folder holds the **Spider dev-set subset** evaluation for Forecast Studio.

It is a *subset* harness — it evaluates on a configurable number of examples
(default 50, `--limit N`) from the **official Spider dev set**. It does **not**
run the full Spider benchmark, and no full-benchmark accuracy is claimed
anywhere in this project.

## Setup

Spider is a Yale-licensed dataset distributed via manual download — it is not
committed here. Get it and point the harness at it:

```bash
backend/.venv/bin/python scripts/download_spider.py     # checks / prints instructions
export SPIDER_DIR=/absolute/path/to/spider              # dir with dev.json + database/
backend/.venv/bin/python scripts/run_spider_subset.py --limit 50
```

If Groq's free rate limit is a concern, use a smaller subset: `--limit 10` or
`--limit 25`.

## Output

`run_spider_subset.py` writes (only when run on real data):

- `results.json` — timestamped, records the provider, subset size, per-example
  outcomes, and aggregate metrics.
- `results.md` — a readable summary table.

Metrics (per mode — baseline vs. full): execution accuracy (result-set match),
generation validity, unsafe-rejection count, wrong-answer-caught count, and
average latency. Numbers are measured, never hardcoded.

> These results files are git-ignored: they are produced from your local Spider
> download, not shipped. Commit them yourself only if you want to publish a run.
