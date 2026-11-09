"""The tracking SDK.

    import dsd
    with dsd.run("xgb", benchmark="churn-v1", task="T-12", params=cfg) as r:
        r.log({"loss": 0.3}, step=1)
        r.log({"auc": 0.81})
        r.artifact("report.html")

Tracking must never break the user's job: every public method swallows its own errors and warns.
If launched under `dsd exec`, dsd.run() attaches to the exec's run instead of creating a new one.
"""

from __future__ import annotations

import atexit
import functools
import json
import math
import os
import sys
import warnings
from pathlib import Path

from ..ids import ulid
from ..project import ProjectNotFound, find_project, load_project
from .bundle import Bundle, now_iso, to_jsonable
from .capture import current_user, dataset, env_info, git_info, packages

ENV_RUN_DIR = "DSD_RUN_DIR"
ENV_RUN_ID = "DSD_RUN_ID"
ENV_TASK = "DSD_TASK"
ENV_BENCHMARK = "DSD_BENCHMARK"
ENV_PROJECT = "DSD_PROJECT_ROOT"

_active: list["Run"] = []


class DsdWarning(UserWarning):
    pass


def _warn(msg: str, stacklevel: int = 4) -> None:
    # default: _warn <- method body <- _safe wrapper <- user code
    warnings.warn(f"[dsd] {msg}", DsdWarning, stacklevel=stacklevel)


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - tracking must not kill the job
            _warn(f"{fn.__name__} failed: {e!r}", stacklevel=3)
            return None

    return wrapper


def _resolve_project():
    root = os.environ.get(ENV_PROJECT)
    try:
        return load_project(Path(root)) if root else find_project()
    except ProjectNotFound:
        return None


def _merge_unique(a: list, b: list) -> list:
    out = list(a or [])
    for x in b or []:
        if x not in out:
            out.append(x)
    return out


