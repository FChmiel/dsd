---
name: dsd-next-task
description: Pick up the next task from the dsd plan, mark it in progress and gather its context. Use when the user says "what's next", "next task", "start T-12", or /dsd-next-task.
---

# Pick up the next task

1. If the user named a task (e.g. T-12), use it. Otherwise call `plan_list` and `plan_read` and pick the first `todo` task whose parent and predecessors are done, preferring the central plan. Say which task you chose and why.
2. Call `task_update(task_id, status="doing")`.
3. Gather context before writing code:
   - The task's notes and its parent task.
   - `docs_search` for its key terms (decisions and notes often explain constraints).
   - If it is experiment work: `runs_query(task=...)` and `bench_board(<benchmark>)` to see what has already been tried.
4. Summarise the context and your approach in a few lines, then do the work.
5. When finished: `task_update(task_id, status="done", note="<one-line outcome, with run ids or metrics if relevant>")`. Use a `Task: T-12` trailer in any commit.
