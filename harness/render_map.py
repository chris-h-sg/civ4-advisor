"""Render map.tiles from a civ4-advisor state file as an ASCII grid.

`map.tiles` is a flat list of per-tile objects - the right export format, but the
one part of the state that cannot be reasoned over spatially without being laid
out. This turns it into named views, one per decision.

The grid is lossy BY DESIGN and never replaces the JSON. Orient on the grid,
then verify the specific tiles you are about to act on against the state file.

Run it directly with the system Python; stdlib only, no setup:

    python harness/render_map.py samples/baseline-early-game/turn_0000.json --view settle
"""

import argparse
import json
import os
import sys

VIEWS = ("settle", "explore", "military", "yields", "worker")

# Founding rules, transcribed from the unmodded BTS ruleset at development time so
# this tool never has to read the game's XML at runtime (harness/ must work with no
# Civ IV install). CvPlayer::canFound rejects a plot when:
#   - a city sits within MIN_CITY_RANGE (GlobalDefines.xml), ON THE SAME LANDMASS
#   - the plot is owned by any other player
#   - the terrain has no bFound/bFoundCoast/bFoundFreshWater, i.e. it is water
#   - the plot is impassable (peak) or carries a bImpassable/bNoCity feature
# The same-landmass term is the one part not derivable from the export - no area id is
# exported - so `settle` over-reports across water. It never under-reports.
MIN_CITY_RANGE = 2
UNFOUNDABLE_FEATURES = ("FEATURE_ICE", "FEATURE_OASIS")

# Coastal (harbour, lighthouse, bFoundCoast) is CvPlot::isCoastalLand: adjacent to
# water whose area has >= MIN_WATER_SIZE_FOR_OCEAN (10) tiles. CvArea::isLake is
# `area <= LAKE_MAX_AREA_SIZE` (9). Those two thresholds abut exactly, so
# "adjacent to a water tile whose `lake` flag is false" REPRODUCES isCoastalLand
# rather than approximating it.
#
# The `lake` flag itself is NOT fog-limited, which is what makes this safe: it comes
# from CvPlot::isLake() -> area()->isLake(), and areas are built by
# CvMap::calculateAreas() over the whole map at generation. So a single revealed sea
# tile surrounded by unexplored water is still correctly flagged sea, never lake.
# Demonstrated in the baseline run by a 9-tile revealed body - at LAKE_MAX_AREA_SIZE -
# that reports lake=False, which a fog-limited flag could not do.
#
# The one gap left really is fog, and it is on the LAND side: water we have not
# revealed at all cannot be counted, so is_coastal() reports how many neighbours are
# unknown and the site report qualifies a "no" rather than asserting it.

# 5x5 minus the four corners: the tiles a city can ever work (NUM_CITY_PLOTS = 21).
CITY_CROSS = tuple(
    (dx, dy)
    for dy in range(-2, 3)
    for dx in range(-2, 3)
    if abs(dx) != 2 or abs(dy) != 2
)

UNREVEALED_MARK = "."

# Grid anchoring. ASCII ONLY - this file is written to stdout, which is cp1252 on
# Windows, so a box-drawing separator like U+2551 raises UnicodeEncodeError on the
# very machine this repo lives on. '||' also needs no legend entry: it reads as a
# stronger version of the cell separator, where a novel glyph would have to be
# learned and would enlarge a symbol set we deliberately keep small.
COLUMN_GROUP = 5
HEADER_EVERY = 10

TERRAIN_GLYPH = {
    "TERRAIN_GRASS": "g",
    "TERRAIN_PLAINS": "p",
    "TERRAIN_DESERT": "d",
    "TERRAIN_TUNDRA": "t",
    "TERRAIN_SNOW": "s",
    "TERRAIN_COAST": "-",
    "TERRAIN_OCEAN": "~",
}

FEATURE_GLYPH = {
    "FEATURE_FOREST": "f",
    "FEATURE_JUNGLE": "j",
    "FEATURE_FLOOD_PLAINS": "=",
    "FEATURE_OASIS": "@",
    # 'I' rather than '%': the water column uses '%' for sea plus non-river fresh
    # water, and ice-vs-water was the one pairing in the whole glyph set where a
    # symbol carried two genuinely unrelated meanings. Everything else that repeats
    # is either the same concept seen from two columns ('~' ocean / sea access,
    # '*' resource / unimproved resource) or a mnemonic improvement letter confined
    # to the worker view.
    "FEATURE_ICE": "I",
    "FEATURE_FALLOUT": "!",
}

IMPROVEMENT_GLYPH = {
    "IMPROVEMENT_FARM": "F",
    "IMPROVEMENT_MINE": "M",
    "IMPROVEMENT_COTTAGE": "n",
    "IMPROVEMENT_HAMLET": "n",
    "IMPROVEMENT_VILLAGE": "n",
    "IMPROVEMENT_TOWN": "n",
    "IMPROVEMENT_PASTURE": "P",
    "IMPROVEMENT_CAMP": "K",
    "IMPROVEMENT_PLANTATION": "L",
    "IMPROVEMENT_QUARRY": "Q",
    "IMPROVEMENT_WORKSHOP": "H",
    "IMPROVEMENT_WINERY": "V",
    "IMPROVEMENT_LUMBERMILL": "B",
    "IMPROVEMENT_FISHING_BOATS": "N",
    "IMPROVEMENT_WHALING_BOATS": "N",
    "IMPROVEMENT_FORT": "T",
    "IMPROVEMENT_GOODY_HUT": "?",
    "IMPROVEMENT_CITY_RUINS": "R",
}

# Own-unit marker. Settler outranks worker outranks everything else, because a live
# settler is the decision the `settle` view exists for. Stacks collapse to one glyph;
# the unit list below every grid is the complete record.
OWN_UNIT_GLYPH = (
    ("UNIT_SETTLER", "S"),
    ("UNIT_WORKER", "W"),
)

# Units the base XML flags bFood: their build can draw on food surplus as well
# as hammers, so a food-starved turn while building one of these is the city
# spending growth on the unit on purpose, not a city that's stuck. Not the
# whole gate in general (a Police State civic makes military units food-fed
# too - see CLAUDE.md) but it's the only case that recurs this early, and
# scope stays there. Same two types as OWN_UNIT_GLYPH above by coincidence of
# scope, not by rule - that list is glyph precedence, unrelated to food cost.
FOOD_COST_UNITS = frozenset(("UNIT_SETTLER", "UNIT_WORKER"))


STATE_SCHEMA_VERSION = 2


def check_schema_version(raw, path):
    """Refuse anything but the current schema version.

    A v1 file (pre y-axis inversion) would parse fine and render a silently
    MIRRORED map, so a version mismatch has to fail loudly here rather than
    downstream as a plausible-looking wrong picture. See CLAUDE.md and
    AdvisorStateWriter._invertY.
    """
    version = raw.get("meta", {}).get("schemaVersion")
    if version != STATE_SCHEMA_VERSION:
        raise SystemExit(
            "%s: schemaVersion %r, expected %d - this file predates the "
            "y-axis inversion (0,0 is now northwest, y increases south) and "
            "will render a mirrored map if read as-is. Re-export it, or "
            "migrate it the way samples/baseline-early-game/ was migrated."
            % (path, version, STATE_SCHEMA_VERSION)
        )


