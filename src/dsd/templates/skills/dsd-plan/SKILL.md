---
name: dsd-plan
description: Plan a piece of work with the user and turn it into a dsd plan - a living, step-by-step design doc with agreed requirements, a way to check each one (tests, benchmarks), and tasks in the project's plans. Use when the user says "plan this", "make a plan", "break this down", "turn this into tasks", "split this into PRs", or /dsd-plan. Also use to revise an existing plan after a review, a merged PR or a changed decision. Not for a one-line change or for picking up the next task (that is /dsd-develop).
---

# Plan work with the user

A dsd plan is a living design doc for work that spans several steps (usually several PRs). It holds the goal, the requirements and how each is checked, the context, and the step-by-step delivery plan, so a fresh session can pick the work up from the plan instead of from chat memory. Each step becomes one task (`T-12`) once the user agrees to it: a high-level product step, not a to-do list. The checks that show a step worked are written in that task's notes, so "done" means "shown to work" without cluttering the board.

`references/conventions.md` holds the rules: where plans live, status values, titles, diagrams, requirements and checks, decisions, the four step rules and plain language. `templates/plan.md` and `templates/decision.md` are the templates. Read both before writing.

Use the dsd MCP tools (`project_overview`, `plan_list`, `plan_read`, `docs_read`, `docs_write`, `task_add`, `task_update`). Plans live in the project's docs folder outside the repo; never write plan files into the repo.

## 1. Understand the work, with the user

1. Call `project_overview` and `plan_list`. Read the central plan (`plan_read("main")`) and any plan this work belongs to, so you don't duplicate tasks or contradict decisions in `decisions/`.
2. Find the written source: notes, a ticket, a PRD, a spike, or this conversation. If there is none and the work is not small, ask the user where it is rather than rebuilding it from memory.
3. Interview the user until you can state the goal in two sentences. Ask about: what will be true when this is done, who notices, what must not change, deadlines, and risks they already see. Ask a few questions at a time, not a questionnaire.

## 2. Agree the requirements and how to check them

Do this before designing. A plan without agreed requirements cannot be validated.

1. Ask the user for the key requirements of the finished work: what must be true for them to call it done, including what must not get worse. Offer a draft list from what you have heard so far, and let them correct it. Aim for 3 to 8.
2. Make each one checkable, and confirm it with the user: an ID (`R1`, `R2`, …), the requirement in one sentence, how it is checked (a test, a benchmark metric with a threshold, a query, a manual check and who does it), and the target ("p95 solve time under 30 s on the estate benchmark", "no change in total cost, within 0.1%").
3. For every requirement checked by a benchmark, find the benchmark (`bench_list`, `bench_board`). If it does not exist or has no baseline run on the current code, the plan needs an early step that sets it up and records a baseline (`dsd bench set`, then `dsd exec -b <benchmark> -- <cmd>` or `/dsd-benchmark`), so later steps can be compared against it.
4. If the user cannot say how something would be checked, record it as an open question rather than dropping it.

## 3. Read the code before you design

Section 3 of the plan ("What is there today") needs file and line references and the gotchas an agent would not spot by reading the code. Pin references to the commit you read (`git rev-parse HEAD` on an up-to-date default branch) and write that commit and the date in the plan. Prefer GitHub permalinks when the repo has a GitHub remote; otherwise `path:line`.

## 4. Draft the plan

1. Pick a short slug and create the sub-plan: `dsd plan new <slug> --title "<Title>"` (it is linked from the central plan). Follow the title rules in the conventions; the Goal's first sentence is shown under the title in the dsd app, so make it the one-line summary.
2. Write the doc from `templates/plan.md` with `docs_write("plans/<slug>.md", ...)`, keeping the ten sections in order and leaving the `## Tasks` section empty for now. Put the agreed requirements in section 2. Set `status: draft`.
3. **Plan the steps.** This matters most, because each step gets a human review and should be safe to ship. Check every row against the four step rules in the conventions. These ways of splitting usually work:
   - Refactors apart from changes in behaviour.
   - New code lands dark first (no callers, or behind a flag that is off), then a small step wires it in.
   - Schema or data migrations alone, additive before the code that uses them and destructive after the code that stops using them.
   - Benchmarks, evals and test tooling before the change they measure, so the change has evidence.
   If you cannot say a row's change in one sentence without "and", split it.
