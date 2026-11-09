---
name: dsd-distill
description: Distill the current conversation into durable project docs - a decision record or research note under docs/. Use when the user says "write this up", "record this decision", "save what we decided", or /dsd-distill.
---

# Distill this conversation into docs

1. Identify what is worth keeping: decisions (with the alternatives considered and why), findings, open questions, and follow-up tasks. Leave out chatter and dead ends unless they explain a decision.
2. Choose the doc type:
   - **Decision** → `docs/decisions/NNNN-short-slug.md` (NNNN = next number; check `docs_list`). Sections: Context, Decision, Alternatives considered, Consequences, Links (tasks, runs, files).
   - **Note** → `docs/notes/YYYY-MM-DD-short-slug.md`. Sections: Summary, Findings, Open questions, Links.
3. Reference tasks as `T-12`, runs by id, and code as relative paths.
4. Draft the doc and show it to the user before writing. After they approve, write it with `docs_write`.
5. Offer to turn the follow-ups into tasks (`task_add`), and link the new doc from the relevant plan.
