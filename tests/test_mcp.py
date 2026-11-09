import json
import os
import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import dsd
from dsd.init import init_project
from dsd.project import load_project


@pytest.fixture
def project(tmp_path, monkeypatch):
    init_project(tmp_path, name="mcp-demo")
    monkeypatch.setenv("DSD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("DSD_RUN_DIR", raising=False)
    with dsd.run("xgb", benchmark="b1", params={"model": "xgb"}) as r:
        r.log({"auc": 0.8})
        r.html("report.html", "<p>hello report</p>")
    return load_project(tmp_path)


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
    assert "Active tasks: `T-2` Try lightgbm" in (project.root / "CLAUDE.md").read_text()
    assert out["runs"][0]["name"] == "xgb" and out["runs"][0]["metrics"] == {"auc": 0.8}
    assert "plans/main.md" in out["search"]
    assert (project.docs_path / "notes/x.md").read_text() == "# hi"
    assert out["escape"].is_error
    assert "hello report" in out["artifact"]


def test_init_writes_mcp_and_skills(tmp_path):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    init_project(tmp_path)
    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"other", "dsd"}
    skills = sorted(p.parent.name for p in (tmp_path / ".claude/skills").glob("*/SKILL.md"))
    assert skills == ["dsd-distill", "dsd-next-task", "dsd-plan", "dsd-report", "dsd-run-experiment"]
    (tmp_path / ".claude/skills/dsd-plan/SKILL.md").write_text("custom")
    assert not init_project(tmp_path).changed
    assert (tmp_path / ".claude/skills/dsd-plan/SKILL.md").read_text() == "custom"
