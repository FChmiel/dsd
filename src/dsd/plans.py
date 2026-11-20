"""Plans: markdown checklists with project-unique task ids.

Files: docs/plans/main.md (central, required) plus any number of sub-plans docs/plans/<slug>.md.

Task line syntax:
    - [ ] T-12 Title words #tag @key:value
      indented description / note lines

All edits are line-preserving: only the touched characters/lines change, so human formatting,
prose and line endings survive byte-for-byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .project import Project

MARK_STATUS = {" ": "todo", "/": "doing", "x": "done", "X": "done", "!": "blocked", "-": "dropped"}
STATUS_MARK = {"todo": " ", "doing": "/", "done": "x", "blocked": "!", "dropped": "-"}
OPEN_STATUSES = ("todo", "doing", "blocked")
MAIN = "main"

TASK_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<bullet>[-*+]|\d+[.)])[ \t]+\[(?P<mark>[ xX/!\-])\]"
    r"(?:[ \t]+(?P<rest>.*?))?[ \t]*\r?\n?$"
)
ID_RE = re.compile(r"^T-(\d+)(?=\s|$)")
TAG_RE = re.compile(r"(?<!\S)#([A-Za-z0-9_][\w\-/]*)")
ATTR_RE = re.compile(r"(?<!\S)@([A-Za-z_][\w\-]*):(\S+)")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t#]*\r?\n?$")
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$")


class PlanError(Exception):
    pass


@dataclass
class Task:
    id: str | None
    status: str
    title: str
    tags: list[str]
    attrs: dict[str, str]
    plan: str
    line: int  # 0-based line index in the plan file
    indent: int  # visual indent width
    indent_str: str
    mark_col: int
    rest_col: int | None
    parent: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def number(self) -> int | None:
        return int(self.id[2:]) if self.id else None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "status": self.status, "title": self.title, "tags": self.tags,
            "attrs": self.attrs, "plan": self.plan, "parent": self.parent, "notes": self.notes,
        }


@dataclass
class Plan:
    path: Path
    slug: str
    meta: dict
    lines: list[str]
    tasks: list[Task]

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.slug)

    @property
    def newline(self) -> str:
        for ln in self.lines:
            if ln.endswith("\r\n"):
                return "\r\n"
            if ln.endswith("\n"):
                return "\n"
        return "\n"

    def task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise PlanError(f"{task_id} not found in plan '{self.slug}'")

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATUS_MARK}
        for t in self.tasks:
            out[t.status] += 1
        return out

    def save(self) -> None:
        self.path.write_bytes("".join(self.lines).encode("utf-8"))


# ---------------------------------------------------------------- parsing

def _indent_width(s: str) -> int:
    return len(s.expandtabs(4))


def _leading(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _is_blank(line: str) -> bool:
    return not line.strip()


def _frontmatter(lines: list[str]) -> tuple[dict, int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            body = "".join(lines[1:i])
            try:
                meta = yaml.safe_load(body) or {}
            except yaml.YAMLError:
                # Hand-written frontmatter is often not strict YAML (e.g. `title: a: b`): fall back to key: value lines.
                meta = {}
                for ln in lines[1:i]:
                    k, sep, v = ln.partition(":")
                    if sep and k.strip() and not k.startswith((" ", "\t")):
                        meta[k.strip()] = v.strip().strip("\"'")
            return (meta if isinstance(meta, dict) else {}), i + 1
    return {}, 0


def _parse_rest(rest: str) -> tuple[str | None, str, list[str], dict[str, str]]:
    m = ID_RE.match(rest)
    task_id = f"T-{int(m.group(1))}" if m else None
    body = rest[m.end():] if m else rest
    tags = TAG_RE.findall(body)
    attrs = dict(ATTR_RE.findall(body))
    title = ATTR_RE.sub("", TAG_RE.sub("", body))
    return task_id, " ".join(title.split()), tags, attrs


def parse_text(text: str, slug: str, path: Path) -> Plan:
    lines = text.splitlines(keepends=True)
    meta, start = _frontmatter(lines)
    tasks: list[Task] = []
    stack: list[Task] = []
    in_fence = False
    for i in range(start, len(lines)):
        line = lines[i]
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if HEADING_RE.match(line):
            stack.clear()
            continue
        m = TASK_RE.match(line)
        if m:
            indent = _indent_width(m.group("indent"))
            while stack and stack[-1].indent >= indent:
                stack.pop()
            rest = m.group("rest") or ""
            task_id, title, tags, attrs = _parse_rest(rest)
            t = Task(
                id=task_id, status=MARK_STATUS[m.group("mark")], title=title, tags=tags, attrs=attrs,
                plan=slug, line=i, indent=indent, indent_str=m.group("indent"),
                mark_col=m.start("mark"), rest_col=m.start("rest") if m.group("rest") else None,
                parent=stack[-1].id if stack else None,
            )
            tasks.append(t)
            stack.append(t)
            continue
        if _is_blank(line):
            continue
        indent = _indent_width(_leading(line))
        while stack and stack[-1].indent >= indent:
            stack.pop()
        if stack:
            stack[-1].notes.append(line.strip())
    return Plan(path=path, slug=slug, meta=meta, lines=lines, tasks=tasks)


def parse_plan(path: Path) -> Plan:
    return parse_text(path.read_bytes().decode("utf-8"), path.stem, path)


# ---------------------------------------------------------------- workspace

def plan_paths(project: Project) -> list[Path]:
    d = project.plans_path
    if not d.is_dir():
        return []
    others = sorted(p for p in d.glob("*.md") if p.stem != MAIN)
    main = d / f"{MAIN}.md"
    return ([main] if main.exists() else []) + others


def load_plans(project: Project) -> list[Plan]:
    return [parse_plan(p) for p in plan_paths(project)]


def plan_tree(project: Project) -> list[tuple[Plan, int]]:
    """Plans as an outline: each sub-plan under its parent, in the order the parent links to them."""
    all_plans = load_plans(project)
    by_slug = {p.slug: p for p in all_plans}
    children: dict[str, list[Plan]] = {}
    for p in all_plans:
        if p.slug == MAIN:
            continue
        parent = p.meta.get("parent") or MAIN
        if parent not in by_slug or parent == p.slug:
            parent = MAIN
        children.setdefault(parent, []).append(p)
    out: list[tuple[Plan, int]] = []
    seen: set[str] = set()

    def walk(p: Plan, depth: int) -> None:
        if p.slug in seen:
            return
        seen.add(p.slug)
        out.append((p, depth))
        text = "".join(p.lines)
        def position(k: Plan) -> tuple[int, str]:
            hits = [i for i in (text.find(f"({k.slug}.md)"), text.find(f"plans/{k.slug}.md")) if i >= 0]
            return (min(hits) if hits else len(text) + 1, k.slug)
        for k in sorted(children.get(p.slug, []), key=position):
            walk(k, depth + 1)

    if MAIN in by_slug:
        walk(by_slug[MAIN], 0)
    for p in all_plans:
        if p.slug not in seen:
            walk(p, 1)
    return out


def plan_summary(plan: Plan, limit: int = 200) -> str:
    """The first sentence of the plan's Goal section, as plain text ('' if it is still the placeholder)."""
    in_goal, para = False, []
    for ln in plan.lines:
        h = HEADING_RE.match(ln)
        if h:
            if in_goal and para:
                break
            in_goal = bool(re.match(r"(\d+\.\s*)?goal\b", h.group(2).strip(), re.IGNORECASE))
            continue
        if not in_goal:
            continue
        if ln.strip():
            para.append(ln.strip())
        elif para:
            break
    text = " ".join(para)
    if not text or (text.startswith("_") and text.endswith("_")) or text.startswith("<"):
        return ""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", text)
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    text = m.group(1) if m else text
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def plan_numbers(tree: list[tuple[Plan, int]]) -> dict[str, str]:
    """Outline numbers for a plan tree: '' for the central plan, then '1', '1.1', '1.2', '2', ..."""
    numbers: dict[str, str] = {}
    path: list[int] = []
    for p, depth in tree:
        if depth == 0:
            numbers[p.slug] = ""
            path = []
            continue
        path = path[: depth - 1]
        path += [0] * (depth - 1 - len(path))
        counters = numbers.setdefault(f"__{'.'.join(map(str, path))}", "0")
        n = int(counters) + 1
        numbers[f"__{'.'.join(map(str, path))}"] = str(n)
        path.append(n)
        numbers[p.slug] = ".".join(map(str, path))
    return {k: v for k, v in numbers.items() if not k.startswith("__")}


