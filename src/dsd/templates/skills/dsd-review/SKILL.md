---
name: dsd-review
description: Review a GitHub pull request so the user understands it - ask whether they want an HTML explainer, summarise the PR, ask what to focus on, then build the explainer with diagrams, small interactive widgets and charts of the PR's evidence, ending with blockers and recommended changes. Use when the user shares a PR link or number and asks for a review, a walkthrough, "help me understand this PR", or /dsd-review.
---

# Review a pull request

The aim is understanding first, judgement second. The user should come away able to explain the PR; recommendations come at the end.

## 1. Ask two things first (wait)

Before reading anything, ask the user, in one short message:

1. The PR link or number, if they haven't given it.
2. Whether they want an HTML explainer page: "Do you want an HTML explainer (diagrams, small interactive widgets, charts of the PR's evidence) to help you understand it, or a review in chat only? I'd recommend the explainer for anything over about 200 lines or with subtle logic."

If they have already given the link and said which they want, don't ask again. If they don't answer the second question, build the explainer.

## 2. Get the PR

Read it (read-only; do not check out over the user's work):

```bash
gh pr view <url-or-number> --json number,title,url,author,body,baseRefName,headRefName,headRefOid,additions,deletions,changedFiles,files,commits,labels,reviews,comments
gh pr diff <url-or-number>
```

Read the changed code in context, not just the diff: fetch the head commit (`git fetch origin pull/<n>/head` in the repo) and read whole functions around each change with `git show <headRefOid>:<path>`. Read the tests the PR adds or changes; they often explain intent best.

Collect the evidence in the description: benchmark tables, metrics, screenshots, logs, linked dashboards or runs. If it references dsd runs or benchmarks, look them up (`runs_query`, `bench_board`).

## 3. Summarise and ask for focus (wait)

In chat, give a short summary: what the PR does and why (from the author's words and the code), its size, the areas it touches, and your first impression of the riskiest part. Then ask the user whether there are areas they want the review to focus on, and whether they want you to run the tests or benchmarks locally. Wait for the answer.

## 4. Build the explainer

If the user chose the explainer (or didn't say), build it now, straight after their answer to step 3; don't end your turn with only a chat review. If they chose chat only, skip to step 5 and put the recommendations in chat.


Follow `references/explainer.md` and start from `assets/explainer.html` in this skill's folder.

- Explain the change the way a good senior colleague would at a whiteboard: the main diagram of how it works, then each key difference before and after.
- Where logic is subtle (thresholds, formulas, ordering, edge cases), add a small widget that runs the real rule on real example values, so the reader can try it.
- Re-draw the PR's evidence: put benchmark numbers in a chart and a table with units, and say what they show and what they do not. Quote the author's figures exactly and link the source.
- Give the user's focus areas their own section, near the top.
- Cite code with permalinks at the PR's head commit.
- End with **Recommendations**: blockers first (must change before merge), then changes worth making, then optional suggestions. Each says where (file and line), what, and why. Mark guesses as questions for the author rather than findings.

Save it with `docs_write("reviews/pr-<number>-<slug>.html", ...)` and tell the user where it is (the dsd Docs view, or `open "<data_dir>/docs/reviews/..."`).

## 5. Hand over

Give the user the three or four things that matter most in chat, and point to the page for the rest. Do not post comments, approve or request changes on GitHub unless the user asks; if they do, show them the exact text first.
