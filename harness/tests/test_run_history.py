"""Tests for harness/run_history.py.

Landmarks are DERIVED from the committed sample files rather than quoted from
prose, so a resample cannot leave these tests asserting fiction. Where a test
needs a broken run - which no real sample is, and none should be - it builds one
by mutating loaded sample data in a tmp_path, never by adding a bad run to
samples/, which is reserved for real captures.
"""

import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_history


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DIR = os.path.join(REPO_ROOT, "samples", "baseline-early-game")


@pytest.fixture(scope="module")
def run():
    return run_history.Run(SAMPLE_DIR)


def load(turn):
    with open(os.path.join(SAMPLE_DIR, "turn_%04d.json" % turn), "r",
              encoding="utf-8") as handle:
        return json.load(handle)


def write_run(directory, states):
    """Write states out as a run folder, numbered by their own gameTurn."""
    for state in states:
        path = os.path.join(str(directory), "turn_%04d.json" % state["game"]["gameTurn"])
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    return str(directory)


def render(run_obj, view, first=None, last=None):
    first = run_obj.turns[0] if first is None else first
    last = run_obj.turns[-1] if last is None else last
    return run_history.render(run_obj, view, first, last)


# -- landmarks derived from the sample ------------------------------------


def first_turn_with(predicate):
    """The earliest sample turn satisfying `predicate`, or None."""
    for turn in range(0, 41):
        if predicate(load(turn)):
            return turn
    return None


def test_sample_run_loads_and_is_continuous(run):
    assert len(run.states) == 41
    assert run.turns == list(range(0, 41))
    assert run.gaps == []


def test_sample_has_one_setup_signature():
    """The guard's whole premise: one game means one unchanging setup."""
    signatures = set(
        run_history.setup_signature(load(turn)) for turn in range(0, 41)
    )
    assert len(signatures) == 1


# -- continuity guard -----------------------------------------------------


def test_duplicate_turn_is_fatal(tmp_path):
    a, b = load(5), load(6)
    b["game"]["gameTurn"] = 5
    # Both files claim turn 5; filenames differ so both survive on disk.
    with open(os.path.join(str(tmp_path), "turn_0005.json"), "w", encoding="utf-8") as h:
        json.dump(a, h)
    with open(os.path.join(str(tmp_path), "turn_0006.json"), "w", encoding="utf-8") as h:
        json.dump(b, h)
    with pytest.raises(run_history.RunError) as error:
        run_history.Run(str(tmp_path))
    assert "duplicate turn 5" in str(error.value)


def test_tech_regression_is_fatal(tmp_path):
    """Techs are never unlearned, so losing one means a different timeline."""
    a, b = load(30), load(31)
    assert "TECH_ANIMAL_HUSBANDRY" in a["player"]["knownTechs"]
    b = copy.deepcopy(b)
    b["player"]["knownTechs"] = [
        t for t in b["player"]["knownTechs"] if t != "TECH_ANIMAL_HUSBANDRY"
    ]
    path = write_run(tmp_path, [a, b])
    with pytest.raises(run_history.RunError) as error:
        run_history.Run(path)
    assert "TECH_ANIMAL_HUSBANDRY" in str(error.value)


def test_forgotten_tiles_are_fatal(tmp_path):
    """Revealed map only ever grows within one game."""
    a, b = load(20), load(21)
    b = copy.deepcopy(b)
    b["map"]["tiles"] = b["map"]["tiles"][:-20]
    path = write_run(tmp_path, [a, b])
    with pytest.raises(run_history.RunError) as error:
        run_history.Run(path)
    assert "forgotten" in str(error.value)


def test_different_game_setup_is_fatal(tmp_path):
    a, b = load(5), load(6)
    b = copy.deepcopy(b)
    b["game"]["climate"] = "CLIMATE_ARID"
    path = write_run(tmp_path, [a, b])
    with pytest.raises(run_history.RunError) as error:
        run_history.Run(path)
    assert "DIFFERENT GAME" in str(error.value)
    assert "climate" in str(error.value)


def test_reused_city_id_with_new_name_is_fatal(tmp_path):
    """Engine ids are stable within a game."""
    a = load(37)
    b = copy.deepcopy(load(38))
    assert a["cities"], "sample turn 37 should have cities"
    b["cities"][0]["name"] = "Atlantis"
    path = write_run(tmp_path, [a, b])
    with pytest.raises(run_history.RunError) as error:
        run_history.Run(path)
    assert "Atlantis" in str(error.value)


