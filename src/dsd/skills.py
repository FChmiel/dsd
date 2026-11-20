"""Claude Code skills on this machine: list them by source, and read or edit the ones that are yours.

Sources: your skills (~/.claude/skills), the ones dsd installed there (marked .dsd-managed), skills
managed by Pane (.pane-managed) or synced from claude.ai (~/.claude/skills/synced), plugin skills, and
the .claude/skills of every repo with a dsd project. Your skills, dsd's and repo skills are editable
(dsd setup keeps your edits); the others are overwritten by their owner.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from .project import all_projects

EDITABLE_SOURCES = ("user", "dsd", "repo")
WRITABLE_SUFFIXES = {".md", ".txt", ".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".html", ".csv", ".js", ".ts"}
MAX_FILES = 500


class SkillError(Exception):
    pass


def _claude_dir() -> Path:
    return Path.home() / ".claude"


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass
    out = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and k.strip() in ("name", "description"):
            out[k.strip()] = v.strip()
    return out


def _files(d: Path) -> list[Path]:
    out = []
    for f in sorted(d.rglob("*")):
        rel = f.relative_to(d)
        if f.is_file() and not any(part.startswith(".") for part in rel.parts):
            out.append(f)
            if len(out) >= MAX_FILES:
                break
    return out


def _entry(d: Path, source: str, **extra) -> dict | None:
    md = d / "SKILL.md"
    if not md.is_file():
        return None
    meta = _frontmatter(md.read_text(errors="replace"))
    files = _files(d)
    return {
        "id": hashlib.sha1(str(d.resolve()).encode()).hexdigest()[:12],
        "name": str(meta.get("name") or d.name), "description": str(meta.get("description") or ""),
        "source": source, "editable": source in EDITABLE_SOURCES, "path": str(d.resolve()),
        "files": len(files), "updated": max((f.stat().st_mtime for f in files), default=None), **extra,
    }


def _subdirs(d: Path) -> list[Path]:
    return sorted(x for x in d.iterdir() if x.is_dir()) if d.is_dir() else []


def _plugin_dirs() -> list[tuple[str, Path]]:
    try:
        data = json.loads((_claude_dir() / "plugins" / "installed_plugins.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    out = []
    for name, installs in (data.get("plugins") or {}).items():
        for inst in installs if isinstance(installs, list) else [installs]:
            if inst.get("installPath"):
                out.append((name, Path(inst["installPath"]) / "skills"))
    return out


def list_skills() -> list[dict]:
    found: list[dict | None] = []
    user = _claude_dir() / "skills"
    for d in _subdirs(user):
        if d.name == "synced":
            found += [_entry(s, "claude.ai") for bucket in _subdirs(d) for s in _subdirs(bucket)]
        else:
            source = "pane" if (d / ".pane-managed").exists() else "dsd" if (d / ".dsd-managed").exists() else "user"
            found.append(_entry(d, source))
    for plugin, d in _plugin_dirs():
        found += [_entry(s, "plugin", plugin=plugin) for s in _subdirs(d)]
    repos: dict[str, list[str]] = {}
    for p in all_projects():
        repos.setdefault(str(p.repo), []).append(p.name)
    for repo, names in repos.items():
        found += [_entry(s, "repo", repo=repo, projects=sorted(names)) for s in _subdirs(Path(repo) / ".claude" / "skills")]
    order = {s: i for i, s in enumerate(("user", "dsd", "repo", "plugin", "claude.ai", "pane"))}
    return sorted((s for s in found if s), key=lambda s: (order[s["source"]], s["name"].lower()))


def _find(sid: str) -> dict:
    for s in list_skills():
        if s["id"] == sid:
            return s
    raise KeyError(f"No skill {sid}")


def get_skill(sid: str) -> dict:
    s = _find(sid)
    base = Path(s["path"])
    return {**s, "files": [{"path": f.relative_to(base).as_posix(), "size": f.stat().st_size} for f in _files(base)]}


def _resolve(s: dict, rel: str) -> Path:
    base = Path(s["path"])
    path = (base / rel.strip().lstrip("/")).resolve()
    if base not in path.parents:
        raise SkillError(f"'{rel}' is outside the skill folder")
    return path


def read_file(sid: str, rel: str) -> str:
    path = _resolve(_find(sid), rel)
    if not path.is_file():
        raise SkillError(f"No such file: {rel}")
    return path.read_text(errors="replace")


def write_file(sid: str, rel: str, content: str) -> Path:
    s = _find(sid)
    if not s["editable"]:
        raise SkillError(f"'{s['name']}' is managed by {s['source']}; edits would be overwritten")
    path = _resolve(s, rel)
    if path.suffix.lower() not in WRITABLE_SUFFIXES:
        raise SkillError(f"Refusing to write '{path.suffix}' files; allowed: {sorted(WRITABLE_SUFFIXES)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path
