import os
import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import dsd
from dsd.init import init_project


@pytest.fixture
def project(tmp_path, monkeypatch):
    p = init_project(tmp_path, name="mcp-demo").project
    monkeypatch.setenv("DSD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("DSD_RUN_DIR", raising=False)
    with dsd.run("xgb", benchmark="b1", params={"model": "xgb"}) as r:
        r.log({"auc": 0.8})
        r.html("report.html", "<p>hello report</p>")
    return p


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def _session_calls(root):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "dsd.cli", "mcp"],
        env={**os.environ, "DSD_PROJECT_ROOT": str(root)},
    )
    out = {}
    async with stdio_client(params) as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            tools = await session.list_tools()
            out["tools"] = sorted(t.name for t in tools.tools)
            out["overview"] = _text(await session.call_tool("project_overview", {}))
            out["add"] = _text(await session.call_tool("task_add", {"title": "Try lightgbm", "tags": ["exp"]}))
            out["update"] = _text(await session.call_tool("task_update", {"task_id": "T-2", "status": "doing", "note": "started"}))
            runs = await session.call_tool("runs_query", {"benchmark": "b1", "sort": "-metrics.auc"})
            out["runs"] = runs.structured_content["result"]
            out["search"] = _text(await session.call_tool("docs_search", {"query": "main plan"}))
            out["write"] = _text(await session.call_tool("docs_write", {"path": "notes/x.md", "content": "# hi"}))
            out["escape"] = await session.call_tool("docs_read", {"path": "../../etc/passwd"})
            rid = out["runs"][0]["id"]
            out["artifact"] = _text(await session.call_tool("artifact_get", {"run_id": rid[-8:], "path": "report.html"}))
    return out


def test_mcp_end_to_end(project):
    out = anyio.run(_session_calls, project.root)
    assert {"project_overview", "plan_read", "task_update", "runs_query", "bench_board", "docs_write"} <= set(out["tools"])
    assert "mcp-demo" in out["overview"]
    assert "T-2" in out["add"]
    assert "doing" in out["update"]
    assert "[/] T-2 Try lightgbm" in project.main_plan_path.read_text()
    assert list(project.root.iterdir()) == []
    assert out["runs"][0]["name"] == "xgb" and out["runs"][0]["metrics"] == {"auc": 0.8}
    assert "plans/main.md" in out["search"]
    assert (project.docs_path / "notes/x.md").read_text() == "# hi"
    assert out["escape"].is_error
    assert "hello report" in out["artifact"]



def test_worktree_rename_tool(tmp_path, monkeypatch):
    import subprocess

    from dsd import mcp_server, worktrees

    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True)
    p = init_project(root, name="demo").project
    w = worktrees.create_worktree(p)
    monkeypatch.setenv("DSD_PROJECT_ROOT", w["path"])
    over = mcp_server.project_overview()
    assert over["worktree"]["name"] == w["name"] and over["worktree"]["auto_named"] is True
    r = mcp_server.worktree_rename("Staffing floors")
    assert r["name"] == "staffing-floors" and r["branch"] == "dsd/staffing-floors"
    assert mcp_server.project_overview()["worktree"]["auto_named"] is False
    monkeypatch.setenv("DSD_PROJECT_ROOT", str(root))
    with pytest.raises(Exception, match="not in"):
        mcp_server.worktree_rename("x")
