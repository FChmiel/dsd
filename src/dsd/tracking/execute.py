"""`dsd exec`: track any command without instrumenting it.

The child gets DSD_RUN_DIR / DSD_RUN_ID in its env. It can:
  * call the SDK (dsd.run() attaches to this run),
  * write $DSD_RUN_DIR/metrics.json (flat or nested dict; numbers become metrics, the rest info),
  * write files into $DSD_RUN_DIR/artifacts/.
stdout/stderr are tee'd to capture/stdout.log; the exit code decides the status.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import yaml

from ..project import Project
from .bundle import Bundle, flatten, now_iso, to_jsonable
from .sdk import ENV_BENCHMARK, ENV_PROJECT, ENV_RUN_DIR, ENV_RUN_ID, ENV_TASK, create_bundle


def load_params_file(path: Path) -> dict:
    text = path.read_text()
    if path.suffix == ".json":
        return json.loads(text)
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {"value": data}


def ingest_metrics_json(bundle: Bundle) -> None:
    path = bundle.path / "metrics.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    metrics, info = {}, {}
    for k, v in flatten(data).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            metrics[k] = v
        else:
            info[k] = v
    bundle.append_metrics(metrics)
    if info:
        meta = bundle.read_meta()
        meta["info"] = {**meta.get("info", {}), **to_jsonable(info)}
        bundle.write_meta(meta)


def default_name(cmd: list[str]) -> str:
    """`uv run python train.py --x` -> 'train'; `make bench` -> 'make'."""
    for arg in cmd:
        if not arg.startswith("-") and Path(arg).suffix in (".py", ".sh", ".ipynb", ".R", ".jl"):
            return Path(arg).stem
    if "-m" in cmd and cmd.index("-m") + 1 < len(cmd):
        return cmd[cmd.index("-m") + 1].rsplit(".", 1)[-1]
    return Path(cmd[0]).name


def exec_command(
    project: Project, cmd: list[str], *, name: str | None = None, benchmark: str | None = None,
    task: str | None = None, tags: list[str] | None = None, params: dict | None = None,
    datasets: list[dict] | None = None, quiet: bool = False,
) -> tuple[Bundle, int]:
    if not cmd:
        raise ValueError("no command given")
    task = task or os.environ.get(ENV_TASK)
    benchmark = benchmark or os.environ.get(ENV_BENCHMARK)
    bundle = create_bundle(
        project.runs_path, project.root, project.id, name=name or default_name(cmd),
        benchmark=benchmark, task=task, params=params, tags=tags, datasets=datasets, command=list(cmd),
        worktree=project.root.name if project.is_worktree else None,
    )
    env = {
        **os.environ,
        ENV_RUN_DIR: str(bundle.path), ENV_RUN_ID: bundle.id, ENV_PROJECT: str(project.root),
        "PYTHONUNBUFFERED": os.environ.get("PYTHONUNBUFFERED", "1"),
    }
    if task:
        env[ENV_TASK] = task
    if benchmark:
        env[ENV_BENCHMARK] = benchmark

    log_path = bundle.capture_dir / "stdout.log"
    status, code = "failed", 1
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        bundle.update_meta(status="failed", ended_at=now_iso(), error=f"could not start: {e}")
        return bundle, 127
    bundle.update_meta(child_pid=proc.pid)
    out = sys.stdout.buffer
    try:
        with open(log_path, "wb") as log:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read1(65536)
                if not chunk:
                    break
                log.write(chunk)
                if not quiet:
                    out.write(chunk)
                    out.flush()
        code = proc.wait()
        status = "finished" if code == 0 else "failed"
    except KeyboardInterrupt:
        try:
            proc.send_signal(signal.SIGINT)
            code = proc.wait(timeout=10)
        except Exception:
            proc.kill()
            code = proc.wait()
        status = "killed"
    ingest_metrics_json(bundle)
    bundle.rescan_artifacts()
    fields = {"status": status, "ended_at": now_iso(), "exit_code": code}
    if status == "failed":
        fields["error"] = f"exit code {code}"
    elif status == "killed":
        fields["error"] = "interrupted"
    bundle.update_meta(**fields)
    return bundle, code
