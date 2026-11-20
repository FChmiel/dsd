---
name: dsd-benchmark
description: Add the results of a benchmark run to a dsd benchmark, so it can be compared with other runs on the leaderboard - find where the run happened and its results (often an HTML or JSON dump), confirm them with the user, record key metrics, and link its artefacts (S3, reports, dashboards). Use when the user says "add this benchmark run", "record these results", "log this benchmark", or /dsd-benchmark.
---

# Add a benchmark run

dsd compares runs on a benchmark by their metrics. This skill records a run that has already happened, with `dsd runs add` (or the MCP tool `run_add`). Confirm with the user before recording anything.

## 1. Find the run

If the user has said where the results are, use that. Otherwise search, then confirm:

- Recently changed result files in the repo and its worktrees, newest first, for example:
  `find . -path ./node_modules -prune -o -type f \( -name "*.html" -o -name "*.json" -o -name "*.csv" \) -mmin -1440 -print 2>/dev/null | head -30`
  and the same under `~/Downloads` when the user mentions a download.
- S3 or cloud paths printed in recent terminal output, the PR description, or the notes of the task the user is on.
- Existing runs, so you don't add a duplicate: `runs_query(benchmark=...)`.

Show the user the candidates and ask which run it is. Also confirm: which benchmark it belongs to, the commit or branch it ran from, when it ran, and the task it serves (`T-12`), if any.

## 2. Read the results and pick the metrics

Open the results file and extract the headline numbers. Then:

1. Call `bench_list` and `bench_board(<benchmark>)`. Reuse the metric names that runs on this benchmark already have, with the same units and scale, so the leaderboard compares like with like. If the new results use different names or units, map them and tell the user.
2. Propose the metrics to record (name, value, unit, and whether higher or lower is better) plus the parameters that distinguish this run (solver version, config, data window). Keep to the key metrics; detail stays in the artefacts.
3. Collect links: S3 buckets or prefixes, dashboards, the PR, notebooks. The results file itself goes in as an artefact (copied into the run).

Show the user the full list and wait for confirmation or corrections.

## 3. Record it

```bash
dsd runs add "<run name>" --benchmark <benchmark> [--task T-12] \
  --metric <name>=<value> [--metric ...] [--metrics-json results.json] \
  --param <name>=<value> [...] \
  --link results=s3://bucket/prefix/ --link dashboard=https://... \
  --artifact path/to/results.html \
  --at <ISO date or time it ran> --commit <sha or branch> --note "<one line of context>"
```

`run_add` takes the same fields. If the benchmark is new, set how it ranks: `dsd bench set <benchmark> --primary <metric> --direction max|min` (ask which metric and direction).

## 4. Show where it lands

Call `bench_board(<benchmark>)` and tell the user where the run ranks and how it compares with the previous best and the last run (`runs_compare`). If it serves a task, add a one-line result to it: `task_update(<id>, note="<benchmark>: <metric> <value> (run <id>)")`. Then offer to post the result to the project's Analytics page with `/dsd-results`.
