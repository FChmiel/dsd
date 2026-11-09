## dsd project: {name}

This repo is managed with **dsd** (plans, docs and experiment tracking).

- Plan of record: `docs/plans/main.md`; sub-plans live in `docs/plans/`. Task IDs (`T-12`) are unique across all plans.
- Task markers: `[ ]` todo, `[/]` doing, `[x]` done, `[!]` blocked, `[-]` dropped. Change status with `dsd task ...` rather than rewriting plan files by hand.
- Tag experiment runs with the task they serve: `dsd.run(..., task="T-12")` or `dsd exec --task T-12 -- <cmd>`.
- Add a `Task: T-12` trailer to commits that implement a task.
- You may be running in a dsd git worktree (branch `dsd/<name>`, see `git branch --show-current`). Commit your work on that branch; the user reviews and merges it from the dsd app (`dsd wt merge`). Experiment runs are still recorded in the main project.
- Decisions go in `docs/decisions/`, notes in `docs/notes/`, HTML reports in `docs/reports/`.

Active tasks: {active}
