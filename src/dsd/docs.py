"""Project docs: list, read, write and search files under the project's docs dir (path-confined)."""

from __future__ import annotations

import re
from pathlib import Path

from .project import Project

TEXT_SUFFIXES = {".md", ".markdown", ".html", ".htm", ".txt", ".yaml", ".yml", ".json", ".csv", ".css", ".py"}
WRITABLE_SUFFIXES = {".md", ".html", ".txt", ".yaml", ".yml", ".json", ".csv"}


class DocsError(Exception):
    pass


def resolve(project: Project, rel: str) -> Path:
    base = project.docs_path.resolve()
    rel = rel.strip().lstrip("/")
    if rel.startswith(f"{project.docs_dir}/"):
        rel = rel[len(project.docs_dir) + 1:]
    path = (base / rel).resolve()
    if path != base and base not in path.parents:
        raise DocsError(f"'{rel}' is outside the docs folder")
    return path


def list_docs(project: Project) -> list[dict]:
    base = project.docs_path
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in TEXT_SUFFIXES | {".png", ".svg", ".jpg", ".pdf"}:
            st = p.stat()
            out.append({"path": p.relative_to(base).as_posix(), "size": st.st_size, "mtime": st.st_mtime})
    return out


def read_doc(project: Project, rel: str) -> str:
    path = resolve(project, rel)
    if not path.is_file():
        raise DocsError(f"No such doc: {rel}")
    return path.read_text(errors="replace")


def write_doc(project: Project, rel: str, content: str) -> Path:
    path = resolve(project, rel)
    if path.suffix.lower() not in WRITABLE_SUFFIXES:
        raise DocsError(f"Refusing to write '{path.suffix}' files; allowed: {sorted(WRITABLE_SUFFIXES)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    return re.sub(r"<[^>]+>", " ", text)


def search(project: Project, query: str, limit: int = 20) -> list[dict]:
    terms = [t.lower() for t in query.split() if t]
    if not terms:
        return []
    hits = []
    for d in list_docs(project):
        path = project.docs_path / d["path"]
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(errors="replace")
        if path.suffix.lower() in (".html", ".htm"):
            text = _strip_html(text)
        low = text.lower()
        name_low = d["path"].lower()
        if not all(t in low or t in name_low for t in terms):
            continue
        score = sum(low.count(t) for t in terms) + 5 * sum(t in name_low for t in terms)
        snippets = []
        for i, line in enumerate(text.splitlines()):
            if any(t in line.lower() for t in terms):
                snippets.append({"line": i + 1, "text": " ".join(line.split())[:200]})
                if len(snippets) >= 3:
                    break
        hits.append({"path": d["path"], "score": score, "snippets": snippets})
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit]
