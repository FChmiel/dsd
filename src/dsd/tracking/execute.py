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
import re
import signal
import subprocess
import sys
import time
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


CONFIG_SUFFIXES = (".yaml", ".yml", ".json", ".toml", ".cfg", ".ini")
OUTPUT_SUFFIXES = {".html", ".htm", ".json", ".csv", ".md", ".txt", ".png", ".svg", ".jpg", ".jpeg", ".pdf", ".yaml", ".yml"}
MAX_OUTPUT_FILE = 10_000_000
MAX_OUTPUT_TOTAL = 50_000_000
PATH_RE = re.compile(r"(?:~|\.{0,2})?/?[\w.@+-]+(?:/[\w.@+-]+)+")


def default_name(cmd: list[str]) -> str:
    """`uv run python train.py --x` -> 'train'; `just bench run configs/base.yaml` -> 'base'; `make bench` -> 'make bench'."""
    for arg in cmd:
        if not arg.startswith("-") and Path(arg).suffix in (".py", ".sh", ".ipynb", ".R", ".jl"):
            return Path(arg).stem
    if "-m" in cmd and cmd.index("-m") + 1 < len(cmd):
        return cmd[cmd.index("-m") + 1].rsplit(".", 1)[-1]
    for arg in cmd:
        if not arg.startswith("-") and Path(arg).suffix in CONFIG_SUFFIXES:
            return Path(arg).stem
    words = [a for a in cmd if not a.startswith("-")][:3] or cmd[:1]
    return " ".join([Path(words[0]).name, *words[1:]])


def detect_outputs(log: Path, cwd: Path, since: float) -> list[Path]:
    """Files the command's output mentions (e.g. 'report /path/to/report.html') that it wrote during the run."""
    try:
        with open(log, "rb") as fh:
            fh.seek(max(0, log.stat().st_size - 4_000_000))
            text = fh.read().decode(errors="replace")
    except OSError:
        return []
    found: list[Path] = []
    for raw in PATH_RE.findall(text):
        candidate = Path(os.path.expanduser(raw.rstrip(".,:;)"))) if raw.startswith("~") else Path(raw.rstrip(".,:;)"))
        path = candidate if candidate.is_absolute() else cwd / candidate
        try:
            if path.is_file() and path.stat().st_mtime >= since and path.resolve() not in found:
                found.append(path.resolve())
        except OSError:
            continue
        if len(found) >= 20:
            break
    return found


def attach_outputs(bundle: Bundle, outputs: list[Path], since: float) -> dict:
    """Copy each detected file, and files written next to it during the run, into the run's artifacts/outputs/."""
    picked: dict[str, Path] = {}
    for out in outputs:
        for f in [out, *sorted(out.parent.iterdir())]:
            try:
                st = f.stat()
            except OSError:
                continue
            if (f.is_file() and f.suffix.lower() in OUTPUT_SUFFIXES and st.st_size <= MAX_OUTPUT_FILE
                    and st.st_mtime >= since and f.name not in picked):
                picked[f.name] = f
    total = 0
    for name, f in picked.items():
        total += f.stat().st_size
        if total > MAX_OUTPUT_TOTAL:
            break
        bundle.add_artifact(f, name=f"outputs/{name}")
    return {"outputs": str(outputs[0].parent)} if outputs else {}


def exec_command(
    project: Project, cmd: list[str], *, name: str | None = None, benchmark: str | None = None,
    task: str | None = None, tags: list[str] | None = None, params: dict | None = None,
    datasets: list[dict] | None = None, quiet: bool = False,
) -> tuple[Bundle, int]:
    if not cmd:
        raise ValueError("no command given")
    task = task or os.environ.get(ENV_TASK)
    benchmark = benchmark or os.environ.get(ENV_BENCHMARK)
    started = time.time() - 1
    bundle = create_bundle(
        project.runs_path, project.root, project.id, name=name or default_name(cmd),
        benchmark=benchmark, task=task, params=params, tags=tags, datasets=datasets, command=list(cmd),
        worktree=project.root.name if project.is_worktree else None,
    )
    env = {
        **os.environ,
        ENV_RUN_DIR: str(bundle.path), ENV_RUN_ID: bundle.id, ENV_PROJECT: str(project.work_dir),
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
    outputs = detect_outputs(log_path, Path.cwd(), started)
    if outputs:
        links = attach_outputs(bundle, outputs, started)
        info = bundle.read_meta().get("info", {})
        bundle.update_meta(info={**info, "links": {**info.get("links", {}), **links},
                                 "detected_outputs": [str(p) for p in outputs]})
    bundle.rescan_artifacts()
    fields = {"status": status, "ended_at": now_iso(), "exit_code": code}
    if status == "failed":
        fields["error"] = f"exit code {code}"
    elif status == "killed":
        fields["error"] = "interrupted"
    bundle.update_meta(**fields)
    return bundle, code
