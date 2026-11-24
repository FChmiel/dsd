"""Build a realistic demo dsd project: git repo, plans, docs, tracked runs, an HTML report, a pending diff.

    uv run python examples/make_demo.py [target-dir]      # default: .demo/churn-model
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

MAIN_PLAN = """---
title: Churn model: main plan
status: active
---

# Churn model: main plan

## Goal

Predict which customers churn in the next 90 days well enough to target retention offers.
Success = **AUC ≥ 0.80** on benchmark `churn-v1` with a calibrated model (logloss below the baseline).
See [[decisions/0001-primary-metric.md]] for why AUC is the primary metric.

## Sub-plans

- [Feature engineering](feature-eng.md)

## Tasks

- [x] T-1 Agree success metric and benchmark protocol #decision
  → AUC primary, logloss secondary; 3 seeds per config. See decisions/0001.
- [x] T-2 EDA on synthetic churn extract
  → tenure and contract type dominate; see notes/2026-11-09-eda.md
- [/] T-3 Baseline models on churn-v1 #exp @benchmark:churn-v1
  Logistic regression and naive Bayes, 3 seeds each.
  - [x] T-4 Naive Bayes baseline #exp
  - [/] T-5 Logistic regression lr sweep #exp
- [ ] T-6 Add interaction features (tenure×contract) #exp @benchmark:churn-v1
- [!] T-7 Get production churn labels from data eng
  → blocked: waiting on access to the warehouse
- [ ] T-8 Calibration check and write-up report #report
"""

FEATURE_PLAN = """---
title: Feature engineering
status: active
parent: main
---

# Feature engineering

## Goal

Find features that add at least +0.01 AUC over the logistic baseline.

## Tasks

- [ ] T-9 Interaction terms tenure×contract, tickets×charges #exp @benchmark:churn-v1
- [ ] T-10 Bucketed tenure (0-6, 6-24, 24+ months) #exp
- [ ] T-11 Support-ticket recency features (needs prod data) #exp
"""

DECISION = """# 0001: AUC is the primary metric for churn-v1

**Status:** accepted · 2026-11-09 · task T-1

## Context
Retention offers go to the top-k riskiest customers, so ranking quality matters more than a threshold.

## Decision
- Primary metric: **AUC** (higher is better). Secondary: **logloss** (calibration) and accuracy.
- Every config runs with **3 seeds**; the leaderboard compares mean ± std.

## Alternatives considered
- *F1 at 0.5*: depends on the threshold and class balance; rejected.
- *Precision@k*: the closest to the business use, but noisy on small test sets. We'll revisit it with prod data (T-7).

## Consequences
`dsd bench set churn-v1 --primary auc --direction max`
"""

EDA_NOTE = """# EDA: synthetic churn extract

*2026-11-09 · task T-2*

## Summary
- ~1,500 customers, churn rate ≈ 30%.
- **Tenure** and **contract type** are the strongest signals; support tickets add a little.
- No missing values in the synthetic extract (prod data will differ, see T-7).

## Live results so far

```dsd-runs
benchmark: churn-v1
sort: -metrics.auc
metrics: auc, logloss, accuracy
limit: 6
```

## Leaderboard report

![[reports/churn-v1-leaderboard.html]]

## Open questions
- Does the lr sweep plateau above 0.3? (T-5)
- Interaction features: [Feature engineering](../plans/feature-eng.md)
"""

BENCH_DOC = """# Benchmark: churn-v1

| | |
|---|---|
| Dataset | `synthetic-churn-v1` (config: `configs/data.yml`) |
| Split | 80/20 holdout, seeded |
| Primary metric | AUC ↑ |
| Secondary | logloss ↓, accuracy ↑ |
| Seeds | 0, 1, 2 |

Run a config:

```
dsd exec -b churn-v1 --task T-5 -- python train.py --model logreg --lr 0.3 --seed 0
```
"""


PIPELINE = """flowchart LR
  raw[(Churn extract)] --> split[Train / test split]
  split --> feats[Features]
  subgraph models[Models on churn-v1]
    nb[Naive Bayes]
    lr[Logistic regression]
    lrx[Logreg + interactions]
  end
  feats --> nb & lr & lrx
  nb & lr & lrx --> board{AUC >= 0.80?}
  board -- yes --> ship[Retention offers]
  board -- no --> feats