class State(object):
    """A loaded state file plus the lookups every view needs."""

    def __init__(self, path):
        self.path = path
        with open(path, "r", encoding="utf-8") as handle:
            self.raw = json.load(handle)
        check_schema_version(self.raw, path)

        game = self.raw["game"]
        self.width = game["mapWidth"]
        self.height = game["mapHeight"]
        self.wrap_x = game["wrapX"]
        self.wrap_y = game["wrapY"]
        self.turn = game["gameTurn"]
        self.year = game["year"]
        self.era = game["era"]

        self.player_id = self.raw["player"]["id"]
        self.tiles = dict(((t["x"], t["y"]), t) for t in self.raw["map"]["tiles"])
        self.cities = self.raw["cities"]
        self.units = self.raw["units"]
        self.foreign_cities = self.raw["foreignCities"]
        self.foreign_units = self.raw["foreignUnits"]
        self.contacts = self.raw["contacts"]
        self.leaders = dict((c["playerId"], c["leader"]) for c in self.contacts)

    # -- geometry ---------------------------------------------------------

    def normalize(self, x, y):
        """Return (x, y) folded onto the map, or None if it falls off an edge.

        The map is a cylinder in the usual Civ IV setup (wrapX true, wrapY false),
        so x wraps and y does not. Both are read from the state file rather than
        assumed.
        """
        if self.wrap_x:
            x %= self.width
        elif not 0 <= x < self.width:
            return None
        if self.wrap_y:
            y %= self.height
        elif not 0 <= y < self.height:
            return None
        return (x, y)

    def distance(self, a, b):
        """Chebyshev distance, wrap-aware - the engine's `stepDistance`.

        NOT the engine's `plotDistance`, which is `max + min/2`
        (`CvGameCoreUtils.h:144`) and differs on every diagonal: at (3,3) it
        says 4 where this says 3. An earlier docstring called this "the
        engine's plot distance", which was the wrong name for the right code -
        the city-minimum-distance rule this serves really is a square dx/dy box
        scan (`CvPlayer.cpp:5005-5008`), so Chebyshev is correct here. Anything
        needing a true plot distance wants `rules.py`'s `plot_distance`.
        """
        dx = abs(a[0] - b[0])
        if self.wrap_x:
            dx = min(dx, self.width - dx)
        dy = abs(a[1] - b[1])
        if self.wrap_y:
            dy = min(dy, self.height - dy)
        return max(dx, dy)

    def neighbours(self, x, y):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                pos = self.normalize(x + dx, y + dy)
                if pos is not None:
                    yield pos

    def bearing(self, origin, pos):
        """Compass bearing from `origin` to `pos`, e.g. 'NNW'. '' when identical.

        Kept in sync with run_history.py's copy rather than imported, since the
        two tools are deliberately standalone scripts.
        """
        dx = pos[0] - origin[0]
        if self.wrap_x:
            if dx > self.width // 2:
                dx -= self.width
            elif dx < -(self.width // 2):
                dx += self.width
        dy = pos[1] - origin[1]
        if not dx and not dy:
            return ""

        ns = "S" if dy > 0 else ("N" if dy < 0 else "")
        ew = "E" if dx > 0 else ("W" if dx < 0 else "")
        if not ns:
            return ew
        if not ew:
            return ns
        if abs(dy) >= 2 * abs(dx):
            return ns + ns + ew
        if abs(dx) >= 2 * abs(dy):
            return ew + ns + ew
        return ns + ew

    def land_distance(self, origin, target):
        """Steps over REVEALED walkable land, or None if no such route exists.

        The same measure run_history.py reports, and it is here because the two
        tools disagreeing about what a distance means is worse than neither
        printing one. The site report used to give Chebyshev alone, labelled "a
        LOWER BOUND on turns" - honest, and on this map badly misleading: an
        agent trial found a settler site 3 tiles away by straight line whose real
        walk was twice that and crossed a one-tile isthmus, and the same gap made
        a lion look 6 tiles away when the walk was 14.

        Revealed tiles only. Routing through fog would be inventing a path, so an
        unrevealed shortcut can make the true figure smaller but never larger.
        """
        if origin == target:
            return 0
        if not self._walkable(origin) or not self._walkable(target):
            return None
        seen = set([origin])
        frontier = [origin]
        steps = 0
        while frontier:
            steps += 1
            nxt = []
            for pos in frontier:
                for other in self.neighbours(pos[0], pos[1]):
                    if other in seen or not self._walkable(other):
                        continue
                    if other == target:
                        return steps
                    seen.add(other)
                    nxt.append(other)
            frontier = nxt
        return None

    def _walkable(self, pos):
        """A land unit can stand here. Peaks are impassable, all water is ocean.

        Keyed on plotType, never terrain: TERRAIN_COAST vs TERRAIN_OCEAN is depth,
        not land-vs-water, and a trial got that wrong before catching itself.
        """
        tile = self.tiles.get(pos)
        if tile is None:
            return False
        return tile.get("plotType") not in ("PLOT_OCEAN", "PLOT_PEAK")

    def city_cross(self, x, y):
        """The 21 tiles a city at (x, y) could work, in row-major order."""
        out = []
        for dx, dy in CITY_CROSS:
            pos = self.normalize(x + dx, y + dy)
            if pos is not None:
                out.append(pos)
        return out

    # -- derived facts ----------------------------------------------------

    def all_cities(self):
        """Every city we know about - ours and revealed foreign ones."""
        out = [(c["x"], c["y"]) for c in self.cities]
        out.extend((c["x"], c["y"]) for c in self.foreign_cities)
        return out

    def blocked_by_city_range(self):
        """Tiles where founding is illegal because a known city is too close.

        See MIN_CITY_RANGE above for the one way this over-reports.
        """
        blocked = set()
        for cx, cy in self.all_cities():
            for dy in range(-MIN_CITY_RANGE, MIN_CITY_RANGE + 1):
                for dx in range(-MIN_CITY_RANGE, MIN_CITY_RANGE + 1):
                    pos = self.normalize(cx + dx, cy + dy)
                    if pos is not None:
                        blocked.add(pos)
        return blocked

    def is_coastal(self, pos):
        """(coastal, unrevealed_neighbours) for a land tile - CvPlot::isCoastalLand.

        See the note at the top of the file: non-lake water is exactly the water
        that qualifies, so this is the engine's rule, not a guess. The second
        value is how much fog is undercutting the answer.
        """
        tile = self.tiles.get(pos)
        if tile is None or tile.get("plotType") == "PLOT_OCEAN":
            return (False, 0)
        coastal = False
        unknown = 0
        for other in self.neighbours(pos[0], pos[1]):
            neighbour = self.tiles.get(other)
            if neighbour is None:
                unknown += 1
            elif neighbour.get("plotType") == "PLOT_OCEAN" and not neighbour.get("lake"):
                coastal = True
        return (coastal, unknown)

    def coastal_one_step_away(self, pos):
        """Land tiles adjacent to `pos` that ARE coastal, when `pos` is not.

        Radius 1 only, deliberately. A site one tile off the coast is the case
        worth flagging: it is frequently an accident, and one step converts a
        landlocked city into a harbour city for no real cost. Beyond one tile you
        are choosing a different site rather than nudging this one, so a wider
        search would be answering a question nobody asked - and would start this
        tool down the nearest-X query road that harness/README.md rules out.

        Reports, does not judge. Settling one off the coast is sometimes right
        (fresh water, a resource, a chokepoint), so the caller states the fact and
        leaves the trade to the reader.
        """
        if self.is_coastal(pos)[0]:
            return []
        out = []
        for other in self.neighbours(pos[0], pos[1]):
            tile = self.tiles.get(other)
            if tile is None or tile.get("plotType") == "PLOT_OCEAN":
                continue
            if self.is_coastal(other)[0] and not self.found_blockers(other):
                out.append(other)
        return sorted(out)

    def overlap_with_own_cities(self, cross):
        """[(city name, shared tile count)] for tiles this site shares with a city.

        Counting shared tiles by hand across two 21-tile sets is exactly the
        repeated arithmetic a tool should absorb - and it is presentation: it
        reports the overlap, it does not judge whether the overlap is acceptable.
        """
        out = []
        for city in self.cities:
            owned = set(self.city_cross(city["x"], city["y"]))
            shared = len([p for p in cross if p in owned])
            if shared:
                out.append((city["name"], shared))
        return out

    def found_blockers(self, pos):
        """Every reason founding at `pos` is illegal, as a list of strings.

        Empty list means legal as far as the export can tell. See the rule
        transcription at the top of this file, including its one over-report.
        """
        tile = self.tiles.get(pos)
        if tile is None:
            return ["never revealed - nothing is known about this tile"]
        reasons = []
        plot = tile.get("plotType")
        if plot == "PLOT_OCEAN":
            reasons.append("water: no land terrain allows founding")
        if plot == "PLOT_PEAK":
            reasons.append("peak: impassable")
        if tile.get("feature") in UNFOUNDABLE_FEATURES:
            reasons.append("feature %s cannot hold a city" % tile["feature"])
        owner = tile.get("owner")
        if owner is not None and owner != self.player_id:
            reasons.append(
                "inside %s's borders (remembered owner - may be stale under fog)"
                % self.owner_of(owner)
            )
        for city in self.all_cities():
            gap = self.distance(pos, city)
            if gap > MIN_CITY_RANGE:
                continue
            if gap == 0:
                reasons.append("a city already stands on this tile")
            else:
                reasons.append(
                    "a known city at (%d,%d) is %d tile(s) away, within Chebyshev %d"
                    " (assumes same landmass)"
                    % (city[0], city[1], gap, MIN_CITY_RANGE)
                )
        return reasons

    def frontier(self):
        """Revealed tiles that touch an unrevealed in-map tile.

        This is where exploring actually gains you something, and it is pure
        adjacency work - the reason `explore` is a view rather than a JSON read.
        """
        out = set()
        for pos in self.tiles:
            for other in self.neighbours(pos[0], pos[1]):
                if other not in self.tiles:
                    out.add(pos)
                    break
        return out

    def worked_tiles(self):
        out = set()
        for city in self.cities:
            for tile in city["workedTiles"]:
                out.add((tile[0], tile[1]))
        return out

    def is_barbarian(self, player_id):
        """Barbarians are BARBARIAN_PLAYER, i.e. the LAST player index.

        Derived, not hardcoded: CvDefines.h has BARBARIAN_PLAYER == MAX_CIV_PLAYERS,
        which is 18 in unmodded BTS but is redefined by mods (Rhye's uses 31). So
        "the highest player id in the game" is the durable rule and "18" is not.
        totalCivs excludes barbarians, and a player id at or above it that we have
        not met is the barbarian player - anything else unmet would not be visible
        to us at all, since seeing a civ's unit is what causes first contact.
        """
        if player_id == self.player_id or player_id in self.leaders:
            return False
        return player_id >= self.raw["game"]["totalCivs"]

    def owner_of(self, player_id):
        if player_id == self.player_id:
            return "you"
        if player_id in self.leaders:
            return self.leaders[player_id]
        if self.is_barbarian(player_id):
            return "BARBARIANS (player %d)" % player_id
        return "player %d - met nobody by that id, treat as hostile" % player_id


# -- region selection -----------------------------------------------------


def axis_window(values, size, wraps):
    """Smallest window covering `values` on an axis of length `size`.

    On a wrapping axis the smallest window is found by dropping the largest gap
    between consecutive occupied coordinates, so a region straddling the seam
    renders contiguously instead of spanning the whole map. The baseline run's
    revealed tiles sit flush against x=83 without crossing it, so this path is
    exercised only via a `--around` crop placed near the seam, not by the
    whole-map case - which is exactly why it is computed rather than assumed
    away.
    """
    present = sorted(set(values))
    if not present:
        return []
    if not wraps:
        return list(range(present[0], present[-1] + 1))

    gaps = []
    for i in range(len(present)):
        lo = present[i]
        hi = present[(i + 1) % len(present)]
        gap = (hi - lo) % size
        gaps.append((gap, lo))
    largest_gap, gap_start = max(gaps)
    if largest_gap == 0:
        return list(range(size))
    start = (gap_start + largest_gap) % size
    return [(start + i) % size for i in range(size - largest_gap + 1)]


def select_region(state, around, radius):
    """Return (xs, ys, description) for the region to draw."""
    if around is None:
        xs = axis_window([p[0] for p in state.tiles], state.width, state.wrap_x)
        ys = axis_window([p[1] for p in state.tiles], state.height, state.wrap_y)
        desc = "full revealed map"
    else:
        cx, cy = around
        xs = []
        for dx in range(-radius, radius + 1):
            pos = state.normalize(cx + dx, cy)
            if pos is not None:
                xs.append(pos[0])
        ys = []
        for dy in range(-radius, radius + 1):
            pos = state.normalize(cx, cy + dy)
            if pos is not None:
                ys.append(pos[1])
        desc = "cropped around (%d,%d) radius %d" % (cx, cy, radius)
    if not xs or not ys:
        return xs, ys, desc
    desc += ": x %s, y %d-%d (%d x %d)" % (
        _x_range_label(xs), ys[0], ys[-1], len(xs), len(ys),
    )
    return xs, ys, desc


def _x_range_label(xs):
    """'80-83' normally; '80-83 then 0-4 (wraps past the east edge)' when the
    window crosses the seam.

    x-only: wrapY is always false in the standard Civ4 cylinder map (see
    State.wrap_y), so y never wraps and needs no equivalent handling.

    axis_window returns values in walk order, not sorted - so a wrapped window
    has xs[0] > xs[-1] (e.g. 80..83,0..4). Printing that pair bare as '80-4'
    reads as a typo'd backwards range rather than as a wrap; a bare comma
    ('80-83,0-4') still leaves the reader to infer which edge and combine the
    two ranges themselves (roadmap item 7).
    """
    if len(xs) > 1 and xs[0] > xs[-1]:
        split = next(i for i in range(1, len(xs)) if xs[i] < xs[i - 1])
        return "%d-%d then %d-%d (wraps past the east edge)" % (
            xs[0], xs[split - 1], xs[split], xs[-1],
        )
    return "%d-%d" % (xs[0], xs[-1])


# -- cell composition -----------------------------------------------------


def is_dead_tile(tile):
    """True for a tile that yields nothing and never will, however it is worked.

    Measured across the whole baseline run rather than assumed:
      flat bare desert 0/0/0 (121 tiles) and peak 0/0/0 (40) -> dead.
      desert + flood plains 3/0/1 (38) and desert HILLS 0/1/1 (30) -> very much NOT.
      deep ocean is 1/0/1 (819) or 0/0/0 (561).
    So "desert" and "ocean" are both too coarse to key on. Deep ocean reads 0/0/0
    only when no land sits in ITS OWN 21-tile cross (the quirk documented at
    map.tiles.yields in the schema), which cannot be true of a tile inside a city's
    cross - so ocean is never dead here.
    """
    if tile.get("plotType") == "PLOT_PEAK":
        return True
    return (
        tile["terrain"] == "TERRAIN_DESERT"
        and tile.get("plotType") is None
        and not tile.get("feature")
    )


# Improvements that are NOT worker development and add no yield, so a tile carrying
# one is not "already improved" in the sense that matters below. A goody hut is the
# live case: it sits in the `improvement` field, is all over the turn-0 map, and
# marking it would fire the whole advisory on a turn when nothing is developed.
NON_DEVELOPMENT_IMPROVEMENTS = (
    "IMPROVEMENT_GOODY_HUT",
    "IMPROVEMENT_CITY_RUINS",
)


def yield_is_improved(tile):
    """True when this tile's exported yield already includes worker output.

    map.tiles.yields is the DISPLAYED yield, so a farmed tile reports the farmed
    number. Comparing two candidate city sites at the same turn therefore compares
    improved tiles inside your borders against raw tiles outside them - which
    silently flatters whichever site overlaps a city you already own, i.e. exactly
    the site that costs you the most. Base yield is not recoverable from the export
    (the mod exports what the game displays and nothing else), so the honest fix is
    to MARK the affected tiles rather than to pretend we can undo the improvement.
    """
    improvement = tile.get("improvement")
    if improvement in NON_DEVELOPMENT_IMPROVEMENTS:
        improvement = None
    # Routes are deliberately NOT counted. CIV4RouteInfos.xml gives ROUTE_ROAD and
    # ROUTE_RAILROAD no <Yields> block at all - they are movement and connectivity
    # only, so a roaded tile's displayed yield is its raw yield. (The +1 commerce
    # from roads is Civ III; BTS moved it onto terrain and improvements.)
    return bool(improvement)


IMPROVED_YIELD_NOTE = (
    "  '+' on F/P/C means that yield ALREADY INCLUDES an improvement."
    " Those tiles",
    "  are almost always ones an existing city of yours has developed, so a site"
    " that",
    "  overlaps your territory will look stronger than it is. Compare '+' tiles"
    " against",
    "  what an UNDEVELOPED tile of the same terrain yields, not against each other.",
)


def describe_distance(state, origin, target):
    """How far apart two tiles are, LEADING WITH THE WALK when they differ.

    The ordering is the point. Both figures were already printed side by side in
    run_history, straight line first - and two independent agent trials reported
    that the straight-line number is the one the eye takes, one of them saying it
    "still caught me on first read" despite a warning in its instructions telling
    it not to. A caveat that does not stick is a caveat that needs a layout fix
    rather than more words, which is the same conclusion the compass reached.

    So the actionable number goes first and the straight line becomes the aside.
    """
    straight = state.distance(origin, target)
    walk = state.land_distance(origin, target)
    if walk is None:
        return (
            "%d tiles straight line, but NO LAND ROUTE over revealed tiles -"
            " water or peaks block every path a land unit could take" % straight
        )
    if walk == straight:
        return (
            "%d tiles to walk (straight line agrees, so the ground is open) -"
            " still a LOWER BOUND on turns, terrain costs more" % walk
        )
    return (
        "%d TILES TO WALK over revealed land (only %d straight line) - a LOWER"
        " BOUND on turns, terrain costs more" % (walk, straight)
    )


def relief_label(tile):
    """Relief and lake-ness for the tables, which have no glyph to carry them.

    Without this the tables contradict the grid: a peak printed as plain GRASS
    with 0/0/0 yields looks like broken arithmetic, and a lake is indistinguishable
    from coastal sea though only one of them makes a site coastal.
    """
    plot = tile.get("plotType")
    if plot == "PLOT_PEAK":
        return "peak"
    if plot == "PLOT_HILLS":
        return "hills"
    if plot == "PLOT_OCEAN":
        return "lake" if tile.get("lake") else "sea"
    return "-"


# Fresh water and sea access are INDEPENDENT, so the water column encodes all four
# states rather than ranking them. A priority rule (river beats coastal) would hide
# sea access on exactly the tiles that have both - 7 of the 139 revealed land tiles at
# turn 34. Sea access is 8-neighbour adjacency (CvPlot::isCoastalLand), NOT "there is
# sea somewhere in the 21-tile cross": a city one tile inland works ocean but cannot
# build a Harbour.
# '_' rather than a space for "neither", because a blank in this column used to mean
# two different things: a landlocked dry tile, and a tile that IS water (where the
# question does not apply). A blank also reads as padding rather than as an answer,
# which is worst on exactly the state that should discourage settling. Blank is now
# reserved for water tiles alone.
# Keyed by (river, non-river fresh water, sea access). River beats lake in the two
# combined states: a tile with a river AND sea is '&' whether or not it also touches
# a lake. Six reachable states, five of the glyphs already familiar from elsewhere.
# The +1 commerce a river adds to a land tile is ALREADY in the exported yield
# (CvPlot::calculateNatureYield adds RiverYieldChange, which is 0/0/1 for every land
# terrain), so this column explains a number rather than changing one.
WATER_GLYPH = {
    (False, False, False): "_",
    (False, True, False): ":",
    (True, False, False): "/",
    (True, True, False): "/",
    (False, False, True): "~",
    (False, True, True): "%",
    (True, False, True): "&",
    (True, True, True): "&",
}

# Two columns in the cross table, because fresh water and sea answer different
# questions - farms and health versus buildings and boats - and one column forced
# them into a shared vocabulary ("both") that conflated them.
WATER_LABEL = {
    (False, False): "-",
    (False, True): "fresh",
    (True, False): "river",
    (True, True): "river+",
}


def water_state(state, pos, tile):
    """(river, non_river_fresh, sea_access), or None for a water tile.

    `freshWater` in the export is true for a river tile too, so the second element
    is the SEPARATE fresh-water sources - a lake or an oasis. Flood plains are not
    among them: CIV4FeatureInfos gives them bRequiresRiver=1 and bAddsFreshWater=0,
    so they sit on a river rather than supplying water themselves.

    River is NOT always a subset of fresh water: a river crossing a peak reports
    river=true, freshWater=false, because a peak can never be farmed or settled.
    """
    if tile.get("plotType") == "PLOT_OCEAN":
        return None
    river = bool(tile.get("river"))
    other_fresh = bool(tile.get("freshWater")) and not river
    return (river, other_fresh, state.is_coastal(pos)[0])


def water_glyph(state, pos, tile):
    key = water_state(state, pos, tile)
    return " " if key is None else WATER_GLYPH[key]


def water_labels(state, pos, tile):
    """(water, coast) as the cross table prints them."""
    key = water_state(state, pos, tile)
    if key is None:
        return ("-", "-")
    river, other_fresh, sea = key
    return (WATER_LABEL[(river, other_fresh)], "sea" if sea else "-")


def base_glyph(tile):
    """Terrain and relief, in one character. Uppercase land = hills."""
    plot = tile.get("plotType")
    if plot == "PLOT_PEAK":
        return "^"
    if plot == "PLOT_OCEAN":
        if tile.get("lake"):
            return "o"
        return TERRAIN_GLYPH.get(tile["terrain"], "?")
    glyph = TERRAIN_GLYPH.get(tile["terrain"], "?")
    if plot == "PLOT_HILLS":
        # Only letters carry the uppercase-means-hills convention. Water glyphs
        # ('-', '~') have no uppercase form, so .upper() would silently return them
        # unchanged and a hills tile would render as flat. Water cannot be hills in
        # the engine, so this never fires today - it fails loudly instead of quietly
        # if a future terrain breaks that assumption.
        assert glyph.isalpha(), (
            "hills on a non-letter terrain glyph %r (%s): uppercase cannot encode"
            " relief here" % (glyph, tile["terrain"])
        )
        return glyph.upper()
    return glyph


def own_unit_glyph(units):
    for unit_type, glyph in OWN_UNIT_GLYPH:
        for unit in units:
            if unit["type"] == unit_type:
                return glyph
    return "U"


def foreign_unit_glyph(state, units):
    owner = units[0]["owner"]
    if owner == state.player_id:
        return "?"
    if state.is_barbarian(owner):
        return "b"
    if owner in state.leaders:
        return str(owner) if owner < 10 else "R"
    return "?"


class Renderer(object):
    """Base class: one subclass per view, each owning its own glyph priorities."""

    name = None
    tracks_fog = False
    omits = ()
    # Which shared-legend symbols this view can actually emit. Kept as an explicit
    # declaration rather than inferred, so a view that starts drawing something new
    # has to say so and cannot silently under-document itself.
    shows = ()
    # Most views spend their cell on marker + terrain + overlay. `yields` spends it
    # on three digits instead and needs one more column for its marker.
    cell_width = 3

    def __init__(self, state, around, radius):
        self.state = state
        self.around = around
        self.radius = radius
        self.own_units_at = {}
        for unit in state.units:
            self.own_units_at.setdefault((unit["x"], unit["y"]), []).append(unit)
        self.foreign_units_at = {}
        for unit in state.foreign_units:
            self.foreign_units_at.setdefault((unit["x"], unit["y"]), []).append(unit)
        self.own_cities_at = dict(((c["x"], c["y"]), c) for c in state.cities)
        self.foreign_cities_at = dict(
            ((c["x"], c["y"]), c) for c in state.foreign_cities
        )
        self.prepare()

    def prepare(self):
        pass

    def marker(self, pos, tile):
        raise NotImplementedError

    def overlay(self, pos, tile):
        raise NotImplementedError

    def fog_marker(self, tile):
        if self.tracks_fog and not tile.get("visibleNow"):
            return "'"
        return " "

    def cell(self, pos):
        tile = self.state.tiles.get(pos)
        if tile is None:
            return UNREVEALED_MARK.center(self.cell_width)
        return self.marker(pos, tile) + base_glyph(tile) + self.overlay(pos, tile)

    def shared_legend(self):
        """The shared symbol block, filtered to what this view can actually draw."""
        capable = set(self.shows)
        if self.tracks_fog:
            capable.add("fog")
        lines = ["  SHARED SYMBOLS (same meaning in every view that shows them)"]
        lines.extend(
            line for capability, line in GLOBAL_LEGEND_ENTRIES
            if capability is None or capability in capable
        )
        return lines

    def legend(self):
        raise NotImplementedError

    def extra_sections(self):
        return []


# Legend lines are operating instructions, not rationale. Why a glyph is the way it
# is belongs in harness/README.md and in the comments here - both read once. What goes
# in a render is the decode table plus any trap that would cause a WRONG ACTION if
# missed. Every line costs on every call, and the grid has to stay much cheaper than
# the JSON it saves you reading.
# A symbol means the SAME THING in every view. Where two views need the same kind of
# fact they use the same glyph; where a glyph was doing different jobs in different
# views it was changed rather than explained away. The column a glyph sits in says
# what KIND of fact it is - that is what each view's `cell = [...]` line is for - but
# no glyph ever changes meaning between views.
# Each entry is (capability, line). A line with capability None is in every view that
# draws a terrain grid; the rest appear only where the view can actually emit that
# glyph. Advertising an inactive symbol is not merely noise - `settle` used to list
# "' revealed but FOGGED" three lines above its own "this view omits fog", which is a
# flat contradiction on the page. Filtering keeps the block honest AND still shared:
# a symbol that appears has the same meaning everywhere it appears.
GLOBAL_LEGEND_ENTRIES = (
    (None, "    terrain  g grass  p plains  d desert  t tundra  s snow"
           "   - coast  ~ ocean  o lake"),
    (None, "             UPPERCASE = hills ('P' plains-hills)   ^ peak (impassable)"),
    (None, "    feature  f forest  j jungle  = flood plains  @ oasis  I ice  ! fallout"),
    ("own_cities", "    who      C your city"),
    ("rival_cities", "             c rival city"),
    ("own_units", "             S your settler   W your worker   U your other unit"),
    ("rival_units",
     "             digit  a rival unit, by player id   b  BARBARIANS"),
    ("resource", "    tile     *  resource"),
    ("worked", "             #  worked by a citizen this turn"),
    ("worked", "             ,  in a city radius but not worked"),
    ("territory", "             +  your territory"),
    ("fog", "             '  revealed but FOGGED"),
    (None, "             .  never revealed - unknown, not empty"),
)

# Kept separate only so views can append their own note to the same line.
class SettleRenderer(Renderer):
    """Where to found a city."""

    name = "settle"
    tracks_fog = False
    # Five columns: [marker][terrain+relief][feature][resource][water]. Every one of
    # these is first-order for city placement and they all coexist freely - grassland
    # hills + forest + gems + fresh water is one ordinary tile. Sharing a slot meant a
    # priority rule, and whatever lost was invisible rather than merely abbreviated.
    # Not hypothetical: 9 of 266 tiles in the baseline run at t40 carry both a resource
    # and a feature (jungle dye/banana/rice, forest spices).
    cell_width = 5
    shows = ("own_cities", "rival_cities", "own_units", "resource")
    omits = (
        ("fog: revealed and visible are drawn alike", "--view military / explore"),
        ("every unit but your settlers, incl. threats", "--view military"),
        ("improvements, routes, worked tiles", "--view worker"),
        ("per-tile yield numbers", "--view yields"),
    )

    def prepare(self):
        self.blocked = self.state.blocked_by_city_range()
        self.settlers = [u for u in self.state.units if u["type"] == "UNIT_SETTLER"]
        self.settlers_at = set((u["x"], u["y"]) for u in self.settlers)

    def marker(self, pos, tile):
        if pos in self.own_cities_at:
            return "C"
        if pos in self.foreign_cities_at:
            return "c"
        # The settler is the actor for this decision - where it stands is how far it
        # has to walk. Other units belong to other views.
        if pos in self.settlers_at:
            return "S"
        # This column answers one question - can I found here - and answers it
        # POSITIVELY. 'A' is marked rather than left blank because the two failure
        # directions are not symmetric: reading water as available is caught at once
        # by the terrain glyph, while reading an available tile as blocked silently
        # loses a site. Blank previously meant both "you may found here" and "this is
        # ocean, the question does not apply", which is the same one-glyph-two-facts
        # bug the water column had.
        #
        # The two blockers get SEPARATE glyphs because they mean different things to
        # a settler: ']' is a rival's cultural border, which can move and which you
        # could take, while 'x' is a city too close, permanent while that city stands.
        # ']' rather than 'X': an x/X case pair would put the two blockers one
        # keystroke apart in a column where misreads have already happened.
        # Terrain-unfoundable tiles (water, peak, ice, oasis) stay BLANK on purpose -
        # once available is positively marked, blank unambiguously means "terrain
        # rules this out", and column 2 already says which. Marking them too would
        # cost ~23% of all cells to restate something unambiguous.
        #
        # A player-id digit deliberately does NOT appear here: a digit means "a rival
        # unit is standing here" in every view, and reusing it for ownership would
        # make one glyph mean two things. Whose border it is: --view military.
        blockers = self.state.found_blockers(pos)
        if not blockers:
            return "A"
        # Terrain wins over every other blocker. Water two tiles from a city was
        # rendering 'x', which the legend explicitly promises means LAND you cannot
        # use - so the grid was contradicting its own key on ~100 ocean tiles.
        if any("water" in b or "peak" in b or "cannot hold a city" in b
               for b in blockers):
            return " "
        owner = tile.get("owner")
        if owner is not None and owner != self.state.player_id:
            return "]"
        return "x"

    def overlay(self, pos, tile):
        feature = FEATURE_GLYPH.get(tile.get("feature"), " ")
        resource = "*" if tile.get("bonus") else " "
        return feature + resource + water_glyph(self.state, pos, tile)

    def legend(self):
        return [
            "  cell = [marker][terrain+relief][feature][resource][water]",
        ] + self.shared_legend() + [
            "  THIS VIEW",
            "    marker   A  YOU MAY FOUND HERE",
            "             cannot found, for two different reasons:",
            "             x  ANY city, yours or a rival's, within %d - permanent"
            % MIN_CITY_RANGE,
            "                while that city stands",
            "             ]  inside a rival's border - can move, and can be taken",
            "             (blank) terrain rules it out - water, peak, ice or oasis;",
            "                     column 2 says which",
            "    water    _  neither      :  fresh water, no river      /  river",
            "             ~  sea access only",
            "             %  sea + fresh water but NO river (a lake or an oasis)",
            "             &  sea + river (whether or not there is also a lake)",
            "             (blank) the tile is itself water, so the question does not"
            " apply",
            "             fresh water = a river, OR beside a lake or oasis -",
            "                           EQUIVALENT for farms and health. A river also",
            "                           adds +1 commerce to a WORKED tile (already in",
            "                           the yield shown) but NOT to a city centre,",
            "                           which floors at 2/1/1. Levee and Hydro Plant",
            "                           are far past this scope.",
            "             sea access  = one of the 8 NEIGHBOURS is non-lake water,",
            "                           which is what a Harbour and Lighthouse need.",
            "                           Sea inside the 21-tile cross is NOT enough.",
            "  TRAPS  'x' assumes same landmass (not exported): over-reports across",
            "         water, never under-reports. Owners under fog may be stale.",
            "         Territory is not drawn here - see --view military.",
            "         --around X,Y gives the full site report for one tile.",
        ]

    def extra_sections(self):
        # The settler glyph occupies the marker column, hiding the availability of
        # the one tile most worth knowing about - "can I just settle in place?" is
        # the whole question on turn 0. There are only ever one or two settlers, so
        # the answer goes here in words rather than costing the grid a column.
        rows = []
        for unit in self.settlers:
            pos = (unit["x"], unit["y"])
            blockers = self.state.found_blockers(pos)
            rows.append(
                "  (%d,%d) %-16s id %-6d moves %d  -- founding HERE: %s"
                % (
                    unit["x"], unit["y"], unit["type"], unit["id"], unit["moves"],
                    "BLOCKED (%s)" % blockers[0] if blockers else "legal",
                )
            )
        sections = [("Your settlers", rows or ["  none alive - nothing to place"])]
        # Scoped to whatever the grid above actually drew. A cropped grid beside a
        # whole-map resource list invites reading a resource into a crop it is
        # nowhere near.
        xs, ys, _ = select_region(self.state, self.around, self.radius)
        region = set(xs)
        rows_in_view = set(ys)
        bonuses = []
        for pos in sorted(self.state.tiles, key=lambda p: (p[1], p[0])):
            tile = self.state.tiles[pos]
            if not tile.get("bonus"):
                continue
            if pos[0] not in region or pos[1] not in rows_in_view:
                continue
            bonuses.append(
                "  (%d,%d) %-18s on %-10s %-6s %s"
                % (
                    pos[0], pos[1],
                    tile["bonus"],
                    tile["terrain"].replace("TERRAIN_", ""),
                    relief_label(tile),
                    (tile.get("feature") or "").replace("FEATURE_", ""),
                )
            )
        scope = "in this crop" if self.around is not None else "revealed"
        if bonuses:
            sections.append(
                ("Resources %s (grid shows only '*')" % scope, bonuses)
            )
        else:
            sections.append(("Resources %s" % scope, ["  none"]))

        if self.around is not None:
            sections.append(self._cross_table())
        else:
            # Name a real tile from this very map. The agent trial that prompted
            # this never invoked --around despite wanting it twice; an abstract
            # "X,Y" is a placeholder to skim past, a concrete legal site is a
            # command to run.
            example = self._example_site()
            hint = ["  --around X,Y gives a site's 21 workable tiles as a yield"
                    " table, plus"]
            hint.append("  coastal / fresh water / overlap / legality for that tile.")
            if example is not None:
                hint.append("")
                hint.append("  e.g.  --view settle --around %d,%d" % example)
            sections.append(("City cross", hint))
        return sections

    def _example_site(self):
        """A real legal tile to name in the --around hint, or None.

        Nearest legal tile to a settler if one is alive, else any legal tile.
        Deliberately NOT the best tile - this is a worked example of the flag, and
        picking a "best" one would be ranking, which this tool does not do.
        """
        legal = [
            pos for pos in sorted(self.state.tiles)
            if not self.state.found_blockers(pos)
        ]
        if not legal:
            return None
        if self.settlers:
            origin = (self.settlers[0]["x"], self.settlers[0]["y"])
            return min(legal, key=lambda p: (self.state.distance(origin, p), p))
        return legal[0]

    def _cross_table(self):
        cx, cy = self.around
        state = self.state
        cross = state.city_cross(cx, cy)
        centre = state.tiles.get(self.around)

        rows = ["  SITE (%d,%d)" % (cx, cy)]

        fatal = self._fatal_verdict(centre)
        if fatal:
            return ("City cross for --around", rows + fatal + [""]
                    + self._cross_rows(cross))

        if centre is not None:
            rows.extend(self._site_header(centre))
        overlap = state.overlap_with_own_cities(cross)
        if overlap:
            rows.append(
                "    overlap    %s"
                % ", ".join("%d tiles shared with %s" % (n, name)
                            for name, n in overlap)
            )
        for unit in self.settlers:
            start = (unit["x"], unit["y"])
            rows.append(
                "    settler    id %d at (%d,%d) - %s"
                % (unit["id"], unit["x"], unit["y"],
                   describe_distance(state, start, self.around))
            )

        rows.append("")
        rows.extend(self._cross_rows(cross))
        rows.append("")
        rows.extend(self._cross_counts(cross))
        blockers = self.state.found_blockers(self.around)
        if blockers:
            rows.append("  Founding at (%d,%d): BLOCKED" % (cx, cy))
            for reason in blockers:
                rows.append("    - %s" % reason)
        else:
            rows.append(
                "  Founding at (%d,%d): legal as far as the export can tell"
                " (terrain, features, ownership and MIN_CITY_RANGE all checked)."
                % (cx, cy)
            )
        return ("City cross for --around", rows)

    def _fatal_verdict(self, centre):
        """Lines for a tile that can never hold a city, or [] if it can.

        Leads with the verdict. A water or peak tile used to get the full treatment
        - coastal status, water status, the whole advisory - with "BLOCKED" only at
        the very bottom: a lot of authoritative output for a site that cannot exist.
        Worse, "coastal: no - landlocked" and "NO fresh water" are nonsense ABOUT A
        LAKE, and the grid already had the rule this was missing: on a water tile
        the question does not apply.
        """
        fatal = [
            b for b in self.state.found_blockers(self.around)
            if "water" in b or "peak" in b or "cannot hold a city" in b
        ]
        if not fatal:
            return []
        rows = ["    CANNOT EVER BE A CITY: %s" % fatal[0]]
        if centre is not None:
            rows.append(
                "    %s %s - coastal and fresh-water do not apply to a tile that"
                % (centre["terrain"].replace("TERRAIN_", ""), relief_label(centre))
            )
            rows.append("    cannot hold a city at all.")
        rows.append(
            "    The 21 tiles below are still listed - they are what a city NEARBY"
            " could"
        )
        rows.append("    work, so they remain useful for judging the neighbourhood.")
        return rows

    def _site_header(self, centre):
        """Centre terrain, coastal status and fresh water for a foundable site."""
        state = self.state
        coastal, unknown = state.is_coastal(self.around)
        if coastal:
            coast_note = (
                "yes - can build Harbour/Lighthouse, work boats and naval units"
            )
        elif unknown:
            coast_note = ("no, but %d adjacent tile(s) unrevealed - explore before"
                          " ruling it out" % unknown)
        else:
            coast_note = "no - landlocked"

        feature = centre.get("feature")
        rows = [
            "    centre     %s %s%s"
            % (
                centre["terrain"].replace("TERRAIN_", ""),
                relief_label(centre),
                ", " + feature.replace("FEATURE_", "") if feature else "",
            ),
            "    coastal    %s" % coast_note,
        ]
        # Only when ONE STEP converts the answer. Silent otherwise.
        nudge = state.coastal_one_step_away(self.around)
        if nudge:
            shown = ", ".join("(%d,%d)" % p for p in nudge[:3])
            if len(nudge) > 3:
                shown += " and %d more" % (len(nudge) - 3)
            rows.append(
                "               ONE TILE OFF THE COAST. %s %s coastal and legal;"
                % (shown, "is" if len(nudge) == 1 else "are")
            )
            rows.append(
                "               one step buys a Harbour. Sometimes deliberate"
                " - compare the crosses."
            )
        rows.append(
            "    water      %s"
            % ("on a river - fresh water" if centre.get("river")
               else "fresh water, no river" if centre.get("freshWater")
               else "NO fresh water - no early farms, less health")
        )
        # The centre-tile caveat, stated only where a river is actually present.
        # CvPlot::calculateYield floors a city tile at YieldInfo iMinCity (2/1/1),
        # which swallows the river's +1 commerce - so as a CENTRE a river is worth
        # exactly what a lake is. An agent trial paid a turn and a wheat resource to
        # move onto a river centre on the strength of the unqualified wording.
        if centre.get("river"):
            rows.append(
                "               As a CITY CENTRE a river is worth no more than a"
                " lake: the centre"
            )
            rows.append(
                "               floors at 2/1/1, which absorbs the +1 commerce. The"
                " river pays off"
            )
            rows.append("               on the WORKED tiles in the cross, not here.")
        return rows

    def _cross_rows(self, cross):
        """The 21-tile table. Shared by the normal and cannot-ever-be-a-city paths."""
        state = self.state
        rows = [
            "  The 21 tiles a city here could ever work:",
            "  %-9s %-9s %-6s %-13s %-9s %-6s %-5s %s"
            % ("tile", "terrain", "relief", "feature", "resource", "water", "coast",
               "F/P/C"),
        ]
        for pos in cross:
            tile = state.tiles.get(pos)
            if tile is None:
                rows.append("  %-9s %s" % ("(%d,%d)" % pos, "-- never revealed --"))
                continue
            yields = tile["yields"]
            rows.append(
                "  %-9s %-9s %-6s %-13s %-9s %-6s %-5s %d/%d/%d%s"
                % (
                    ("(%d,%d)" % pos,
                     tile["terrain"].replace("TERRAIN_", ""),
                     relief_label(tile),
                     (tile.get("feature") or "-").replace("FEATURE_", ""),
                     (tile.get("bonus") or "-").replace("BONUS_", ""))
                    + water_labels(state, pos, tile)
                    + (yields[0], yields[1], yields[2],
                       "+" if yield_is_improved(tile) else "")
                )
            )
        if any(
            yield_is_improved(state.tiles[p]) for p in cross if p in state.tiles
        ):
            rows.append("")
            rows.extend(IMPROVED_YIELD_NOTE)
        return rows

    def _cross_counts(self, cross):
        """How many chances the site gives you, never how good they are.

        This replaced a yield TOTAL. A sum implies a ranking it cannot support:
        coast is 1/0/2 forever and already at its ceiling, while grass-jungle
        reads 1/0/0 today and 2/0/0 once a worker clears it - so summing current
        yields rewards finished tiles and punishes improvable ones, which is
        backwards. Good early sites are made by one or two great tiles anyway,
        and a sum cannot see a great tile at all. Counts say what is there; the
        table above says how good it is; the reader decides.

        DEAD is bare flat desert and peaks - see is_dead_tile for why those two
        and nothing else. Jungle reading 0/1/0 is emphatically NOT dead; it is a
        worker's to-do item, and counting it here would smuggle the TOTAL's bias
        back in through the counts.
        """
        state = self.state
        # Tiles already inside one of your own cities' radii. A count that includes
        # them describes your empire, not what this site ADDS - and it inflates
        # exactly the sites that overlap most, i.e. the ones that gain you least.
        # At turn 34 (78,15) and (79,13) read 13 vs 12 workable land, near-identical;
        # counting only new land they are 7 vs 11.
        already = set()
        for city in state.cities:
            already.update(state.city_cross(city["x"], city["y"]))

        land = water = dead = unrevealed = resources = 0
        new_land = new_water = new_resources = 0
        for pos in cross:
            tile = state.tiles.get(pos)
            if tile is None:
                unrevealed += 1
                continue
            fresh = pos not in already
            if tile.get("bonus"):
                resources += 1
                new_resources += fresh
            plot = tile.get("plotType")
            if is_dead_tile(tile):
                dead += 1
            elif plot == "PLOT_OCEAN":
                # Lakes count as workable water, not a separate class. A citizen
                # works them on the same terms, and CvPlot::calculateYield gates the
                # Lighthouse/Harbour sea-plot bonus on isWater() with no lake
                # exclusion, so a Lighthouse improves a lake tile like any other.
                # What lakes DO change - fresh water for the city - is a property of
                # the centre tile and is already reported above as `water`.
                water += 1
                new_water += fresh
            else:
                land += 1
                new_land += fresh
        overlap = sum(n for _, n in state.overlap_with_own_cities(cross))
        landlocked = (
            state.tiles.get(self.around) is not None
            and not state.is_coastal(self.around)[0]
        )

        rows = [
            "  OF THE 21 TILES",
            "    %2d workable land" % land,
            # The Harbour/Lighthouse clause only makes sense if this site can build
            # them. On a landlocked centre it contradicts the note printed three
            # lines below, in the very spot that note exists to clarify.
            "    %2d workable water   sea and lake alike - a citizen works both the"
            " same%s" % (water, "" if landlocked else ", and"),
        ] + ([] if landlocked else [
            "                         the Lighthouse/Harbour sea bonus applies to"
            " both too",
        ]) + [
            "    %2d dead             bare flat desert (0/0/0), and peaks, which no"
            " citizen" % dead,
            "                         can be assigned to at all",
            "    %2d never revealed   unknown - could be anything" % unrevealed,
            "    %2d already inside one of your cities' radii" % overlap,
            "    %2d carrying a visible resource" % resources,
        ] + ([] if not overlap else [
            "",
            "    NEW to your empire, i.e. excluding the %d overlapping tile%s:"
            % (overlap, "" if overlap == 1 else "s"),
            "    %2d land   %2d water   %2d with a resource" % (
                new_land, new_water, new_resources),
            "    Those are what this site ADDS. The counts above describe the whole",
            "    cross, so they credit this site with land you already own.",
        ]) + [
        ]
        rows.append(
            "  Counts, not a score. A city works pop+1 tiles, so 1-2 strong tiles"
            " usually"
        )
        rows.append(
            "  decide a site - read the table, not these numbers, for that."
        )
        # Fires only when it changes how the counts should be read. An agent trial
        # compared "17 workable land" against "15" and took the landlocked site;
        # the coastal fact was prose above the table while the land/water split was
        # numbers inside it, which is an invitation to weigh the wrong thing.
        if water and landlocked:
            rows.extend(self._landlocked_note(water))
        return rows

    def _landlocked_note(self, water):
        """What a non-coastal centre costs, stated without overstating it.

        NOT "water tiles are wasted" - CvCity::canWork gates water on
        CvTeam::isWaterWork(), which TECH_FISHING sets for the whole team, so a
        landlocked city works its water tiles like any other. What it actually
        loses is the Harbour/Lighthouse (both bWater, so coastal-only), work
        boats, and the naval options below.
        """
        return [
            "  NOT COASTAL - how to read the %d water tile(s) above:" % water,
            "    they ARE workable (Fishing enables water tiles team-wide), but this",
            "    city can build no Harbour and no Lighthouse, so they stay at base",
            "    yield, and no work boat can ever improve seafood among them.",
            "    Strategically it also gives up naval unit production and overseas",
            "    trade routes from this city. A strong enough site can outweigh all",
            "    of that - but decide it, do not let the land count decide it.",
        ]


class ExploreRenderer(Renderer):
    """Where to send a scout."""

    name = "explore"
    tracks_fog = True
    # Features get their own column: forest and jungle cost 2 moves, which is half
    # the reason one direction is cheaper to scout than another.
    cell_width = 4
    shows = ("own_cities", "own_units")
    omits = (
        ("rival units, rival cities, territory", "--view military"),
        ("resources, rivers, fresh water", "--view settle"),
        ("improvements, routes, worked tiles", "--view worker"),
    )

    def prepare(self):
        self.frontier = self.state.frontier()

    def marker(self, pos, tile):
        if pos in self.own_units_at:
            return own_unit_glyph(self.own_units_at[pos])
        if pos in self.own_cities_at:
            return "C"
        return self.fog_marker(tile)

    def overlay(self, pos, tile):
        feature = FEATURE_GLYPH.get(tile.get("feature"), " ")
        if tile.get("improvement") == "IMPROVEMENT_GOODY_HUT":
            target = "?"
        elif pos in self.frontier:
            target = ">"
        else:
            target = " "
        return feature + target

    def legend(self):
        return [
            "  cell = [marker][terrain+relief][feature][where to go]",
        ] + self.shared_legend() + [
            "  THIS VIEW",
            "    marker   (blank) visible now",
            "    go       ?  goody hut     >  frontier: touches unexplored map",
            "  Forest and jungle cost 2 moves; peaks and water are impassable to land.",
            "  TRAPS  unit stacks collapse to one marker; the list below is complete.",
        ]

    def extra_sections(self):
        rows = []
        for unit in sorted(self.state.units, key=lambda u: (u["y"], u["x"], u["id"])):
            rows.append(
                "  (%d,%d) %-16s id %-6d moves %d%s"
                % (
                    unit["x"], unit["y"], unit["type"], unit["id"], unit["moves"],
                    "  damage %d%%" % unit["damage"] if unit.get("damage") else "",
                )
            )
        sections = [("Your units", rows or ["  none"])]
        huts = []
        for pos in sorted(self.state.tiles, key=lambda p: (p[1], p[0])):
            if self.state.tiles[pos].get("improvement") == "IMPROVEMENT_GOODY_HUT":
                huts.append(
                    "  (%d,%d)%s" % (
                        pos[0], pos[1],
                        "" if self.state.tiles[pos].get("visibleNow")
                        else "  (fogged - remembered, may already be taken)",
                    )
                )
        sections.append(("Goody huts", huts or ["  none revealed"]))
        sections.append((
            "Frontier",
            ["  %d of %d revealed tiles touch unexplored map."
             % (len(self.frontier), len(self.state.tiles))],
        ))
        return sections


class MilitaryRenderer(Renderer):
    """What can reach you, and what you can currently see."""

    name = "military"
    tracks_fog = True
    # Features get their own column: forest and jungle are +50% defence and cost 2
    # moves, so they decide where a fight happens as much as ownership does.
    cell_width = 4
    shows = ("own_cities", "rival_cities", "own_units", "rival_units", "territory")
    omits = (
        ("resources, rivers, fresh water", "--view settle"),
        ("the unexplored frontier, goody huts", "--view explore"),
        ("improvements, routes, worked tiles", "--view worker"),
    )

    def marker(self, pos, tile):
        if pos in self.foreign_units_at:
            return foreign_unit_glyph(self.state, self.foreign_units_at[pos])
        if pos in self.foreign_cities_at:
            return "c"
        if pos in self.own_cities_at:
            return "C"
        if pos in self.own_units_at:
            return own_unit_glyph(self.own_units_at[pos])
        return self.fog_marker(tile)

    def overlay(self, pos, tile):
        feature = FEATURE_GLYPH.get(tile.get("feature"), " ")
        owner = tile.get("owner")
        if owner is None:
            territory = " "
        elif owner == self.state.player_id:
            territory = "+"
        else:
            territory = "%d" % owner if owner < 10 else "R"
        return feature + territory

    def legend(self):
        return [
            "  cell = [marker][terrain+relief][feature][territory]",
        ] + self.shared_legend() + [
            "  THIS VIEW",
            "    marker     a digit means a rival UNIT is standing on the tile",
            "               (blank) means the tile is visible right now",
            "    territory  a digit means that player OWNS the tile",
            "  Defence: forest +50%, jungle +50%, hills +25% (they stack).",
            "  READ THE FOG FIRST. Rival units are reported ONLY on visible tiles, so",
            "  a fogged region renders as no enemies whether or not any are there.",
            "  Absence of a threat on a ' tile means nothing at all.",
            "  TRAPS  rival units are forgotten between turns; rival cities persist.",
            "         Unit stacks collapse to one marker; the list below is complete.",
        ]

    def extra_sections(self):
        state = self.state
        rows = []
        for unit in state.foreign_units:
            pos = (unit["x"], unit["y"])
            nearest = ""
            if state.cities:
                best = min(
                    state.cities,
                    key=lambda c: state.distance(pos, (c["x"], c["y"])),
                )
                gap = state.distance(pos, (best["x"], best["y"]))
                compass = state.bearing((best["x"], best["y"]), pos)
                where = "%s of %s" % (compass, best["name"]) if compass else "in %s" % best["name"]
                nearest = "  %d %s %s" % (
                    gap, "tile" if gap == 1 else "tiles", where,
                )
            rows.append(
                "  (%d,%d) %-16s owner %s%s%s"
                % (
                    unit["x"], unit["y"], unit["type"],
                    state.owner_of(unit["owner"]),
                    "  damage %d%%" % unit["damage"] if unit.get("damage") else "",
                    nearest,
                )
            )
        sections = [(
            "Rival units in sight RIGHT NOW (this is not everything that exists)",
            rows or ["  none visible this turn"],
        )]

        rows = []
        for city in state.foreign_cities:
            tile = state.tiles.get((city["x"], city["y"]))
            seen = "visible now" if tile and tile.get("visibleNow") else "fogged - population and name are live, but nothing else is known"
            rows.append(
                "  (%d,%d) %-14s pop %-3d owner %s%s"
                % (
                    city["x"], city["y"], city["name"], city["population"],
                    state.owner_of(city["owner"]),
                    "  CAPITAL" if city.get("capital") else "",
                )
            )
            rows.append("           %s" % seen)
        sections.append(("Rival cities you have seen", rows or ["  none seen"]))

        rows = []
        for contact in state.contacts:
            rows.append(
                "  player %-3d %-18s %-24s %-20s %s"
                % (
                    contact["playerId"], contact["leader"], contact["civilization"],
                    contact["attitude"],
                    "AT WAR" if contact["atWar"] else "not at war",
                )
            )
        sections.append(("Civs met", rows or ["  none met"]))

        # The grid has always drawn your units; only the coordinate list was missing,
        # so answering "what can I defend with / what is exposed" meant running a
        # different view. Both sides of a military question belong in one place.
        rows = []
        for unit in sorted(state.units, key=lambda u: (u["y"], u["x"], u["id"])):
            pos = (unit["x"], unit["y"])
            nearest = ""
            if state.foreign_units:
                closest = min(
                    state.foreign_units,
                    key=lambda f: state.distance(pos, (f["x"], f["y"])),
                )
                closest_pos = (closest["x"], closest["y"])
                gap = state.distance(pos, closest_pos)
                compass = state.bearing(pos, closest_pos)
                where = " %s" % compass if compass else ""
                nearest = "  nearest rival in sight %d %s%s" % (
                    gap, "tile" if gap == 1 else "tiles", where,
                )
            rows.append(
                "  (%d,%d) %-16s id %-6d moves %d%s%s"
                % (
                    unit["x"], unit["y"], unit["type"], unit["id"], unit["moves"],
                    "  damage %d%%" % unit["damage"] if unit.get("damage") else "",
                    nearest,
                )
            )
        sections.append(("Your units", rows or ["  none"]))
        return sections


class OwnEmpireRenderer(Renderer):
    """Shared machinery for the two views about your own cities."""

    def prepare(self):
        self.worked = self.state.worked_tiles()
        self.workable = set()
        for city in self.state.cities:
            self.workable.update(self.state.city_cross(city["x"], city["y"]))

    def city_header_rows(self, city):
        # An empty queue used to render as "nothing 0/- (+5/turn)", which reads as a
        # formatting failure rather than as the actionable fact it is.
        if city["producing"] is None:
            build = "BUILDING NOTHING - %d hammers/turn going nowhere" % (
                city["productionPerTurn"],
            )
        elif city["productionNeeded"] is None:
            build = "%s %+d/turn (a process: never completes)" % (
                city["producing"], city["productionPerTurn"],
            )
        else:
            build = "%s %d/%d (%+d/turn)" % (
                city["producing"], city["production"],
                city["productionNeeded"], city["productionPerTurn"],
            )
        rows = [
            "  %s (%d,%d) pop %d, %d/%d food (%+d/turn), %s"
            % (
                city["name"], city["x"], city["y"], city["population"],
                city["food"], city["growthThreshold"], city["foodPerTurn"],
                build,
            ),
        ]
        # foodPerTurn<=0 alone is ambiguous - a Settler or Worker costs 1 pop
        # regardless of how its hammers happen to be funded that turn, so the
        # city isn't "stuck", it's paused on purpose for the build. Checking
        # productionFromFood==0 doesn't tell them apart: a Worker/Settler can
        # show 0 there too (all-hammer turn, food banked for later in the
        # build) and still be exactly this deliberate case. Check the unit
        # type building, not the turn's funding split.
        if (city["foodPerTurn"] <= 0
                and city["producing"] not in FOOD_COST_UNITS):
            rows.append(
                "  NOT GROWING: 0 or negative food this turn, and it isn't a"
                " Settler/Worker build spending it on purpose."
            )
        rows.append(
            "  culture %d/%d, happy %d vs unhappy %d, healthy %d vs unhealthy %d"
            % (
                city["culture"], city["cultureThreshold"],
                city["happy"], city["unhappy"],
                city["healthy"], city["unhealthy"],
            )
        )
        return rows


class YieldsRenderer(OwnEmpireRenderer):
    """Which tiles your citizens should work.

    The only question here is yields, so the grid spends its whole cell on the
    three numbers instead of terrain letters.
    """

    name = "yields"
    tracks_fog = False
    cell_width = 4
    # No terrain or feature glyphs at all - the cell is three digits - so this view
    # declares only the marker symbols it can actually emit.
    shows = ("own_cities", "worked")
    omits = (
        ("WHY a tile yields what it does (terrain, features)", "--view settle"),
        ("improvements and roads: what a tile could yield", "--view worker"),
        ("all rival units and cities", "--view military"),
    )

    def marker(self, pos, tile):
        if pos in self.own_cities_at:
            return "C"
        if pos in self.worked:
            return "#"
        if pos in self.workable:
            return ","
        return " "

    def cell(self, pos):
        tile = self.state.tiles.get(pos)
        if tile is None:
            return UNREVEALED_MARK.center(self.cell_width)
        yields = tile["yields"]
        digits = "".join("+" if v > 9 else str(v) for v in yields[:3])
        return self.marker(pos, tile) + digits

    def overlay(self, pos, tile):  # unused: cell() is overridden
        return " "

    def legend(self):
        return [
            "  cell = [marker][food][production][commerce]",
        ] + self.shared_legend() + [
            "  THIS VIEW  the three digits are food/production/commerce.",
            "             A 0 is a real 0.",
            "             These are DISPLAYED yields, so an improved tile",
            "             already shows the improved number. The per-city tables",
            "             below mark those with '+' - see the note there before",
            "             comparing a developed tile against an undeveloped one.",
            "             C is your city centre - worked for free.",
            "             (blank) marker = outside every city radius.",
            "  A city works pop+1 tiles, centre free; the rest are specialists.",
            "  TRAPS  displayed yields, so improvement/route/owner are baked in.",
            "         Deep ocean reads 000 whatever it is. Unowned land already has",
            "         your traits applied, so its commerce can DROP when claimed.",
        ]

    def extra_sections(self):
        sections = []
        for city in self.state.cities:
            rows = self.city_header_rows(city)
            worked = set((t[0], t[1]) for t in city["workedTiles"])
            rows.append(
                "  %-9s %-7s %-9s %-6s %-13s %-11s %s"
                % ("tile", "status", "terrain", "relief", "feature", "improvement",
                   "F/P/C")
            )
            totals = [0, 0, 0]
            for pos in self.state.city_cross(city["x"], city["y"]):
                tile = self.state.tiles.get(pos)
                if tile is None:
                    rows.append("  %-9s -- not in map.tiles --" % ("(%d,%d)" % pos))
                    continue
                # The centre is always worked and always counts; labelling it "worked"
                # would hide that it costs no citizen.
                is_centre = pos == (city["x"], city["y"])
                status = "CENTRE" if is_centre else ("worked" if pos in worked else "-")
                if pos in worked:
                    for i in range(3):
                        totals[i] += tile["yields"][i]
                rows.append(
                    "  %-9s %-7s %-9s %-6s %-13s %-11s %d/%d/%d%s"
                    % (
                        "(%d,%d)" % pos, status,
                        tile["terrain"].replace("TERRAIN_", ""),
                        relief_label(tile),
                        (tile.get("feature") or "-").replace("FEATURE_", ""),
                        (tile.get("improvement") or "-").replace("IMPROVEMENT_", ""),
                        tile["yields"][0], tile["yields"][1], tile["yields"][2],
                        "+" if yield_is_improved(tile) else "",
                    )
                )
            rows.append(
                "  TOTAL of tiles actually worked (CENTRE is always worked and is"
                " included): %d food / %d prod / %d commerce"
                % (totals[0], totals[1], totals[2])
            )
            specialists = city["population"] + 1 - len(city["workedTiles"])
            rows.append(
                "  citizens: %d worked tiles (incl. free centre) + %d specialist(s)"
                % (len(city["workedTiles"]), specialists)
            )
            sections.append(("City: %s - all 21 workable tiles" % city["name"], rows))
        if not sections:
            # The per-city allocation tables are what is missing, NOT the grid: the
            # yield numbers above are the whole point of this view and are exactly
            # what `settle` cannot show. Saying "nothing to allocate" up front reads
            # as "this render is useless", which it is not.
            sections.append((
                "Cities",
                ["  No cities yet, so there are no citizens to allocate and no",
                 "  per-city tables below.",
                 "  The GRID ABOVE IS STILL THE POINT: it is the food/production/",
                 "  commerce of every revealed tile, which is what --view settle",
                 "  cannot tell you. Use it to compare candidate sites tile by tile,",
                 "  then --view settle --around X,Y for one site's full cross."],
            ))
        return sections


class WorkerRenderer(OwnEmpireRenderer):
    """What your workers should build, and where.

    Deliberately stops short of saying whether you CAN build a given improvement:
    that needs the bonus -> build -> tech chain out of the game's XML, which is
    the rules-lookup tool's job and would make this tool depend on a Civ IV
    install. This view locates the candidate tiles; `rules.py improvement --at`
    finishes the question for any one of them.
    """

    name = "worker"
    tracks_fog = False
    # Features get their own column rather than losing to the improvement glyph:
    # whether a tile is jungle is itself a worker order (clear it), and it does not
    # stop being true because something is already built there.
    cell_width = 4
    shows = ("own_cities", "own_units", "resource", "worked")
    omits = (
        ("which improvement a tile wants, what it would yield, and the tech "
         "for it", "rules.py improvement --at X,Y"),
        ("per-tile yield numbers", "--view yields"),
        ("rival cities, territory, and the fog that hides rival units",
         "--view military"),
    )

    def marker(self, pos, tile):
        if pos in self.own_cities_at:
            return "C"
        if pos in self.own_units_at:
            return own_unit_glyph(self.own_units_at[pos])
        if pos in self.worked:
            return "#"
        if pos in self.workable:
            return ","
        return " "

    def overlay(self, pos, tile):
        feature = FEATURE_GLYPH.get(tile.get("feature"), " ")
        improvement = tile.get("improvement")
        if improvement:
            built = IMPROVEMENT_GLYPH.get(improvement, "i")
        elif tile.get("bonus"):
            built = "*"
        elif tile.get("route"):
            built = "r"
        else:
            built = " "
        return feature + built

    def legend(self):
        return [
            "  cell = [marker][terrain+relief][feature][what is built]",
        ] + self.shared_legend() + [
            "  THIS VIEW",
            "    built    F farm  M mine  n cottage/hamlet/village/town  P pasture",
            "             K camp  L plantation  Q quarry  H workshop  V winery",
            "             B lumbermill  N boats  T fort  ? goody hut  R ruins  i other",
            "             r  road with nothing else built on the tile",
            "  A feature is itself work: clearing jungle is a worker order.",
            "  '#' marker + '*' built is the strongest signal: an unimproved resource",
            "  a citizen is already working. ',' + '*' is next.",
            "  TRAPS  improvements and routes are REMEMBERED, so stale under fog.",
            "         This view does not know what you can BUILD - see omissions.",
        ]

    def extra_sections(self):
        sections = []
        state = self.state

        rows = []
        for pos in sorted(self.workable, key=lambda p: (p[1], p[0])):
            tile = state.tiles.get(pos)
            if tile is None or not tile.get("bonus") or tile.get("improvement"):
                continue
            rows.append(
                "  (%d,%d) %-18s on %-10s %-16s %s"
                % (
                    pos[0], pos[1], tile["bonus"],
                    tile["terrain"].replace("TERRAIN_", ""),
                    (tile.get("feature") or "-").replace("FEATURE_", ""),
                    "worked now" if pos in self.worked else "not worked",
                )
            )
        sections.append((
            "Unimproved resources inside a city radius",
            rows or ["  none - every resource you can reach is already improved"],
        ))

        rows = []
        for pos in sorted(self.worked, key=lambda p: (p[1], p[0])):
            tile = state.tiles.get(pos)
            if tile is None or tile.get("improvement") or pos in self.own_cities_at:
                continue
            rows.append(
                "  (%d,%d) %-10s %-16s %-16s yields %d/%d/%d"
                % (
                    pos[0], pos[1],
                    tile["terrain"].replace("TERRAIN_", ""),
                    (tile.get("feature") or "-").replace("FEATURE_", ""),
                    (tile.get("bonus") or "-").replace("BONUS_", ""),
                    tile["yields"][0], tile["yields"][1], tile["yields"][2],
                )
            )
        sections.append((
            "Worked tiles with no improvement (a citizen is already standing on the payoff)",
            rows or ["  none - every worked tile is improved or is a city centre"],
        ))

        rows = []
        for pos in sorted(state.tiles, key=lambda p: (p[1], p[0])):
            tile = state.tiles[pos]
            if tile.get("route"):
                rows.append(
                    "  (%d,%d) %-14s %s"
                    % (pos[0], pos[1], tile["route"],
                       "" if tile.get("visibleNow") else "(fogged - remembered)")
                )
        connected = []
        for city in state.cities:
            connected.append(
                "  %s (%d,%d): road on the city tile? %s"
                % (
                    city["name"], city["x"], city["y"],
                    "yes" if (state.tiles.get((city["x"], city["y"])) or {}).get("route")
                    else "no",
                )
            )
        sections.append(("Roads", (rows or ["  none built or seen"]) + connected))

        rows = []
        for city in state.cities:
            rows.extend(self.city_header_rows(city))
            rows.append("")
        sections.append(("Your cities", rows[:-1] if rows else ["  none yet"]))

        rows = []
        for unit in state.units:
            rows.append(
                "  (%d,%d) %-16s id %-6d moves %d"
                % (unit["x"], unit["y"], unit["type"], unit["id"], unit["moves"])
            )
        sections.append(("Your units", rows or ["  none"]))

        # A worker walking to an unimproved resource is unarmed and slow. This view
        # is not the military picture and does not pretend to be - it is the minimum
        # needed to notice that a tile you are about to send a worker to is contested.
        rows = []
        for unit in state.foreign_units:
            pos = (unit["x"], unit["y"])
            nearest = ""
            if state.units:
                closest = min(
                    state.units, key=lambda u: state.distance(pos, (u["x"], u["y"]))
                )
                gap = state.distance(pos, (closest["x"], closest["y"]))
                nearest = "  %d %s from your %s" % (
                    gap, "tile" if gap == 1 else "tiles",
                    closest["type"].replace("UNIT_", "").lower(),
                )
            rows.append(
                "  (%d,%d) %-16s owner %s%s"
                % (unit["x"], unit["y"], unit["type"],
                   state.owner_of(unit["owner"]), nearest)
            )
        sections.append((
            "Rival units in sight - do not walk a worker into these",
            rows or ["  none visible this turn (fogged tiles report nothing:"
                     " --view military)"],
        ))
        return sections


RENDERERS = {
    "settle": SettleRenderer,
    "explore": ExploreRenderer,
    "military": MilitaryRenderer,
    "yields": YieldsRenderer,
    "worker": WorkerRenderer,
}


# -- output ---------------------------------------------------------------


def format_year(year):
    if year < 0:
        return "%d BC" % -year
    return "AD %d" % year


def _preamble(state, view, region_desc, brief):
    """Header echoing the invocation, plus how to read the grid."""
    visible = sum(1 for t in state.tiles.values() if t.get("visibleNow"))
    lines = [
        "civ4-advisor map render",
        "  file    %s" % state.path,
        "  turn    %d (%s, %s)" % (state.turn, format_year(state.year), state.era),
        "  view    %s" % view,
        "  region  %s" % region_desc,
        "  map     %d x %d, wrapX=%s wrapY=%s   |   %d tiles revealed, %d visible now"
        % (
            state.width, state.height,
            str(state.wrap_x).lower(), str(state.wrap_y).lower(),
            len(state.tiles), visible,
        ),
        "  Lossy by design - confirm any tile you act on against map.tiles.",
        "",
    ]
    if brief:
        lines.append(
            "  (--brief: symbol legend and grid-reading notes omitted."
            " Drop --brief for the full key.)"
        )
        # Fog is the one symbol whose absence changes a decision rather than just
        # costing a lookup: a fogged tile reports no enemies whether or not any are
        # there. So the fog key survives --brief in the views that draw it, even
        # though the rest of the legend does not.
        if RENDERERS[view].tracks_fog:
            lines.append(
                "  Fog still applies: a leading ' is REVEALED BUT FOGGED, blank is"
                " visible now,"
            )
            lines.append(
                "  '.' is never revealed. Rival units are reported ONLY on visible"
                " tiles."
            )
    else:
        lines.extend([
            "  READING THE GRID",
            "    columns  every cell is closed by '|'. '||' every %d columns, so you"
            % COLUMN_GROUP,
            "             can count groups of %d instead of cells from the edge."
            % COLUMN_GROUP,
            "    rows     every row shows its y on BOTH the left and the right.",
            "    header   the x header is reprinted every %d rows (a grid of %d rows"
            % (HEADER_EVERY, HEADER_EVERY),
            "             or fewer gets none; a final short block is normal, not a"
            " gap).",
        ])
    lines.append("")
    return lines


def render(state, view, around=None, radius=5, brief=False, site_only=False):
    """Render one view. `brief` drops the legend and the reading-the-grid note.

    Brief exists because an agent making a dozen calls was piping the legend
    through `sed` to get at the content - and stripping a legend by hand is
    exactly how the TRAPS warnings get lost. Better to offer the cut than to
    have it made badly. The TRAPS and THIS VIEW OMITS blocks stay in brief
    output: they are the parts whose absence changes a decision.

    `site_only` (only meaningful with `around`) drops the grid too and prints
    just the preamble plus extra_sections - the site report / city cross a
    caller wanted was already there in extra_sections; four trials found
    `--radius 1` as a workaround (a 3x3 grid still printed, just small) and one
    piped through `sed`, so the grid itself is what needed a way to opt out.
    """
    renderer = RENDERERS[view](state, around, radius)
    xs, ys, region_desc = select_region(state, around, radius)

    lines = _preamble(state, view, region_desc, brief)

    if site_only:
        _append_extra_sections(lines, renderer)
        return "\n".join(lines).rstrip() + "\n"

    if not xs or not ys:
        lines.append("(nothing revealed in this region)")
        return "\n".join(lines)

    # Horizontal indexing is the measured failure mode: agent trials on the 20-column
    # grid repeatedly described a tile as its left neighbour. Three anchors, all
    # cheap, attack it from different directions:
    #   '|' between cells - takes the gutter that was already there, so zero width.
    #   '||' every GROUP columns - turns "count to 13" into "third group, third cell".
    #   the column header repeated every HEADER_EVERY rows - so a reader in the middle
    #     of a tall grid never has to scroll back to re-anchor.
    # Column labels are left-aligned so the ones digit lands on the terrain character.
    cell = renderer.cell_width

    def compose(parts):
        out = ""
        for i, part in enumerate(parts):
            if i and i % COLUMN_GROUP == 0:
                out += "|"
            out += part + "|"
        return out

    header = "     " + compose([("%2d" % x).ljust(cell) for x in xs])
    # A header every HEADER_EVERY MAP ROWS - a fixed stride, so "there is a header
    # every 10 rows" is a rule a reader can rely on rather than measure. Counting
    # map rows and not emitted lines matters: the header is itself a line, so
    # counting output would push each successive header one further down.
    # Any short group lands at the bottom, where the closing header bounds it.
    # ys is already ascending (select_region/axis_window), and y now increases
    # SOUTH (schemaVersion 2 - see AdvisorStateWriter._invertY), so printing
    # ascending y top-to-bottom puts north at the top with no reversal needed.
    body = []
    for row_index, y in enumerate(ys):
        if row_index and row_index % HEADER_EVERY == 0:
            body.append(header)
        body.append(
            "%4d " % y
            + compose([renderer.cell((x, y)).ljust(cell) for x in xs])
            + "%3d" % y
        )
    # Compass rules bounding the grid, rather than a legend entry to look up:
    # the letter sits on the edge it names, in the same place the reader is
    # already looking to find a row's y label.
    width = len(header)
    lines.append(("  N ^ NORTH").ljust(width))
    lines.append(header)
    lines.extend(body)
    lines.append(header)
    lines.append(("  S v SOUTH").ljust(width))
    lines.append("")

    if not brief:
        lines.append("LEGEND")
        lines.extend(renderer.legend())
        lines.append("")

    lines.append("THIS VIEW OMITS")
    for what, where in renderer.omits:
        lines.append("  %-54s ->  %s" % (what, where))
    lines.append("")

    _append_extra_sections(lines, renderer)

    return "\n".join(lines).rstrip() + "\n"


def _append_extra_sections(lines, renderer):
    for title, rows in renderer.extra_sections():
        lines.append(title.upper())
        lines.extend(row.rstrip() for row in rows)
        lines.append("")


def parse_point(text):
    parts = text.replace(" ", "").split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected X,Y (e.g. 75,15), got %r" % text)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        raise argparse.ArgumentTypeError("expected integers, got %r" % text)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="render_map.py",
        description=__doc__.split("\n\n")[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "views:\n"
            "  settle    where to found a city: terrain, resources, fresh water,\n"
            "            existing cities, your settlers, and founding legality\n"
            "            (rival borders + MIN_CITY_RANGE). No fog - by design.\n"
            "  explore   where to send a scout: fog states, the frontier with the\n"
            "            unexplored map, goody huts, barriers, your units.\n"
            "  military  what can reach you: fog states, rival units by owner, rival\n"
            "            cities, territory, defensive terrain.\n"
            "  yields    which tiles your citizens should work: the grid is the raw\n"
            "            food/production/commerce numbers, nothing else.\n"
            "  worker    what your workers should build: improvements, roads and\n"
            "            unimproved resources inside your city radii.\n"
        ),
    )
    parser.add_argument("state_file", help="path to a turn_NNNN.json state file")
    parser.add_argument(
        "--view", choices=VIEWS, default="settle",
        help="which view to render (default: settle)",
    )
    parser.add_argument(
        "--around", type=parse_point, metavar="X,Y",
        help="crop around this tile instead of drawing the whole revealed map",
    )
    parser.add_argument(
        "--radius", type=int, default=5,
        help="crop radius for --around (default: 5). Affects the GRID only - the"
             " site report and its 21-tile cross are always the full city radius.",
    )
    parser.add_argument(
        "--brief", action="store_true",
        help="drop the symbol legend and the reading-the-grid note. Traps and"
             " omissions are kept. Use after the first call in a session.",
    )
    parser.add_argument(
        "--site-only", action="store_true",
        help="requires --around. Skip the grid entirely and print just the site"
             " report / city cross for that tile.",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.state_file):
        parser.error("no such state file: %s" % args.state_file)
    if args.radius < 1:
        parser.error("--radius must be at least 1")
    if args.site_only and args.around is None:
        parser.error("--site-only requires --around")

    state = State(args.state_file)
    sys.stdout.write(
        render(state, args.view, args.around, args.radius, args.brief,
               args.site_only)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
