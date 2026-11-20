"""Local HTTP + WebSocket API for the dsd app. Binds to localhost only.

The React UI (built into dsd/web/dist) is served from the same origin.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import mimetypes
import tomllib
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, analytics, archive, plans, review, skills, worktrees
from .. import docs as docs_mod
from ..init import init_project
from ..project import Project, ProjectNotFound, all_projects, checkout_of, find_project
from ..tracking.index import Index
from ..tracking.query import QueryError, compare, leaderboard, list_runs, load_bench_specs, set_bench_spec
from .terminals import TerminalManager

DIST = Path(__file__).parent / "dist"


def create_app(current: Path | None = None) -> FastAPI:
    terms = TerminalManager()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        from .terminals import resolve_claude_command

        asyncio.get_running_loop().run_in_executor(None, resolve_claude_command)  # warm the lookup
        yield
        terms.close_all()

    app = FastAPI(title="dsd", version=__version__, lifespan=lifespan)

    # ------------------------------------------------------------ helpers
    def get_project(pid: str) -> Project:
        for p in all_projects():
            if p.id == pid:
                return p
        raise HTTPException(404, f"unknown project {pid}")

    def guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (plans.PlanError, docs_mod.DocsError, QueryError, ValueError, worktrees.WorktreeError,
                skills.SkillError, archive.ArchiveError) as e:
            raise HTTPException(400, str(e))
        except (KeyError, FileNotFoundError) as e:
            raise HTTPException(404, str(e.args[0] if e.args else e))

    current_root = checkout_of(current.resolve()) if current else None

    def sync_terminals(p: Project) -> None:
        """Keep sessions' worktree names current, also after a rename made elsewhere (e.g. by Claude via MCP)."""
        live = [t for t in terms.terms.values() if t.project_id == p.id and t.worktree]
        if not live:
            return
        by_path = {m["path"]: (n, m.get("branch")) for n, m in worktrees._load_meta(p).items() if "path" in m}
        for t in live:
            for path, (n, branch) in by_path.items():
                if t.cwd == path or t.cwd.startswith(path + "/"):
                    t.worktree, t.branch = n, branch or t.branch
                    break

    def include(p: Project) -> list[Path]:
        return [current] if current else []

    def index(p: Project) -> Index:
        idx = Index(p)
        idx.sync()
        return idx

    def plan_rows(p: Project) -> list[dict]:
        tree = plans.plan_tree(p)
        numbers = plans.plan_numbers(tree)
        return [{"slug": pl.slug, "title": pl.title, "status": pl.meta.get("status", "active"),
                 "parent": pl.meta.get("parent"), "depth": depth, "number": numbers.get(pl.slug, ""),
                 "summary": plans.plan_summary(pl), **pl.counts()}
                for pl, depth in tree]

    def project_json(p: Project) -> dict:
        return {"id": p.id, "name": p.name, "root": str(p.root), "repo": str(p.repo), "scope": p.scope,
                "data_dir": str(p.data_dir), "docs_dir": p.docs_dir}

    # ------------------------------------------------------------ projects
    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/cli")
    async def cli_status():
        from ..appsupport import cli_status as status

        return await asyncio.to_thread(status)

    @app.post("/api/cli/install")
    def cli_install():
        from ..appsupport import install_cli

        try:
            return install_cli()
        except (RuntimeError, OSError) as e:
            raise HTTPException(400, str(e))

    # ------------------------------------------------------------ home (cross-project)
    @app.get("/api/home")
    async def home_dashboard():
        from .. import home

        by_project: dict[str, list[dict]] = {}
        for t in terms.list():
            by_project.setdefault(t["project_id"], []).append(t)
        return await asyncio.to_thread(home.dashboard, by_project)

    @app.get("/api/todos")
    def todos_list():
        from .. import home

        return home.list_todos()

    @app.post("/api/todos")
    def todos_add(text: str = Body(...), due: str | None = Body(None), project: str | None = Body(None)):
        from .. import home

        if not text.strip():
            raise HTTPException(400, "empty to-do")
        return home.add_todo(text, due, project)

    @app.patch("/api/todos/{task_id}")
    def todos_update(task_id: str, status: str | None = Body(None), due: str | None = Body("__keep__"),
                     title: str | None = Body(None), project: str | None = Body("__keep__")):
        from .. import home

        return guard(home.update_todo, task_id, status, due, title, project)

    @app.delete("/api/todos/{task_id}")
    def todos_delete(task_id: str):
        from .. import home

        guard(home.delete_todo, task_id)
        return {"ok": True}

    # ------------------------------------------------------------ skills (global)
    @app.get("/api/skills")
    def skills_list():
        return skills.list_skills()

    @app.get("/api/skills/dsd")
    def skills_dsd_status():
        from .. import agents

        return [{"name": n, "state": agents.skill_state(n, b)} for n, b in agents.bundled_skills().items()]

    @app.post("/api/skills/dsd/install")
    def skills_dsd_install(force: bool = Body(False, embed=True)):
        from .. import agents

        return [{"action": a, "path": str(p)} for a, p in agents.install_skills(force=force)]

    @app.get("/api/skills/terminals")
    def skills_terminals():
        return terms.list("skills")

    @app.get("/api/skills/{sid}")
    def skill_get(sid: str):
        return guard(skills.get_skill, sid)

    @app.get("/api/skills/{sid}/file")
    def skill_file(sid: str, path: str):
        return {"path": path, "content": guard(skills.read_file, sid, path)}

    @app.put("/api/skills/{sid}/file")
    def skill_file_write(sid: str, path: str = Body(...), content: str = Body(...)):
        guard(skills.write_file, sid, path, content)
        return {"ok": True}

    @app.post("/api/skills/{sid}/session")
    async def skill_session(sid: str, kind: str = Body("claude", embed=True)):
        s = guard(skills.get_skill, sid)
        title = f"{'Claude' if kind == 'claude' else 'Shell'} · {s['name']}"
        return terms.create("skills", s["path"], kind=kind, title=title).info()

    @app.get("/api/projects")
    def projects_list():
        return [project_json(p) for p in all_projects()]

    @app.post("/api/projects")
    def projects_add(path: str = Body(..., embed=True), init: bool = Body(False, embed=True),
                     name: str | None = Body(None, embed=True), scope: str | None = Body(None, embed=True)):
        root = Path(path).expanduser()
        if not root.is_dir():
            raise HTTPException(400, f"{root} is not a directory")
        if not init:
            try:
                return project_json(find_project(root))
            except ProjectNotFound:
                raise HTTPException(409, "no dsd project for this folder yet (send init=true to start one)")
        return project_json(guard(init_project, root, name, scope).project)

    @app.get("/api/projects/archived")
    def projects_archived():
        return [{**project_json(p), "archived_at": tomllib.loads(p.project_file.read_text()).get("archived_at")}
                for p in all_projects(include_archived=True) if p.archived]

    @app.post("/api/projects/{pid}/restore")
    def projects_restore(pid: str):
        p = next((x for x in all_projects(include_archived=True) if x.id == pid and x.archived), None)
        if p is None:
            raise HTTPException(404, f"no archived project {pid}")
        return guard(archive.restore_project, p)

    @app.get("/api/p/{pid}/archive")
    def project_archive_preview(pid: str):
        return archive.preview(get_project(pid))

    @app.post("/api/p/{pid}/archive")
    def project_archive(pid: str, force: bool = Body(False, embed=True)):
        p = get_project(pid)
        if archive.preview(p)["blockers"] and not force:
            guard(archive.archive_project, p, False)
        for t in terms.list(pid):
            terms.close(t["id"])
        return guard(archive.archive_project, p, force)

    @app.get("/api/p/{pid}/overview")
    def overview(pid: str, worktree: str | None = None):
        p = get_project(pid)
        repo = review.is_repo(p.root)
        listed = worktrees.list_worktrees(p, with_status=False, include=include(p)) if repo else []
        if repo and worktree and worktree != "main":
            wt = guard(worktrees.get_worktree, p, worktree)
            changes = review.change_count(p, Path(wt["path"]), base=wt["base"], ignore=wt["copied"])
        else:
            changes = review.change_count(p) if repo else 0
        all_plans = plans.load_plans(p)
        with index(p) as idx:
            recent = list_runs(idx, limit=8)
            benches = idx.benchmarks()
        return {
            "project": project_json(p),
            "plans": plan_rows(p),
            "in_progress": [t.to_dict() for pl in all_plans for t in pl.tasks if t.status == "doing"],
            "blocked": [t.to_dict() for pl in all_plans for t in pl.tasks if t.status == "blocked"],
            "benchmarks": benches,
            "recent_runs": recent,
            "changes": changes,
            "open_comments": sum(1 for c in review.load_comments(p) if c["status"] == "open"),
            "worktrees": max(0, len(listed) - 1),
            "current_worktree": next((w["name"] for w in listed if not w["is_main"] and current_root
                                      and w["path"] == str(current_root)), None),
        }

    # ------------------------------------------------------------ plans & tasks
    @app.get("/api/p/{pid}/plans")
    def plans_list(pid: str):
        p = get_project(pid)
        return plan_rows(p)

    @app.post("/api/p/{pid}/plans")
    def plans_new(pid: str, slug: str = Body(...), title: str | None = Body(None), parent: str = Body("main")):
        p = get_project(pid)
        pl = guard(plans.new_plan, p, slug, title, parent)
        return {"slug": pl.slug, "title": pl.title}

    @app.get("/api/p/{pid}/plans/{slug}")
    def plan_get(pid: str, slug: str):
        p = get_project(pid)
        pl = guard(plans.load_plan, p, slug)
        return {"slug": pl.slug, "title": pl.title, "meta": pl.meta, "path": str(pl.path.relative_to(p.docs_path)),
                "markdown": "".join(pl.lines), "tasks": [t.to_dict() for t in pl.tasks]}

    @app.get("/api/p/{pid}/tasks")
    def tasks_list(pid: str):
        return [t.to_dict() for t in plans.all_tasks(get_project(pid))]

    @app.post("/api/p/{pid}/tasks")
    def task_add(pid: str, title: str = Body(...), plan: str = Body("main"), tags: list[str] = Body([]),
                 attrs: dict[str, str] = Body({}), parent: str | None = Body(None)):
        p = get_project(pid)
        return guard(plans.add_task, p, title, plan, tags, attrs, parent).to_dict()

    @app.get("/api/p/{pid}/tasks/{task_id}")
    def task_get(pid: str, task_id: str):
        import subprocess

        p = get_project(pid)
        pl, t = guard(plans.find_task, p, task_id)
        with index(p) as idx:
            runs = list_runs(idx, task=t.id, limit=50)
        log = subprocess.run(
            ["git", "log", "--format=%h%x1f%ad%x1f%s", "--date=short", "-E", f"--grep=^Task:.*{t.id}([^0-9]|$)"],
            cwd=p.root, capture_output=True, text=True)
        commits = [dict(zip(("short", "date", "subject"), ln.split("\x1f"))) for ln in log.stdout.splitlines() if ln]
        return {**t.to_dict(), "runs": runs, "commits": commits}

    @app.patch("/api/p/{pid}/tasks/{task_id}")
    def task_update(pid: str, task_id: str, status: str | None = Body(None), note: str | None = Body(None)):
        p = get_project(pid)
        pl, t = guard(plans.find_task, p, task_id)
        if status:
            guard(plans.set_status, pl, t, status)
        if note:
            plans.append_note(pl, t, note)
        pl.save()
        return plans.find_task(p, t.id)[1].to_dict()

    @app.delete("/api/p/{pid}/tasks/{task_id}")
    def task_delete(pid: str, task_id: str):
        return {"deleted": guard(plans.remove_task, get_project(pid), task_id)}

    @app.get("/api/p/{pid}/analytics")
    def analytics_list(pid: str):
        return analytics.list_posts(get_project(pid))

    # ------------------------------------------------------------ docs
    @app.get("/api/p/{pid}/docs")
    def docs_list(pid: str):
        return docs_mod.list_docs(get_project(pid))

    @app.get("/api/p/{pid}/docs/search")
    def docs_search(pid: str, q: str):
        return docs_mod.search(get_project(pid), q, 30)

    @app.get("/api/p/{pid}/docs/file")
    def docs_read(pid: str, path: str):
        return {"path": path, "content": guard(docs_mod.read_doc, get_project(pid), path)}

    @app.put("/api/p/{pid}/docs/file")
    def docs_write(pid: str, path: str = Body(...), content: str = Body(...)):
        guard(docs_mod.write_doc, get_project(pid), path, content)
        return {"ok": True}

    @app.get("/api/p/{pid}/docs/raw/{path:path}")
    def docs_raw(pid: str, path: str):
        full = guard(docs_mod.resolve, get_project(pid), path)
        if not full.is_file():
            raise HTTPException(404)
        return FileResponse(full, media_type=mimetypes.guess_type(full.name)[0])

    # ------------------------------------------------------------ runs & benchmarks
    @app.get("/api/p/{pid}/runs")
    def runs(pid: str, benchmark: str | None = None, task: str | None = None, status: str | None = None,
             tag: str | None = None, where: list[str] = Query([]), sort: str | None = None, limit: int = 500):
        p = get_project(pid)
        with index(p) as idx:
            return guard(list_runs, idx, benchmark=benchmark or None, task=task or None, status=status or None,
                         tag=tag or None, where=[w for w in where if w.strip()], sort=sort or None, limit=limit)

    @app.get("/api/p/{pid}/runs/{rid}")
    def run_get(pid: str, rid: str):
        p = get_project(pid)
        with index(p) as idx:
            rid = guard(idx.resolve_id, rid)
            d = idx.run_detail(rid)
            d["series"] = idx.series([rid])[rid]
        d.pop("meta", None)
        return d

    @app.get("/api/p/{pid}/runs/{rid}/diff")
    def run_diff(pid: str, rid: str):
        p = get_project(pid)
        with index(p) as idx:
            d = idx.run_detail(guard(idx.resolve_id, rid))
        f = Path(d["bundle_path"]) / "capture" / "git.diff"
        log = Path(d["bundle_path"]) / "capture" / "stdout.log"
        return {"diff": f.read_text(errors="replace") if f.is_file() else "",
                "stdout": log.read_text(errors="replace")[-200_000:] if log.is_file() else ""}

    @app.get("/api/p/{pid}/runs/{rid}/artifacts/{path:path}")
    def run_artifact(pid: str, rid: str, path: str):
        p = get_project(pid)
        with index(p) as idx:
            d = idx.run_detail(guard(idx.resolve_id, rid))
        base = (Path(d["bundle_path"]) / "artifacts").resolve()
        full = (base / path).resolve()
        if base not in full.parents or not full.is_file():
            raise HTTPException(404)
        return FileResponse(full, media_type=mimetypes.guess_type(full.name)[0])

    @app.get("/api/p/{pid}/series")
    def series(pid: str, ids: str, keys: str | None = None):
        p = get_project(pid)
        with index(p) as idx:
            rids = [guard(idx.resolve_id, r) for r in ids.split(",") if r]
            return idx.series(rids, keys.split(",") if keys else None)

    @app.get("/api/p/{pid}/compare")
    def runs_compare(pid: str, ids: str):
        p = get_project(pid)
        with index(p) as idx:
            return guard(compare, idx, [r for r in ids.split(",") if r])

    @app.get("/api/p/{pid}/benchmarks")
    def benchmarks(pid: str):
        p = get_project(pid)
        specs = load_bench_specs(p)
        with index(p) as idx:
            bs = idx.benchmarks()
        names = {b["name"] for b in bs}
        return [{**b, "spec": specs.get(b["name"], {})} for b in bs] + \
            [{"name": n, "runs": 0, "last_run": None, "spec": s} for n, s in specs.items() if n not in names]

    @app.get("/api/p/{pid}/benchmarks/{name}")
    def bench_board(pid: str, name: str, group_by: str | None = None, all_status: bool = False):
        p = get_project(pid)
        with index(p) as idx:
            return guard(leaderboard, idx, p, name, group_by=group_by or None,
                         status=None if all_status else "finished")

    @app.put("/api/p/{pid}/benchmarks/{name}")
    def bench_spec(pid: str, name: str, primary: str | None = Body(None), direction: str | None = Body(None),
                   description: str | None = Body(None)):
        return guard(set_bench_spec, get_project(pid), name, primary, direction, description)

    # ------------------------------------------------------------ review (diffs + comments)
    @app.get("/api/p/{pid}/changes")
    def changes(pid: str, ref: str | None = None, worktree: str | None = None):
        p = get_project(pid)
        if ref:
            return guard(review.commit_changes, p, ref)
        if worktree and worktree != "main":
            wt = guard(worktrees.get_worktree, p, worktree)
            res = review.working_changes(p, Path(wt["path"]), base=wt["base"], ignore=wt["copied"])
            return {**res, "worktree": wt["name"], "branch": wt["branch"]}
        return review.working_changes(p)

    @app.get("/api/p/{pid}/commits")
    def commits(pid: str):
        return review.recent_commits(get_project(pid))

    @app.get("/api/p/{pid}/comments")
    def comments(pid: str):
        return review.load_comments(get_project(pid))

    @app.post("/api/p/{pid}/comments")
    def comment_add(pid: str, path: str = Body(...), line: int | None = Body(None), text: str = Body(...),
                    side: str = Body("new"), code: str | None = Body(None), ref: str | None = Body(None),
                    worktree: str | None = Body(None)):
        return review.add_comment(get_project(pid), path, line, text, side, code, ref,
                                  None if worktree in (None, "main") else worktree)

    @app.patch("/api/p/{pid}/comments/{cid}")
    def comment_update(pid: str, cid: str, text: str | None = Body(None), status: str | None = Body(None)):
        return guard(review.update_comment, get_project(pid), cid, text=text, status=status)

    @app.delete("/api/p/{pid}/comments/{cid}")
    def comment_delete(pid: str, cid: str):
        review.delete_comment(get_project(pid), cid)
        return {"ok": True}

    @app.post("/api/p/{pid}/comments/send")
    def comments_send(pid: str, terminal_id: str = Body(...), ids: list[str] | None = Body(None),
                      submit: bool = Body(False)):
        p = get_project(pid)
        cs = [c for c in review.load_comments(p) if (ids and c["id"] in ids) or (not ids and c["status"] == "open")]
        if not cs:
            raise HTTPException(400, "no comments to send")
        if terminal_id not in terms.terms:
            raise HTTPException(404, "terminal not found")
        terms.paste(terminal_id, review.format_for_agent(cs), submit=submit)
        for c in cs:
            review.update_comment(p, c["id"], status="sent")
        return {"sent": len(cs)}

    # ------------------------------------------------------------ terminals
    @app.get("/api/p/{pid}/terminals")
    def terminals_list(pid: str):
        p = next((x for x in all_projects() if x.id == pid), None)
        if p is not None:
            sync_terminals(p)
        return terms.list(pid)

    @app.post("/api/p/{pid}/terminals")
    async def terminals_new(pid: str, kind: str = Body("shell", embed=True), command: str | None = Body(None, embed=True),
                            title: str | None = Body(None, embed=True), worktree: str | None = Body(None, embed=True),
                            new_worktree: dict | None = Body(None, embed=True)):
        """Open a terminal in the main checkout, an existing worktree, or a brand-new worktree.

        new_worktree: {"name"?, "base"?, "task"?, "task_title"?} creates dsd/<name> first and runs the
        project's [worktree] setup command (if any) before starting the agent.
        """
        p = get_project(pid)
        setup = None
        if new_worktree is not None:
            wt = await asyncio.to_thread(
                guard, worktrees.create_worktree, p, new_worktree.get("name") or None, new_worktree.get("base") or None,
                new_worktree.get("task") or None, new_worktree.get("task_title") or None)
            setup = worktrees.setup_command(p)
        elif worktree and worktree != "main":
            wt = guard(worktrees.get_worktree, p, worktree)
        else:
            wt = None
        if wt is None:
            branch = worktrees.current_branch(p.root) if review.is_repo(p.root) else None
            return terms.create(p.id, str(p.work_dir), kind=kind, command=command, title=title, branch=branch).info()
        cwd = Path(wt["path"]) / p.scope if p.scope and (Path(wt["path"]) / p.scope).is_dir() else Path(wt["path"])
        return terms.create(p.id, str(cwd), kind=kind, command=command, title=title, worktree=wt["name"],
                            branch=wt["branch"], setup=setup).info()

    # ------------------------------------------------------------ worktrees
    @app.get("/api/p/{pid}/worktrees")
    def worktrees_list(pid: str):
        p = get_project(pid)
        if not review.is_repo(p.root):
            return []
        wts = worktrees.list_worktrees(p, include=include(p))
        sync_terminals(p)
        open_terms = terms.list(pid)
        for w in wts:
            w["terminals"] = [t["id"] for t in open_terms if (t["worktree"] or "main") == w["name"]]
        return wts

    @app.get("/api/p/{pid}/branches")
    def branches_list(pid: str):
        p = get_project(pid)
        if not review.is_repo(p.root):
            return {"current": None, "default": None, "branches": []}
        return {"current": worktrees.current_branch(p.root), "default": worktrees.default_branch(p),
                "branches": worktrees.relevant_branches(p, include(p))}

    @app.get("/api/p/{pid}/worktrees/candidates")
    def worktrees_candidates(pid: str):
        p = get_project(pid)
        if not review.is_repo(p.root):
            return []
        listed = {w["path"] for w in worktrees.list_worktrees(p, with_status=False, include=include(p))}
        return [c for c in worktrees.candidates(p) if c["path"] not in listed]

    @app.post("/api/p/{pid}/worktrees/adopt")
    def worktrees_adopt(pid: str, path: str = Body(...), task: str | None = Body(None)):
        return guard(worktrees.adopt_worktree, get_project(pid), path, task or None)

    @app.post("/api/p/{pid}/worktrees/{name}/rename")
    def worktrees_rename(pid: str, name: str, new_name: str = Body(..., alias="name", embed=True),
                         rename_branch: bool = Body(False, embed=True)):
        p = get_project(pid)
        r = guard(worktrees.rename_worktree, p, name, new_name, rename_branch)
        sync_terminals(p)
        return r

    @app.post("/api/p/{pid}/worktrees/{name}/move")
    def worktrees_move(pid: str, name: str, to: str = Body(..., embed=True)):
        p, dest = get_project(pid), get_project(to)
        old = guard(worktrees.get_worktree, p, name)["name"]
        moved = guard(worktrees.move_worktree, p, name, dest)
        for t in terms.terms.values():
            if t.project_id == pid and t.worktree == old:
                t.project_id, t.worktree = dest.id, moved["name"]
        return moved

    @app.post("/api/p/{pid}/worktrees/{name}/hide")
    def worktrees_hide(pid: str, name: str):
        return guard(worktrees.hide_worktree, get_project(pid), name)

    @app.post("/api/p/{pid}/worktrees")
    def worktrees_create(pid: str, name: str | None = Body(None), base: str | None = Body(None),
                         task: str | None = Body(None), task_title: str | None = Body(None)):
        return guard(worktrees.create_worktree, get_project(pid), name, base, task, task_title)

    @app.delete("/api/p/{pid}/worktrees/{name}")
    def worktrees_remove(pid: str, name: str, force: bool = False, delete_branch: bool = False):
        p = get_project(pid)
        wt = guard(worktrees.get_worktree, p, name)
        for t in terms.list(pid):
            if t["worktree"] == wt["name"]:
                terms.close(t["id"])
        return guard(worktrees.remove_worktree, p, name, force, delete_branch)

    @app.post("/api/p/{pid}/worktrees/{name}/commit")
    def worktrees_commit(pid: str, name: str, message: str = Body(..., embed=True)):
        return guard(worktrees.commit_all, get_project(pid), name, message)

    @app.post("/api/p/{pid}/worktrees/{name}/merge")
    def worktrees_merge(pid: str, name: str, strategy: str = Body("merge", embed=True),
                        message: str | None = Body(None, embed=True)):
        return guard(worktrees.merge_worktree, get_project(pid), name, strategy, message)

    @app.post("/api/terminals/{tid}/input")
    def terminal_input(tid: str, text: str = Body(..., embed=True), submit: bool = Body(False, embed=True)):
        if tid not in terms.terms:
            raise HTTPException(404)
        terms.paste(tid, text, submit)
        return {"ok": True}

    @app.patch("/api/terminals/{tid}")
    def terminal_rename(tid: str, title: str = Body(..., embed=True)):
        terms.rename(tid, title)
        return {"ok": True}

    @app.delete("/api/terminals/{tid}")
    def terminal_close(tid: str):
        terms.close(tid)
        return {"ok": True}

    @app.websocket("/api/terminals/{tid}/ws")
    async def terminal_ws(ws: WebSocket, tid: str):
        await ws.accept()
        term = terms.terms.get(tid)
        if term is None:
            await ws.close(code=4404)
            return
        q: asyncio.Queue = asyncio.Queue()
        if term.buffer:
            await ws.send_bytes(bytes(term.buffer))
        if term.exited:
            await ws.close()
            return
        term.listeners.add(q)

        async def pump():
            while True:
                data = await q.get()
                if data is None:
                    await ws.close()
                    return
                await ws.send_bytes(data)

        sender = asyncio.create_task(pump())
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    terms.write(tid, msg["bytes"])
                elif msg.get("text"):
                    try:
                        ctl = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        terms.write(tid, msg["text"].encode())
                        continue
                    if ctl.get("type") == "resize":
                        terms.resize(tid, int(ctl["rows"]), int(ctl["cols"]))
                    elif ctl.get("type") == "input":
                        terms.write(tid, ctl["data"].encode())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            term.listeners.discard(q)
            sender.cancel()

    # ------------------------------------------------------------ UI
    if DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(404)
            f = DIST / full_path
            if full_path and f.is_file():
                return FileResponse(f)
            return FileResponse(DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_ui():
            return HTMLResponse("<h1>dsd API is running</h1><p>The UI isn't built. Run <code>npm run build</code> in <code>ui/</code>.</p>")

    @app.exception_handler(ProjectNotFound)
    async def _pnf(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    return app
