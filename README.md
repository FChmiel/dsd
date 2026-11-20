# dsd

An agentic development platform for data scientists: project **plans and docs**, **experiment tracking and benchmarks**, and **Claude Code** in one workspace.

- **Plans:** markdown checklists with project-wide task ids (`T-12`). There's one central plan plus sub-plans, and edits only change the characters they need to.
- **Docs:** decisions, notes and HTML reports live in the project's `docs/` folder. Docs support live `dsd-runs` tables and `![[report.html]]` embeds.
- **Experiments:** use `dsd.run(...)` or `dsd exec -- <cmd>`. Each run records params, metrics, info and HTML artifacts, along with its git state, command and dataset references. Benchmarks rank runs, and grouped leaderboards show mean ± std across seeds.
- **Agents:** Claude sessions started from the dsd app get dsd's MCP tools and skills automatically. To use them in Claude Code elsewhere, click **Connect Claude Code** in the app (or run `dsd setup`): it registers the MCP server for your user, pointing at the dsd you installed, and installs the skills. The skills are:
  - `/dsd-plan` plans work with you: a step-by-step design doc, then tasks once you agree them.
  - `/dsd-develop` picks up the next task, checks it against recent PRs and code, shows an HTML explainer of what will change, then builds it.
  - `/dsd-review` reviews a GitHub PR: a summary, your focus areas, then an HTML explainer with diagrams, widgets and charts of the evidence, with blockers and changes at the end.
  - `/dsd-benchmark` records a finished benchmark run (often an HTML dump) on a benchmark, with key metrics and links to its artefacts.
  - `/dsd-results` posts key results to the project's **Analytics** page: a headline number, key metrics against a baseline, a chart, and links to the task, plan and runs.
  - `/dsd-run-experiment`, `/dsd-distill` and `/dsd-report` track experiments, write decisions and notes, and build reports.

  dsd keeps them up to date when it starts, but keeps any skill you've edited. The **Skills** page in the app lists them with all your other Claude skills.
- **Outside your repo:** dsd keeps all of a project's state in `~/.dsd/projects/<id>/` and never writes into the repo, so you can use it on any codebase, including a large shared monorepo.
- **App:** `dsd ui` serves the plans board, docs, runs, compare, leaderboards, diff review with comments you can send to an agent, and embedded Claude/shell terminals.

## Home: your command centre

The landing page pulls together everything across your projects:
- **Agenda:** your personal to-dos plus any project plan task with a due date, grouped into Overdue, Today, the days of the coming week, Later and Someday.
- **Needs you:** blocked tasks, worktrees ready to merge or left with uncommitted changes, failed runs and unsent review comments.
- **Recent docs:** designs, decisions and reports edited across all projects.
- **Project cards.**

Quick add understands days and projects: `Send David the AUC numbers tomorrow #churn-model`. It recognises *today, tomorrow, yesterday, fri, next fri, next week, in 3 days, 11/24, 3 Dec, 2026-12-01*.

To-dos live in plain markdown at `~/.dsd/home/docs/plans/main.md`. To give a project task a date, add `@due:2026-11-12` to it.

```sh
dsd today                                   # your day in the terminal
dsd todo add Send David the numbers fri #churn-model
dsd todo done T-3 ; dsd todo move T-4 next week
```

Claude can manage them too, from any project, with the MCP tools `todo_add`, `todo_list` and `todo_update` (e.g. "remind me to email Priya on Friday").

## Install

**Mac app (Apple Silicon):** `brew install --cask OWNER/dsd/dsd`, or download the DMG from Releases. See [docs/distribution.md](docs/distribution.md) for how releases are built and published.

**From source:**

```sh
uv tool install -e .     # puts `dsd` on PATH (needed by the MCP server Claude Code launches)
packaging/build-macos.sh # optional: build dsd.app + DMG locally (needs Rust, Node, uv)
```

## Quick start

```sh
dsd setup                # optional: lets Claude Code outside the app use dsd (MCP server + skills); the app's "Connect Claude Code" does the same
cd ~/code/my-repo
dsd init                 # starts a project for this repo in ~/.dsd/projects/<id>/; the repo is untouched
dsd ui                   # opens the app at http://127.0.0.1:8765
```

## Where things live

dsd stores nothing in your repo: no `.dsd/` folder, no `CLAUDE.md` or `.gitignore` edits, no `.mcp.json`. Each project has a data directory (`dsd info` prints it; `DSD_HOME` overrides `~/.dsd`):

