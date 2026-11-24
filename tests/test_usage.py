import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from dsd import usage
from dsd.init import init_project


def reply(ts: datetime, mid: str, model: str, cwd: str, session: str, inp=100, out=50, cw=10, cr=5000) -> str:
    return json.dumps({
        "type": "assistant", "timestamp": ts.isoformat().replace("+00:00", "Z"), "cwd": cwd, "sessionId": session,
        "requestId": f"req-{mid}",
        "message": {"id": mid, "model": model, "usage": {"input_tokens": inp, "output_tokens": out,
                                                         "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}},
    })


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("HOME", str(h))
    return h


def test_usage_by_day_model_and_project(home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    p = init_project(repo, name="churn").project
    now = datetime.now(timezone.utc).replace(hour=12)
    older = now - timedelta(days=3)
    proj = home / ".claude" / "projects" / "-repo"
    (proj / "s1" / "subagents").mkdir(parents=True)
    (proj / "s1.jsonl").write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": "secret prompt"}}),
        reply(now, "m1", "claude-opus-5-5", str(repo), "s1"),
        reply(now, "m1", "claude-opus-5-5", str(repo), "s1"),
        reply(older, "m2", "claude-sonnet-5", str(repo / "src"), "s1", inp=1000, out=500, cw=0),
        "not json",
    ]) + "\n")
    (proj / "s1" / "subagents" / "a.jsonl").write_text(reply(now, "m3", "claude-haiku-4-5", "/elsewhere", "s1", inp=10) + "\n")
    u = usage.claude_usage(days=30)
    today = now.astimezone().date().isoformat()
    assert u["days"][today] == {"tokens": 230, "output": 100, "messages": 2, "sessions": 1}
    assert u["totals"]["tokens"] == 230 + 1500 and u["totals"]["messages"] == 3 and u["totals"]["sessions"] == 1
    assert u["totals"]["cache_read"] == 15000
    assert [m["model"] for m in u["models"]] == ["claude-sonnet-5", "claude-opus-5-5", "claude-haiku-4-5"]
    assert {x["project"]: x["tokens"] for x in u["projects"]} == {"churn": 1660, "other": 70}
    assert u["projects"][0]["project_id"] == p.id


def test_usage_is_cached_and_refreshed(home):
    proj = home / ".claude" / "projects" / "-x"
    proj.mkdir(parents=True)
    f = proj / "s.jsonl"
    now = datetime.now(timezone.utc)
    f.write_text(reply(now, "m1", "claude-opus-5-5", "/x", "s") + "\n")
    assert usage.claude_usage()["totals"]["messages"] == 1
    cache = json.loads((usage.cache_file()).read_text())
    assert str(f) in cache["files"]
    time.sleep(0.01)
    with open(f, "a") as fh:
        fh.write(reply(now, "m2", "claude-opus-5-5", "/x", "s") + "\n")
    os.utime(f, (time.time() + 2, time.time() + 2))
    assert usage.claude_usage()["totals"]["messages"] == 2


def test_no_transcripts(home):
    u = usage.claude_usage()
    assert u["totals"]["tokens"] == 0 and u["models"] == [] and u["days"] == {}


def test_usage_api(home):
    from fastapi.testclient import TestClient

    from dsd.web.server import create_app

    proj = home / ".claude" / "projects" / "-x"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(reply(datetime.now(timezone.utc), "m1", "claude-opus-5-5", "/x", "s") + "\n")
    with TestClient(create_app()) as c:
        u = c.get("/api/usage").json()
    assert u["totals"]["messages"] == 1 and u["models"][0]["model"] == "claude-opus-5-5"
