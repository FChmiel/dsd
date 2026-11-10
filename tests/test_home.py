from datetime import date

import pytest
from fastapi.testclient import TestClient

from dsd import home, registry
from dsd.init import init_project
from dsd.project import load_project
from dsd.web.server import create_app

TUE = date(2026, 11, 10)  # a Tuesday


@pytest.mark.parametrize("text,title,due", [
    ("Send David the numbers tomorrow", "Send David the numbers", "2026-11-11"),
    ("call bank today", "call bank", "2026-11-10"),
    ("expense GPU credits yesterday", "expense GPU credits", "2026-11-09"),
    ("review PR fri", "review PR", "2026-11-13"),
    ("review PR on Friday", "review PR", "2026-11-13"),
    ("standup notes tue", "standup notes", "2026-11-17"),  # same weekday -> next week
    ("next fri retro", "retro", "2026-11-20"),
    ("plan Q1 next week", "plan Q1", "2026-11-16"),
    ("renew licence in 3 days", "renew licence", "2026-11-13"),
    ("submit 2026-12-01 report", "submit report", "2026-12-01"),
    ("dentist 11/24", "dentist", "2026-11-24"),
    ("pay invoice 3 Dec", "pay invoice", "2026-12-03"),
    ("pay invoice Dec 3", "pay invoice", "2026-12-03"),
    ("year end 1/5", "year end", "2027-01-05"),
    ("think about monday.com pricing", "think about monday.com pricing", None),
    ("just a note", "just a note", None),
])
def test_parse_due(text, title, due):
    rest, d = home.parse_due(text, TUE)
    assert rest == title
    assert (d.isoformat() if d else None) == due


def test_parse_quick_project_and_tags():
    q = home.parse_quick("Send David AUC tomorrow #churn-model #email", ["churn-model", "other"], TUE)
    assert q == {"title": "Send David AUC", "due": "2026-11-11", "project": "churn-model", "tags": ["email"]}


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "proj"
    init_project(root, name="churn")
    registry.register(root)
    p = load_project(root)
    (p.main_plan_path).write_text(p.main_plan_path.read_text()
                                  + "- [!] T-2 Waiting on data\n- [ ] T-3 Model card @due:2026-01-01\n")
    return p


def test_todos_crud_and_dashboard(setup):
    t = home.add_todo("Send David the numbers today #churn")
    assert t["project"] == "churn" and t["due"] == date.today().isoformat() and t["id"] == "T-1"
    t2 = home.add_todo("someday idea")
    assert t2["due"] is None
    home.update_todo("T-2", due="2030-01-02")
    assert [x["due"] for x in home.list_todos()] == [date.today().isoformat(), "2030-01-02"]
    home.update_todo("T-1", status="done")
    assert home.list_todos()[0]["status"] == "done"  # done today stays visible
    d = home.dashboard()
    assert d["counts"]["overdue"] == 1  # the project's T-3 dated 2026-01-01
    kinds = {a["kind"] for a in d["attention"]}
    assert "blocked" in kinds
    assert any(a["source"] == "project" and a["id"] == "T-3" for a in d["agenda"])
    assert d["projects"][0]["name"] == "churn" and d["projects"][0]["counts"]["blocked"] == 1
    home.delete_todo("T-2")
    assert [x["id"] for x in home.list_todos()] == ["T-1"]
    text = home.home_project().main_plan_path.read_text()
    assert "- [x] T-1 Send David the numbers @due:" in text and "@project:churn" in text


def test_home_api(setup):
    with TestClient(create_app()) as c:
        t = c.post("/api/todos", json={"text": "email Sam fri #churn"}).json()
        assert t["title"] == "email Sam" and t["project"] == "churn"
        assert c.patch(f"/api/todos/{t['id']}", json={"due": None}).json()["due"] is None
        assert c.patch(f"/api/todos/{t['id']}", json={"title": "email Sam re: churn"}).json()["title"] == "email Sam re: churn"
        h = c.get("/api/home").json()
        assert h["summary"] and h["projects"][0]["name"] == "churn"
        assert c.delete(f"/api/todos/{t['id']}").status_code == 200