def load_plan(project: Project, slug: str = MAIN) -> Plan:
    path = project.plans_path / f"{slug}.md"
    if not path.exists():
        raise PlanError(f"No plan '{slug}' ({path})")
    return parse_plan(path)


def all_tasks(project: Project) -> list[Task]:
    return [t for p in load_plans(project) for t in p.tasks]


def find_task(project: Project, task_id: str) -> tuple[Plan, Task]:
    task_id = normalize_id(task_id)
    for plan in load_plans(project):
        for t in plan.tasks:
            if t.id == task_id:
                return plan, t
    raise PlanError(f"Task {task_id} not found in any plan")


def normalize_id(task_id: str) -> str:
    s = task_id.strip().upper()
    if s.isdigit():
        s = f"T-{s}"
    m = re.fullmatch(r"T-?(\d+)", s)
    if not m:
        raise PlanError(f"Invalid task id '{task_id}' (expected T-12)")
    return f"T-{int(m.group(1))}"


def next_id(project: Project) -> int:
    nums = [t.number for t in all_tasks(project) if t.number is not None]
    return max(nums, default=0) + 1


# ---------------------------------------------------------------- line-preserving edits

def _block_end(plan: Plan, t: Task) -> int:
    """Exclusive end index of a task's block (its notes and children), excluding trailing blanks."""
    end = t.line + 1
    j = t.line + 1
    while j < len(plan.lines):
        ln = plan.lines[j]
        if _is_blank(ln):
            j += 1
            continue
        if HEADING_RE.match(ln) or _indent_width(_leading(ln)) <= t.indent:
            break
        j += 1
        end = j
    return end


