---
name: dsd-results
description: Post key results and analytics to the dsd project's Analytics page - a short, plain-language post with the headline number, the key metrics compared with a baseline, a chart, and links to the task, plan, benchmark and runs. Use when the user says "post the results", "share what we found", "write up the numbers", "add this to analytics", or /dsd-results, and offer it after a benchmark run, an experiment or a finished task.
---

# Post results to Analytics

The Analytics page is where the team sees what the work has shown, newest first. Each post is one result: what was measured, the headline number, and what it means. Keep it short; the detail lives in the runs, reports and plans it links to.

## 1. Gather the numbers

- From this conversation, and from dsd: `project_overview`, `runs_query`, `run_get`, `runs_compare`, `bench_board`, and the task's notes (`plan_read`).
- Find the comparison that makes each number meaningful: the baseline, the previous best, the target in the plan's requirements, or the last release.
- Note the run ids, the benchmark, the task and the plan.

## 2. Agree the post with the user (wait)

Draft and show the user, in chat:

- **Title:** the result in a few words ("Rules-aware target 23% faster at p95").
- **Headline:** one sentence with the main number and its comparison ("p95 solve time fell from 31 s to 24 s on the estate benchmark, against a 30 s target").
- **Key metrics:** 3 to 6 numbers, each named with its unit (`p95 solve time (s)`), plus the change where it helps (`change vs baseline: -23%`).
- What it means, and caveats (sample size, which brands or weeks, what was not measured).

Ask whether anything is wrong or missing. Only post once the user agrees.

## 3. Write the body

Plain language (ISO 24495-1): main point first, short sentences, units on every number, and say what was not measured. Then:

1. **What we measured**: one or two sentences, with the benchmark and data window.
2. **The result**: a chart, then a short table.
   - A Mermaid chart for a few numbers:
     ````
     ```mermaid
     xychart-beta
       title "p95 solve time (s)"
       x-axis [baseline, rules_aware]
       y-axis "seconds" 0 --> 40
       bar [31, 24]
     ```
     ````
   - Or a live table of the benchmark's runs:
     ````
     ```dsd-runs
     benchmark: estate
     metrics: p95_solve_s, total_cost
     limit: 8
     ```
     ````
   - To show a richer report, embed it: `![[reports/<name>.html]]` (or `![[run:<run id>/<artifact>.html]]` for a run's artifact).
3. **What it means**, and **caveats**.
4. **Links**: the task (`[T-26](task:T-26)`), the plan, the runs (`[run 3ax47yw7](run:<id>)`), the PR.

## 4. Post it

Call `analytics_post(title, headline, body, metrics={...}, task=..., plan=..., benchmark=..., runs=[...])`. It saves the post in the project's docs (`analytics/<date>-<slug>.md`) and it appears on the Analytics page. Tell the user it is there. If the result closes a check on a task, add a note to the task too (`task_update(<id>, note="Checked R2: ... (analytics/<file>)")`).