def test_turn_gap_is_allowed_and_reported(tmp_path):
    """A failed export is skipped, not fatal - so a gap must not raise."""
    states = [load(t) for t in (10, 11, 14, 15)]
    path = write_run(tmp_path, states)
    gapped = run_history.Run(path)
    assert gapped.gaps == [(11, 14)]
    text = render(gapped, "timeline")
    assert "GAP" in text
    # The block spanning the gap must say it covers more than one turn, or a
    # three-turn diff reads as one turn of change.
    assert "covers 3 turns of change" in text


def test_single_file_is_a_valid_run(tmp_path):
    """Degenerate but legal: one turn, no pairs, no crash."""
    path = write_run(tmp_path, [load(0)])
    single = run_history.Run(path)
    assert single.turns == [0]
    assert "nothing changed" in render(single, "timeline")
    render(single, "intel")


def test_empty_folder_is_an_error(tmp_path):
    with pytest.raises(run_history.RunError) as error:
        run_history.Run(str(tmp_path))
    assert "no turn_*.json" in str(error.value)


# -- timeline -------------------------------------------------------------


def test_timeline_reports_tech_completion_on_the_right_turn(run):
    """Derived: find when a tech first appears, assert the timeline says so."""
    turn = first_turn_with(
        lambda s: "TECH_ANIMAL_HUSBANDRY" in s["player"]["knownTechs"]
    )
    text = render(run, "timeline", turn, turn)
    assert "COMPLETED TECH_ANIMAL_HUSBANDRY" in text


def test_timeline_reports_resource_reveal_with_its_tech(run):
    """BONUS_HORSE unhides the same turn Animal Husbandry lands.

    Both facts must be in the SAME block, which is what makes the causation
    readable without the agent joining two files by hand.
    """
    turn = first_turn_with(
        lambda s: any(t.get("bonus") == "BONUS_HORSE" for t in s["map"]["tiles"])
    )
    text = render(run, "timeline", turn, turn)
    assert "RESOURCE NOW VISIBLE: BONUS_HORSE" in text
    assert "COMPLETED TECH_ANIMAL_HUSBANDRY" in text


def test_timeline_reports_city_founding(run):
    turn = first_turn_with(
        lambda s: any(c["name"] == "Oporto" for c in s["cities"])
    )
    text = render(run, "timeline", turn, turn)
    assert "FOUNDED Oporto" in text


def test_timeline_reports_own_unit_loss_by_id(run):
    """Our units have stable ids, so a loss is certain - not a fog artefact."""
    turn = first_turn_with(
        lambda s: not any(u["id"] == 16385 for u in s["units"])
        and s["game"]["gameTurn"] > 36
    )
    text = render(run, "timeline", turn, turn)
    assert "LOST UNIT_WARRIOR (id 16385)" in text


def test_timeline_reports_first_contact(run):
    turn = first_turn_with(
        lambda s: any(c["leader"] == "LEADER_ALEXANDER" for c in s["contacts"])
    )
    text = render(run, "timeline", turn, turn)
    assert "MET LEADER_ALEXANDER" in text


def test_timeline_skips_turns_with_no_change(run):
    """Turn 2 changes nothing in the sample, so it must not get a block."""
    text = render(run, "timeline", 2, 2)
    assert "nothing changed in this turn range" in text


# -- the fog distinction, which is the point of the tool ------------------


def test_departure_under_fog_is_not_reported_as_a_kill(run):
    """Rome's tile fogs at t27, so its garrison reads 'lost sight'.

    Flattening this into 'gone' is how a tool gets a unit killed: the archers
    are still there, we merely stopped looking.
    """
    before, after = load(26), load(27)
    rome = [c for c in before["foreignCities"] if c["name"] == "Rome"][0]
    pos = (rome["x"], rome["y"])
    # Establish the premise from the data rather than trusting it.
    visible_after = any(
        t["x"] == pos[0] and t["y"] == pos[1] and t.get("visibleNow")
        for t in after["map"]["tiles"]
    )
    assert not visible_after, "premise: Rome's tile is fogged at t27"

    archer = [
        u for u in before["foreignUnits"]
        if u["type"] == "UNIT_ARCHER" and (u["x"], u["y"]) == pos
    ][0]
    assert run_history.classify_departure(before, after, archer) == "lost sight"

    text = render(run, "timeline", 27, 27)
    assert "gone from (%d,%d): UNIT_ARCHER" % pos in text
    assert "[lost sight]" in text