def _insert(plan: Plan, idx: int, new_lines: list[str]) -> None:
    nl = plan.newline
    if idx > 0 and not plan.lines[idx - 1].endswith("\n"):
        plan.lines[idx - 1] += nl
    plan.lines[idx:idx] = [ln + nl for ln in new_lines]


def set_status(plan: Plan, t: Task, status: str) -> None:
    if status not in STATUS_MARK:
        raise PlanError(f"Unknown status '{status}'")
    ln = plan.lines[t.line]
    plan.lines[t.line] = ln[: t.mark_col] + STATUS_MARK[status] + ln[t.mark_col + 1:]
    t.status = status


def append_note(plan: Plan, t: Task, note: str) -> None:
    j = t.line + 1
    while j < len(plan.lines):
        ln = plan.lines[j]
        if _is_blank(ln) or TASK_RE.match(ln) or _indent_width(_leading(ln)) <= t.indent:
            break
        j += 1
    _insert(plan, j, [f"{t.indent_str}  → {note.strip()}"])


def _task_line(n: int, title: str, tags: list[str] | None, attrs: dict[str, str] | None) -> str:
    parts = [f"- [ ] T-{n}", title.strip()]
    parts += [f"#{tag.lstrip('#')}" for tag in tags or []]
    parts += [f"@{k}:{v}" for k, v in (attrs or {}).items()]
    return " ".join(p for p in parts if p)


def _section_range(plan: Plan, heading: str) -> tuple[int, int] | None:
    target = heading.strip().lower()
    for i, ln in enumerate(plan.lines):
        m = HEADING_RE.match(ln)
        if m and m.group(2).strip().lower() == target:
            level = len(m.group(1))
            end = len(plan.lines)
            for j in range(i + 1, len(plan.lines)):
                m2 = HEADING_RE.match(plan.lines[j])
                if m2 and len(m2.group(1)) <= level:
                    end = j
                    break
            return i, end
    return None


def _append_to_section(plan: Plan, heading: str, new_line: str, placeholder: str | None = None) -> None:
    rng = _section_range(plan, heading)
    if rng is None:
        tail = [] if not plan.lines or _is_blank(plan.lines[-1]) else [""]
        _insert(plan, len(plan.lines), tail + [f"## {heading}", "", new_line])
        return
    start, end = rng
    if placeholder:
        for k in range(start + 1, end):
            if plan.lines[k].strip() == placeholder:
                nl = "\r\n" if plan.lines[k].endswith("\r\n") else ("\n" if plan.lines[k].endswith("\n") else "")
                plan.lines[k] = new_line + nl
                return
    last = start
    for k in range(start + 1, end):
        if not _is_blank(plan.lines[k]):
            last = k
    _insert(plan, last + 1, ([""] if last == start else []) + [new_line])


def add_task(
    project: Project, title: str, plan_slug: str = MAIN, tags: list[str] | None = None,
    attrs: dict[str, str] | None = None, parent: str | None = None, section: str = "Tasks",
) -> Task:
    n = next_id(project)
    line = _task_line(n, title, tags, attrs)
    if parent:
        plan, ptask = find_task(project, parent)
        _insert(plan, _block_end(plan, ptask), [f"{ptask.indent_str}  {line}"])
    else:
        plan = load_plan(project, plan_slug)
        _append_to_section(plan, section, line)
    plan.save()
    return parse_plan(plan.path).task(f"T-{n}")


