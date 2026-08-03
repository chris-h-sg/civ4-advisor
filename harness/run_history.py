"""Read a whole run of civ4-advisor state files and report across turns.

`mod/` writes one full snapshot per turn and each snapshot is deliberately
forgetful - `foreignUnits` reports only units standing on a CURRENTLY VISIBLE
tile, so a rival Axeman seen on turn 14 is simply absent from turn 15. The
sequence is what restores the memory a human player keeps. Answering "what has
Rome ever fielded" from the raw files means reading every one of them, which is
expensive enough that it does not happen reliably.

Two views:

    timeline  what changed, turn by turn
    intel     what is known about each rival, and when it was learned

THE BOUNDARY THIS TOOL IS BUILT ON: a past turn is evidence about the past, not
current state. Every fact below is printed with the turn it was observed and is
never restated as though it were still true. A city that was size 3 on turn 14
is not size 3 now.

Run it directly with the system Python; stdlib only, no setup:

    python harness/run_history.py samples/baseline-early-game --view intel
"""

import argparse
import glob
import json
import os
import sys

VIEWS = ("timeline", "intel")

# Fields on a map tile whose turn-to-turn change is worth reporting. Terrain is
# deliberately absent: it never changes, so a change would mean the run is broken,
# and the continuity check owns that. `visibleNow` is absent because it flips
# constantly by design - it is the fog, not a change in the world.
TRACKED_TILE_FIELDS = ("improvement", "route", "owner", "bonus", "feature")

# How a tracked field's change should be described. The engine has several distinct
# mechanisms that all surface as "this field differs from last turn", and collapsing
# them would invent causes the export cannot support.
TILE_CHANGE_LABEL = {
    "owner": "territory",
    "improvement": "improvement",
    "route": "route",
    "bonus": "RESOURCE NOW VISIBLE",
    "feature": "feature",
}


class RunError(Exception):
    """The run is not a single continuous game, so no view can be trusted."""


# -- loading and continuity ----------------------------------------------


def turn_files(path):
    """Every turn file in a run folder, ORDERED BY FILENAME.

    Never by mtime: loading a save re-exports that turn over its existing file,
    so timestamps within a run are not monotonic, and git does not preserve them
    anyway - a fresh clone restamps everything at checkout.
    """
    if os.path.isfile(path):
        return [path]
    if not os.path.isdir(path):
        raise RunError("no such run folder or state file: %s" % path)
    found = sorted(glob.glob(os.path.join(path, "turn_*.json")))
    if not found:
        raise RunError(
            "no turn_*.json files in %s - point this at a run FOLDER (the whole"
            " game), not at a single turn" % path
        )
    return found


def setup_signature(state):
    """The game-setup facts that must be identical across one game.

    These are chosen at the setup screen and cannot change while a game is played,
    so any disagreement means two different games' files are sitting in one folder.
    Deliberately NOT including anything that legitimately varies: era advances,
    year and gameTurn move, and options is a list so it is compared as a tuple.
    """
    game = state["game"]
    return (
        game["mapScript"], game["worldSize"], game["climate"], game["seaLevel"],
        game["handicap"], game["totalCivs"], game["gameSpeed"],
        game["mapWidth"], game["mapHeight"], game["wrapX"], game["wrapY"],
        tuple(game["options"]), tuple(game["victories"]),
        state["player"]["id"], state["player"]["leader"],
        state["player"]["civilization"],
    )


def describe_signature_mismatch(first, other):
    names = (
        "mapScript", "worldSize", "climate", "seaLevel", "handicap", "totalCivs",
        "gameSpeed", "mapWidth", "mapHeight", "wrapX", "wrapY", "options",
        "victories", "player id", "leader", "civilization",
    )
    out = []
    for name, a, b in zip(names, first, other):
        if a != b:
            out.append("%s %r != %r" % (name, a, b))
    return "; ".join(out)