def test_departure_on_a_still_visible_tile_reads_as_real(run):
    """The opposite case, from the same turn - both must be distinguishable."""
    before, after = load(26), load(27)
    lion = [
        u for u in before["foreignUnits"]
        if u["type"] == "UNIT_LION" and (u["x"], u["y"]) == (71, 17)
    ][0]
    still_visible = any(
        t["x"] == 71 and t["y"] == 17 and t.get("visibleNow")
        for t in after["map"]["tiles"]
    )
    assert still_visible, "premise: (71,17) is still visible at t27"
    assert run_history.classify_departure(before, after, lion) == "left or died"


def test_moving_unit_gets_a_move_hint_not_a_kill_claim(run):
    """A scout stepping one tile must not read as one unit lost and another found.

    The hint names the coincidence and explicitly refuses to confirm identity,
    because foreignUnits carries no id.
    """
    text = render(run, "timeline", 37, 37)
    assert "probably this unit moving" in text
    assert "no id to confirm it" in text


def test_move_hint_stays_silent_beyond_one_tile(run):
    """A two-tile step gets no hint - the note claims only what it can support."""
    departed = {"owner": 1, "type": "UNIT_SCOUT", "x": 74, "y": 18}
    appeared = [{"owner": 1, "type": "UNIT_SCOUT", "x": 76, "y": 18}]
    assert run_history.probable_move_note(departed, appeared) == ""


def test_move_hint_ignores_a_different_owner(run):
    departed = {"owner": 1, "type": "UNIT_SCOUT", "x": 74, "y": 18}
    appeared = [{"owner": 2, "type": "UNIT_SCOUT", "x": 74, "y": 19}]
    assert run_history.probable_move_note(departed, appeared) == ""


# -- intel ----------------------------------------------------------------


def test_intel_lists_every_unit_type_ever_seen_per_owner(run):
    """Derived: build the expected set straight from the files."""
    expected = {}
    for turn in range(0, 41):
        for unit in load(turn)["foreignUnits"]:
            expected.setdefault(unit["owner"], set()).add(unit["type"])
    sightings = run_history.collect_sightings(run)
    actual = dict((owner, set(types)) for owner, types in sightings.items())
    assert actual == expected


def test_intel_reports_the_archer_that_carries_the_tech_implication(run):
    """The best tech-implication case in the run, per samples/README.md."""
    text = render(run, "intel")
    assert "UNIT_ARCHER" in text
    turn = first_turn_with(
        lambda s: any(u["type"] == "UNIT_ARCHER" for u in s["foreignUnits"])
    )
    assert "first seen t%d" % turn in text
    # It must survive as a capability long after the sighting - the whole point.
    assert run.turns[-1] - turn > 10


def test_intel_separates_barbarians_from_civs(run):
    """Animals imply no tech; putting them in a civ dossier would teach that."""
    text = render(run, "intel")
    barb_section = text.split("BARBARIANS AND ANIMALS")[1]
    assert "UNIT_LION" in barb_section
    assert "UNIT_PANTHER" in barb_section
    # And they must not be attributed to a met civ above.
    civ_section = text.split("BARBARIANS AND ANIMALS")[0]
    assert "UNIT_LION" not in civ_section


def test_intel_collapses_a_stack_into_one_line(run):
    """Two archers on one tile is one line with a count, not a repeated line."""
    turn = first_turn_with(
        lambda s: sum(1 for u in s["foreignUnits"] if u["type"] == "UNIT_ARCHER") > 1
    )
    assert turn is not None, "premise: the sample has a stack of two archers"
    text = render(run, "intel")
    assert "x2 STACKED" in text


def test_intel_attributes_a_sighting_made_before_contact(run):
    """Player 1's units are sighted the same turn contact is made; player 4's
    scout is sighted at t23 having been met at t15. The name lookup spans the
    whole run so an early sighting is never left as a bare player id."""
    text = render(run, "intel")
    assert "LEADER_ALEXANDER (player 4)" in text
    assert "player 4 (never met)" not in text


