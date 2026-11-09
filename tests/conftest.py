import pytest


@pytest.fixture(autouse=True)
def isolated_dsd_home(tmp_path_factory, monkeypatch):
    """Never let tests touch the real ~/.dsd project registry."""
    monkeypatch.setenv("DSD_HOME", str(tmp_path_factory.mktemp("dsd-home")))
