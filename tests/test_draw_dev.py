import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("draw_dev", Path(__file__).resolve().parents[1] / "scripts" / "draw_dev.py")
draw_dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(draw_dev)

IDS = [f"fake{i:03d}" for i in range(100)]


def test_draw_is_reproducible_and_ignores_input_order():
    a = draw_dev.draw(IDS, seed=7, n=40)
    assert a == draw_dev.draw(list(reversed(IDS)), seed=7, n=40)
    assert len(set(a)) == 40
    assert a != draw_dev.draw(IDS, seed=8, n=40)


def test_draw_count_makes_dev_the_requested_share_of_the_working_set():
    assert draw_dev.draw_count(working_dev=13, working_eval=101, dev_share=0.70) == 67   # dev 80, eval 34
    assert draw_dev.draw_count(working_dev=90, working_eval=10, dev_share=0.70) == 0     # already past the share
    with pytest.raises(ValueError):
        draw_dev.draw_count(13, 101, 1.0)


def test_draw_needs_enough_candidates():
    with pytest.raises(ValueError):
        draw_dev.draw(IDS[:10], seed=1, n=40)
