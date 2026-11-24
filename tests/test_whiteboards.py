import json

import pytest
from fastapi.testclient import TestClient

from dsd import whiteboards as wb
from dsd.init import init_project
from dsd.web.server import create_app


@pytest.fixture
def project(tmp_path):
    return init_project(tmp_path, name="demo").project


def test_create_list_rename_delete(project):
    slug = wb.new_board(project, "Target pipeline")
    assert slug == "target-pipeline" and wb.new_board(project, "Target pipeline") == "target-pipeline-2"
    path = project.docs_path / "whiteboards" / "target-pipeline.excalidraw"
    data = json.loads(path.read_text())
    assert data["type"] == "excalidraw" and data["elements"] == [] and data["dsd"]["name"] == "Target pipeline"
    assert [b["slug"] for b in wb.list_boards(project)][0] in ("target-pipeline", "target-pipeline-2")
    new = wb.rename_board(project, "target-pipeline", "Resolver flow")
    assert new == "resolver-flow" and not path.exists() and wb.read_board(project, new)["dsd"]["name"] == "Resolver flow"
    with pytest.raises(wb.WhiteboardError):
        wb.rename_board(project, "target-pipeline-2", "Resolver flow")
    wb.delete_board(project, "resolver-flow")
    assert [b["slug"] for b in wb.list_boards(project)] == ["target-pipeline-2"]
    with pytest.raises(wb.WhiteboardError):
        wb.read_board(project, "../../project")


def test_claude_queues_drawings_and_the_app_applies_them(project):
    r = wb.queue_drawing(project, "Flow", mermaid="flowchart LR\n  A[Readers] --> B[Resolver]")
    assert r["board"] == "flow"
    r2 = wb.queue_drawing(project, "flow", elements=[
        {"type": "rectangle", "id": "a", "x": 0, "y": 0, "width": 160, "height": 60, "label": {"text": "Compute"}},
        {"type": "arrow", "x": 160, "y": 30, "start": {"id": "a"}, "end": {"id": "b"}},
        {"type": "diamond", "id": "b", "x": 300, "y": 0, "label": {"text": "Floor?"}, "strokeColor": "#e03131"},
    ])
    board = wb.read_board(project, "flow")
    pending = board["dsd"]["pending"]
    assert [("mermaid" in p, "elements" in p) for p in pending] == [(True, False), (False, True)]
    assert wb.list_boards(project)[0]["pending"] == 2
    wb.queue_drawing(project, "flow", mermaid="flowchart LR\n  X --> Y")
    elements = [{"id": "r1", "type": "rectangle", "x": 0, "y": 0, "width": 10, "height": 10},
                {"id": "t1", "type": "text", "containerId": "r1", "text": "Compute", "x": 0, "y": 0},
                {"id": "r2", "type": "diamond", "x": 100, "y": 0},
                {"id": "a1", "type": "arrow", "x": 10, "y": 5, "startBinding": {"elementId": "r1"}, "endBinding": {"elementId": "r2"}}]
    res = wb.save_board(project, "flow", {"elements": elements, "appState": {"viewBackgroundColor": "#fff"}},
                        applied=[r["queued"], r2["queued"]])
    assert res["pending"] == 1
    d = wb.describe(project, "flow")
    assert d["shapes"][0]["text"] == "Compute" and d["connections"] == [{"type": "arrow", "from": "Compute", "to": "diamond", "text": ""}]
    with pytest.raises(wb.WhiteboardError):
        wb.queue_drawing(project, "flow", elements=[{"type": "image", "x": 0, "y": 0}])
    with pytest.raises(wb.WhiteboardError):
        wb.queue_drawing(project, "flow")


def test_whiteboard_api(project):
    with TestClient(create_app()) as c:
        base = f"/api/p/{project.id}/whiteboards"
        slug = c.post(base, json={"name": "Ideas"}).json()["slug"]
        assert [b["name"] for b in c.get(base).json()] == ["Ideas"]
        board = c.get(f"{base}/{slug}").json()
        assert board["elements"] == []
        assert c.put(f"{base}/{slug}", json={"scene": {"elements": [{"id": "x", "type": "ellipse", "x": 1, "y": 2}]}, "applied": []}).json()["ok"]
        assert c.get(f"{base}/{slug}").json()["elements"][0]["type"] == "ellipse"
        assert c.post(f"{base}/{slug}/rename", json={"name": "Better ideas"}).json()["slug"] == "better-ideas"
        assert c.get(f"{base}/ideas").status_code == 404
        assert c.delete(f"{base}/better-ideas").status_code == 200
        assert c.get(base).json() == []


def test_mcp_whiteboard_tools(project, monkeypatch):
    from dsd import mcp_server

    monkeypatch.setenv("DSD_PROJECT_ROOT", str(project.repo))
    r = mcp_server.whiteboard_draw("Pipeline", mermaid="flowchart LR\n  A --> B")
    assert r["board"] == "pipeline" and "Whiteboards" in r["note"]
    assert mcp_server.whiteboard_list()[0]["pending"] == 1
    assert mcp_server.whiteboard_read("Pipeline")["pending"] == 1
