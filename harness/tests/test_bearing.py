"""Tests for harness/bearing.py."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE = os.path.join(REPO_ROOT, "samples", "baseline-early-game", "turn_0040.json")
SCRIPT = os.path.join(REPO_ROOT, "harness", "bearing.py")


def run(*args):
    result = subprocess.run(
        [sys.executable, SCRIPT] + list(args),
        capture_output=True, text=True,
    )
    return result


def test_same_tile():
    result = run("10,10", "10,10", SAMPLE)
    assert result.returncode == 0
    assert result.stdout.strip() == "same tile"


def test_reports_compass_and_straight_distance():
    # Higher y is now SOUTH (schemaVersion 2 - see AdvisorStateWriter._invertY).
    result = run("10,10", "10,15", SAMPLE)
    assert result.returncode == 0
    assert "S, 5 tiles straight" in result.stdout


def test_singular_tile_wording():
    result = run("10,10", "10,11", SAMPLE)
    assert "1 tile straight" in result.stdout
    assert "1 tiles" not in result.stdout


def test_matches_state_bearing_convention():
    """Cross-check against render_map.State.bearing rather than a hardcoded
    string, so the two cannot silently drift apart.
    """
    import render_map
    state = render_map.State(SAMPLE)
    origin, target = (73, 18), (79, 25)
    compass = state.bearing(origin, target)
    result = run("73,18", "79,25", SAMPLE)
    assert compass in result.stdout


def test_rejects_malformed_point():
    result = run("nope", "1,1", SAMPLE)
    assert result.returncode != 0
    assert "X,Y" in result.stderr


def test_no_land_route_across_water_or_off_map():
    result = run("5,5", "900,900", SAMPLE)
    assert result.returncode == 0
    assert "NO LAND ROUTE" in result.stdout
