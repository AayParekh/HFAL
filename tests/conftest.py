import pytest

from hfal import paths


@pytest.fixture(autouse=True)
def runs_in_tmp(tmp_path_factory, monkeypatch):
    """No test writes to the real runs/ folder (the usage ledger lives there). Tests that need a particular runs
    folder set paths.RUNS themselves, after this."""
    monkeypatch.setattr(paths, "RUNS", tmp_path_factory.mktemp("runs"))
