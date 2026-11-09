---
name: dsd-report
description: Build a polished, self-contained HTML analysis report from dsd experiment runs and save it to docs/reports/. Use when the user asks for a report, write-up, analysis page, results summary, or /dsd-report.
---

# Build an HTML analysis report

1. Gather the data: `bench_board`, `runs_query`, `run_get` and `runs_compare` for the runs in scope. Note the run ids you use.
2. Write a generator script `docs/reports/<slug>.py` so the report can be regenerated. It should:
   - load runs with the dsd Python API (`from dsd.project import find_project; from dsd.tracking.index import Index; from dsd.tracking.query import list_runs, leaderboard`);
   - render one self-contained `docs/reports/<slug>.html` with inline CSS, and charts as inline SVG or plotly (CDN);
   - include: the question, a headline result, a leaderboard table, key curves/plots, what changed between the best runs, caveats, and the run ids used.
3. Run it, open the result with `open docs/reports/<slug>.html`, and fix any layout problems.
4. Link the report from the relevant plan or task note (`task_update(note="report: docs/reports/<slug>.html")`).
