# dsd

An agentic development platform for data scientists: project **plans and docs**, **experiment tracking and benchmarks**, and **Claude Code** in one workspace.

- **Plans:** markdown checklists with project-wide task ids (`T-12`). There's one central plan plus sub-plans, and edits only change the characters they need to.
- **Docs:** decisions, notes and HTML reports live in `docs/`. Docs support live `dsd-runs` tables and `![[report.html]]` embeds.
- **Experiments:** use `dsd.run(...)` or `dsd exec -- <cmd>`. Each run records params, metrics, info and HTML artifacts, along with its git state, command and dataset references. Benchmarks rank runs, and grouped leaderboards show mean ± std across seeds.
- **Agents:** `dsd init` registers an MCP server and installs five Claude Code skills: `/dsd-plan`, `/dsd-next-task`, `/dsd-run-experiment`, `/dsd-distill` and `/dsd-report`.
- **App:** `dsd ui` serves the plans board, docs, runs, compare, leaderboards, diff review with comments you can send to an agent, and embedded Claude/shell terminals.

## Install

```sh
uv tool install -e .     # puts `dsd` on PATH (needed by the MCP server Claude Code launches)
```

## Quick start

```sh
cd my-project
dsd init                 # .dsd/, docs/plans/main.md, CLAUDE.md block, .mcp.json, .claude/skills
dsd ui                   # opens the app at http://127.0.0.1:8765
```

Track experiments:

```sh
dsd exec -b churn-v1 --task T-3 -- python train.py --lr 0.1      # no code changes needed
dsd bench set churn-v1 --primary auc --direction max
dsd bench board churn-v1 -g params.model,params.lr
```

```python
import dsd
with dsd.run("xgb", benchmark="churn-v1", task="T-3", params=cfg,
             datasets=[dsd.dataset(id="churn-2024q3", config="configs/data.yml")]) as r:
    r.log({"loss": loss}, step=epoch)
    r.log({"auc": auc})
    r.html("eval.html", html)
```

Plans:

```sh
dsd plan show            # central plan
dsd task add "Try LightGBM" --tag exp --attr benchmark=churn-v1
dsd task start T-4 ; dsd task done T-4 -m "AUC 0.84, run 3ax47yw7"
dsd plan new feature-eng --title "Feature engineering"
```

## Demo

```sh
uv run python examples/make_demo.py      # builds .demo/churn-model (git repo, plans, docs, 16 runs, report, pending diff)
dsd ui .demo/churn-model
```

## Agent terminals

"+ Claude" runs Claude Code in a PTY inside the project. The command it uses is the first of these that exists:
1. `$DSD_CLAUDE_CMD`
2. `claude` on your login-shell PATH
3. A common install location
4. The newest binary bundled with the VS Code extension

Terminals keep running if you close the browser tab, and reattach when you reopen it.

## Develop

```sh
uv run pytest                           # Python: 44 tests
cd ui && npm install && npm run dev     # UI dev server on :5173, proxied to `dsd ui --no-open` on :8765
cd ui && npm run build                  # builds into src/dsd/web/dist (served by `dsd ui`)
```

Design docs: [requirements](docs/requirements.md) · [Phase 0 design](docs/design/phase0-headless-core.md) · [plan](docs/plans/main.md)

### Not done yet
- **Tauri desktop wrapper:** needs a Rust toolchain. The app is a local web UI so far, and Tauri will wrap the same UI.
- **SageMaker/S3 import:** the run-bundle format and the `backend` / `external_id` fields are in place for it.
- **Chat transcript distillation from files** (`~/.claude/projects/*.jsonl`): today the `/dsd-distill` skill works on the live conversation instead.
- **Marimo pane**, and git/S3 backup targets.
