---
name: dsd-run-experiment
description: Run and track an experiment with dsd, then compare results against the benchmark leaderboard. Use when the user asks to run an experiment, train/evaluate a model, run a benchmark, or /dsd-run-experiment.
---

# Run a tracked experiment

1. Work out the task (`T-..`) and benchmark this run belongs to. Check the plan (`plan_read`) and existing runs (`bench_board`). Ask if it's ambiguous.
2. Track it - prefer whichever needs the least change to the user's code:
   - **Uninstrumented script**: `dsd exec --benchmark <b> --task <T-..> --params <config.yaml> -- python train.py ...`
     The script can write `$DSD_RUN_DIR/metrics.json` (a dict of numbers) and files into `$DSD_RUN_DIR/artifacts/`.
   - **Instrumented code**:
     ```python
     import dsd
     with dsd.run("name", benchmark="b", task="T-12", params=cfg,
                  datasets=[dsd.dataset(id="...", uri="...", config="configs/data.yml")]) as r:
         r.log({"loss": l}, step=epoch)       # curves
         r.log({"auc": auc})                  # summary metrics
         r.info(notes="anything JSON")
         r.html("eval.html", html)             # or r.artifact("plot.png"), r.figure(fig, "roc")
     ```
   - Datasets are references: an id, a link (GitHub/S3) or a config file path - never copy data.
   - For seeds, run once per seed with `--param seed=N` so the leaderboard can show mean ± std.
3. After it finishes, name it: `run_update(<id>, name="<what varied, e.g. lgbm · depth 8 · seed 2>", description="<one line: what it tried>")`. If it failed, read the end of its log (`run_get`, or `dsd runs show <id>`) and put a short diagnosis in the description ("OOM at epoch 3 with batch 512"). If it wrote a report but logged no metrics, propose metrics from it as `/dsd-benchmark` does. Then `run_get(<id>)`, then `bench_board(<benchmark>, group_by=...)` to place it against previous runs. Report the key numbers and what changed versus the best previous run (`runs_compare`).
4. Add a one-line result note to the task with `task_update(task_id, note=...)`, including the run id.
