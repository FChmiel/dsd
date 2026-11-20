"""Record a run that already happened (e.g. a benchmark whose results were dumped to an HTML file).

Unlike `dsd exec` and `dsd.run`, nothing is executed: the metrics, parameters, links and artifacts
are given, and the run is stored as finished so it ranks on its benchmark like any other run.
"""

from __future__ import annotations

import math
import subprocess
from datetime import datetime
from pathlib import Path

from ..project import Project
from .bundle import Bundle, flatten, to_jsonable
from .sdk import create_bundle


class RecordError(ValueError):
    pass


def _numeric(metrics: dict) -> dict[str, float]:
    out = {}
    for k, v in flatten(metrics).items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise RecordError(f"metric {k!r}={v!r} is not a number")
        if math.isnan(f) or math.isinf(f):
            raise RecordError(f"metric {k!r} is {f}")
        out[k] = f
    return out


def _resolve_commit(root: Path, ref: str) -> str:
    r = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], cwd=root,
                       capture_output=True, text=True)
    return r.stdout.strip() or ref


def record_run(
    project: Project, name: str, *, benchmark: str | None = None, task: str | None = None,
    metrics: dict | None = None, params: dict | None = None, links: dict[str, str] | None = None,
    artifacts: list[str | Path] | None = None, notes: str | None = None, tags: list[str] | None = None,
    created_at: str | None = None, commit: str | None = None,
) -> Bundle:
    if not metrics and not artifacts and not links:
        raise RecordError("give at least one metric, artifact or link")
    values = _numeric(metrics or {})
    missing = [str(a) for a in artifacts or [] if not Path(a).exists()]
    if missing:
        raise RecordError(f"artifact not found: {', '.join(missing)}")
    if created_at:
        try:
            datetime.fromisoformat(created_at)
        except ValueError:
            raise RecordError(f"created_at must be an ISO date or datetime, got {created_at!r}")
    info: dict = {"recorded": True}
    if links:
        info["links"] = dict(links)
    if notes:
        info["notes"] = notes
    bundle = create_bundle(project.runs_path, project.root, project.id, name=name, benchmark=benchmark, task=task,
                           params=to_jsonable(params or {}), info=info, tags=tags, command=[], status="running",
                           worktree=project.root.name if project.is_worktree else None)
    if values:
        bundle.append_metrics(values)
    for a in artifacts or []:
        bundle.add_artifact(Path(a))
    fields: dict = {"status": "finished", "ended_at": created_at or bundle.read_meta()["created_at"]}
    if created_at:
        fields["created_at"] = created_at
    if commit:
        (bundle.capture_dir / "git.diff").unlink(missing_ok=True)
        fields["git"] = {"sha": _resolve_commit(project.root, commit), "branch": None, "dirty": None, "recorded": True}
    bundle.update_meta(**fields)
    return bundle


def update_run(
    project: Project, ref: str, *, name: str | None = None, description: str | None = None,
    metrics: dict | None = None, params: dict | None = None, links: dict[str, str] | None = None,
    artifacts: list[str | Path] | None = None, tags: list[str] | None = None,
) -> Bundle:
    """Improve a recorded run: a clearer name, a description (e.g. why it failed), metrics read from its report,
    params, links and artifacts. Existing metrics, params and links are kept unless overwritten."""
    from .index import Index

    values = _numeric(metrics or {})
    missing = [str(a) for a in artifacts or [] if not Path(a).exists()]
    if missing:
        raise RecordError(f"artifact not found: {', '.join(missing)}")
    with Index(project) as idx:
        idx.sync()
        try:
            rid = idx.resolve_id(ref)
        except KeyError:
            raise RecordError(f"No run '{ref}'")
        bundle = Bundle(Path(idx.run_detail(rid)["bundle_path"]))
    meta = bundle.read_meta()
    if name:
        meta["name"] = name
    info = dict(meta.get("info") or {})
    if description is not None:
        info["description"] = description
    if links:
        info["links"] = {**info.get("links", {}), **links}
    meta["info"] = info
    if params:
        meta["params"] = {**meta.get("params", {}), **to_jsonable(params)}
    if tags:
        meta["tags"] = list(dict.fromkeys([*meta.get("tags", []), *tags]))
    bundle.write_meta(meta)
    if values:
        bundle.append_metrics(values)
    for a in artifacts or []:
        bundle.add_artifact(Path(a))
    return bundle