def test_intel_states_every_fact_with_its_turn(run):
    """The boundary: nothing is presented as current except the latest turn."""
    text = render(run, "intel")
    assert "THE ONLY TURN THAT IS 'NOW'" in text
    assert "not where it is" in text
    assert "never an inventory of what exists" in text


def test_intel_reports_rival_city_with_observation_turn(run):
    text = render(run, "intel")
    latest = load(40)
    rome = [c for c in latest["foreignCities"] if c["name"] == "Rome"][0]
    assert "Rome" in text
    assert "pop %d as of t40" % rome["population"] in text


def test_intel_ignores_turn_range(run, capsys):
    """A truncated dossier would drop the earliest sighting, which is the fact
    that proves a capability - so the range is refused rather than applied."""
    assert run_history.main([SAMPLE_DIR, "--view", "intel", "--from", "30"]) == 0
    captured = capsys.readouterr()
    assert "ignored for --view intel" in captured.err
    turn = first_turn_with(
        lambda s: any(u["type"] == "UNIT_ARCHER" for u in s["foreignUnits"])
    )
    assert turn < 30
    assert "UNIT_ARCHER" in captured.out


# -- output contract ------------------------------------------------------


# -- settler consumed vs killed -------------------------------------------


def test_settler_consumed_founding_is_not_reported_as_a_loss(run):
    """Two trials read `LOST UNIT_SETTLER` as a casualty. It founded a city."""
    turn = first_turn_with(lambda s: any(c["name"] == "Oporto" for c in s["cities"]))
    text = render(run, "timeline", turn, turn)
    assert "FOUNDED Oporto" in text
    assert "NOT a casualty" in text
    assert "LOST UNIT_SETTLER" not in text


def test_a_real_unit_death_is_still_reported_as_lost(run):
    """The distinction only helps if genuine losses keep the strong word."""
    turn = first_turn_with(
        lambda s: s["game"]["gameTurn"] > 36
        and not any(u["id"] == 16385 for u in s["units"])
    )
    text = render(run, "timeline", turn, turn)
    assert "LOST UNIT_WARRIOR (id 16385)" in text
    assert "NOT a casualty" not in text


def test_ambiguous_settler_pairing_is_refused():
    """Two settlers gone and two cities founded cannot be paired safely."""
    settlers = [
        {"id": 1, "type": "UNIT_SETTLER", "x": 0, "y": 0},
        {"id": 2, "type": "UNIT_SETTLER", "x": 5, "y": 5},
    ]
    founded = [{"name": "A", "x": 1, "y": 1}, {"name": "B", "x": 6, "y": 6}]
    pairs, unmatched = run_history.pair_settlers_with_foundings(settlers, founded)
    assert pairs == []
    assert unmatched == settlers


def test_pairing_ignores_position(run):
    """The settler moves then founds, so its last position is NOT the city tile."""
    settler = [{"id": 9, "type": "UNIT_SETTLER", "x": 77, "y": 15}]
    founded = [{"name": "Oporto", "x": 78, "y": 14}]
    pairs, unmatched = run_history.pair_settlers_with_foundings(settler, founded)
    assert len(pairs) == 1 and unmatched == []


def test_a_settler_lost_with_no_founding_is_a_real_loss():
    settler = [{"id": 9, "type": "UNIT_SETTLER", "x": 3, "y": 3}]
    pairs, unmatched = run_history.pair_settlers_with_foundings(settler, [])
    assert pairs == [] and unmatched == settler


# -- --as-of ---------------------------------------------------------------


def test_as_of_discards_later_turns(run):
    clamped = run_history.Run(SAMPLE_DIR, as_of=34)
    assert clamped.turns[-1] == 34
    assert clamped.as_of == 34


def test_as_of_hides_the_future_from_intel():
    """The failure it fixes: a dossier headed t40 for a question set at t34.

    Rome is pop 5 at t34 and pop 3 at t40, so the clamped run must report 5 -
    and the t35-40 scout swarm must be absent entirely.
    """
    clamped = run_history.Run(SAMPLE_DIR, as_of=34)
    text = render(clamped, "intel")
    assert "pop 5 as of t34" in text
    assert "t40" not in text
    assert "pop 3" not in text


def test_as_of_applies_to_timeline_too(run):
    clamped = run_history.Run(SAMPLE_DIR, as_of=20)
    text = render(clamped, "timeline")
    assert "TURN 21" not in text
    assert "clamped to t20" in text


