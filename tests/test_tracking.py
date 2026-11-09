import json
import subprocess
import sys
import textwrap

import pytest
from typer.testing import CliRunner

import dsd
from dsd.cli import app
from dsd.init import init_project
from dsd.project import load_project
from dsd.tracking.bundle import Bundle, flatten
from dsd.tracking.execute import default_name, exec_command
from dsd.tracking.index import Index
from dsd.tracking.query import Where, compare, leaderboard, list_runs, set_bench_spec


@pytest.fixture
def project(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    init_project(tmp_path, name="churn")
    p = load_project(tmp_path)
    monkeypatch.setenv("DSD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("DSD_RUN_DIR", raising=False)
    monkeypatch.delenv("DSD_TASK", raising=False)
    return p


def make_runs(seeds=(0, 1, 2)):
    for model, base in (("xgb", 0.80), ("lr", 0.70)):
        for s in seeds:
            with dsd.run(f"{model}-s{s}", benchmark="churn-v1", task="T-3",
                         params={"model": {"type": model, "eta": 0.1 * (s + 1)}, "seed": s},
                         datasets=[dsd.dataset(id="churn-2024q3")]) as r:
                for step in range(3):
                    r.log({"loss": 1.0 / (step + 1)}, step=step)
                r.log({"auc": base + 0.01 * s, "f1": base - 0.2})
                r.info(notes=f"seed {s}")


def test_sdk_writes_bundle(project):
    with dsd.run("baseline", benchmark="b1", task="T-1", params={"model": {"eta": 0.1}}, tags=["x"],
                 datasets=[dsd.dataset(name="train", uri="https://github.com/o/d")]) as r:
        r.log({"loss": 0.5}, step=0)
        r.log(loss=0.4, step=1)
        r.log({"auc": 0.81, "bad": "nope"})
        r.info(feature_count=212, cols=["a", "b"])
        r.html("report", "<h1>hi</h1>", description="Eval report")
        rid = r.id
    b = Bundle(project.runs_path / rid)
    meta = b.read_meta()
    assert meta["status"] == "finished" and meta["ended_at"]
    assert meta["params"] == {"model": {"eta": 0.1}}
    assert meta["info"] == {"feature_count": 212, "cols": ["a", "b"]}
    assert meta["datasets"] == [{"name": "train", "uri": "https://github.com/o/d"}]
    assert meta["git"]["branch"] == "main" and meta["git"]["dirty"] is True
    assert [m["k"] for m in b.read_metrics()] == ["loss", "loss", "auc"]
    assert b.read_manifest()[0]["path"] == "report.html"
    assert b.read_manifest()[0]["description"] == "Eval report"
    assert (b.capture_dir / "git.diff").exists()


def test_sdk_failure_and_interrupt(project):
    with pytest.raises(ValueError):
        with dsd.run("boom") as r:
            raise ValueError("bad data")
    assert Bundle(r.dir).read_meta()["status"] == "failed"
    assert "ValueError: bad data" in Bundle(r.dir).read_meta()["error"]
    with pytest.raises(KeyboardInterrupt):
        with dsd.run("ctrl-c") as r2:
            raise KeyboardInterrupt
    assert Bundle(r2.dir).read_meta()["status"] == "killed"


def test_sdk_never_raises_on_bad_input(project):
    with dsd.run("tolerant") as r:
        r.artifact("/does/not/exist.html")  # warns, doesn't raise
        r.log({"x": float("nan")})
    assert Bundle(r.dir).read_meta()["status"] == "finished"


def test_index_queries_and_reindex(project):
    make_runs()
    with Index(project) as idx:
        assert idx.sync()["added"] == 6
        assert idx.sync() == {"added": 0, "updated": 0, "removed": 0}
        runs = list_runs(idx, benchmark="churn-v1", where=["params.model.type=xgb", "metrics.auc>=0.805"],
                         sort="-metrics.auc")
        assert [r["name"] for r in runs] == ["xgb-s2", "xgb-s1"]
        assert runs[0]["metrics"]["auc"] == pytest.approx(0.82)
        series = idx.series([runs[0]["id"]], ["loss"])
        assert series[runs[0]["id"]]["loss"] == [[0, 1.0], [1, 0.5], [2, pytest.approx(1 / 3)]]
        before = [(r["id"], r["metrics"]) for r in list_runs(idx, sort="name")]
        idx.rebuild()
        assert [(r["id"], r["metrics"]) for r in list_runs(idx, sort="name")] == before
        c = compare(idx, [runs[0]["id"], runs[1]["id"]])
        differs = {p["key"] for p in c["params"] if p["differs"]}
        assert differs == {"model.eta", "seed"}


def test_index_picks_up_deletions(project):
    make_runs(seeds=(0,))
    import shutil

    with Index(project) as idx:
        idx.sync()
        victim = list_runs(idx)[0]["id"]
        shutil.rmtree(project.runs_path / victim)
        assert idx.sync()["removed"] == 1


def test_leaderboard(project):
    make_runs()
    set_bench_spec(project, "churn-v1", primary="auc", direction="max")
    with Index(project) as idx:
        idx.sync()
        flat = leaderboard(idx, project, "churn-v1")
        assert flat["metrics"][0] == "auc"
        assert flat["rows"][0]["run"]["name"] == "xgb-s2" and flat["rows"][0]["rank"] == 1
        g = leaderboard(idx, project, "churn-v1", group_by="params.model.type")
        assert [r["group"] for r in g["rows"]] == ["xgb", "lr"]
        assert g["rows"][0]["stats"]["auc"]["mean"] == pytest.approx(0.81)
        assert g["rows"][0]["stats"]["auc"]["n"] == 3


def test_leaderboard_without_spec_lists_all_metrics(project):
    make_runs(seeds=(0,))
    with Index(project) as idx:
        idx.sync()
        b = leaderboard(idx, project, "churn-v1")
        assert set(b["metrics"]) == {"auc", "f1", "loss"} and b["rows"][0]["rank"] is None


def test_where_parse():
    w = Where.parse("metrics.auc >= 0.8")
    assert (w.field, w.op, w.value) == ("metrics.auc", ">=", 0.8)
    assert Where.parse("name~xgb").matches({"name": "XGB-1"})
    assert flatten({"a": {"b": 1, "c": {}}}) == {"a.b": 1, "a.c": {}}


SCRIPT = textwrap.dedent("""
    import json, os, sys
    import dsd
    run_dir = os.environ["DSD_RUN_DIR"]
    with dsd.run(params={"from_sdk": 1}) as r:   # attaches to the exec run
        r.log({"sdk_metric": 2.0})
    json.dump({"acc": 0.9, "nested": {"f1": 0.5}, "note": "hello"}, open(os.path.join(run_dir, "metrics.json"), "w"))
    os.makedirs(os.path.join(run_dir, "artifacts"), exist_ok=True)
    open(os.path.join(run_dir, "artifacts", "report.html"), "w").write("<p>r</p>")
    print("training...")
    sys.exit(int(sys.argv[1]))
""")


def test_exec_success_and_failure(project, tmp_path, capfd):
    script = tmp_path / "train.py"
    script.write_text(SCRIPT)
    bundle, code = exec_command(project, [sys.executable, str(script), "0"], benchmark="b", task="T-2",
                                params={"lr": 0.1})
    assert code == 0
    meta = bundle.read_meta()
    assert meta["status"] == "finished" and meta["name"] == "train" and meta["task"] == "T-2"
    assert meta["params"] == {"lr": 0.1, "from_sdk": 1}
    assert meta["info"]["note"] == "hello"
    keys = {m["k"] for m in bundle.read_metrics()}
    assert keys == {"sdk_metric", "acc", "nested.f1"}
    assert [a["path"] for a in bundle.read_manifest()] == ["report.html"]
    assert "training..." in (bundle.capture_dir / "stdout.log").read_text()

    bundle2, code2 = exec_command(project, [sys.executable, str(script), "3"], quiet=True)
    assert code2 == 3 and bundle2.read_meta()["status"] == "failed"


def test_default_name():
    assert default_name(["uv", "run", "python", "train.py", "--x"]) == "train"
    assert default_name(["python", "-m", "pkg.bench"]) == "bench"
    assert default_name(["make", "bench"]) == "make"


def test_cli_runs_and_bench(project, monkeypatch):
    make_runs()
    monkeypatch.chdir(project.root)
    r = CliRunner()
    res = r.invoke(app, ["runs", "ls", "-b", "churn-v1", "--sort", "-metrics.auc"])
    assert res.exit_code == 0 and "xgb-s2" in res.output, res.output
    assert r.invoke(app, ["bench", "set", "churn-v1", "-p", "auc", "-d", "max"]).exit_code == 0
    res = r.invoke(app, ["bench", "board", "churn-v1", "-g", "params.model.type"])
    assert res.exit_code == 0 and "xgb" in res.output, res.output
    res = r.invoke(app, ["runs", "ls", "--json"])
    rid = json.loads(res.output)[0]["id"]
    res = r.invoke(app, ["runs", "show", rid[-8:]])
    assert res.exit_code == 0 and "params" in res.output, res.output
