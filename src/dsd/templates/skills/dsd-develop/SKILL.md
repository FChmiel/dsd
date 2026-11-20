---
name: dsd-develop
description: Pick up the next piece of work from the dsd plan and build it with the user - check recent PRs and code, confirm and refine the plan, show an HTML explainer of what will change, then build it. Use when the user says "what's next", "next task", "pick up the next step", "start T-12", "let's build", or /dsd-develop. Not for planning new work from scratch (that is /dsd-plan).
---

# Develop the next piece of work

Work through this in order. Stop and wait for the user where it says so.

## 1. Find where things stand

1. Call `project_overview` (plans, tasks in progress, recent runs) and `plan_list`.
2. Look at what has happened since the plan was written:
   - `git fetch -q` then `git log --oneline -15 origin/HEAD` for recent commits on the default branch.
   - `gh pr list --state merged --limit 10` and `gh pr list --author @me --state open` (skip if `gh` is not available or the repo has no GitHub remote).
   - `git branch --show-current` and `git status --short`. You may be in a dsd worktree (branch `dsd/<name>`); if so, the work belongs on that branch.
3. Pick the task:
   - If the user named one (`T-12`), use it.
   - Otherwise prefer a task already `doing`, then the first `todo` in an `agreed` or `in progress` plan whose earlier steps are done. Read that plan with `plan_read`.
   - If the plan is still `draft`, stop: say it has not been agreed and suggest reviewing it (or `/dsd-plan`) first.
   - If an earlier step's PR is still open and this one is not marked as stacked on it, ask before starting.

## 2. Check the plan still fits the code

Re-read what binds the task: the plan's requirements, "What is there today", "What does not change", the decisions it rests on (`decisions/`), and the task's notes, especially its `Done when` line (the checks for this step). If a check needs a benchmark baseline that doesn't exist yet, say so: it has to be recorded before the change. Then read the code it touches at the current commit. If the code has moved under the plan (a merged PR changed the shape, a file moved, a decision no longer holds), note exactly what differs.

## 3. Confirm and refine with the user (wait)

Tell the user, briefly:

- the task (id and one sentence) and why it is next;
- your approach: the files you will change and how, and what you will leave alone;
- how you will show it worked: the step's checks (requirement IDs, tests, benchmark and threshold). If the step has no `Done when` note, propose checks and add them as a note once the user agrees;
- anything in the plan that no longer fits, with your proposed correction;
- open questions.

Ask whether to go ahead or refine. Iterate until the user agrees. If the plan changes, update the plan doc (`docs_write("plans/<slug>.md", ...)`) and add a line to its change log before building.

## 4. Show what will be built

Write an HTML explainer of the agreed change, following `references/explainer.md` and starting from `assets/explainer.html` in this skill's folder. Focus on the key differences: a before-and-after diagram of the flow or structure, the files and functions that change, what stays the same, the risks, and the checks that will show it worked (with the baseline numbers, if a benchmark measures it). Save it with `docs_write("designs/<task-id>-<slug>.html", ...)` and tell the user where it is (the dsd Docs view, or `open "<data_dir>/docs/designs/..."`). Ask if it matches what they expect; adjust the plan if not.

## 5. Build it

1. `task_update(task_id, status="doing")`. If `project_overview` shows you are in a dsd worktree with an auto-generated name, rename it after the task with `worktree_rename` (2 to 4 words, e.g. `rules-aware-target`).
2. Build only this step. If it turns out bigger, unsafe, or needs a decision, stop and update the plan with the user rather than letting the code and the plan drift apart.
3. Run the step's checks. Run the tests for the files you touched. For benchmark checks, record the run on its benchmark (`dsd exec -b <benchmark> --task <id> -- <cmd>`, or `/dsd-benchmark` for a run that has already happened) and compare it with the baseline (`bench_board`, `runs_compare`). For long runs, give the user the command unless they ask you to run it. Write each result as a note on the step's task: `task_update(<task id>, note="Checked R2: p95 24 s vs 31 s baseline (run 3ax47yw7)")`. If a check fails, note the result, set the task `blocked`, and talk to the user before going further.
4. Check the size against the base: `git diff --shortstat <base>...HEAD -- . ':(exclude)*.lock'`. At 800 lines or more, talk to the user about splitting.
5. **Ask before committing, pushing or opening a PR.** Stage files by name (no `git add .`), and add a `Task: <id>` trailer to the commit message. Write the PR description in plain language: one or two short paragraphs saying what the change is and why, readable without the plan. If the step is stacked, follow the repo's stacking tool.
6. Afterwards: mark the step done only when every check in its `Done when` has passed: `task_update(task_id, status="done", note="PR #<n>, <one-line outcome>")` once merged (or leave it `doing` with a note while in review), fill in the task and PR columns in the plan's delivery table, and set the plan's `status: in progress` after the first step. If the step produced results worth sharing (benchmark numbers, a finding), offer to post them with `/dsd-results`.