```
~/.dsd/projects/<id>/
  project.toml        # id, name, repo = "/abs/path/to/main/checkout", optional scope, [worktree], [[backup]]
  docs/               # plans/ (main.md + sub-plans), decisions/, notes/, reports/, experiments/
  runs/  index.db     # experiment run bundles and their SQLite index
  benchmarks.toml  review.json  worktrees.json
```

dsd finds the project from wherever you are: the repo root, any subdirectory, a linked git worktree of the repo (dsd's own or Pane's), or the data directory itself. Set `DSD_PROJECT_ROOT` to any of those paths to override the lookup for the CLI, the SDK and the MCP server.

By default a project covers a whole repo. To run several projects in one monorepo, give each a scope; the most specific scope wins:

```sh
dsd init ~/code/nory --name forecasting --scope apps/forecasting
dsd init ~/code/nory --name pricing --scope services/pricing
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

Record a run that already happened (e.g. a benchmark that dumped its results to HTML):

```sh
dsd runs add "solver-v2 full estate" -b estate --metric cost=1234.5 --metric hours=812 \
  --link results=s3://bucket/run-7/ --artifact results.html --commit HEAD --at 2026-11-18
```

## Demo

```sh
uv run python examples/make_demo.py      # builds .demo/churn-model (git repo, plans, docs, 16 runs, report, pending diff)
dsd ui .demo/churn-model
```

## Archiving a project

Like archiving a pane in Pane: **Archive project** on a project's overview (or `dsd archive [name] --yes`) hides the project and removes the checkouts of the worktrees dsd made for it. Their branches stay, so committed work is safe; uncommitted changes block the archive unless you choose to discard them (`--force`). Adopted worktrees are only unlisted, never deleted. Docs, plans and runs are kept.

Restore it from **Archived projects** on Home (or `dsd restore <name>`): the project comes back and its worktrees are recreated from their branches. `dsd projects -a` lists every project, archived ones included.

## Worktrees: one session per branch

By default, **+ New session** in the agent pane starts Claude in a **new git worktree** on branch `dsd/<name>`, so parallel agents never edit the same checkout. The launcher can also attach to an existing worktree or use the main checkout. "Work on this in a worktree" on a plan task creates (or reuses) a worktree named after the task.

- Worktrees live in `~/.dsd/worktrees/<project>/<name>`.
- Like Pane, dsd lists only the worktrees it owns: the ones it created, ones you adopted, and the worktree you started `dsd ui` from (marked *current*). A large repo's other worktrees stay out of the way. **Adopt existing worktree…** (or `dsd wt adopt <path>`) adds one, for example a Pane worktree. **Hide** (`dsd wt hide <name>`) stops listing it. dsd never deletes an adopted worktree unless you remove it explicitly.
- Git status is checked only for listed worktrees, in parallel. A scoped project's status, Changes and commit list only cover its scope.
- dsd copies the local files you list (by default `.env` and `.env.local`) into each new worktree. These copies are never shown as changes and never committed.
- Plans, docs and runs are shared by every worktree. Experiment runs made inside a worktree are tagged with the worktree and branch.
- **Changes** reviews a worktree's whole branch against its base: its commits, uncommitted edits and new files. Comments go to that worktree's agent.
- **Worktrees** shows ahead/behind and dirty status, and lets you commit, merge (merge commit or squash; a merge with conflicts is aborted cleanly) or remove each worktree.

```toml
# ~/.dsd/projects/<id>/project.toml
[worktree]
setup = "uv sync"          # runs in a new worktree before the agent starts
copy = [".env", "data/local.parquet"]
```

```sh
dsd wt new --task T-6        # prints the path:  cd "$(dsd wt new --task T-6)"
dsd wt ls [--all]            # --all also lists worktrees you could adopt
dsd wt adopt ~/code/nory/worktrees/my-pane
dsd wt hide my-pane
dsd wt merge t-6-add-interaction-features [--squash]
dsd wt rm sharp-orca --delete-branch
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
uv run pytest                           # Python tests
cd ui && npm install && npm run dev     # UI dev server on :5173, proxied to `dsd ui --no-open` on :8765
cd ui && npm run build                  # builds into src/dsd/web/dist (served by `dsd ui`)
```

Release and signing guide: [docs/distribution.md](docs/distribution.md)

### Not done yet
- **Tauri desktop wrapper:** needs a Rust toolchain. The app is a local web UI so far, and Tauri will wrap the same UI.
- **SageMaker/S3 import:** the run-bundle format and the `backend` / `external_id` fields are in place for it.
- **Chat transcript distillation from files** (`~/.claude/projects/*.jsonl`): today the `/dsd-distill` skill works on the live conversation instead.
- **Marimo pane**, and git/S3 backup targets.
