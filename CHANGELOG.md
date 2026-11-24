# Changelog

All notable changes to dsd. Versions follow [semantic versioning](https://semver.org); while dsd is 0.x, minor versions may change behaviour.

## Unreleased

## 0.1.0

The first public alpha.

- **Projects outside your repo:** `dsd init` keeps a project's plans, docs and runs in `~/.dsd/projects/<id>/`. Several scoped projects can share one monorepo.
- **Plans:** markdown checklists with project-wide task ids, a central plan with sub-plans, and a task board and document view in the app.
- **Experiment tracking:** `dsd exec` and the `dsd.run` SDK record params, metrics, artifacts, git state and datasets. Benchmarks rank runs, and grouped leaderboards show mean ± std across seeds.
- **Docs, reports and Analytics:** decisions, notes and HTML reports with live run tables, Mermaid charts and embeds, plus an Analytics feed of key results.
- **Whiteboards:** Excalidraw boards per project that Claude can draw on from Mermaid or placed shapes.
- **Claude Code:** an MCP server and eight skills (`/dsd-plan`, `/dsd-develop`, `/dsd-run-experiment`, `/dsd-benchmark`, `/dsd-results`, `/dsd-report`, `/dsd-distill`, `/dsd-review`), set up by `dsd setup` or **Connect Claude Code**.
- **Agent sessions:** Claude and shell terminals in the app, each in its own git worktree if you like, with diff review, comments sent to the agent, and commit and merge.
- **Home:** an agenda across projects, to-dos with natural-language dates, what needs you, recent docs and Claude Code usage.
- **Mac app:** an Apple Silicon build with the backend bundled, installable with Homebrew.
