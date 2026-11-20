from pathlib import Path

import pytest
from typer.testing import CliRunner

from dsd import plans
from dsd.cli import app
from dsd.init import init_project

SAMPLE = """---
title: Churn main plan
status: active
---

# Churn

Some *prose* that   must survive.

## Tasks

- [ ] T-1 Baseline model #exp @benchmark:churn-v1
  Use the v2 features.
  - [x] T-2 Build features
  - [/] T-3 Tune xgb   #exp
* [!] T-4 Blocked on data access
- [-] T-5 Dropped idea
- [ ] Untracked task without id

```markdown
- [ ] T-99 not a task, inside a fence
```

1. [ ] T-6 Numbered task
"""


@pytest.fixture
def project(tmp_path):
    return init_project(tmp_path, name="churn").project


def write_main(project, text: str) -> Path:
    project.main_plan_path.write_bytes(text.encode())
    return project.main_plan_path


def test_parse(project):
    write_main(project, SAMPLE)
    pl = plans.load_plan(project)
    assert pl.meta["title"] == "Churn main plan"
    by_id = {t.id: t for t in pl.tasks}
    assert set(by_id) == {"T-1", "T-2", "T-3", "T-4", "T-5", "T-6", None}
    t1 = by_id["T-1"]
    assert t1.title == "Baseline model" and t1.tags == ["exp"] and t1.attrs == {"benchmark": "churn-v1"}
    assert t1.notes == ["Use the v2 features."]
    assert by_id["T-2"].parent == "T-1" and by_id["T-3"].parent == "T-1"
    assert by_id["T-3"].status == "doing" and by_id["T-3"].title == "Tune xgb"
    assert by_id["T-4"].status == "blocked" and by_id["T-4"].parent is None
    assert by_id["T-5"].status == "dropped"
    assert "T-99" not in by_id


def test_set_status_changes_one_byte(project):
    path = write_main(project, SAMPLE)
    pl = plans.load_plan(project)
    plans.set_status(pl, pl.task("T-1"), "done")
    pl.save()
    after = path.read_text()
    assert after == SAMPLE.replace("- [ ] T-1 Baseline", "- [x] T-1 Baseline")


def test_crlf_preserved(project):
    crlf = SAMPLE.replace("\n", "\r\n")
    path = write_main(project, crlf)
    pl = plans.load_plan(project)
    plans.set_status(pl, pl.task("T-3"), "done")
    plans.append_note(pl, pl.task("T-3"), "AUC 0.81")
    pl.save()
    raw = path.read_bytes().decode()
    assert "\n" not in raw.replace("\r\n", "")
    assert "    → AUC 0.81\r\n" in raw


def test_append_note_goes_after_existing_notes(project):
    write_main(project, SAMPLE)
    pl, t = plans.find_task(project, "T-1")
    plans.append_note(pl, t, "first result")
    pl.save()
    t1 = plans.load_plan(project).task("T-1")
    assert t1.notes == ["Use the v2 features.", "→ first result"]


def test_next_id_spans_all_plans(project):
    write_main(project, SAMPLE)
    plans.new_plan(project, "features", "Feature work")
    (project.plans_path / "features.md").write_text(
        (project.plans_path / "features.md").read_text() + "- [ ] T-40 Far ahead\n"
    )
    assert plans.next_id(project) == 41
    t = plans.add_task(project, "Next one")
    assert t.id == "T-41" and t.plan == "main"


def test_add_task_to_section_and_parent(project):
    write_main(project, SAMPLE)
    t = plans.add_task(project, "Calibrate", tags=["exp"], attrs={"owner": "me"})
    text = project.main_plan_path.read_text()
    assert "- [ ] T-7 Calibrate #exp @owner:me\n" in text
    # appended at the end of the Tasks section (the section runs to EOF here)
    assert text.rstrip().endswith("- [ ] T-7 Calibrate #exp @owner:me")
    child = plans.add_task(project, "Isotonic", parent="T-1")
    assert child.parent == "T-1"
    lines = project.main_plan_path.read_text().splitlines()
    assert lines[lines.index("  - [/] T-3 Tune xgb   #exp") + 1] == "  - [ ] T-8 Isotonic"


def test_add_task_creates_section_if_missing(project):
    write_main(project, "# Plan\n\nJust prose.\n")
    plans.add_task(project, "First")
    assert project.main_plan_path.read_text() == "# Plan\n\nJust prose.\n\n## Tasks\n\n- [ ] T-1 First\n"


def test_add_task_into_empty_section(project):
    write_main(project, "# Plan\n\n## Tasks\n\n## Notes\n\nhello\n")
    plans.add_task(project, "First")
    assert project.main_plan_path.read_text() == "# Plan\n\n## Tasks\n\n- [ ] T-1 First\n\n## Notes\n\nhello\n"


def test_new_plan_links_from_main(project):
    pl = plans.new_plan(project, "feature-eng", "Feature engineering")
    assert pl.meta == {"title": "Feature engineering", "status": "active", "parent": "main"}
    main = project.main_plan_path.read_text()
    assert "- [Feature engineering](feature-eng.md)" in main and "_None yet._" not in main
    plans.new_plan(project, "eval")
    assert "- [Eval](eval.md)" in project.main_plan_path.read_text()
    assert plans.check(project) == []
    with pytest.raises(plans.PlanError):
        plans.new_plan(project, "eval")
    with pytest.raises(plans.PlanError):
        plans.new_plan(project, "Bad Slug")


def test_fmt_and_check(project):
    write_main(project, SAMPLE + "- [ ] T-6 duplicate\n")
    problems = plans.check(project)
    assert any("duplicate id T-6" in p for p in problems)
    assert any("without id" in p for p in problems)
    assigned = plans.fmt_ids(project)
    assert [t.id for t in assigned] == ["T-7"]
    assert "- [ ] T-7 Untracked task without id\n" in project.main_plan_path.read_text()


def test_normalize_id():
    assert plans.normalize_id("t12") == "T-12"
    assert plans.normalize_id("12") == "T-12"
    assert plans.normalize_id("T-012") == "T-12"
    with pytest.raises(plans.PlanError):
        plans.normalize_id("X-1")


def test_cli_task_flow(project, monkeypatch):
    monkeypatch.chdir(project.root)
    r = CliRunner()
    assert r.invoke(app, ["task", "add", "Train baseline", "--tag", "exp"]).exit_code == 0
    res = r.invoke(app, ["task", "start", "2", "-m", "kicked off"])
    assert res.exit_code == 0, res.output
    assert "[/] T-2 Train baseline" in project.main_plan_path.read_text()
    assert r.invoke(app, ["task", "done", "T-2"]).exit_code == 0
    assert list(project.root.iterdir()) == []
    res = r.invoke(app, ["task", "ls", "--status", "done", "--json"])
    assert '"T-2"' in res.output
    assert r.invoke(app, ["plan", "new", "eval"]).exit_code == 0
    assert r.invoke(app, ["plan", "check"]).exit_code == 0
    assert r.invoke(app, ["task", "start", "T-404"]).exit_code == 1


def test_lenient_frontmatter(project):
    write_main(project, "---\ntitle: Churn: main plan\nstatus: active\n---\n\n- [ ] T-1 x\n")
    pl = plans.load_plan(project)
    assert pl.meta == {"title": "Churn: main plan", "status": "active"} and pl.title == "Churn: main plan"