class Run(object):
    """A loaded run: every turn file, checked for continuity before use.

    The check runs in the constructor rather than being offered as a separate
    command, because a precondition the caller has to remember is one that gets
    skipped - and this is exactly the tool that gets fooled by a broken run.
    """

    def __init__(self, path, as_of=None):
        self.path = path
        self.states = []
        for filename in turn_files(path):
            with open(filename, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.states.append((filename, state))

        # --as-of clamps the WHOLE run, not one view's output. Live play never needs
        # it (the newest file is the current turn), but replaying a finished run to
        # a past turn otherwise leaks the future into every view at once: `intel`
        # would report sightings that have not happened and its header would assert
        # they are current. Dropping the files outright is the only version of this
        # that cannot leak, since nothing downstream can reach a state that is not
        # loaded.
        self.as_of = as_of
        if as_of is not None:
            kept = [s for s in self.states if s[1]["game"]["gameTurn"] <= as_of]
            if not kept:
                raise RunError(
                    "--as-of %d leaves no turns: this run starts at turn %d."
                    % (as_of, self.states[0][1]["game"]["gameTurn"])
                )
            self.states = kept

        self.gaps = []
        self._check_continuity()

        first = self.states[0][1]
        self.setup = first["game"]
        self.player_id = first["player"]["id"]
        self.leader = first["player"]["leader"]
        self.turns = [s["game"]["gameTurn"] for _, s in self.states]

    def _check_continuity(self):
        """Refuse a run that is not one continuous game.

        Save-scumming into a different branch is out of scope: reloading an older
        save rewrites that turn and leaves later files from the abandoned timeline
        behind, producing a folder that looks continuous but is not. Rather than
        report and work around it, this exits - advice built across two timelines
        contradicts itself in ways nothing in the data explains.

        GAPS ARE LEGAL AND ARE NOT AN ERROR. A failed export is logged and skipped
        rather than crashing the game, so a run can legitimately be missing a turn.
        They are recorded and labelled at the point of use instead, because a diff
        spanning a gap covers more than one turn of change.
        """
        signature = None
        previous = None
        for filename, state in self.states:
            turn = state["game"]["gameTurn"]

            current = setup_signature(state)
            if signature is None:
                signature = current
            elif current != signature:
                raise RunError(
                    "%s is from a DIFFERENT GAME than the first file in this run:"
                    " %s.\nOne run folder must hold one game."
                    % (filename, describe_signature_mismatch(signature, current))
                )

            if previous is not None:
                self._check_against_previous(filename, state, turn, previous)
            previous = (filename, state, turn)

    def _check_against_previous(self, filename, state, turn, previous):
        prev_file, prev_state, prev_turn = previous

        if turn == prev_turn:
            raise RunError(
                "duplicate turn %d: %s and %s both report gameTurn %d."
                % (turn, prev_file, filename, turn)
            )
        if turn < prev_turn:
            raise RunError(
                "turn numbers go backwards: %s reports turn %d after %s reported"
                " turn %d." % (filename, turn, prev_file, prev_turn)
            )
        if turn > prev_turn + 1:
            self.gaps.append((prev_turn, turn))

        # Quantities that only ever increase within one game. A decrease means the
        # later file belongs to a branch that never had the earlier one's history.
        # Score is NOT among them - it legitimately falls when a city is lost.
        prev_techs = set(prev_state["player"]["knownTechs"])
        techs = set(state["player"]["knownTechs"])
        lost = prev_techs - techs
        if lost:
            raise RunError(
                "turn %d (%s) is missing techs known at turn %d: %s. Techs are"
                " never unlearned, so these files are from different games."
                % (turn, filename, prev_turn, ", ".join(sorted(lost)))
            )

        prev_tiles = tile_positions(prev_state)
        tiles = tile_positions(state)
        forgotten = prev_tiles - tiles
        if forgotten:
            raise RunError(
                "turn %d (%s) has forgotten %d tile(s) revealed by turn %d, e.g."
                " %s. Revealed map is never un-revealed, so these files are from"
                " different games."
                % (
                    turn, filename, len(forgotten), prev_turn,
                    ", ".join("(%d,%d)" % p for p in sorted(forgotten)[:3]),
                )
            )

        prev_cities = set(c["id"] for c in prev_state["cities"])
        cities = set(c["id"] for c in state["cities"])
        # A city genuinely can be lost, but not while it is still in the list under
        # a different id. Only a reused id with a different name is impossible.
        prev_named = dict((c["id"], c["name"]) for c in prev_state["cities"])
        for city in state["cities"]:
            was = prev_named.get(city["id"])
            if was is not None and was != city["name"]:
                raise RunError(
                    "turn %d (%s): city id %d is named %r but was %r at turn %d."
                    " Engine ids are stable within a game, so these files are from"
                    " different games."
                    % (turn, filename, city["id"], city["name"], was, prev_turn)
                )
        del cities, prev_cities

    def pairs(self):
        """Consecutive (previous, current) state pairs, with the turn gap size."""
        for i in range(1, len(self.states)):
            _, before = self.states[i - 1][0], self.states[i - 1][1]
            _, after = self.states[i][0], self.states[i][1]
            yield before, after

    def latest(self):
        return self.states[-1][1]


def tile_positions(state):
    return set((t["x"], t["y"]) for t in state["map"]["tiles"])


def tile_map(state):
    return dict(((t["x"], t["y"]), t) for t in state["map"]["tiles"])


# -- shared vocabulary ----------------------------------------------------


def is_barbarian(state, player_id):
    """Barbarians are the LAST player index, derived rather than hardcoded.

    CvDefines.h has BARBARIAN_PLAYER == MAX_CIV_PLAYERS (18 in unmodded BTS, but
    redefined by mods), and totalCivs excludes barbarians. A player id at or above
    totalCivs that we have not met is the barbarian player; anything else unmet
    would not be visible to us at all, since seeing a civ's unit causes contact.
    """
    if player_id == state["player"]["id"]:
        return False
    for contact in state["contacts"]:
        if contact["playerId"] == player_id:
            return False
    return player_id >= state["game"]["totalCivs"]


def leader_names(run):
    """playerId -> leader, accumulated across the WHOLE run.

    Contacts only appear once met, and a civ met on turn 27 is nameless in the
    turn-26 file - but its units may already have been sighted. Building this
    across every turn means an early sighting is still attributed correctly.
    """
    out = {}
    for _, state in run.states:
        for contact in state["contacts"]:
            out[contact["playerId"]] = contact["leader"]
    return out


def owner_label(run, names, player_id):
    if player_id == run.player_id:
        return "you"
    if player_id in names:
        return "%s (player %d)" % (names[player_id], player_id)
    if is_barbarian(run.latest(), player_id):
        return "BARBARIANS (player %d)" % player_id
    return "player %d (never met)" % player_id


def chebyshev(state, a, b):
    """Wrap-aware plot distance - the engine's own metric, and a LOWER BOUND.

    Straight-line, ignoring terrain: it counts diagonals as one step and knows
    nothing about peaks, water, forest movement cost or whose borders are in the
    way. Real travel time is always >= this and usually more. Anything better is
    the pathfinding harness/README.md declines to build, so the number is always
    labelled rather than presented as turns.

    The wrap term is why this is a function and not something the reader does in
    their head: with wrapX true on an 84-wide map, the short way east may be around
    the seam, and an agent computing distances by hand can get that silently wrong.
    """
    width = state["game"]["mapWidth"]
    height = state["game"]["mapHeight"]
    dx = abs(a[0] - b[0])
    if state["game"]["wrapX"]:
        dx = min(dx, width - dx)
    dy = abs(a[1] - b[1])
    if state["game"]["wrapY"]:
        dy = min(dy, height - dy)
    return max(dx, dy)


def nearest_city_note(run, state, pos):
    """'  4 from Lisbon' for the nearest OWN city, or '' when there are none.

    Nearest rather than one figure per city: 'how far is this from me' is a single
    number a reader scans, while a per-city list grows with the empire and mostly
    repeats. Two cities makes per-city look cheap; ten makes it noise. A specific
    pair can always be computed from the coordinates, which are right there.
    """
    cities = state["cities"]
    if not cities:
        return ""
    best = min(cities, key=lambda c: chebyshev(state, pos, (c["x"], c["y"])))
    return "  %d from %s" % (
        chebyshev(state, pos, (best["x"], best["y"])), best["name"],
    )


def format_year(year):
    if year < 0:
        return "%d BC" % -year
    return "AD %d" % year


def format_turns(turns):
    """Turn numbers as compact ranges: [3,4,5,9] -> '3-5, 9'."""
    if not turns:
        return "never"
    ordered = sorted(set(turns))
    runs = [[ordered[0], ordered[0]]]
    for turn in ordered[1:]:
        if turn == runs[-1][1] + 1:
            runs[-1][1] = turn
        else:
            runs.append([turn, turn])
    return ", ".join(
        "t%d" % lo if lo == hi else "t%d-%d" % (lo, hi) for lo, hi in runs
    )


# -- observation model ----------------------------------------------------


class Sighting(object):
    """One rival unit type seen on one turn at one place.

    `foreignUnits` entries carry NO id - unlike our own units, which have stable
    engine ids - so cross-turn identity cannot be established, only inferred. This
    tool therefore never claims two sightings are the same unit. It records what
    was seen, where, and when, and leaves identity to the reader.
    """

    __slots__ = ("turn", "x", "y", "damage")

    def __init__(self, turn, x, y, damage):
        self.turn = turn
        self.x = x
        self.y = y
        self.damage = damage


def collect_sightings(run):
    """owner -> unit type -> [Sighting], across the whole run."""
    out = {}
    for _, state in run.states:
        turn = state["game"]["gameTurn"]
        for unit in state["foreignUnits"]:
            by_type = out.setdefault(unit["owner"], {})
            by_type.setdefault(unit["type"], []).append(
                Sighting(turn, unit["x"], unit["y"], unit.get("damage"))
            )
    return out


def foreign_unit_key(unit):
    return (unit["owner"], unit["type"], unit["x"], unit["y"])


def classify_departure(before, after, unit):
    """Why a rival unit present last turn is absent now.

    THIS IS THE CENTRAL DISTINCTION IN THE WHOLE TOOL. `foreignUnits` reports only
    units on a currently-visible tile, so absence has two completely different
    meanings and flattening them is how a unit gets killed:

      LEFT OR DIED  the tile is STILL VISIBLE and the unit is not on it. Something
                    real happened - it moved away or was destroyed.
      LOST SIGHT    the tile went fogged. We stopped looking. It is very probably
                    still there, and nothing can be concluded about it.

    Measured on the baseline run, this is not a technicality: at t35-t40 two rival
    scouts are continuously observed while MOVING, so a diff keyed on position
    alone reports them vanishing and reappearing every single turn - six turns of
    noise about units that never left sight.
    """
    after_tiles = tile_map(after)
    tile = after_tiles.get((unit["x"], unit["y"]))
    if tile is None:
        return "tile no longer in the export (should not happen)"
    if tile.get("visibleNow"):
        return "left or died"
    return "lost sight"


# One tile: a departure and an appearance further apart than this are not obviously
# the same unit, and a wider radius would start ASSERTING identity, which nothing in
# the export supports. Most early units have 1 move; a Scout has 2, so its move can
# exceed this and simply goes unannotated - the note is a hint that costs nothing
# when absent, never a claim that its absence means anything.
MOVE_HINT_RADIUS = 1


def probable_move_note(unit, appeared):
    """Flag a departure that has a same-type, same-owner appearance right beside it.

    Without this, one scout stepping one tile prints as 'gone [left or died]' plus
    a separate 'UNIT SEEN' - which reads as two units and a possible kill when it
    is almost certainly one unit walking. But foreignUnits carries NO id, so this
    CANNOT be resolved into a single move event without inventing identity the
    export does not support. The honest form is to leave both lines standing and
    point at the coincidence, leaving the inference to the reader.
    """
    near = []
    for other in appeared:
        if other["owner"] != unit["owner"] or other["type"] != unit["type"]:
            continue
        if max(abs(other["x"] - unit["x"]), abs(other["y"] - unit["y"])) <= MOVE_HINT_RADIUS:
            near.append((other["x"], other["y"]))
    if not near:
        return ""
    return "  (same type+owner appeared at %s this turn - probably this unit moving," \
           " but there is no id to confirm it)" % ", ".join(
               "(%d,%d)" % p for p in sorted(near)
           )


# -- timeline -------------------------------------------------------------


def diff_own_units(before, after):
    """Gained and lost own units, keyed by STABLE ENGINE ID.

    Our own units carry ids, so this diff is exact - no inference. A disappearance
    is unambiguous: the unit is gone, not merely out of sight.
    """
    was = dict((u["id"], u) for u in before["units"])
    now = dict((u["id"], u) for u in after["units"])
    gained = [now[i] for i in sorted(set(now) - set(was))]
    lost = [was[i] for i in sorted(set(was) - set(now))]
    return gained, lost


def pair_settlers_with_foundings(lost_units, founded):
    """Match settlers that vanished against cities founded the same turn.

    A settler is CONSUMED when it founds a city, so it leaves `units` on exactly
    the turn the city appears. Reporting that as "LOST" is what the raw diff does
    and it is badly misleading: in trials, two separate agents read `LOST
    UNIT_SETTLER` as a combat casualty, and one nearly built an advisory around a
    second unit death that never happened.

    The export does not record WHICH settler founded a city, so this is an
    inference - but a safe one when there is exactly one of each. It is not a
    positional match: the settler moves and then founds in the same turn, so its
    last exported position is where it stood at the END of the previous turn, one
    or more tiles from the city (Oporto is founded at (78,14) with its settler
    last seen at (77,15)). Matching on position would therefore fail on the real
    case it exists to handle.

    Returns (pairs, unmatched_lost). With more than one settler vanishing on the
    same turn as more than one founding, the pairing is genuinely ambiguous, so
    nothing is paired and the caller says so rather than guessing.
    """
    settlers = [u for u in lost_units if u["type"] == "UNIT_SETTLER"]
    others = [u for u in lost_units if u["type"] != "UNIT_SETTLER"]
    if len(settlers) == 1 and len(founded) == 1:
        return [(settlers[0], founded[0])], others
    return [], lost_units


def diff_own_cities(before, after):
    was = dict((c["id"], c) for c in before["cities"])
    now = dict((c["id"], c) for c in after["cities"])
    founded = [now[i] for i in sorted(set(now) - set(was))]
    lost = [was[i] for i in sorted(set(was) - set(now))]
    grown = []
    for city_id in sorted(set(now) & set(was)):
        if now[city_id]["population"] != was[city_id]["population"]:
            grown.append((was[city_id], now[city_id]))
    return founded, lost, grown


def diff_tiles(before, after):
    """Newly revealed tiles, and per-field changes on tiles known to both.

    Kept separate because they mean different things: a newly revealed tile is
    exploration, while a changed field on an already-revealed tile is the world
    moving (or, for `bonus`, a tech unhiding what was always there).
    """
    was = tile_map(before)
    now = tile_map(after)
    revealed = sorted(set(now) - set(was))
    changes = []
    for pos in sorted(set(now) & set(was), key=lambda p: (p[1], p[0])):
        for field in TRACKED_TILE_FIELDS:
            old = was[pos].get(field)
            new = now[pos].get(field)
            if old != new:
                changes.append((pos, field, old, new))
    return revealed, changes


def diff_foreign_units(before, after):
    """(appeared, departed) rival unit sightings between two turns.

    Position is part of the key because there is no id to use instead - so a unit
    that merely moved shows up as one departure and one appearance. That is why
    every departure is classified against the fog rather than reported bare.
    """
    was = dict((foreign_unit_key(u), u) for u in before["foreignUnits"])
    now = dict((foreign_unit_key(u), u) for u in after["foreignUnits"])
    appeared = [now[k] for k in sorted(set(now) - set(was))]
    departed = [was[k] for k in sorted(set(was) - set(now))]
    return appeared, departed


def timeline_block(run, names, before, after):
    """Everything that changed between two consecutive exports."""
    turn = after["game"]["gameTurn"]
    prev_turn = before["game"]["gameTurn"]
    rows = []

    span = turn - prev_turn
    header = "TURN %d (%s)" % (turn, format_year(after["game"]["year"]))
    if span > 1:
        header += "   [GAP: no export for turn(s) %s - this covers %d turns of change]" % (
            format_turns(range(prev_turn + 1, turn)), span,
        )
    rows.append(header)

    body = []

    new_techs = sorted(
        set(after["player"]["knownTechs"]) - set(before["player"]["knownTechs"])
    )
    for tech in new_techs:
        body.append("  tech      COMPLETED %s" % tech)
    if before["player"]["research"]["current"] != after["player"]["research"]["current"]:
        body.append(
            "  research  now %s (was %s)"
            % (
                after["player"]["research"]["current"] or "nothing selected",
                before["player"]["research"]["current"] or "nothing selected",
            )
        )

    founded, lost_cities, grown = diff_own_cities(before, after)
    gained, lost_units = diff_own_units(before, after)
    consumed, lost_units = pair_settlers_with_foundings(lost_units, founded)
    consumed_settlers = set(unit["id"] for unit, _ in consumed)

    for city in founded:
        settler = None
        for unit, built in consumed:
            if built is city:
                settler = unit
        if settler is None:
            body.append(
                "  city      FOUNDED %s at (%d,%d)"
                % (city["name"], city["x"], city["y"])
            )
        else:
            body.append(
                "  city      FOUNDED %s at (%d,%d) - built by settler id %d, which"
                " was consumed doing it (NOT a casualty)"
                % (city["name"], city["x"], city["y"], settler["id"])
            )
    for city in lost_cities:
        body.append(
            "  city      LOST %s at (%d,%d)" % (city["name"], city["x"], city["y"])
        )
    for was, now in grown:
        body.append(
            "  city      %s pop %d -> %d" % (now["name"], was["population"],
                                             now["population"])
        )

    for unit in gained:
        body.append(
            "  unit      GAINED %s (id %d) at (%d,%d)"
            % (unit["type"], unit["id"], unit["x"], unit["y"])
        )
    for unit in lost_units:
        if unit["id"] in consumed_settlers:
            continue
        # Ours have ids, so a disappearance IS certain - not a visibility artefact
        # the way a rival's is. But see the settler case above: "gone from the unit
        # list" and "died" are not the same thing.
        note = ""
        if unit["type"] == "UNIT_SETTLER" and founded:
            note = ("  (a city was also founded this turn - too many settlers/cities"
                    " to pair them safely, so check whether this one founded it)")
        body.append(
            "  unit      LOST %s (id %d), last at (%d,%d)%s"
            % (unit["type"], unit["id"], unit["x"], unit["y"], note)
        )

    known = set(c["playerId"] for c in before["contacts"])
    for contact in after["contacts"]:
        if contact["playerId"] not in known:
            body.append(
                "  contact   MET %s of %s (player %d), attitude %s"
                % (
                    contact["leader"], contact["civilization"],
                    contact["playerId"], contact["attitude"],
                )
            )
    was_attitude = dict((c["playerId"], c) for c in before["contacts"])
    for contact in after["contacts"]:
        old = was_attitude.get(contact["playerId"])
        if old is None:
            continue
        if old["attitude"] != contact["attitude"]:
            body.append(
                "  contact   %s attitude %s -> %s"
                % (contact["leader"], old["attitude"], contact["attitude"])
            )
        if old["atWar"] != contact["atWar"]:
            body.append(
                "  contact   %s %s"
                % (contact["leader"],
                   "WAR DECLARED" if contact["atWar"] else "peace made")
            )

    was_cities = dict(((c["x"], c["y"]), c) for c in before["foreignCities"])
    for city in after["foreignCities"]:
        pos = (city["x"], city["y"])
        old = was_cities.get(pos)
        if old is None:
            body.append(
                "  rival     CITY SEEN %s pop %d at (%d,%d), owner %s%s"
                % (
                    city["name"], city["population"], city["x"], city["y"],
                    owner_label(run, names, city["owner"]),
                    " CAPITAL" if city.get("capital") else "",
                )
            )
        elif old["population"] != city["population"]:
            body.append(
                "  rival     %s pop %d -> %d"
                % (city["name"], old["population"], city["population"])
            )

    appeared, departed = diff_foreign_units(before, after)
    for unit in appeared:
        body.append(
            "  rival     UNIT SEEN %s at (%d,%d), owner %s%s"
            % (
                unit["type"], unit["x"], unit["y"],
                owner_label(run, names, unit["owner"]),
                "  damage %d%%" % unit["damage"] if unit.get("damage") else "",
            )
        )
    for unit in departed:
        body.append(
            "  rival     gone from (%d,%d): %s, owner %s  [%s]%s"
            % (
                unit["x"], unit["y"], unit["type"],
                owner_label(run, names, unit["owner"]),
                classify_departure(before, after, unit),
                probable_move_note(unit, appeared),
            )
        )

    revealed, changes = diff_tiles(before, after)
    if revealed:
        body.append("  map       %d tile(s) newly revealed" % len(revealed))
    for pos, field, old, new in changes:
        if field == "owner":
            body.append(
                "  map       (%d,%d) territory %s -> %s"
                % (
                    pos[0], pos[1],
                    "unowned" if old is None else owner_label(run, names, old),
                    "unowned" if new is None else owner_label(run, names, new),
                )
            )
        elif field == "bonus" and old is None and new is not None:
            # Worth its own wording: the resource was always there, and a tech
            # (or first sight of the tile) is what made it visible. In the
            # baseline run BONUS_HORSE appears on two tiles the same turn Animal
            # Husbandry completes, which the tech line above makes joinable.
            body.append(
                "  map       (%d,%d) RESOURCE NOW VISIBLE: %s" % (pos[0], pos[1], new)
            )
        else:
            body.append(
                "  map       (%d,%d) %s %s -> %s"
                % (
                    pos[0], pos[1], TILE_CHANGE_LABEL[field],
                    old if old is not None else "none",
                    new if new is not None else "none",
                )
            )

    if not body:
        return None
    return rows + body


def render_timeline(run, first_turn, last_turn):
    names = leader_names(run)
    lines = []
    shown = 0
    for before, after in run.pairs():
        turn = after["game"]["gameTurn"]
        if turn < first_turn or turn > last_turn:
            continue
        block = timeline_block(run, names, before, after)
        if block is None:
            continue
        shown += 1
        lines.extend(block)
        lines.append("")

    if not shown:
        lines.append("(nothing changed in this turn range)")
        lines.append("")

    lines.append("THIS VIEW OMITS")
    lines.append(
        "  %-54s ->  %s" % ("the state of anything at a given turn", "the turn's JSON file")
    )
    lines.append(
        "  %-54s ->  %s" % ("per-rival summary of everything ever seen", "--view intel")
    )
    lines.append(
        "  %-54s ->  %s" % ("map layout and anything spatial", "harness/render_map.py")
    )
    lines.append(
        "  %-54s ->  %s"
        % ("turns where nothing changed (skipped entirely)", "they are not errors")
    )
    return lines


# -- intel ----------------------------------------------------------------


def render_intel(run):
    """Per-rival dossier: recent sightings, then everything ever fielded.

    Two sections per rival because they answer two different questions and go
    stale at completely different rates. WHERE something was recently is
    perishable and positional; WHAT a civ has ever fielded is a permanent
    capability record where position is incidental.
    """
    names = leader_names(run)
    latest = run.latest()
    latest_turn = latest["game"]["gameTurn"]
    sightings = collect_sightings(run)

    lines = []

    contacts = dict((c["playerId"], c) for c in latest["contacts"])
    civ_ids = sorted(set(sightings) | set(contacts))
    civ_ids = [p for p in civ_ids if not is_barbarian(latest, p)]
    barb_ids = [p for p in sorted(sightings) if is_barbarian(latest, p)]

    if not civ_ids and not barb_ids:
        lines.append("Nobody met and nothing sighted in this run.")
        lines.append("")
    for player_id in civ_ids:
        lines.extend(_rival_block(run, names, sightings, contacts, player_id,
                                  latest, latest_turn))
        lines.append("")

    if barb_ids:
        lines.append("BARBARIANS AND ANIMALS")
        lines.append(
            "  Separate because they carry NO TECH IMPLICATION. Animals and barbarian"
        )
        lines.append(
            "  units come from the barbarian player, not from a civ's research, so"
        )
        lines.append("  nothing here tells you what any rival can build.")
        lines.append(
            "  They ARE the main military threat of the early game, so every sighting"
        )
        lines.append("  is listed with where and when it was seen.")
        for player_id in barb_ids:
            for unit_type in sorted(sightings[player_id]):
                seen = sightings[player_id][unit_type]
                turns = [s.turn for s in seen]
                lines.append(
                    "  %-18s %d sighting(s) on %s"
                    % (unit_type, len(seen), format_turns(turns))
                )
                for sighting in sorted(seen, key=lambda s: -s.turn):
                    age = latest_turn - sighting.turn
                    lines.append(
                        "      t%-4d (%d,%d)%s%s  %s"
                        % (
                            sighting.turn, sighting.x, sighting.y,
                            nearest_city_note(run, latest, (sighting.x, sighting.y)),
                            "  damage %d%%" % sighting.damage
                            if sighting.damage else "",
                            "LATEST TURN" if age == 0 else "%d turn(s) ago" % age,
                        )
                    )
        lines.append(
            "  Positions are where it WAS on that turn. Animals roam, and a sighting"
        )
        lines.append(
            "  several turns old constrains almost nothing about where it is now."
        )
        lines.append("")

    lines.extend(_garrisons(run, latest, latest_turn))
    lines.append("")
    lines.extend(_intel_footer(run, latest_turn))
    return lines


def _garrisons(run, latest, latest_turn):
    """Which of your units are standing in each city, as of the latest turn.

    A COUNT, deliberately, and never a verdict. Joining `units` against `cities`
    by coordinate is exactly the consistent-arithmetic-over-rows case tooling is
    for - three separate agent trials derived it by hand and one called it the
    most important fact in its answer. But whether an empty city is actually in
    danger depends on what can REACH it: terrain, water, borders and what you can
    see. None of that is computable from the export (no landmass id is exported,
    so 'can anything walk here' is unanswerable), and a city reachable only by sea
    in the ancient era is safe in a way a defender count cannot show. So this
    reports who is where and stops; the reachability judgement is the reader's,
    and AGENT_GUIDE.md says so.
    """
    lines = ["YOUR CITIES AND WHAT IS STANDING IN THEM  [as of t%d]" % latest_turn]
    cities = latest["cities"]
    if not cities:
        lines.append("  no cities yet")
        return lines

    at = {}
    for unit in latest["units"]:
        at.setdefault((unit["x"], unit["y"]), []).append(unit)
    for city in sorted(cities, key=lambda c: (c["x"], c["y"])):
        pos = (city["x"], city["y"])
        inside = at.get(pos, [])
        if inside:
            what = ", ".join(
                "%s (id %d)" % (u["type"].replace("UNIT_", ""), u["id"])
                for u in inside
            )
        else:
            what = "nothing standing in it"
        lines.append("  %-12s (%d,%d)  %s" % (city["name"], pos[0], pos[1], what))

    outside = [
        u for u in latest["units"]
        if (u["x"], u["y"]) not in set((c["x"], c["y"]) for c in cities)
    ]
    if outside:
        lines.append("  in the field:")
        for unit in sorted(outside, key=lambda u: (u["y"], u["x"], u["id"])):
            lines.append(
                "    %-16s id %-6d (%d,%d)%s"
                % (
                    unit["type"], unit["id"], unit["x"], unit["y"],
                    nearest_city_note(run, latest, (unit["x"], unit["y"])),
                )
            )
    lines.append(
        "  A count, not a verdict. Whether an empty city is exposed depends on what"
    )
    lines.append(
        "  can actually reach it - check the approach on --view military before"
    )
    lines.append("  treating this as an alarm, or as reassurance.")
    return lines


def _rival_block(run, names, sightings, contacts, player_id, latest, latest_turn):
    lines = []
    contact = contacts.get(player_id)
    label = names.get(player_id, "player %d" % player_id)
    lines.append("%s (player %d)" % (label, player_id))

    if contact is not None:
        first_met = None
        for _, state in run.states:
            if any(c["playerId"] == player_id for c in state["contacts"]):
                first_met = state["game"]["gameTurn"]
                break
        lines.append(
            "  contact    met t%s, %s, %s   [as of t%d]"
            % (
                first_met if first_met is not None else "?",
                contact["attitude"],
                "AT WAR" if contact["atWar"] else "not at war",
                latest_turn,
            )
        )
    else:
        lines.append(
            "  contact    NOT MET - units sighted but no diplomatic contact"
        )

    by_type = sightings.get(player_id, {})

    # -- what is near you now, and lately. Perishable, positional.
    # Stacks are collapsed: two archers on one tile on one turn is ONE line with a
    # count, not two identical lines. Civ IV stacks units freely, and a repeated
    # line reads as a rendering fault rather than as the militarily important fact
    # that a stack is a stack.
    stacks = {}
    for unit_type, seen in by_type.items():
        for sighting in seen:
            key = (sighting.turn, unit_type, sighting.x, sighting.y)
            entry = stacks.setdefault(key, {"count": 0, "damage": []})
            entry["count"] += 1
            if sighting.damage:
                entry["damage"].append(sighting.damage)
    recent = sorted(stacks.items(), key=lambda kv: (-kv[0][0], kv[0][1], kv[0][2]))
    if recent:
        lines.append("  RECENT SIGHTINGS (most recent first) - where things were")
        for (turn, unit_type, x, y), entry in recent[:8]:
            age = latest_turn - turn
            damage = ""
            if entry["damage"]:
                damage = "  damage %s" % ", ".join(
                    "%d%%" % d for d in sorted(entry["damage"], reverse=True)
                )
            lines.append(
                "    t%-4d %-18s (%d,%d)%s%s%s  %s"
                % (
                    turn, unit_type, x, y,
                    nearest_city_note(run, latest, (x, y)),
                    " x%d STACKED" % entry["count"] if entry["count"] > 1 else "",
                    damage,
                    "LATEST TURN" if age == 0 else "%d turn(s) ago" % age,
                )
            )
        if len(recent) > 8:
            lines.append(
                "    ... and %d earlier sighting(s) - EVER FIELDED below is complete"
                % (len(recent) - 8)
            )
        lines.append(
            "    Positions are where a unit WAS on that turn, not where it is."
            " Units move."
        )
    else:
        lines.append("  RECENT SIGHTINGS  none - no unit of theirs has ever been seen")

    # -- what they have ever fielded. Permanent, capability-bearing.
    if by_type:
        lines.append(
            "  EVER FIELDED - each type proves they had the tech and resources for it"
        )
        ordered = sorted(by_type, key=lambda t: min(s.turn for s in by_type[t]))
        for unit_type in ordered:
            seen = by_type[unit_type]
            turns = [s.turn for s in seen]
            lines.append(
                "    %-18s first seen t%-4d %d sighting(s) on %s"
                % (unit_type, min(turns), len(seen), format_turns(turns))
            )
        lines.append(
            "    STILL TRUE NOW: a type seen once is a capability they keep. Look up"
        )
        lines.append(
            "    each unit's prerequisites in the game's CIV4UnitInfos.xml (and the"
        )
        lines.append(
            "    tech that unlocks it) to read their tech level off this list."
        )

    cities = _rival_cities(run, player_id)
    if cities:
        lines.append("  CITIES SEEN")
        for pos in sorted(cities):
            record = cities[pos]
            lines.append(
                "    (%d,%d) %-14s pop %d as of t%d%s   first seen t%d"
                % (
                    pos[0], pos[1], record["name"], record["population"],
                    record["turn"], "  CAPITAL" if record["capital"] else "",
                    record["first"],
                )
            )
    return lines


def _rival_cities(run, player_id):
    """Latest observation of each of this player's cities, plus first-seen turn.

    Cities persist once revealed - unlike units - and the exported fields are LIVE,
    which is what the game itself paints on the nameplate through fog. So the
    latest value is genuinely the current value, and only the turn it was recorded
    is stated for provenance.
    """
    out = {}
    for _, state in run.states:
        turn = state["game"]["gameTurn"]
        for city in state["foreignCities"]:
            if city["owner"] != player_id:
                continue
            pos = (city["x"], city["y"])
            record = out.get(pos)
            if record is None:
                out[pos] = {
                    "name": city["name"], "population": city["population"],
                    "capital": bool(city.get("capital")), "turn": turn,
                    "first": turn,
                }
            else:
                record["name"] = city["name"]
                record["population"] = city["population"]
                record["capital"] = bool(city.get("capital"))
                record["turn"] = turn
    return out


def _intel_footer(run, latest_turn):
    lines = [
        "HOW TO READ THIS",
        "  Every line carries the turn it was observed. A past turn is evidence"
        " about",
        "  the PAST, not current state - only turn %d is now." % latest_turn,
        "  Rival units are reported only while standing on a tile you could SEE, so",
        "  this is what you happened to observe, never an inventory of what exists.",
        "  Absence of a unit type means you never saw one, NOT that they have none.",
        "  foreignUnits entries carry no id, so two sightings of the same type are",
        "  not necessarily the same unit - and a unit that merely moved looks like",
        "  one disappearing and another appearing. Identity is yours to infer.",
        "",
        "THIS VIEW OMITS",
        "  %-54s ->  %s" % ("when each change happened, turn by turn", "--view timeline"),
        "  %-54s ->  %s" % ("your own empire's history", "the turn JSON files"),
        "  %-54s ->  %s"
        % ("which tech a unit implies", "CIV4UnitInfos.xml in the game's XML"),
        "  %-54s ->  %s" % ("where anything is on the map", "harness/render_map.py"),
    ]
    return lines


# -- output ---------------------------------------------------------------


def preamble(run, view, first_turn, last_turn):
    latest = run.latest()
    lines = [
        "civ4-advisor run history",
        "  run     %s" % run.path,
        "  view    %s" % view,
        "  turns   %d files, t%d - t%d"
        % (len(run.states), run.turns[0], run.turns[-1]),
        "  game    %s, %s, %s, %s, %d civs"
        % (
            run.leader.replace("LEADER_", ""), run.setup["mapScript"],
            run.setup["handicap"].replace("HANDICAP_", ""),
            run.setup["worldSize"].replace("WORLDSIZE_", ""),
            run.setup["totalCivs"],
        ),
        "  latest  t%d (%s) - THE ONLY TURN THAT IS 'NOW'"
        % (latest["game"]["gameTurn"], format_year(latest["game"]["year"])),
    ]
    if run.as_of is not None:
        lines.append(
            "  AS-OF   clamped to t%d: every later turn file was discarded before"
            " reading," % run.as_of
        )
        lines.append(
            "          so nothing below can contain information from after that turn."
        )
    if view == "timeline" and (first_turn > run.turns[0] or last_turn < run.turns[-1]):
        lines.append("  range   restricted to t%d - t%d" % (first_turn, last_turn))
    if run.gaps:
        lines.append(
            "  GAPS    no export for %s. Legal (a failed export is skipped, not"
            % ", ".join(
                format_turns(range(a + 1, b)) for a, b in run.gaps
            )
        )
        lines.append(
            "          fatal), but a diff across a gap covers more than one turn."
        )
    lines.append("")
    return lines


def render(run, view, first_turn, last_turn):
    lines = preamble(run, view, first_turn, last_turn)
    if view == "timeline":
        lines.extend(render_timeline(run, first_turn, last_turn))
    else:
        lines.extend(render_intel(run))
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="run_history.py",
        description=__doc__.split("\n\n")[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "views:\n"
            "  timeline  what changed between consecutive turns: techs, cities,\n"
            "            units gained and lost, contacts, rival sightings, tiles\n"
            "            revealed, territory, resources unhidden. Turns where\n"
            "            nothing changed are skipped.\n"
            "  intel     per rival: recent sightings with positions (what is near\n"
            "            you), then every unit type ever fielded with the turn it\n"
            "            was first seen (what they can build). Barbarians and\n"
            "            animals are listed separately - they imply no tech.\n"
        ),
    )
    parser.add_argument(
        "run", help="path to a run FOLDER of turn_*.json files (not a single turn)"
    )
    parser.add_argument(
        "--view", choices=VIEWS, default="timeline",
        help="which view to render (default: timeline)",
    )
    parser.add_argument(
        "--from", dest="first", type=int, default=None, metavar="N",
        help="first turn to report (timeline only; default: start of run)",
    )
    parser.add_argument(
        "--to", dest="last", type=int, default=None, metavar="N",
        help="last turn to report (timeline only; default: end of run)",
    )
    parser.add_argument(
        "--as-of", dest="as_of", type=int, default=None, metavar="N",
        help="pretend turn N is the present: discard every later turn file before"
             " anything reads them. Affects BOTH views, unlike --from/--to. Live"
             " play never needs this (the newest file is the current turn); it is"
             " for replaying a finished run without leaking the future.",
    )
    args = parser.parse_args(argv)

    try:
        run = Run(args.run, as_of=args.as_of)
    except RunError as error:
        sys.stderr.write("run_history: %s\n" % error)
        return 2

    first = run.turns[0] if args.first is None else args.first
    last = run.turns[-1] if args.last is None else args.last
    if first > last:
        parser.error("--from %d is after --to %d" % (first, last))
    if args.view == "intel" and (args.first is not None or args.last is not None):
        # A dossier truncated at turn M silently drops the first sighting that
        # carries the tech implication - the one fact the view exists to surface.
        sys.stderr.write(
            "run_history: --from/--to are ignored for --view intel (a truncated"
            " dossier would drop the earliest sighting of a unit type, which is"
            " exactly the fact that proves a capability).\n"
        )

    sys.stdout.write(render(run, args.view, first, last))
    return 0


if __name__ == "__main__":
    sys.exit(main())
