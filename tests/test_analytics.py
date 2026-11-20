from fastapi.testclient import TestClient

from dsd import analytics
from dsd.init import init_project
from dsd.web.server import create_app


def test_post_and_list_results(tmp_path):
    p = init_project(tmp_path, name="demo").project
    assert (p.docs_path / "analytics").is_dir()
    first = analytics.write_post(p, "Baseline recorded", "Today's preset solves the estate in 31 s at p95.",
                                 "Body one.", metrics={"p95 solve time (s)": 31}, benchmark="estate", date="2026-11-18")
    second = analytics.write_post(p, "Rules-aware is 23% faster", "p95 solve time fell from 31 s to 24 s.",
                                  "```mermaid\nxychart-beta\n  bar [31, 24]\n```", metrics={"p95 solve time (s)": 24, "change": "-23%"},
                                  task="T-26", plan="sof-rules-aware-target", runs=["01ABC"], date="2026-11-20")
    assert first == "analytics/2026-11-18-baseline-recorded.md" and second.startswith("analytics/2026-11-20-")
    posts = analytics.list_posts(p)
    assert [x["title"] for x in posts] == ["Rules-aware is 23% faster", "Baseline recorded"]
    top = posts[0]
    assert top["headline"] == "p95 solve time fell from 31 s to 24 s." and top["metrics"]["change"] == "-23%"
    assert top["task"] == "T-26" and top["runs"] == ["01ABC"] and top["date"] == "2026-11-20"
    text = (p.docs_path / second).read_text()
    assert text.startswith("---\n") and "# Rules-aware is 23% faster" in text and "xychart-beta" in text
    again = analytics.write_post(p, "Baseline recorded", "Re-run.", "Body.", date="2026-11-18")
    assert again == "analytics/2026-11-18-baseline-recorded-2.md"


def test_analytics_api(tmp_path, monkeypatch):
    p = init_project(tmp_path, name="demo").project
    analytics.write_post(p, "A result", "One line.", "Body.", metrics={"auc": 0.81})
    (p.docs_path / "analytics" / "hand-written.md").write_text("# Notes by hand\n\nNo frontmatter.\n")
    with TestClient(create_app()) as c:
        posts = c.get(f"/api/p/{p.id}/analytics").json()
        assert {x["title"] for x in posts} == {"A result", "Notes by hand"}