def new_plan(project: Project, slug: str, title: str | None = None, parent: str = MAIN) -> Plan:
    if not SLUG_RE.match(slug) or slug == MAIN:
        raise PlanError(f"Invalid plan slug '{slug}' (lowercase letters, digits, - and _; not 'main')")
    path = project.plans_path / f"{slug}.md"
    if path.exists():
        raise PlanError(f"Plan '{slug}' already exists")
    title = title or slug.replace("-", " ").replace("_", " ").capitalize()
    meta = yaml.safe_dump({"title": title, "status": "active", "parent": parent}, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{meta}---\n\n# {title}\n\n## Goal\n\n_What is this plan for?_\n\n## Tasks\n\n")
    parent_plan = load_plan(project, parent)
    _append_to_section(parent_plan, "Sub-plans", f"- [{title}]({slug}.md)", placeholder="_None yet._")
    parent_plan.save()
    return parse_plan(path)


def fmt_ids(project: Project) -> list[Task]:
    """Assign ids to tasks that lack one. Returns the newly numbered tasks."""
    n = next_id(project)
    assigned = []
    for plan in load_plans(project):
        changed = False
        for t in plan.tasks:
            if t.id is None:
                ln = plan.lines[t.line]
                if t.rest_col is None:
                    body = ln.rstrip("\r\n")
                    plan.lines[t.line] = f"{body} T-{n}" + ln[len(body):]
                else:
                    plan.lines[t.line] = ln[: t.rest_col] + f"T-{n} " + ln[t.rest_col:]
                t.id = f"T-{n}"
                assigned.append(t)
                n += 1
                changed = True
        if changed:
            plan.save()
    return assigned


def check(project: Project) -> list[str]:
    problems: list[str] = []
    plans = load_plans(project)
    if not project.main_plan_path.exists():
        problems.append("Central plan docs/plans/main.md is missing (run `dsd init`).")
    seen: dict[str, str] = {}
    for plan in plans:
        for t in plan.tasks:
            if t.id is None:
                problems.append(f"{plan.slug}:{t.line + 1} task without id (run `dsd plan fmt`): {t.title}")
            elif t.id in seen:
                problems.append(f"{plan.slug}:{t.line + 1} duplicate id {t.id} (also in {seen[t.id]})")
            else:
                seen[t.id] = plan.slug
    main_text = project.main_plan_path.read_text() if project.main_plan_path.exists() else ""
    for plan in plans:
        if plan.slug != MAIN and f"({plan.slug}.md)" not in main_text and plan.meta.get("parent", MAIN) == MAIN:
            problems.append(f"Sub-plan '{plan.slug}' is not linked from the central plan")
    return problems


def set_attr(plan: Plan, t: Task, key: str, value: str | None) -> None:
    """Set (or remove, with value=None) an @key:value attribute on a task line, in place."""
    ln = plan.lines[t.line]
    body = ln.rstrip("\r\n")
    ending = ln[len(body):]
    body = re.sub(rf"\s+@{re.escape(key)}:\S+", "", body)
    if value:
        body = f"{body} @{key}:{value}"
    plan.lines[t.line] = body + ending
    if value:
        t.attrs[key] = value
    else:
        t.attrs.pop(key, None)


def set_title(plan: Plan, t: Task, title: str) -> None:
    """Replace a task's title, keeping its id, tags and attributes."""
    ln = plan.lines[t.line]
    body = ln.rstrip("\r\n")
    ending = ln[len(body):]
    m = TASK_RE.match(ln)
    if not m:
        raise PlanError(f"{t.id} is not a task line")
    prefix = body[: m.start("rest")] if m.group("rest") else body + " "
    extras = [f"#{g}" for g in t.tags] + [f"@{k}:{v}" for k, v in t.attrs.items()]
    parts = ([t.id] if t.id else []) + [title.strip()] + extras
    plan.lines[t.line] = prefix + " ".join(parts) + ending
    t.title = title.strip()


def delete_task(plan: Plan, t: Task) -> None:
    """Remove a task and its notes/children."""
    del plan.lines[t.line:_block_end(plan, t)]


def remove_task(project: Project, task_id: str) -> list[str]:
    """Delete a task with its notes and subtasks from its plan; returns the ids removed."""
    pl, t = find_task(project, task_id)
    end = _block_end(pl, t)
    removed = [x.id for x in pl.tasks if x.id and t.line <= x.line < end]
    delete_task(pl, t)
    pl.save()
    return removed
