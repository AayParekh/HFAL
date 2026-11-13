"""scripts/final_run.py: the pilot hospitals are never drawn, and the budget stop leaves room for calls in flight."""
import importlib.util
from pathlib import Path

import pytest

from hfal import paths

_spec = importlib.util.spec_from_file_location("final_run", Path(__file__).parents[1] / "scripts" / "final_run.py")
final_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(final_run)


def _review(tmp_path, monkeypatch, pilot_text=None):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    (tmp_path / "review").mkdir()
    if pilot_text is not None:
        (tmp_path / "review" / "pilot_ids.txt").write_text(pilot_text, encoding="utf-8")
    monkeypatch.setattr(final_run, "working_set", lambda s: [f"h{i}" for i in range(10)])


def test_the_draw_never_includes_a_pilot_hospital(tmp_path, monkeypatch):
    _review(tmp_path, monkeypatch, "h0\nh1\nh2\n")
    for seed in range(20):
        ids, n_pilot = final_run.draw(7, seed)
        assert n_pilot == 3 and len(ids) == 7 and not {"h0", "h1", "h2"} & set(ids)


def test_no_pilot_list_means_no_run(tmp_path, monkeypatch):
    _review(tmp_path, monkeypatch)                                   # pilot_ids.txt missing
    with pytest.raises(SystemExit, match="pilot hospitals the final run must leave alone"):
        final_run.draw(5, 1)


def test_an_empty_pilot_list_means_no_run(tmp_path, monkeypatch):
    _review(tmp_path, monkeypatch, "\n")
    with pytest.raises(SystemExit, match="lists no hospitals"):
        final_run.draw(5, 1)


def test_keep_awake_ties_caffeinate_to_this_process(monkeypatch):
    import os
    started = []
    monkeypatch.setattr(final_run.sys, "platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/caffeinate")
    monkeypatch.setattr(final_run.subprocess, "Popen", lambda cmd: started.append(cmd) or "proc")
    assert final_run.keep_awake() == "proc"
    assert started == [["caffeinate", "-i", "-s", "-w", str(os.getpid())]]   # ends when this script ends


def test_keep_awake_does_nothing_off_a_mac(monkeypatch):
    monkeypatch.setattr(final_run.sys, "platform", "linux")
    monkeypatch.setattr(final_run.subprocess, "Popen", lambda cmd: pytest.fail("started a process"))
    assert final_run.keep_awake() is None


def test_the_run_stops_early_enough_that_calls_in_flight_stay_within_the_budget():
    assert final_run.stop_at(50, 2) == 50 - 2 * final_run.MAX_CALL_USD
    assert final_run.stop_at(50, 1) < 50
    assert final_run.stop_at(10, 2, 0.9) == pytest.approx(8.2)     # a run of small prompts holds back less


def test_a_listed_run_takes_dev_hospitals_only_and_never_a_pilot(tmp_path, monkeypatch):
    _review(tmp_path, monkeypatch, "h0\n")
    f = tmp_path / "ids.txt"
    f.write_text("h5\nh3\n\nh5\n", encoding="utf-8")
    assert final_run.from_file(f) == ["h3", "h5"]
    f.write_text("h3\nh0\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="pilot"):
        final_run.from_file(f)
    f.write_text("h3\nzz\n", encoding="utf-8")                        # not in the dev working set (e.g. eval)
    with pytest.raises(SystemExit, match="not dev"):
        final_run.from_file(f)


def test_an_eval_list_needs_set_eval_and_still_refuses_pilot_hospitals(tmp_path, monkeypatch):
    _review(tmp_path, monkeypatch, "d0\n")
    sets = {"dev": ["d0", "d1"], "eval": ["e0", "e1"]}
    monkeypatch.setattr(final_run, "working_set", lambda s: sets[s])
    f = tmp_path / "ids.txt"
    f.write_text("e1\ne0\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not dev"):
        final_run.from_file(f)                                        # dev is the default
    assert final_run.from_file(f, "eval") == ["e0", "e1"]
    f.write_text("e0\nd1\n", encoding="utf-8")                        # a dev hospital in an eval list
    with pytest.raises(SystemExit, match="not eval"):
        final_run.from_file(f, "eval")