class Run:
    def __init__(self, bundle: Bundle, owned: bool):
        self.bundle = bundle
        self.owned = owned  # False when attached to a `dsd exec` run (the parent finalizes)
        self._finished = False

    @property
    def id(self) -> str:
        return self.bundle.id

    @property
    def dir(self) -> Path:
        return self.bundle.path

    @property
    def artifacts_dir(self) -> Path:
        return self.bundle.artifacts_dir

    def __repr__(self) -> str:
        return f"<dsd.Run {self.id} at {self.dir}>"

    # ---- logging
    @_safe
    def log(self, values: dict | None = None, step: int | None = None, **kwargs) -> None:
        """Log numeric metrics. With `step` they form a curve; without, they are summary values."""
        clean = {}
        for k, v in {**(values or {}), **kwargs}.items():
            try:
                f = float(v)
            except (TypeError, ValueError):
                _warn(f"metric {k!r}={v!r} is not numeric; use run.info() for non-numeric values")
                continue
            if math.isnan(f) or math.isinf(f):
                _warn(f"metric {k!r} is {f}; skipped")
                continue
            clean[k] = f
        self.bundle.append_metrics(clean, step=step)

    @_safe
    def params(self, values: dict | None = None, **kwargs) -> None:
        meta = self.bundle.read_meta()
        meta["params"] = {**meta.get("params", {}), **to_jsonable({**(values or {}), **kwargs})}
        self.bundle.write_meta(meta)

    @_safe
    def info(self, values: dict | None = None, **kwargs) -> None:
        """Free-form JSON metadata (strings, lists, nested dicts...)."""
        meta = self.bundle.read_meta()
        meta["info"] = {**meta.get("info", {}), **to_jsonable({**(values or {}), **kwargs})}
        self.bundle.write_meta(meta)

    @_safe
    def tag(self, *tags: str) -> None:
        meta = self.bundle.read_meta()
        meta["tags"] = _merge_unique(meta.get("tags", []), list(tags))
        self.bundle.write_meta(meta)

    @_safe
    def artifact(self, path: str | os.PathLike, name: str | None = None, description: str | None = None) -> None:
        """Copy a file or directory into the run (HTML reports, plots, model cards...)."""
        self.bundle.add_artifact(Path(path), name=name, description=description)

    @_safe
    def html(self, name: str, content: str, description: str | None = None) -> None:
        """Write an HTML (or any text) artifact directly from a string."""
        if not Path(name).suffix:
            name += ".html"
        self.bundle.write_artifact_text(name, content, description)

    @_safe
    def figure(self, fig, name: str, description: str | None = None) -> None:
        """Save a matplotlib or plotly figure as an artifact."""
        if hasattr(fig, "write_html"):  # plotly
            if not name.endswith(".html"):
                name += ".html"
            path = self.artifacts_dir / name
            fig.write_html(str(path), include_plotlyjs="cdn")
        else:
            if not Path(name).suffix:
                name += ".png"
            path = self.artifacts_dir / name
            fig.savefig(str(path), bbox_inches="tight", dpi=150)
        self.bundle.rescan_artifacts({name: description})

    # ---- lifecycle
    @_safe
    def finish(self, status: str = "finished", error: str | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        if self in _active:
            _active.remove(self)
        self.bundle.rescan_artifacts()
        if not self.owned:
            if error:
                self.info(error=error)
            return
        fields = {"status": status, "ended_at": now_iso()}
        if error:
            fields["error"] = error
        self.bundle.update_meta(**fields)

    def __enter__(self) -> "Run":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.finish("finished")
        elif issubclass(exc_type, KeyboardInterrupt):
            self.finish("killed", error="KeyboardInterrupt")
        else:
            self.finish("failed", error=f"{exc_type.__name__}: {exc}")
        return False


def _attach(name, benchmark, task, params, info, tags, datasets) -> Run | None:
    run_dir = os.environ.get(ENV_RUN_DIR)
    if not run_dir:
        return None
    bundle = Bundle(Path(run_dir))
    if not bundle.exists():
        return None
    meta = bundle.read_meta()
    if name:
        meta["name"] = name
    meta["benchmark"] = benchmark or meta.get("benchmark")
    meta["task"] = task or meta.get("task")
    meta["params"] = {**meta.get("params", {}), **to_jsonable(params or {})}
    meta["info"] = {**meta.get("info", {}), **to_jsonable(info or {})}
    meta["tags"] = _merge_unique(meta.get("tags", []), list(tags or []))
    meta["datasets"] = list(meta.get("datasets", [])) + list(datasets or [])
    bundle.write_meta(meta)
    return Run(bundle, owned=False)


def create_bundle(
    runs_dir: Path, root: Path, project_id: str | None, *, name: str | None = None,
    benchmark: str | None = None, task: str | None = None, params: dict | None = None,
    info: dict | None = None, tags: list[str] | None = None, datasets: list[dict] | None = None,
    command: list[str] | None = None, backend: str = "local", external_id: str | None = None,
    status: str = "running", pid: int | None = None, worktree: str | None = None,
) -> Bundle:
    run_id = ulid()
    started = now_iso()
    bundle = Bundle.create(runs_dir, run_id, {
        "project_id": project_id,
        "name": name or Path(sys.argv[0]).stem or "run",
        "benchmark": benchmark,
        "task": task,
        "tags": list(tags or []),
        "status": status,
        "backend": backend,
        "external_id": external_id,
        "created_at": started,
        "ended_at": None,
        "pid": pid if pid is not None else os.getpid(),
        "user": current_user(),
        "command": command if command is not None else list(sys.argv),
        "cwd": os.getcwd(),
        "params": to_jsonable(params or {}),
        "info": to_jsonable(info or {}),
        "datasets": list(datasets or []),
        "worktree": worktree,
    })
    try:
        g = git_info(root, diff_out=bundle.capture_dir / "git.diff")
        env = env_info(root)
        bundle.update_meta(git=g, env=env)
        (bundle.capture_dir / "packages.json").write_text(json.dumps(packages(), indent=1))
    except Exception as e:  # noqa: BLE001
        _warn(f"context capture failed: {e!r}")
    return bundle


def start_run(
    name: str | None = None, *, benchmark: str | None = None, task: str | None = None,
    params: dict | None = None, info: dict | None = None, tags: list[str] | None = None,
    datasets: list[dict] | None = None, backend: str = "local", external_id: str | None = None,
) -> Run:
    """Start (or, under `dsd exec`, attach to) a run. Use as a context manager or call .finish()."""
    benchmark = benchmark or os.environ.get(ENV_BENCHMARK)
    task = task or os.environ.get(ENV_TASK)
    attached = _attach(name, benchmark, task, params, info, tags, datasets)
    if attached:
        _active.append(attached)
        return attached

    project = _resolve_project()
    if project is None:
        root = Path.cwd()
        runs_dir = root / ".dsd" / "runs"
        _warn(f"not inside a dsd project; writing run to {runs_dir} (run `dsd init` to set one up)")
        project_id = None
    else:
        root, runs_dir, project_id = project.root, project.runs_path, project.id
    runs_dir.mkdir(parents=True, exist_ok=True)
    bundle = create_bundle(
        runs_dir, root, project_id, name=name, benchmark=benchmark, task=task, params=params,
        info=info, tags=tags, datasets=datasets, backend=backend, external_id=external_id,
        worktree=project.root.name if project is not None and project.is_worktree else None,
    )
    r = Run(bundle, owned=True)
    _active.append(r)
    return r


# ---------------------------------------------------------------- module-level convenience

def active_run() -> Run | None:
    return _active[-1] if _active else None


def log(values: dict | None = None, step: int | None = None, **kwargs) -> None:
    r = active_run()
    if r is None:
        _warn("dsd.log() called with no active run; call dsd.run(...) first")
        return
    r.log(values, step=step, **kwargs)


def finish(status: str = "finished") -> None:
    r = active_run()
    if r is not None:
        r.finish(status)


_uncaught: list[BaseException] = []
_prev_hook = sys.excepthook


def _excepthook(tp, value, tb):
    _uncaught.append(value)
    _prev_hook(tp, value, tb)


sys.excepthook = _excepthook


@atexit.register
def _finish_dangling() -> None:
    for r in list(_active):
        if _uncaught:
            e = _uncaught[-1]
            status = "killed" if isinstance(e, KeyboardInterrupt) else "failed"
            r.finish(status, error=f"{type(e).__name__}: {e}")
        else:
            r.finish("finished")


__all__ = ["Run", "start_run", "active_run", "log", "finish", "dataset", "create_bundle"]