4. **Give every step its own "Done when".** For each row, list the checks that show the step worked: the requirements it moves or must not break (by ID), the tests that must pass, and the benchmark run that must be recorded with its threshold. A step that changes behaviour without a check is not finished being planned. Steps that only refactor must show the output is unchanged (same tests, same benchmark numbers).
5. Write a sample description for each row (section 8, "Sample descriptions"): one or two plain-language paragraphs, as a reviewer would read them. If a row only makes sense with the plan open, fix the row.
6. Record each real decision in `decisions/NNNN-<slug>.md` from `templates/decision.md` (next free number; check `docs_list`). In the plan's section 4 list only the decisions it rests on, one line each. Recommend an answer but leave it `open` until the user decides.
7. Put anything you do not know in "Open questions" rather than guessing.
8. **Draw the change.** Readers should be able to see the design, not only read it. Use Mermaid code blocks (they render in the dsd app), following "Diagrams" in the conventions:
   - section 3: how it works today, as a flow of the parts this plan touches;
   - section 5: before and after, with the parts that change highlighted (`classDef changed`);
   - section 8: the delivery steps and what each unlocks, as a flow;
   - section 2 or 9: requirement targets and baselines as a chart (`xychart-beta`) when they are numbers.
   For something a static diagram can't show (a rule to try with real numbers, a before-and-after on real output), write an explainer page following `references/explainer.md` from `assets/explainer.html`, save it as `designs/<slug>.html`, and embed it in the plan with `![[designs/<slug>.html]]`.

## 5. Walk the user through it, then add tasks

1. Summarise the plan in chat in a few lines: the goal, the requirements and how each is checked, the steps (one line each, with their "Done when"), and the decisions and open questions that need the user. Point them to the doc (`plans/<slug>.md` in the dsd Docs view).
2. Revise until the user agrees. Expect to change the steps and the checks; that is the point of this stage.
3. **Only after the user confirms the steps and checks**, add the tasks, in delivery order. Keep the board high level: one task per step, and no separate tasks for checks or sub-steps.
   - `task_add(title, plan="<slug>", attrs={...})`, titled by the title rules: what the step achieves, in about 6 to 12 words ("Every reader gets its target from one resolver", not "Add resolver arg and tests (#13688 rebased)"). PR numbers, file names and flags go in the notes. Tag experiment work `#exp`, and add `benchmark` to `attrs` when a benchmark measures the step.
   - Write the step's documentation as notes on that task with `task_update(task_id, note=...)`, one line each:
     - `Done when: R2 p95 solve time < 30 s on estate (benchmark estate); R4 goldens byte-identical (tests/golden).`
     - `Safe to ship because: <reason>.` `Size: ~<n> lines.` `Rests on: 0003, 0005.`
   - A last task, `Requirements met`, whose notes list every project requirement and how it is checked.
   Then put each step's task id in the plan's delivery table.
4. Set `status: agreed` only when the user says so. Tell them the next step is `/dsd-develop`.

## Keep it current

- A step is done only when every check in its "Done when" has passed. Record each result as a note on the step's task (`task_update(<id>, note="Checked R2: p95 24 s on estate (run 3ax47yw7)")`). If a check fails, note the result, set the task `blocked`, and revise the plan with the user.
- When a step merges, mark its task done (`task_update(..., status="done", note="PR #123")`) and fill in the row. After the last one, set `status: done`.
- The plan says only what is planned now. When the plan changes, rewrite it and add a dated line to the plan's "Change log" saying what changed and why. Do not leave struck-out rows or "changed on" notes in the body.
- When a decision changes, edit its file: strike through the old answer, write the new one, and update the one-line summary in every plan that rests on it.
- Keep the user's own wording; add next to it instead of rewording it.
