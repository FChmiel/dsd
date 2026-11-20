# Explainer pages

An explainer is one self-contained HTML page that helps someone understand a change quickly: what it does, why, how it works, and what to watch. `/dsd-plan` can embed one in a plan when a diagram isn't enough; `/dsd-develop` writes one before building; `/dsd-review` writes one for a pull request. Start from `assets/explainer.html` in this skill folder. Replace every `TITLE`, `SUBTITLE` and `TODO` in it, swap the example rule in the widget script and the example chart data for the real ones, and delete sections that add nothing.

## Who it is for

A good graduate who is new to this code: clever, short of time, and not yet fluent in the team's jargon. They should understand the change in about ten minutes.

## Write in plain language (ISO 24495-1)

- **Main point first.** The page opens with a two- or three-sentence summary a reader could stop after.
- **Short sentences, everyday words, active voice.** "The solver now skips closed days", not "Closed days are now excluded from consideration by the solver".
- **Define each term once,** the first time you use it, in a few words. Prefer the plain word if one exists.
- **Headings say what the section tells you** ("Why the totals changed"), not just a topic ("Totals").
- **Numbers carry units and a comparison** ("12% fewer hours than last week's run"), never a bare figure.
- **Say what you don't know.** Mark estimates and assumptions as such. Never invent numbers, results or behaviour.

## Show, don't only tell

Use a picture wherever it is quicker than prose. Each one gets a one-sentence caption that says what to notice.

- **Before and after.** For the key difference, show the old and the new side by side: a flow, a data shape, a small code excerpt (10 to 20 lines, not whole files), or an output.
- **Flow and structure diagrams.** Mermaid (`<pre class="mermaid">`) for flows, sequences and component boxes. Keep to about 12 nodes; split larger ones. Highlight what changed (for example a `changed` class) rather than drawing everything.
- **Charts.** Chart.js for benchmark and metric results: bar charts to compare runs, line charts for curves. Label axes with units. Put the source of the numbers in the caption.
- **Small widgets for logic.** When a rule is easier to feel than read (a threshold, a formula, a branch), build a tiny interactive: inputs or sliders on the left, the result on the right, using the real rule and real example values from the code or tests. Keep each under about 40 lines of JavaScript.
- **Tables** for short comparisons (options, before and after numbers, file roles).

## Structure

Adapt it to the change; drop sections that add nothing.

1. **At a glance**: the summary, then key facts (size, areas touched, risk level).
2. **Why**: the problem or goal, in the reader's terms.
3. **How it works**: the main diagram and a short walk through it.
4. **What changes**: the key differences, before and after, each with a picture or excerpt.
5. **What stays the same**: what a reader might worry about but need not.
6. **Evidence**: tests, benchmarks, screenshots and results (for a PR, everything in its description), re-drawn as charts or tables where that helps.
7. **Risks and open questions.**
8. **Recommendations** (reviews only, always last): blockers, then changes worth making, then optional suggestions, each with the file and line, and why.

## Make it trustworthy

- Link every code claim to the file and line, pinned to the commit you read (a GitHub permalink at the PR's head commit when there is one).
- Quote evidence exactly as the author gave it, and say where it came from.
- One file, no build step. Libraries only from `cdn.jsdelivr.net`. The page must still read sensibly if the scripts fail to load: put the key numbers in the text too.
- Light and dark mode both readable (the template handles this).

## Where it goes

Save it in the dsd project's docs with `docs_write`, so it shows in the dsd app's Docs view: `designs/<slug>.html` for `/dsd-plan` (embed it in the plan with `![[designs/<slug>.html]]`), `designs/<task-id>-<slug>.html` for `/dsd-develop`, `reviews/pr-<number>-<slug>.html` for `/dsd-review`. Tell the user the path; to open it directly, run `open "<data_dir>/docs/<path>"` (data_dir from `project_overview`).
