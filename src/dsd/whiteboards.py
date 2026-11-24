"""Whiteboards: Excalidraw drawings kept in the project's docs (docs/whiteboards/<slug>.excalidraw).

Each board is a standard Excalidraw file plus a `dsd` block with its display name and drawings Claude has
queued (`pending`): Mermaid source or Excalidraw element skeletons. Turning those into Excalidraw elements
needs Excalidraw itself, so the app applies them in the browser when the board is open, then saves the
board and drops the queue entries it applied.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .ids import ulid
from .project import Project

FOLDER = "whiteboards"
SUFFIX = ".excalidraw"
SKELETON_TYPES = {"rectangle", "diamond", "ellipse", "arrow", "line", "text", "freedraw", "frame"}


class WhiteboardError(Exception):
    pass


def _dir(project: Project) -> Path:
    return project.docs_path / FOLDER


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "board"


def _path(project: Project, slug: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise WhiteboardError(f"Invalid board '{slug}'")
    return _dir(project) / f"{slug}{SUFFIX}"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise KeyError(f"No whiteboard '{path.stem}'")
    except ValueError:
        raise WhiteboardError(f"{path.name} is not a valid Excalidraw file")
    data.setdefault("elements", [])
    data.setdefault("dsd", {})
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _empty(name: str) -> dict:
    return {"type": "excalidraw", "version": 2, "source": "dsd", "elements": [],
            "appState": {"viewBackgroundColor": "#ffffff"}, "files": {}, "dsd": {"name": name, "pending": []}}


def list_boards(project: Project) -> list[dict]:
    out = []
    for f in sorted(_dir(project).glob(f"*{SUFFIX}")) if _dir(project).is_dir() else []:
        try:
            data = _read(f)
        except (KeyError, WhiteboardError):
            continue
        live = [e for e in data["elements"] if not e.get("isDeleted")]
        out.append({"slug": f.stem, "name": data["dsd"].get("name") or f.stem, "updated": f.stat().st_mtime,
                    "shapes": len(live), "pending": len(data["dsd"].get("pending") or [])})
    out.sort(key=lambda b: -b["updated"])
    return out


def new_board(project: Project, name: str) -> str:
    name = name.strip() or "Untitled"
    slug, n = _slugify(name), 1
    while _path(project, slug).exists():
        n += 1
        slug = f"{_slugify(name)}-{n}"
    _write(_path(project, slug), _empty(name))
    return slug


def find_board(project: Project, ref: str) -> str | None:
    """A board's slug from its slug or display name."""
    if _path(project, _slugify(ref)).exists():
        return _slugify(ref)
    return next((b["slug"] for b in list_boards(project) if b["name"].lower() == ref.strip().lower()), None)


def read_board(project: Project, slug: str) -> dict:
    return _read(_path(project, slug))


def save_board(project: Project, slug: str, scene: dict, applied: list[str] | None = None) -> dict:
    """Save the app's scene; drop the queued drawings it applied, keep any queued since."""
    path = _path(project, slug)
    data = _read(path)
    if not isinstance(scene.get("elements"), list):
        raise WhiteboardError("scene.elements must be a list")
    data["elements"] = scene["elements"]
    if isinstance(scene.get("appState"), dict):
        data["appState"] = scene["appState"]
    if isinstance(scene.get("files"), dict):
        data["files"] = scene["files"]
    done = set(applied or [])
    data["dsd"]["pending"] = [p for p in data["dsd"].get("pending") or [] if p.get("id") not in done]
    _write(path, data)
    return {"ok": True, "pending": len(data["dsd"]["pending"])}


def rename_board(project: Project, slug: str, name: str) -> str:
    data = read_board(project, slug)
    data["dsd"]["name"] = name.strip() or data["dsd"].get("name") or slug
    new = _slugify(name)
    if new != slug and _path(project, new).exists():
        raise WhiteboardError(f"A board named '{name}' already exists")
    _write(_path(project, new), data)
    if new != slug:
        _path(project, slug).unlink()
    return new


def delete_board(project: Project, slug: str) -> None:
    path = _path(project, slug)
    if not path.exists():
        raise KeyError(f"No whiteboard '{slug}'")
    path.unlink()


def queue_drawing(project: Project, board: str, *, mermaid: str | None = None, elements: list[dict] | None = None,
                  replace: bool = False) -> dict:
    """Queue a drawing for the app to add to a board (created if it doesn't exist)."""
    if bool(mermaid) == bool(elements):
        raise WhiteboardError("Give either mermaid or elements")
    for i, el in enumerate(elements or []):
        if not isinstance(el, dict) or el.get("type") not in SKELETON_TYPES:
            raise WhiteboardError(f"elements[{i}]: type must be one of {sorted(SKELETON_TYPES)}")
        if el["type"] != "arrow" or "start" not in el:
            for k in ("x", "y"):
                if not isinstance(el.get(k), (int, float)):
                    raise WhiteboardError(f"elements[{i}]: '{k}' must be a number")
    slug = find_board(project, board) or new_board(project, board)
    path = _path(project, slug)
    data = _read(path)
    entry = {"id": ulid(), "queued": time.time(), "replace": replace}
    entry.update({"mermaid": mermaid} if mermaid else {"elements": elements})
    data["dsd"].setdefault("pending", []).append(entry)
    _write(path, data)
    return {"board": slug, "name": data["dsd"].get("name") or slug, "queued": entry["id"]}


def describe(project: Project, slug: str) -> dict:
    """A compact, text-only view of a board, for Claude: shapes, their text, and what the arrows connect."""
    data = read_board(project, slug)
    live = [e for e in data["elements"] if not e.get("isDeleted")]
    by_id = {e["id"]: e for e in live}
    text_of: dict[str, str] = {}
    for e in live:
        if e.get("type") == "text" and e.get("containerId"):
            text_of[e["containerId"]] = e.get("text", "")
    shapes, arrows, notes = [], [], []
    for e in live:
        t = e.get("type")
        if t in ("rectangle", "diamond", "ellipse", "frame"):
            shapes.append({"id": e["id"], "type": t, "text": text_of.get(e["id"], ""), "x": round(e.get("x", 0)),
                           "y": round(e.get("y", 0)), "color": e.get("strokeColor")})
        elif t in ("arrow", "line"):
            start = (e.get("startBinding") or {}).get("elementId")
            end = (e.get("endBinding") or {}).get("elementId")
            label = lambda i: text_of.get(i) or (by_id.get(i, {}).get("type") if i else None)
            arrows.append({"type": t, "from": label(start), "to": label(end), "text": text_of.get(e["id"], "")})
        elif t == "text" and not e.get("containerId"):
            notes.append({"text": e.get("text", ""), "x": round(e.get("x", 0)), "y": round(e.get("y", 0))})
        elif t == "freedraw":
            notes.append({"text": "(freehand drawing)", "x": round(e.get("x", 0)), "y": round(e.get("y", 0))})
    return {"board": slug, "name": data["dsd"].get("name") or slug, "shapes": shapes, "connections": arrows,
            "text": notes, "pending": len(data["dsd"].get("pending") or [])}