"""


def sh(*args, cwd, check=True, quiet=True):
    return subprocess.run(list(args), cwd=cwd, check=check, capture_output=quiet, text=True)


def main() -> None:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO / ".demo" / "churn-model"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    git = ["git", "-c", "user.name=dsd demo", "-c", "user.email=demo@dsd.local"]

    sh("git", "init", "-q", "-b", "main", cwd=target)
    shutil.copy(HERE / "churn" / "train.py", target / "train.py")
    (target / "configs").mkdir()
    (target / "configs" / "data.yml").write_text("source: synthetic\nversion: v1\nrows: 1500\nsplit: {train: 0.8, test: 0.2}\n")
    (target / "README.md").write_text("# churn-model\n\nToy churn model used to demo dsd.\n")

    from dsd.init import init_project
    from dsd.project import all_projects

    for old in all_projects():
        if old.repo == target:
            shutil.rmtree(old.data_dir)
    p = init_project(target, name="churn-model").project
    (p.plans_path / "main.md").write_text(MAIN_PLAN)
    (p.plans_path / "feature-eng.md").write_text(FEATURE_PLAN)
    (p.docs_path / "decisions" / "0001-primary-metric.md").write_text(DECISION)
    (p.docs_path / "notes" / "2026-11-09-eda.md").write_text(EDA_NOTE)
    (p.docs_path / "experiments" / "churn-v1.md").write_text(BENCH_DOC)
    sh(*git, "add", "-A", cwd=target)
    sh(*git, "commit", "-qm", "Initial churn project\n\nTask: T-1", cwd=target)
    sh(*git, "commit", "-q", "--allow-empty", "-m", "Add naive Bayes and logreg trainers\n\nTask: T-4", cwd=target)

    dsd_cmd = [sys.executable, "-m", "dsd.cli"]
    sh(*dsd_cmd, "bench", "set", "churn-v1", "--primary", "auc", "--direction", "max", cwd=target)

    configs = [("nb", {"lr": 0}, "T-4")] + [("logreg", {"lr": lr}, "T-5") for lr in (0.03, 0.1, 0.3)] + [("logreg_x", {"lr": 0.1}, "T-6")]
    total = sum(1 for _ in configs) * 3
    i = 0
    for model, extra, task in configs:
        for seed in range(3):
            i += 1
            args = ["--model", model, "--seed", str(seed)] + [x for k, v in extra.items() for x in (f"--{k}", str(v))]
            print(f"[{i}/{total}] {model} {extra} seed={seed}", flush=True)
            sh(*dsd_cmd, "exec", "-b", "churn-v1", "--task", task, "--tag", model, "--",
               sys.executable, "train.py", *args, cwd=target, check=False)

    # one failed run, for realism
    sh(*dsd_cmd, "exec", "-b", "churn-v1", "--task", "T-5", "--name", "logreg-lr3-diverged", "--",
       sys.executable, "-c", "import sys; print('loss is nan, aborting'); sys.exit(1)", cwd=target, check=False)

    write_report(p)
    sh(*git, "commit", "-q", "--allow-empty", "-m", "Leaderboard report for churn-v1\n\nTask: T-3", cwd=target)

    # pending agent edit + a review comment, for the Changes view
    train = target / "train.py"
    src = train.read_text()
    src = src.replace('    ap.add_argument("--epochs", type=int, default=12)',
                      '    ap.add_argument("--epochs", type=int, default=20)\n    ap.add_argument("--patience", type=int, default=3)  # early stopping')
    src = src.replace("        noise=0.8)", "        noise=0.8)  # TODO: read from configs/data.yml")
    train.write_text(src)
    from dsd import review

    review.add_comment(p, "train.py", None, "Early stopping is parsed but never used. Wire --patience into train_logreg on val_auc.")

    from dsd import whiteboards

    whiteboards.queue_drawing(p, "Training pipeline", mermaid=PIPELINE)
    print(f"\nDemo project ready: {target}")


def write_report(p) -> None:
    from dsd.tracking.index import Index
    from dsd.tracking.query import leaderboard

    with Index(p) as idx:
        idx.sync()
        b = leaderboard(idx, p, "churn-v1", group_by="params.model,params.lr")
        rows = b["rows"]
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
    lo = min(r["stats"]["auc"]["min"] for r in rows) - 0.01
    hi = max(r["stats"]["auc"]["max"] for r in rows) + 0.005
    x = lambda v: 140 + (v - lo) / (hi - lo) * 380
    bars = []
    for i, r in enumerate(rows):
        s = r["stats"]["auc"]
        y = 30 + i * 34
        bars.append(
            f'<text x="130" y="{y + 4}" text-anchor="end" font-size="12" fill="#52514e">{r["group"]}</text>'
            f'<line x1="{x(s["min"]):.1f}" x2="{x(s["max"]):.1f}" y1="{y}" y2="{y}" stroke="{colors[i % 5]}" stroke-width="2"/>'
            f'<circle cx="{x(s["mean"]):.1f}" cy="{y}" r="5" fill="{colors[i % 5]}" stroke="white" stroke-width="2"/>'
            f'<text x="{x(s["max"]) + 10:.1f}" y="{y + 4}" font-size="11" fill="#191917">{s["mean"]:.4f} ± {s["std"]:.4f}</text>'
        )
    table = "".join(
        f"<tr><td>{r['rank']}</td><td><b>{r['group']}</b></td><td>{r['n']}</td>"
        f"<td>{r['stats']['auc']['mean']:.4f} ± {r['stats']['auc']['std']:.4f}</td>"
        f"<td>{r['stats']['logloss']['mean']:.4f}</td><td>{r['stats']['accuracy']['mean']:.4f}</td></tr>"
        for r in rows
    )
    best = rows[0]
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>churn-v1 leaderboard</title>
<style>body{{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:28px;color:#191917;max-width:820px}}
h1{{font-size:22px;margin:0 0 4px}}.sub{{color:#85847e;margin-bottom:20px}}
.hero{{display:flex;gap:28px;margin:18px 0}}.hero div b{{display:block;font-size:26px}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #eee}}
th{{color:#85847e;font-weight:550;font-size:12px}}</style></head><body>
<h1>churn-v1 leaderboard</h1><div class="sub">Generated by dsd · grouped by model · mean ± std over seeds</div>
<div class="hero"><div><span>Best model</span><b>{best['group']}</b></div>
<div><span>AUC</span><b>{best['stats']['auc']['mean']:.4f}</b></div>
<div><span>Runs</span><b>{sum(r['n'] for r in rows)}</b></div></div>
<svg width="680" height="{40 + 34 * len(rows)}" role="img" aria-label="AUC by model">{''.join(bars)}</svg>
<table><tr><th>#</th><th>model, lr</th><th>n</th><th>AUC</th><th>logloss</th><th>accuracy</th></tr>{table}</table>
<p style="color:#85847e;font-size:12px">Regenerate: <code>python examples/make_demo.py</code> (report section)</p>
</body></html>"""
    (p.docs_path / "reports").mkdir(exist_ok=True)
    (p.docs_path / "reports" / "churn-v1-leaderboard.html").write_text(html)


if __name__ == "__main__":
    main()