def test_as_of_before_the_run_starts_is_an_error():
    with pytest.raises(run_history.RunError):
        run_history.Run(SAMPLE_DIR, as_of=-1)


def test_as_of_from_the_cli(capsys):
    assert run_history.main([SAMPLE_DIR, "--view", "intel", "--as-of", "26"]) == 0
    out = capsys.readouterr().out
    assert "clamped to t26" in out
    assert "t27" not in out


# -- barbarian positions ---------------------------------------------------


def test_barbarian_sightings_carry_positions(run):
    """Animals are the early-game threat; a count with no coordinates is useless."""
    text = render(run, "intel")
    barb = text.split("BARBARIANS AND ANIMALS")[1]
    expected = set()
    for turn in range(0, 41):
        for unit in load(turn)["foreignUnits"]:
            if unit["owner"] == 18:
                expected.add((unit["x"], unit["y"]))
    assert expected, "premise: the sample has barbarian sightings"
    for x, y in expected:
        assert "(%d,%d)" % (x, y) in barb


def test_barbarian_positions_are_qualified_as_stale(run):
    text = render(run, "intel")
    barb = text.split("BARBARIANS AND ANIMALS")[1]
    assert "where it WAS on that turn" in barb


# -- distance and garrisons ------------------------------------------------


def test_chebyshev_is_wrap_aware():
    state = load(40)
    width = state["game"]["mapWidth"]
    assert state["game"]["wrapX"], "premise: this map wraps in x"
    # Two tiles either side of the seam are adjacent, not width-1 apart.
    assert run_history.chebyshev(state, (0, 10), (width - 1, 10)) == 1
    assert run_history.chebyshev(state, (75, 15), (69, 31)) == 16


def test_sightings_carry_distance_from_your_nearest_city(run):
    text = render(run, "intel")
    assert "from Lisbon" in text


def test_no_distance_note_before_any_city_exists():
    """turn_0000 has no cities, so there is nothing to measure from."""
    state = load(0)
    assert not state["cities"]
    assert run_history.nearest_city_note(None, state, (10, 10)) == ""


def test_garrison_section_lists_what_is_in_each_city(run):
    """Three trials derived this by hand from units-vs-cities coordinates."""
    text = render(run, "intel")
    section = text.split("YOUR CITIES AND WHAT IS STANDING IN THEM")[1]
    latest = load(40)
    for city in latest["cities"]:
        assert city["name"] in section
    # At t40 both cities are empty and the warrior is in the field.
    assert "nothing standing in it" in section
    assert "in the field" in section


def test_garrison_section_refuses_to_judge(run):
    """A count, never a verdict - reachability is not computable from the export."""
    text = render(run, "intel")
    section = text.split("YOUR CITIES AND WHAT IS STANDING IN THEM")[1]
    assert "A count, not a verdict" in section
    assert "UNDEFENDED" not in section.upper().replace("NOTHING STANDING", "")


def test_garrison_section_finds_a_unit_inside_a_city():
    """t34: the settler is standing in Lisbon."""
    clamped = run_history.Run(SAMPLE_DIR, as_of=34)
    text = render(clamped, "intel")
    section = text.split("YOUR CITIES AND WHAT IS STANDING IN THEM")[1]
    assert "SETTLER" in section


@pytest.mark.parametrize("view", run_history.VIEWS)
def test_every_view_states_what_it_omits(run, view):
    assert "THIS VIEW OMITS" in render(run, view)


@pytest.mark.parametrize("view", run_history.VIEWS)
def test_every_view_is_ascii(run, view):
    """stdout is cp1252 on the machine this repo lives on."""
    render(run, view).encode("ascii")


@pytest.mark.parametrize("view", run_history.VIEWS)
def test_main_runs_each_view_from_the_cli(view, capsys):
    assert run_history.main([SAMPLE_DIR, "--view", view]) == 0
    assert capsys.readouterr().out.strip()


def test_main_exits_nonzero_on_a_broken_run(tmp_path, capsys):
    a, b = load(5), copy.deepcopy(load(6))
    b["game"]["climate"] = "CLIMATE_ARID"
    path = write_run(tmp_path, [a, b])
    assert run_history.main([path, "--view", "timeline"]) == 2
    assert "run_history:" in capsys.readouterr().err


def test_main_rejects_a_missing_run(capsys):
    assert run_history.main([os.path.join(SAMPLE_DIR, "nope")]) == 2
