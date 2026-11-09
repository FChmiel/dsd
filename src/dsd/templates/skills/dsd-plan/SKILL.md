---
name: dsd-plan
description: Turn the current conversation into a dsd project plan - new tasks in the central plan or a new sub-plan in docs/plans/. Use when the user says "make a plan", "add this to the plan", "turn this into tasks", or /dsd-plan.
---

# Turn this conversation into a plan

1. Call `plan_read` (MCP tool `dsd`) for `main` so you know the existing goal, sub-plans and tasks. Don't duplicate tasks that already exist.
2. Decide the shape:
   - A few concrete next steps → add tasks to the central plan with `task_add`.
   - A coherent multi-step effort (a milestone, a spike, an experiment campaign) → a sub-plan: run `dsd plan new <slug> --title "<Title>"` and then add tasks with `task_add(plan="<slug>")`.
3. Write good tasks:
   - One outcome per task, phrased as a verb ("Train XGBoost baseline on v2 features").
   - Tag experiment work `#exp` and set `@benchmark:<name>` when it'll produce comparable runs.
   - Nest sub-steps with `parent`.
4. If the plan needs context (goal, constraints, decisions made in this chat), edit the plan's prose with `docs_write`, keeping every existing task line unchanged.
5. Show the user the resulting plan (`dsd plan show <slug>`) and ask what to start with.
