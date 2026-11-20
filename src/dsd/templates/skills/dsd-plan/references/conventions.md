# Plan conventions

The rules every dsd plan follows. `SKILL.md` holds the steps; this file holds the rules. If the user edits this file, it wins.

## Where things live

All of it is in the dsd project's docs folder, outside the repo (`data_dir` from `project_overview`, or `dsd info`):

```
docs/
├── plans/
│   ├── main.md            # the central plan; links every sub-plan
│   └── <slug>.md          # one plan per piece of work (dsd plan new <slug>)
└── decisions/
    └── NNNN-<slug>.md     # one file per decision, numbered across the project
```

Read and write them with the dsd MCP tools (`docs_read`, `docs_write`, `plan_read`, `task_add`, `task_update`). Task ids (`T-12`) are unique across all plans; never type one by hand.

## Frontmatter

```yaml
---
title: <Title>
status: draft
updated: <YYYY-MM-DD>
source: <link to the notes, ticket or doc it came from>
---
```

## Status values

| Status | Meaning | Who sets it |
|---|---|---|
| `draft` | Written, not agreed. No build work. | Claude |
| `agreed` | The user has reviewed it. Build work can start. | The user only |
| `in progress` | The first step is being built. | Claude |
| `done` | Every step is merged. | Claude |
| `parked` | Paused on purpose. Say why in the change log. | The user |
| `dropped` | Will not ship. Say why in the change log. | The user |

## Requirements and checks

- The plan's section 2 lists the requirements of the finished work, agreed with the user: `R1`, `R2`, … per plan. Never reuse an ID; mark a dropped one `dropped` with the reason.
- Every requirement says how it is checked and the target: a test, a benchmark metric with a threshold and direction, a query, or a manual check with who does it. "Works well" is not a requirement; "p95 solve time under 30 s on the estate benchmark" is.
- Include what must not get worse (guardrails), not only what must improve.
- Every step in the delivery plan has a "Done when": the requirement IDs it must meet or must not break, the tests, and the benchmark run with its threshold.
- Checks are tasks: nested under their step, tagged `#check`, with `@req:R<n>` and `@benchmark:<name>` when a benchmark measures it. The last task in the plan checks every project requirement.
- A requirement measured by a benchmark needs a baseline run on the code before the change. If there is none, an early step records one.
- A step is not done until its checks are done, with the result (numbers, run id) written on each check task.

## Decisions

- Number decision files `0001`, `0002`, … across the project. Never reuse a number.
- Each has **Context**, **Options**, **Recommendation**, **Decision** and **Plans that rest on it**.
- A decision is `open` until the user answers. Write the recommendation, but leave **Decision** as `open`.
- When a decision changes, strike through the old answer (`~~old~~`) and write the new one beside it.

## The four step rules

Every row in a delivery plan passes all four.

1. **One change.** You can say what the step does in one sentence, without "and".
2. **Small.** Ideally under 400 changed lines, and under 800. At 800 or more, split the row or write the very good reason in it.
3. **Safe to ship alone.** The main branch is releasable after the step merges, even if no later step ever ships. The row says why: "no callers yet", "behind a flag that is off", "additive migration", "output is identical, shown by the benchmark".
4. **One at a time.** Only one step is open for review at once, unless rows are marked as a stack (at most 3 tall).

Count lines against the step's base, leaving out lockfiles and generated files:

```bash
git diff --shortstat <base>...HEAD -- . ':(exclude)*.lock' ':(exclude)**/*.lock'
```

## Plain language

Plans, decisions and PR descriptions are read by busy people. Write to ISO 24495-1: the main point first, short sentences, everyday words, the active voice, and terms defined the first time they appear. A PR description is one or two short paragraphs that say what the change is and why; it must make sense without the plan.

## Asking first

Ask the user before every commit, push, PR, or change to a shared system. Hand them the commands for long test, benchmark or eval runs unless they ask you to run them.
