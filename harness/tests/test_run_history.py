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

# Derived, not quoted. The sample was extended from 41 turns to 44 and five
# hardcoded `range(0, 41)` literals broke - the exact failure this file's
# docstring says landmarks are derived to prevent. Counting the files instead
# means the next extension needs no edit here.
SAMPLE_TURNS = sorted(
    int(name[len("turn_"):-len(".json")])
    for name in os.listdir(SAMPLE_DIR)
    if name.startswith("turn_") and name.endswith(".json")
)
LAST_TURN = SAMPLE_TURNS[-1]


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


def render_single(tmp_path, state, view):
    """Render one mutated state as a whole (single-turn) run."""
    path = write_run(tmp_path, [state])
    run_obj = run_history.Run(path)
    return render(run_obj, view)


# -- landmarks derived from the sample ------------------------------------


def first_turn_with(predicate):
    """The earliest sample turn satisfying `predicate`, or None."""
    for turn in SAMPLE_TURNS:
        if predicate(load(turn)):
            return turn
    return None


def test_sample_run_loads_and_is_continuous(run):
    assert len(run.states) == len(SAMPLE_TURNS)
    assert run.turns == SAMPLE_TURNS
    assert run.gaps == []


def test_sample_has_one_setup_signature():
    """The guard's whole premise: one game means one unchanging setup."""
    signatures = set(
        run_history.setup_signature(load(turn)) for turn in SAMPLE_TURNS
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


def test_timeline_reports_rival_territory_first_seen(run):
    """Greek borders at (66,32-34) were the first evidence of a Greek city.

    (mapHeight 52, so new y = 51 - old y - was (66,17-19).)
    They arrive ALREADY OWNED on the turn the tiles are first revealed, so an
    owner-change diff never fires - which is why this needed its own branch.
    """
    text = render(run, "timeline", 35, 36)
    assert "TERRITORY FIRST SEEN" in text
    assert "LEADER_ALEXANDER" in text
    assert "(66,32)" in text


def test_rival_territory_hints_at_a_city(run):
    text = render(run, "timeline", 35, 35)
    assert "a border implies a city within" in text


def test_own_territory_is_not_reported_as_rival(run):
    """Founding Oporto claims tiles; they must not read as a rival's."""
    text = render(run, "timeline", 36, 36)
    rival_lines = [l for l in text.split("\n") if "TERRITORY FIRST SEEN" in l]
    for line in rival_lines:
        assert "you" not in line


def test_small_reveals_list_their_coordinates(run):
    """The five tiles revealed at t38 are the evidence for where a unit died."""
    text = render(run, "timeline", 38, 38)
    # mapHeight 52, so new y = 51 - old y (were (69,15),(69,16),(70,15),(70,16),(71,19)).
    for pos in ("(69,36)", "(69,35)", "(70,36)", "(70,35)", "(71,32)"):
        assert pos in text


def test_large_reveals_stay_a_count(run):
    """A 48-tile scouting sweep is not evidence and would bury the block."""
    turn = first_turn_with(lambda s: s["game"]["gameTurn"] == 1)
    text = render(run, "timeline", 1, 1)
    assert "48 tile(s) newly revealed" in text
    assert "(75,13), (75,14)" not in text


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
    # mapHeight 52, so new y = 51 - old y (was (71,17)).
    before, after = load(26), load(27)
    lion = [
        u for u in before["foreignUnits"]
        if u["type"] == "UNIT_LION" and (u["x"], u["y"]) == (71, 34)
    ][0]
    still_visible = any(
        t["x"] == 71 and t["y"] == 34 and t.get("visibleNow")
        for t in after["map"]["tiles"]
    )
    assert still_visible, "premise: (71,34) is still visible at t27"
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
    for turn in SAMPLE_TURNS:
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
    """Derived from the last turn Rome is actually reported, not a fixed turn.

    This pinned t40 and broke when the sample was extended to t43 - Rome is
    still observed there, so the dossier correctly moved on while the test
    stayed behind. The reported turn is the provenance of the population
    figure, so it has to track the newest observation.
    """
    text = render(run, "intel")
    seen = [(turn, city)
            for turn in SAMPLE_TURNS
            for city in load(turn).get("foreignCities", [])
            if city["name"] == "Rome"]
    assert seen, "sample should contain observations of Rome"
    last_turn, rome = seen[-1]
    assert "Rome" in text
    assert "pop %d as of t%d" % (rome["population"], last_turn) in text


# -- production history ----------------------------------------------------


def production_changes():
    """Every (turn, city name, from, to) production change in the sample."""
    changes = []
    for prev, turn in zip(SAMPLE_TURNS, SAMPLE_TURNS[1:]):
        was = dict((c["id"], c) for c in load(prev)["cities"])
        now = dict((c["id"], c) for c in load(turn)["cities"])
        for city_id in sorted(set(was) & set(now)):
            old, new = was[city_id], now[city_id]
            if old.get("producing") != new.get("producing"):
                changes.append(
                    (turn, new["name"], old.get("producing"), new.get("producing"))
                )
    return changes


def test_timeline_reports_every_production_change_in_the_sample():
    """No change in what a city is building may pass unreported.

    Derived rather than spot-checked: 4 of 6 trials went to raw JSON for this,
    so the guarantee that matters is completeness, not that one known line
    renders.
    """
    text = render(run_history.Run(SAMPLE_DIR), "timeline")
    changes = production_changes()
    assert changes, "sample should contain production changes"
    for turn, name, _was, became in changes:
        expected = "nothing" if became is None else became.split("_", 1)[1]
        block = [line for line in text.splitlines() if name in line and expected in line]
        assert block, "t%d %s -> %s went unreported" % (turn, name, became)


def test_timeline_reports_the_mind_changed_twice_case(run):
    """The sharpest production fact in the run, and the item's motivating case.

    Lisbon abandons a Worker at 27/60 for a Warrior, then returns to that same
    Worker two turns later at 39/60 - the banked hammers were never lost. It is
    derived here rather than quoted: find a city that switches AWAY from
    something and back to it within a few turns.
    """
    changes = production_changes()
    revisited = None
    for i, (turn, name, was, became) in enumerate(changes):
        # Both ends must be real builds: a completion empties the queue and the
        # next choice reads as (None -> X), which is not a change of mind.
        if was is None or became is None:
            continue
        for later_turn, later_name, later_was, later_became in changes[i + 1:]:
            if later_name == name and later_became == was:
                revisited = (turn, later_turn, name, was, became)
                break
        if revisited:
            break
    assert revisited, "sample should contain a build abandoned and resumed"
    turn, later_turn, name, original, detour = revisited

    text = render(run, "timeline")
    lines = text.splitlines()
    away = [l for l in lines if name in l and "SWITCHED" in l
            and original.split("_", 1)[1] in l and detour.split("_", 1)[1] in l]
    assert away, "the switch away from %s was not reported as a decision" % original

    # And the resumption carries the banked total forward rather than resetting.
    before = [c for c in load(turn - 1)["cities"] if c["name"] == name][0]
    after = [c for c in load(later_turn)["cities"] if c["name"] == name][0]
    assert after["production"] > before["production"], (
        "sample premise: banked hammers should survive the detour"
    )
    back = [l for l in lines if name in l and str(after["production"]) in l]
    assert back, "the resumed build did not report its carried-forward total"


def test_timeline_calls_a_switch_a_decision_not_a_completion(run):
    """A falling production total does NOT mean the previous item finished.

    Switching from a Worker at 27/60 to a Warrior at 2/15 drops the total
    exactly as a completion would; the sample contains that case and the unit
    never arrived. Completion is claimed only when the item shows up in the
    turn's gains, so this asserts the two are not conflated.
    """
    text = render(run, "timeline")
    for turn, name, was, became in production_changes():
        if was is None or became is None:
            continue
        gained = set(u["type"] for u in run_history.diff_own_units(
            load(turn - 1), load(turn))[0])
        if was in gained:
            continue
        def buildings_of(t):
            for c in load(t)["cities"]:
                if c["name"] == name:
                    return set(c.get("buildings") or [])
            return set()
        if was in buildings_of(turn) - buildings_of(turn - 1):
            continue
        block = [l for l in text.splitlines()
                 if name in l and "SWITCHED" in l and was.split("_", 1)[1] in l]
        assert block, "t%d %s switch was not reported" % (turn, name)
        assert "COMPLETED" not in block[0], (
            "t%d: %s did not arrive, so this is a decision, not a completion"
            % (turn, was)
        )


def test_timeline_reports_a_completion_that_empties_the_queue(run):
    """The commonest production event of all: the item arrives, queue empties.

    Reading that as "STOPPED building" would mislabel most completions in a
    run, so it is asserted directly.
    """
    text = render(run, "timeline")
    found = False
    for turn, name, was, became in production_changes():
        if became is not None or was is None:
            continue
        gained = set(u["type"] for u in run_history.diff_own_units(
            load(turn - 1), load(turn))[0])
        if was not in gained:
            continue
        found = True
        block = [l for l in text.splitlines()
                 if name in l and "COMPLETED" in l and was.split("_", 1)[1] in l]
        assert block, "t%d completion of %s was not reported" % (turn, was)
    assert found, "sample should contain a completion that empties the queue"


def test_timeline_reports_a_completed_building(run, tmp_path):
    """No sample turn finishes a building, so this path is built synthetically.

    It works only because `producing` and `cities[].buildings` are both
    `BUILDING_` form. The top-level `wonders` section is deliberately not
    consulted (it is `BUILDINGCLASS_` keyed and reports rivals' builds too), so
    this asserts the join that IS used.
    """
    before = copy.deepcopy(load(LAST_TURN - 1))
    after = copy.deepcopy(load(LAST_TURN))
    name = before["cities"][0]["name"]
    for state, producing in ((before, "BUILDING_BARRACKS"), (after, "UNIT_WARRIOR")):
        city = [c for c in state["cities"] if c["name"] == name][0]
        city["producing"] = producing
        city["productionNeeded"] = 60
    kept = [c for c in before["cities"] if c["name"] == name][0]
    built = [c for c in after["cities"] if c["name"] == name][0]
    kept["buildings"] = ["BUILDING_PALACE"]
    built["buildings"] = ["BUILDING_PALACE", "BUILDING_BARRACKS"]

    path = write_run(tmp_path, [before, after])
    text = render(run_history.Run(path), "timeline")
    line = [l for l in text.splitlines() if name in l and "BARRACKS" in l]
    assert line, "the completed building was not reported"
    assert "COMPLETED" in line[0], line[0]


def test_timeline_does_not_credit_a_rival_wonder_to_your_city(run, tmp_path):
    """`wonders` reports builds from ANYWHERE, so it must not settle this."""
    before = copy.deepcopy(load(LAST_TURN - 1))
    after = copy.deepcopy(load(LAST_TURN))
    name = before["cities"][0]["name"]
    for state, producing in ((before, "BUILDING_PYRAMIDS"), (after, "UNIT_WARRIOR")):
        city = [c for c in state["cities"] if c["name"] == name][0]
        city["producing"] = producing
        city["productionNeeded"] = 300
    # A rival finished it: it appears in the global list, never in our city.
    after["wonders"] = dict(after.get("wonders") or {})
    after["wonders"]["built"] = ["BUILDINGCLASS_PYRAMIDS"]

    path = write_run(tmp_path, [before, after])
    text = render(run_history.Run(path), "timeline")
    line = [l for l in text.splitlines() if name in l and "PYRAMIDS" in l]
    assert line, "the abandoned wonder was not reported"
    assert "COMPLETED" not in line[0], (
        "a wonder built elsewhere must not read as our completion: %s" % line[0]
    )


def test_intel_reports_what_each_city_is_building(run):
    """The join 4 of 6 trials made by hand after being told a city was empty."""
    text = render(run, "intel")
    for city in run.latest()["cities"]:
        assert city["name"] in text
        order = city.get("producing")
        expected = "NOTHING QUEUED" if order is None else order.split("_", 1)[1]
        assert expected in text, "%s's current build is missing" % city["name"]


def test_intel_turns_to_complete_matches_the_arithmetic(run):
    """The ETA is checked against the fields, not against a remembered number."""
    text = render(run, "intel")
    for city in run.latest()["cities"]:
        turns = run_history.turns_to_complete(city)
        if turns is None or turns == 0:
            continue
        assert "~%d turn(s)" % turns in text


def test_turns_to_complete_refuses_to_answer_when_it_cannot():
    """An empty queue, a process and a stalled city all have no honest number.

    `productionNeeded` is None for both an empty queue and a process, and a
    city producing nothing per turn would need "never" - any integer there
    would be a lie.
    """
    assert run_history.turns_to_complete({"productionNeeded": None}) is None
    assert run_history.turns_to_complete(
        {"productionNeeded": 60, "production": 10, "productionPerTurn": 0}
    ) is None
    assert run_history.turns_to_complete(
        {"productionNeeded": 60, "production": 10, "productionPerTurn": 5}
    ) == 10


def test_intel_flags_a_food_fed_build_as_stopping_growth(run, tmp_path):
    """The growth cost is a Findings entry - under-weighted by a live trial -
    so where the export carries the split, the view states it."""
    state = copy.deepcopy(run.latest())
    assert state["cities"], "sample should have cities"
    city = state["cities"][0]
    city["producing"] = "UNIT_SETTLER"
    city["productionNeeded"] = 100
    city["production"] = 10
    city["productionFromFood"] = 6
    city["productionFromHammers"] = 7
    city["productionPerTurn"] = 13
    text = render_single(tmp_path, state, "intel")
    assert "growth is stopped" in text


def test_intel_says_plainly_when_a_city_is_building_nothing(run, tmp_path):
    """An empty queue in an empty city is sharper than either fact alone."""
    state = copy.deepcopy(run.latest())
    city = state["cities"][0]
    city["producing"] = None
    city["productionNeeded"] = None
    text = render_single(tmp_path, state, "intel")
    assert "NOTHING QUEUED" in text


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
    for turn in SAMPLE_TURNS:
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
    assert "of Lisbon" in text


def test_sightings_carry_a_compass_bearing(run):
    """Ten trials narrated north/south backwards; the tool states it now."""
    text = render(run, "intel")
    # Rome and Lisbon's y both flipped with the schemaVersion 2 migration
    # (higher y is now SOUTH), and so did the bearing sign, so the physical
    # NNW relationship between them is unchanged.
    assert "NNW of Lisbon" in text


def test_bearing_matches_the_axis_convention():
    # Pure geometry - these are arbitrary points, not tied to sample tiles, so
    # only the N/S sign changes (higher y is now SOUTH, schemaVersion 2 - see
    # AdvisorStateWriter._invertY); the points themselves are unchanged.
    state = load(40)
    lisbon = (75, 15)
    assert run_history.bearing(state, lisbon, (75, 31)) == "S"
    assert run_history.bearing(state, lisbon, (75, 5)) == "N"
    assert run_history.bearing(state, lisbon, (79, 15)) == "E"
    assert run_history.bearing(state, lisbon, (69, 15)) == "W"
    assert run_history.bearing(state, lisbon, (69, 31)) == "SSW"
    assert run_history.bearing(state, lisbon, (76, 16)) == "SE"
    assert run_history.bearing(state, lisbon, lisbon) == ""


def test_bearing_dominant_axis_leads():
    """WSW, not SWW - the major axis comes first, as on a real compass."""
    # Pure geometry - only the N/S sign changes (see above).
    state = load(40)
    assert run_history.bearing(state, (75, 15), (69, 17)) == "WSW"
    assert run_history.bearing(state, (75, 15), (69, 13)) == "WNW"


def test_bearing_is_wrap_aware():
    state = load(40)
    width = state["game"]["mapWidth"]
    assert state["game"]["wrapX"]
    # One tile east across the seam is EAST, not width-1 tiles west.
    assert run_history.bearing(state, (width - 1, 20), (0, 20)) == "E"


def test_land_path_reports_the_detour_chebyshev_hides(run):
    """The measured case: a lion 6 tiles away is a 14-step walk around a bay.

    Two trials found this independently and both called the bare Chebyshev
    figure the most misleading number they were given.
    """
    # mapHeight 52, so new y = 51 - old y (were (75,15), (69,21)).
    state = load(34)
    lisbon = (75, 36)
    lion = (69, 30)
    assert run_history.chebyshev(state, lion, lisbon) == 6
    steps, _ = run_history.land_path(state, lion, lisbon)
    assert steps == 14


def test_land_distance_is_shown_when_it_differs(run):
    clamped = run_history.Run(SAMPLE_DIR, as_of=34)
    text = render(clamped, "intel")
    assert "14 TO WALK" in text
    assert "(only 6 straight)" in text


def test_every_distance_line_states_the_unit_of_measurement():
    """A bare '12 NNW of Lisbon' beside '14 TO WALK NNW (12 straight)' left two
    trials unsure which figure the bare form meant. Every line now says 'walk'."""
    clamped = run_history.Run(SAMPLE_DIR, as_of=34)
    text = render(clamped, "intel")
    checked = 0
    for line in text.splitlines():
        if " of Lisbon" in line and "NO LAND ROUTE" not in line:
            assert "to walk" in line.lower(), line
            checked += 1
    assert checked > 5, "expected several distance lines to check"


def test_land_path_refuses_to_route_through_fog():
    """Unrevealed tiles are never walked; they are counted as unknowns."""
    # mapHeight 52, so new y = 51 - old y (were (75,15), (69,21)).
    state = load(34)
    steps, gaps = run_history.land_path(state, (75, 36), (69, 30))
    assert steps == 14
    assert gaps > 0, "the revealed region should border unrevealed tiles"


def test_land_path_none_when_separated_by_water():
    state = load(34)
    tiles = {(t["x"], t["y"]): t for t in state["map"]["tiles"]}
    water = [p for p, t in tiles.items() if t.get("plotType") == "PLOT_OCEAN"]
    assert water, "premise: the sample has water"
    steps, _ = run_history.land_path(state, (75, 15), water[0])
    assert steps is None


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


# -- loss reporting --------------------------------------------------------


def test_loss_line_says_last_exported_not_last_position(run):
    """'last at' read as the death tile to two trials. It is not."""
    text = render(run, "timeline", 38, 38)
    # mapHeight 52, so new y = 51 - old y (was (69,18)).
    assert "last exported at (69,33) on t37" in text
    assert "may have moved before dying" in text


def test_loss_line_carries_distance_and_bearing(run):
    """Rival sightings had this; our own unit's death did not."""
    text = render(run, "timeline", 38, 38)
    assert "WNW of Lisbon" in text
    # The walk leads when it differs; the straight line becomes the aside.
    assert "TO WALK" in text
    assert "(only 6 straight)" in text


def test_lost_view_reports_the_warrior(run):
    text = render(run, "lost")
    assert "UNIT_WARRIOR id 16385" in text
    assert "gone from the turn 38 export" in text


def test_lost_view_gives_the_track(run):
    """The path leading up to a loss is what makes it interpretable."""
    text = render(run, "lost")
    # mapHeight 52, so new y = 51 - old y (were (69,18), (68,21)).
    assert "t37 (69,33)" in text
    assert "t34 (68,30)" in text


def test_lost_view_reports_damage_history(run):
    """This warrior was hurt at t16 and healed - a hand-scripted sweep before."""
    text = render(run, "lost")
    assert "t16 30%" in text


def test_lost_view_gives_the_final_turn_reveals(run):
    """The evidence a trial used to locate the real death tile."""
    text = render(run, "lost")
    # mapHeight 52, so new y = 51 - old y (were (69,15), (70,16), (71,19)).
    for pos in ("(69,36)", "(70,35)", "(71,32)"):
        assert pos in text


def test_lost_view_lists_what_was_in_sight(run):
    text = render(run, "lost")
    assert "UNIT_LION" in text
    assert "BARBARIANS" in text


def test_lost_view_refuses_to_name_a_killer(run):
    """It presents evidence and stops - the export has no combat log."""
    text = render(run, "lost")
    assert "NOTHING here says what killed it" in text
    assert "killed by" not in text.lower()


def test_lost_view_excludes_settlers_consumed_founding(run):
    """Two settlers vanish in this run; both founded cities."""
    text = render(run, "lost")
    assert "1 unit(s) of yours disappeared" in text
    assert "UNIT_SETTLER" not in text


def test_lost_view_warns_that_range_flags_are_ignored(capsys):
    """Silently accepting a flag that does nothing is worse than rejecting it.

    `lost` spans the whole run by design - a loss report scoped to a window
    would hide the track that led into it - but the caller must be told.
    """
    assert run_history.main([SAMPLE_DIR, "--view", "lost", "--from", "20"]) == 0
    assert "ignored for --view lost" in capsys.readouterr().err


def test_lost_view_when_nothing_was_lost():
    clamped = run_history.Run(SAMPLE_DIR, as_of=30)
    text = render(clamped, "lost")
    assert "No unit of yours has disappeared" in text


# -- non-combat garrison flag ---------------------------------------------


def test_garrison_flags_a_non_combat_occupant():
    """`Lisbon SETTLER` read as defended to two trials. A settler is combat 0."""
    clamped = run_history.Run(SAMPLE_DIR, as_of=34)
    text = render(clamped, "intel")
    assert "[NON-COMBAT]" in text
    assert "nothing here can defend" in text


def test_garrison_does_not_flag_a_real_defender(run):
    """A warrior in a city must not be marked non-combat."""
    assert "UNIT_WARRIOR" not in run_history.NON_COMBAT_UNITS
    assert "UNIT_SETTLER" in run_history.NON_COMBAT_UNITS


# -- promotion/XP visibility ------------------------------------------------
#
# Roadmap item 3's motivating case: a scout took two promotions from a Lion
# fight and the agent could not see it from the export - it only knew because
# the player mentioned it. samples/baseline-early-game predates schema
# increment 7 (no unit ever carries promotions/experience), so these mutate a
# loaded turn rather than reading it as-is, the same pattern the Run-validation
# tests above use.


def test_garrison_shows_promotions_on_a_defender(tmp_path):
    state = copy.deepcopy(load(34))
    warrior = next(u for u in state["units"] if u["type"] == "UNIT_WARRIOR")
    warrior["x"], warrior["y"] = 75, 36  # Lisbon's coordinates at t34.
    warrior["promotions"] = ["PROMOTION_COMBAT1", "PROMOTION_COMBAT2"]
    text = render_single(tmp_path, state, "intel")
    section = text.split("YOUR CITIES AND WHAT IS STANDING IN THEM")[1]
    assert "[COMBAT1, COMBAT2]" in section


def test_garrison_shows_promotions_available_without_a_pick_yet(tmp_path):
    """promotionsAvailable, not just promotions - a unit can be one fight away
    from its first promotion with none yet in the list."""
    state = copy.deepcopy(load(34))
    warrior = next(u for u in state["units"] if u["type"] == "UNIT_WARRIOR")
    warrior["x"], warrior["y"] = 75, 36
    warrior["promotionsAvailable"] = 1
    text = render_single(tmp_path, state, "intel")
    section = text.split("YOUR CITIES AND WHAT IS STANDING IN THEM")[1]
    assert "[1 promotion available]" in section


def test_garrison_omits_the_note_for_an_unpromoted_unit(run):
    """Field-level omission upstream (see schema) means most units carry
    neither key at all - the common case must add nothing to the line."""
    clamped = run_history.Run(SAMPLE_DIR, as_of=34)
    text = render(clamped, "intel")
    section = text.split("YOUR CITIES AND WHAT IS STANDING IN THEM")[1]
    lisbon_line = next(line for line in section.splitlines() if "Lisbon" in line)
    assert "[" not in lisbon_line.replace("[NON-COMBAT]", "")


def test_field_unit_shows_promotions_too(tmp_path):
    """The note applies outside cities as well as inside them."""
    state = copy.deepcopy(load(34))
    warrior = next(u for u in state["units"] if u["type"] == "UNIT_WARRIOR"
                   and u["x"] != 75)
    warrior["promotions"] = ["PROMOTION_COMBAT1"]
    text = render_single(tmp_path, state, "intel")
    section = text.split("YOUR CITIES AND WHAT IS STANDING IN THEM")[1]
    assert "[COMBAT1]" in section


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
