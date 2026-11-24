import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(root: Path):
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = root
    mod.CHANGELOG = root / "CHANGELOG.md"
    return mod


def test_repo_versions_agree():
    mod = load(ROOT)
    assert mod.check(None) == []
    version = mod.versions()["src/dsd/__init__.py"]
    assert mod.check(f"v{version}") == []
    assert mod.check("v99.0.0")


def test_bump_sets_every_version_and_cuts_the_changelog(tmp_path):
    for rel, _ in load(ROOT).FILES + [("CHANGELOG.md", None)]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n- Faster boards\n\n## 0.1.0\n\n- First\n")
    mod = load(tmp_path)
    assert mod.main(["0.2.0"]) == 0
    assert set(mod.versions().values()) == {"0.2.0"}
    assert mod.notes("0.2.0") == "- Faster boards"
    assert mod.notes("0.1.0") == "- First"
    assert "## Unreleased\n\n## 0.2.0 - " in (tmp_path / "CHANGELOG.md").read_text()
    assert mod.check("v0.2.0") == []
    assert mod.main(["--check", "v0.3.0"]) == 1
