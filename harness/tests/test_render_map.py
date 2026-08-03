"""Tests for harness/render_map.py.

Every landmark asserted here is derived from the committed sample files, never
from a figure quoted in prose - see `landmarks()` below, which reads them back
out of the JSON so a resample cannot leave the tests asserting fiction.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_map


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DIR = os.path.join(REPO_ROOT, "samples", "baseline-early-game")


def sample(turn):
    return os.path.join(SAMPLE_DIR, "turn_%04d.json" % turn)


def all_samples():
    return sorted(
        os.path.join(SAMPLE_DIR, name)
        for name in os.listdir(SAMPLE_DIR)
        if name.startswith("turn_") and name.endswith(".json")
    )


def state(turn):
    return render_map.State(sample(turn))


# -- grid parsing ---------------------------------------------------------


class Grid(object):
    """The rendered grid, parsed back out of the output text.

    Going through the real output rather than calling Renderer.cell directly is
    the point: orientation lives in how rows are ordered, not in a cell.
    """

    def __init__(self, text):
        lines = text.split("\n")
        # Header lines are the only ones indented a full five spaces; every data
        # row starts with a right-aligned y label inside four characters.
        header_idx = [
            i for i, line in enumerate(lines)
            if line.startswith("     ") and line.strip()
            and all(part.isdigit() for part in line.replace("|", " ").split())
        ]
        # A tall grid repeats the header partway down, so there are 2 or more.
        assert len(header_idx) >= 2, "expected a header above and below the grid"
        top, bottom = header_idx[0], header_idx[-1]
        headers = set(header_idx)
        self.xs = [int(p) for p in lines[top].replace("|", " ").split()]
        # 5-char label, then cells each closed by '|', plus one extra '|' before
        # every COLUMN_GROUP-th cell - so a cell offset is NOT a flat multiple.
        groups = (len(self.xs) - 1) // render_map.COLUMN_GROUP
        self.cell_width = (
            len(lines[top]) - 5 - len(self.xs) - groups
        ) // len(self.xs)
        assert lines[top].endswith("|"), "every cell should be closed by a separator"
        self.ys = []
        self.rows = {}
        for i in range(top + 1, bottom):
            if i in headers:
                continue
            line = lines[i]
            y = int(line[:4])
            assert line.rstrip().endswith(str(y)), (
                "each row should repeat its y on the right: %r" % line)
            self.ys.append(y)
            self.rows[y] = line

    def offset(self, i):
        """Where cell i starts, accounting for the '||' every COLUMN_GROUP."""
        return 5 + i * (self.cell_width + 1) + i // render_map.COLUMN_GROUP

    def cell(self, x, y):
        i = self.xs.index(x)
        start = self.offset(i)
        raw = self.rows[y][start:start + self.cell_width + 1]
        assert raw.endswith("|"), (x, y, raw)
        return raw[:-1].rstrip() or " "

    def marker(self, x, y):
        return self.cell(x, y)[:1]


def grid(turn, view, around=None, radius=5):
    return Grid(render_map.render(state(turn), view, around, radius))


# -- landmarks read back out of the samples -------------------------------


def landmarks():
    """Pull the facts the tests assert straight from the sample files."""
    out = {}
    with open(sample(0), encoding="utf-8") as handle:
        t0 = json.load(handle)
    settlers = [u for u in t0["units"] if u["type"] == "UNIT_SETTLER"]
    assert len(settlers) == 1, "turn 0 should have exactly one settler"
    out["t0_settler"] = (settlers[0]["x"], settlers[0]["y"])
    out["t0_revealed"] = len(t0["map"]["tiles"])
    out["t0_cities"] = t0["cities"]

    with open(sample(36), encoding="utf-8") as handle:
        t36 = json.load(handle)
    out["t36_cities"] = dict((c["name"], (c["x"], c["y"])) for c in t36["cities"])

    with open(sample(34), encoding="utf-8") as handle:
        t34 = json.load(handle)
    out["t34_tiles"] = t34["map"]["tiles"]

    with open(sample(40), encoding="utf-8") as handle:
        t40 = json.load(handle)
    out["t40_tiles"] = t40["map"]["tiles"]
    out["t40_foreign_cities"] = t40["foreignCities"]
    out["t40_foreign_units"] = t40["foreignUnits"]
    return out


LANDMARKS = landmarks()


# -- orientation ----------------------------------------------------------


@pytest.mark.parametrize("view", render_map.VIEWS)
def test_rows_run_from_high_y_down(view):
    """North is up. Getting this backwards mirrors every directional judgement."""
    g = grid(40, view)
    assert g.ys == sorted(g.ys, reverse=True)
    assert g.ys[0] > g.ys[-1]


@pytest.mark.parametrize("view", render_map.VIEWS)
def test_grid_is_bracketed_by_compass_rules(view):
    """Ten agent trials narrated north/south inverted with correct coordinates.

    Prose did not fix it, so the letters sit on the edges they name.
    """
    text = render_map.render(state(40), view)
    lines = text.split("\n")
    north = [i for i, l in enumerate(lines) if l.strip().startswith("N ^ NORTH")]
    south = [i for i, l in enumerate(lines) if l.strip().startswith("S v SOUTH")]
    assert len(north) == 1 and len(south) == 1
    assert north[0] < south[0], "north marker must sit above the south marker"


def test_compass_rules_survive_brief(run=None):
    """--brief drops the legend; the compass is not legend, it is orientation."""
    text = render_map.render(state(40), "settle", brief=True)
    assert "N ^ NORTH" in text and "S v SOUTH" in text


def test_north_is_up_matches_the_terrain_banding():
    """Independent check: the sample's own terrain says which way is north.

    y=0 is the south pole edge and y rises toward the equator, so tundra must
    render ABOVE nothing and jungle must render below it in row order - i.e.
    the tundra row appears later in the output than the jungle rows.
    """
    tiles = LANDMARKS["t40_tiles"]
    tundra_ys = set(t["y"] for t in tiles if t["terrain"] == "TERRAIN_TUNDRA")
    jungle_ys = set(t["y"] for t in tiles if t.get("feature") == "FEATURE_JUNGLE")
    assert tundra_ys and jungle_ys
    assert max(tundra_ys) < min(jungle_ys), "sample banding changed; recheck the axis"

    text = render_map.render(state(40), "settle")
    lines = text.split("\n")
    tundra_row = min(i for i, l in enumerate(lines) if l[:4].strip().isdigit()
                     and int(l[:4]) in tundra_ys)
    jungle_row = max(i for i, l in enumerate(lines) if l[:4].strip().isdigit()
                     and int(l[:4]) in jungle_ys)
    assert jungle_row < tundra_row, "equatorial jungle should render above polar tundra"


# -- the three required landmarks -----------------------------------------


def test_turn0_settler_is_on_the_settle_grid():
    x, y = LANDMARKS["t0_settler"]
    assert grid(0, "settle").marker(x, y) == "S"
    assert not LANDMARKS["t0_cities"], "turn 0 is the pre-first-city snapshot"


def test_turn0_settler_is_listed_with_its_coordinates():
    x, y = LANDMARKS["t0_settler"]
    text = render_map.render(state(0), "settle")
    assert "YOUR SETTLERS" in text
    assert "(%d,%d) UNIT_SETTLER" % (x, y) in text


def test_turn36_founded_city_is_on_the_grid():
    g = grid(36, "settle")
    for name, (x, y) in LANDMARKS["t36_cities"].items():
        assert g.marker(x, y) == "C", "%s at (%d,%d) not drawn" % (name, x, y)


def test_turn36_city_appears_where_turn35_said_it_was_legal():
    """The second-city decision, end to end: legal at t35, founded at t36."""
    oporto = LANDMARKS["t36_cities"]["Oporto"]
    assert state(35).found_blockers(oporto) == []
    blockers = state(36).found_blockers(oporto)
    assert blockers, "a founded city must block founding on its own tile"


# -- coexisting tile facts ------------------------------------------------


def test_settle_shows_resource_and_feature_together():
    """A resource must not hide the feature under it, or vice versa.

    Grassland hills + forest + gems + fresh water is one ordinary tile. In the
    baseline run at t40 the jungle luxuries and forest spices are exactly this
    case, so a shared slot would silently drop one fact on every one of them.
    """
    both = [t for t in LANDMARKS["t40_tiles"] if t.get("bonus") and t.get("feature")]
    assert both, "sample no longer exercises the collision; pick another turn"
    g = grid(40, "settle")
    for tile in both:
        cell = g.cell(tile["x"], tile["y"])
        assert cell[2] == render_map.FEATURE_GLYPH[tile["feature"]]
        assert cell[3] == "*"


def test_settle_shows_relief_separately_from_terrain():
    """Hills must be distinguishable from flat land of the same terrain."""
    g = grid(40, "settle")
    hills = [t for t in LANDMARKS["t40_tiles"] if t.get("plotType") == "PLOT_HILLS"]
    flat = [t for t in LANDMARKS["t40_tiles"] if "plotType" not in t]
    peaks = [t for t in LANDMARKS["t40_tiles"] if t.get("plotType") == "PLOT_PEAK"]
    assert hills and flat and peaks
    for tile in hills:
        assert g.cell(tile["x"], tile["y"])[1].isupper()
    for tile in flat:
        assert g.cell(tile["x"], tile["y"])[1].islower()
    for tile in peaks:
        assert g.cell(tile["x"], tile["y"])[1] == "^"


def test_settle_water_column_encodes_river_lake_and_sea():
    """Three independent bits in one column, none allowed to hide another.

    River, non-river fresh water and sea access are separate facts; a priority
    rule would hide whichever lost on every tile carrying more than one.
    """
    s = state(34)
    g = grid(34, "settle")
    seen = set()
    for tile in LANDMARKS["t34_tiles"]:
        pos = (tile["x"], tile["y"])
        cell = g.cell(*pos).ljust(5)
        if tile.get("plotType") == "PLOT_OCEAN":
            assert cell[4] == " ", pos
            continue
        river = bool(tile.get("river"))
        other = bool(tile.get("freshWater")) and not river
        sea = s.is_coastal(pos)[0]
        seen.add((river, other, sea))
        assert cell[4] == render_map.WATER_GLYPH[(river, other, sea)], (pos, cell)
    assert len(seen) >= 5, ("sample should exercise most water states", seen)


def test_river_beats_lake_in_the_combined_states():
    """A tile with a river AND sea is '&', never '%', lake or no lake."""
    for other in (False, True):
        assert render_map.WATER_GLYPH[(True, other, True)] == "&"
        assert render_map.WATER_GLYPH[(True, other, False)] == "/"
    assert render_map.WATER_GLYPH[(False, True, True)] == "%"
    assert render_map.WATER_GLYPH[(False, True, False)] == ":"
    assert render_map.WATER_GLYPH[(False, False, True)] == "~"
    assert render_map.WATER_GLYPH[(False, False, False)] == "_"


def test_river_over_a_peak_is_not_fresh_water():
    """The one tile in the run where river and freshWater disagree.

    A peak can never be farmed or settled, so the engine reports river=true with
    freshWater=false - which is why river is not treated as a subset of fresh.
    """
    s = state(34)
    odd = [(p, t) for p, t in s.tiles.items()
           if t.get("river") and not t.get("freshWater")]
    assert odd, "sample no longer has a river tile without fresh water"
    for pos, tile in odd:
        assert tile.get("plotType") == "PLOT_PEAK", (pos, tile)
        river, other, _ = render_map.water_state(s, pos, tile)
        assert river and not other


def test_the_eight_neighbours_are_inside_the_twenty_one_tile_cross():
    """Structural: this is why `coastal yes` implies workable water exists."""
    neighbours = set(
        (dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)
    )
    assert neighbours <= set(render_map.CITY_CROSS)


def test_coastal_always_implies_at_least_one_workable_water_tile():
    """`coastal yes` with `0 workable water` must be impossible, not merely rare.

    The 8 adjacency neighbours are a subset of the 21 workable tiles, so a coastal
    site always has water it can work. Checked across the whole run: 1884 coastal
    tiles, none with an empty water count, minimum 2 - a 1-tile sea cannot exist
    because the engine would classify it as a lake.
    """
    checked = 0
    for path in all_samples():
        s = render_map.State(path)
        for pos, tile in s.tiles.items():
            if tile.get("plotType") == "PLOT_OCEAN":
                continue
            if not s.is_coastal(pos)[0]:
                continue
            water = sum(
                1 for p in s.city_cross(*pos)
                if (s.tiles.get(p) or {}).get("plotType") == "PLOT_OCEAN"
            )
            assert water >= 1, (path, pos)
            checked += 1
    assert checked > 100, "expected plenty of coastal tiles in the run"


def test_lake_flag_is_engine_truth_not_a_fog_limited_guess():
    """A partly-revealed sea must not be mistaken for a lake.

    CvPlot::isLake() is area()->isLake(), and areas come from CvMap::calculateAreas()
    over the WHOLE map at generation, so the flag ignores fog. The proof in this run
    is a water body with only 9 tiles revealed - at or under LAKE_MAX_AREA_SIZE (9) -
    that is still flagged lake=False. A fog-limited flag could not do that.
    """
    s = state(40)
    seen = set()
    small_non_lake = 0
    for pos, tile in s.tiles.items():
        if tile.get("plotType") != "PLOT_OCEAN" or pos in seen:
            continue
        stack, body = [pos], []
        seen.add(pos)
        while stack:
            cur = stack.pop()
            body.append(cur)
            for nb in s.neighbours(*cur):
                nt = s.tiles.get(nb)
                if nt and nt.get("plotType") == "PLOT_OCEAN" and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        if len(body) <= 9 and not any(s.tiles[p].get("lake") for p in body):
            small_non_lake += 1
    assert small_non_lake, (
        "expected a partly-revealed sea body of <=9 tiles flagged as sea; without "
        "one this run cannot demonstrate the flag ignores fog"
    )


def test_unrevealed_neighbours_never_turn_a_sea_tile_into_a_lake():
    """The case that looks dangerous: a site whose surrounding water is UNSCOUTED.

    Distinct from fog - these tiles have never been seen and are absent from
    map.tiles entirely. At turn 0 only 29 of 4368 tiles are revealed, and three
    water tiles have 5 of 8 neighbours unrevealed. All read lake=False, because
    nothing here counts water-body size: the flag is a boolean the engine derived
    from the complete map before any exploration. This test exists so that if
    anyone ever replaces it with a computed size check, it fails at once.
    """
    s = state(0)
    exposed = [
        (pos, tile) for pos, tile in s.tiles.items()
        if tile.get("plotType") == "PLOT_OCEAN"
        and sum(1 for nb in s.neighbours(*pos) if nb not in s.tiles) >= 4
    ]
    assert exposed, "turn 0 should have water tiles with mostly unrevealed neighbours"
    for pos, tile in exposed:
        assert not tile.get("lake"), pos
        # And the independent yield signal agrees.
        assert tile["yields"][0] == 1, pos

    # Meanwhile the revealed water around the start looks like a 12-tile body and a
    # 1-tile body. A size-based rule would call BOTH lakes at this point in the run.
    assert any(t.get("lake") for t in s.tiles.values()), "turn 0 has a real lake too"


def test_one_food_water_is_never_a_lake():
    """Independent cross-check on the lake flag, from yields alone.

    A lake is coast base 1 food plus YIELD_FOOD iLakeChange 1, so a lake always
    reads >= 2 food and a 1-food water tile is always sea. One-directional: a
    Lighthouse makes sea read 2 as well, so 2 food proves nothing. Used as a
    tripwire rather than an override - the exported flag is already engine truth,
    and overriding truth with a heuristic could only introduce error. This fires
    if the mod regresses, or under a ruleset where the yields differ.
    """
    checked = 0
    for path in all_samples():
        s = render_map.State(path)
        for tile in s.tiles.values():
            if tile.get("plotType") != "PLOT_OCEAN":
                continue
            if tile.get("bonus") or tile.get("improvement"):
                continue
            if tile["yields"][0] == 1:
                assert not tile.get("lake"), tile
                checked += 1
            if tile.get("lake"):
                assert tile["yields"][0] >= 2, tile
    assert checked > 100


def test_no_revealed_non_lake_water_body_is_a_single_tile():
    """A 1-tile sea cannot exist: <= LAKE_MAX_AREA_SIZE (9) tiles is a lake.

    Flood-fills the revealed water and checks every 1-tile body is flagged as a
    lake. Bodies can be partially revealed, so this only bounds them from below -
    which is the direction that matters for trusting the lake flag.
    """
    s = state(40)
    seen = set()
    for pos, tile in s.tiles.items():
        if tile.get("plotType") != "PLOT_OCEAN" or pos in seen:
            continue
        stack, body, is_lake = [pos], [], False
        seen.add(pos)
        while stack:
            cur = stack.pop()
            body.append(cur)
            if s.tiles[cur].get("lake"):
                is_lake = True
            for nb in s.neighbours(*cur):
                nt = s.tiles.get(nb)
                if nt and nt.get("plotType") == "PLOT_OCEAN" and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        if len(body) == 1:
            assert is_lake, "a single-tile water body must be a lake: %r" % (body,)


def test_sea_access_is_eight_neighbour_adjacency_not_the_city_cross():
    """A city one tile inland works ocean but cannot build a Harbour."""
    s = state(34)
    inland = [
        pos for pos, tile in s.tiles.items()
        if tile.get("plotType") not in ("PLOT_OCEAN", "PLOT_PEAK")
        and not s.is_coastal(pos)[0]
        and any(
            (s.tiles.get(p) or {}).get("plotType") == "PLOT_OCEAN"
            for p in s.city_cross(*pos)
        )
    ]
    assert inland, "sample should have a tile with sea in its cross but not adjacent"
    for pos in inland:
        text = render_map.render(s, "settle", pos, 1)
        assert "coastal    no" in text, pos


def test_cross_table_states_water_per_tile():
    s = state(34)
    text = render_map.render(s, "settle", (78, 14), 1)
    # Scope to the cross table itself - the resource list above it also begins
    # its lines with a coordinate.
    table = text.split("The 21 tiles a city here could ever work:", 1)[1]
    table = table.split("OF THE 21 TILES", 1)[0]
    header = table.split("\n")[1]
    assert "water" in header and "coast" in header, header
    for pos in s.city_cross(78, 14):
        tile = s.tiles.get(pos)
        if tile is None:
            continue
        row = [l for l in table.split("\n") if l.startswith("  (%d,%d)" % pos)]
        assert row, pos
        water, coast = render_map.water_labels(s, pos, tile)
        fields = row[0].split()
        assert water in fields, (pos, water, row[0])
        # "sea" reads as a sentence on its own line; "yes" would not.
        assert coast in ("-", "sea") and coast in fields, (pos, coast, row[0])


def test_worker_shows_feature_under_an_improvement():
    """Clearing jungle is a worker order and does not stop being one."""
    g = grid(40, "worker")
    improved = [t for t in LANDMARKS["t40_tiles"]
                if t.get("improvement") and t.get("feature")]
    for tile in improved:
        cell = g.cell(tile["x"], tile["y"])
        assert cell[2] == render_map.FEATURE_GLYPH[tile["feature"]]
    # And the improvement still gets its own glyph beside it.
    for tile in LANDMARKS["t40_tiles"]:
        if tile.get("improvement") in render_map.IMPROVEMENT_GLYPH:
            cell = g.cell(tile["x"], tile["y"])
            assert cell[3] == render_map.IMPROVEMENT_GLYPH[tile["improvement"]]


def test_military_shows_feature_under_a_territory_digit():
    g = grid(40, "military")
    owned = [t for t in LANDMARKS["t40_tiles"]
             if t.get("owner") is not None and t.get("feature")]
    assert owned, "sample no longer exercises owned-and-featured tiles"
    for tile in owned:
        assert g.cell(tile["x"], tile["y"])[2] == render_map.FEATURE_GLYPH[tile["feature"]]


# -- what the tables must not hide ----------------------------------------
#
# Every test below comes from a subagent that made a real second-city call from
# these renders alone. It reached the right tile, but each of these was either a
# table contradicting the grid or a derivation it repeated by hand.


def test_cross_table_states_relief_so_it_cannot_contradict_the_grid():
    """A peak printed as plain GRASS with 0/0/0 reads as broken arithmetic."""
    peaks = [t for t in LANDMARKS["t34_tiles"] if t.get("plotType") == "PLOT_PEAK"]
    assert peaks
    peak = peaks[0]
    text = render_map.render(state(34), "settle", (peak["x"], peak["y"]), 1)
    row = [l for l in text.split("\n") if l.startswith("  (%d,%d)" % (peak["x"], peak["y"]))]
    assert row and "peak" in row[0]


def test_cross_table_distinguishes_a_lake_from_open_sea():
    """Lake vs sea decides fresh water and whether a site is coastal."""
    lakes = [t for t in LANDMARKS["t34_tiles"] if t.get("lake")]
    assert lakes
    lake = lakes[0]
    text = render_map.render(state(34), "settle", (lake["x"], lake["y"]), 1)
    row = [l for l in text.split("\n") if l.startswith("  (%d,%d)" % (lake["x"], lake["y"]))]
    assert row and "lake" in row[0]


def coastal_by_hand(tiles, pos, width, height):
    """Independent reimplementation: adjacent to revealed non-lake water."""
    lookup = dict(((t["x"], t["y"]), t) for t in tiles)
    if lookup[pos].get("plotType") == "PLOT_OCEAN":
        return False
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            other = lookup.get(((pos[0] + dx) % width, pos[1] + dy))
            if other and other.get("plotType") == "PLOT_OCEAN" and not other.get("lake"):
                return True
    return False


def test_is_coastal_matches_an_independent_computation():
    s = state(34)
    land = [t for t in LANDMARKS["t34_tiles"] if t.get("plotType") != "PLOT_OCEAN"]
    assert land
    for tile in land:
        pos = (tile["x"], tile["y"])
        assert s.is_coastal(pos)[0] == coastal_by_hand(
            LANDMARKS["t34_tiles"], pos, s.width, s.height
        ), pos


def test_coastal_separates_two_adjacent_near_identical_sites():
    """The whole second-city call turned on this one-tile difference."""
    s = state(34)
    assert s.is_coastal((78, 14))[0] is True
    assert s.is_coastal((78, 13))[0] is False
    text = render_map.render(s, "settle", (78, 14), 1)
    assert "coastal    yes" in text
    assert "coastal    no" in render_map.render(s, "settle", (78, 13), 1)


def test_overlap_with_existing_cities_is_counted_for_you():
    s = state(34)
    lisbon = [c for c in s.cities if c["name"] == "Lisbon"][0]
    owned = set(s.city_cross(lisbon["x"], lisbon["y"]))
    for site in [(78, 14), (78, 13), (75, 18)]:
        expected = len([p for p in s.city_cross(*site) if p in owned])
        text = render_map.render(s, "settle", site, 1)
        if expected:
            assert "%d tiles shared with Lisbon" % expected in text
        assert "%2d already inside one of your cities' radii" % expected in text


def test_cross_reports_settler_distance():
    """An open route prints one figure and says the straight line agrees."""
    s = state(34)
    settler = [u for u in s.units if u["type"] == "UNIT_SETTLER"][0]
    start = (settler["x"], settler["y"])
    site = (78, 14)
    assert s.distance(start, site) == s.land_distance(start, site)
    text = render_map.render(s, "settle", site, 1)
    assert "%d tiles to walk" % s.land_distance(start, site) in text
    assert "straight line agrees" in text


def test_cross_leads_with_the_walk_when_it_differs():
    """4 straight line vs 16 on foot - the walk is what the settler pays.

    An agent trial found a site whose real route crossed a one-tile isthmus
    while the straight-line figure implied open ground, and two trials
    independently reported that the leading number is the one that sticks.
    """
    s = state(34)
    settler = [u for u in s.units if u["type"] == "UNIT_SETTLER"][0]
    start = (settler["x"], settler["y"])
    site = (71, 18)
    assert s.distance(start, site) == 4
    assert s.land_distance(start, site) == 16
    text = render_map.render(s, "settle", site, 1)
    assert "16 TILES TO WALK" in text
    assert "(only 4 straight line)" in text


def test_land_distance_is_none_across_water():
    s = state(34)
    water = [p for p, t in s.tiles.items() if t.get("plotType") == "PLOT_OCEAN"]
    assert water
    assert s.land_distance((75, 15), water[0]) is None


def test_land_distance_matches_run_history():
    """Two tools must not disagree about what a distance means."""
    import run_history
    s = state(34)
    raw = json.load(open(sample(34), encoding="utf-8"))
    for target in [(71, 18), (69, 21), (78, 14)]:
        mine = s.land_distance((75, 15), target)
        theirs, _ = run_history.land_path(raw, (75, 15), target)
        assert mine == theirs, target


def test_settler_distance_still_says_it_is_not_turns():
    """Whichever figure leads, neither is turns - terrain costs more."""
    text = render_map.render(state(34), "settle", (78, 14), 1)
    assert "LOWER BOUND" in text, "Chebyshev is not turns; say so"


def test_empty_build_queue_reads_as_a_fact_not_a_formatting_bug():
    s = state(34)
    assert any(c["producing"] is None for c in s.cities), "t34 should have an idle city"
    text = render_map.render(s, "yields")
    assert "BUILDING NOTHING" in text
    assert "nothing 0/-" not in text


def test_around_crops_the_resource_list_to_what_the_grid_shows():
    """A cropped grid beside a whole-map resource list invites a false join."""
    s = state(34)
    text = render_map.render(s, "settle", (78, 14), 2)
    listed = set()
    for line in text.split("\n"):
        if line.startswith("  (") and "BONUS_" in line:
            coords = line.strip()[1:].split(")")[0]
            listed.add(tuple(int(v) for v in coords.split(",")))
    assert listed, "expected some resources in this crop"
    xs, ys, _ = render_map.select_region(s, (78, 14), 2)
    for pos in listed:
        assert pos[0] in set(xs) and pos[1] in set(ys), pos
    far = [t for t in LANDMARKS["t34_tiles"]
           if t.get("bonus") and (t["x"], t["y"]) not in listed]
    assert far, "sample should have resources outside this crop"


def test_relief_label_covers_every_plot_type():
    assert render_map.relief_label({"plotType": "PLOT_PEAK"}) == "peak"
    assert render_map.relief_label({"plotType": "PLOT_HILLS"}) == "hills"
    assert render_map.relief_label({"plotType": "PLOT_OCEAN", "lake": True}) == "lake"
    assert render_map.relief_label({"plotType": "PLOT_OCEAN"}) == "sea"
    assert render_map.relief_label({}) == "-"


# -- the cross reports counts, never a score ------------------------------


def test_cross_has_no_yield_total():
    """A sum of current yields ranks finished tiles above improvable ones.

    Coast is 1/0/2 forever; grass-jungle is 1/0/0 now and 2/0/0 once cleared.
    Summing rewards the wrong one, and a sum cannot see the one or two great
    tiles that actually decide an early site. Counts replaced it.
    """
    for site in [(78, 14), (75, 23)]:
        text = render_map.render(state(34), "settle", site, 1)
        assert "TOTAL" not in text
        assert "food /" not in text


def counts_by_hand(tiles, cross):
    lookup = dict(((t["x"], t["y"]), t) for t in tiles)
    out = dict(land=0, water=0, dead=0, unrevealed=0, resources=0)
    for pos in cross:
        tile = lookup.get(pos)
        if tile is None:
            out["unrevealed"] += 1
            continue
        if tile.get("bonus"):
            out["resources"] += 1
        plot = tile.get("plotType")
        if plot == "PLOT_PEAK" or (
            tile["terrain"] == "TERRAIN_DESERT" and plot is None
            and not tile.get("feature")
        ):
            out["dead"] += 1
        elif plot == "PLOT_OCEAN":
            out["water"] += 1
        else:
            out["land"] += 1
    return out


@pytest.mark.parametrize("site", [(78, 14), (75, 23), (75, 15), (68, 21)])
def test_cross_counts_match_an_independent_count(site):
    s = state(34)
    expected = counts_by_hand(LANDMARKS["t34_tiles"], s.city_cross(*site))
    text = render_map.render(s, "settle", site, 1)
    assert "%2d workable land" % expected["land"] in text
    assert "%2d workable water" % expected["water"] in text
    assert "%2d dead" % expected["dead"] in text
    assert "%2d never revealed" % expected["unrevealed"] in text
    assert "%2d carrying a visible resource" % expected["resources"] in text
    assert sum(expected[k] for k in ("land", "water", "dead", "unrevealed")) == 21


def test_dead_is_bare_flat_desert_and_peaks_and_nothing_else():
    """The tempting definition - 'yields 0/0/0' - is wrong in both directions.

    Desert hills (0/1/1) and flood plains (3/0/1) are desert but very much alive;
    jungle (0/1/0 on hills) is a worker's to-do item, not a dead tile; and deep
    ocean reads 0/0/0 only through the engine quirk in the schema. Counting any
    of them dead would re-import the TOTAL's bias through the counts.
    """
    for tile in LANDMARKS["t34_tiles"]:
        dead = render_map.is_dead_tile(tile)
        plot = tile.get("plotType")
        if plot == "PLOT_PEAK":
            assert dead, tile
        elif tile["terrain"] == "TERRAIN_DESERT" and plot is None:
            assert dead is bool(not tile.get("feature")), tile
        else:
            assert not dead, tile


def test_flood_plains_and_desert_hills_are_never_called_dead():
    live = [t for t in LANDMARKS["t34_tiles"]
            if t["terrain"] == "TERRAIN_DESERT"
            and (t.get("feature") == "FEATURE_FLOOD_PLAINS"
                 or t.get("plotType") == "PLOT_HILLS")]
    assert live, "sample should have flood plains and/or desert hills"
    for tile in live:
        assert not render_map.is_dead_tile(tile), tile
        assert tile["yields"] != [0, 0, 0], tile


def test_jungle_is_never_called_dead():
    jungle = [t for t in LANDMARKS["t34_tiles"] if t.get("feature") == "FEATURE_JUNGLE"]
    assert jungle
    for tile in jungle:
        assert not render_map.is_dead_tile(tile), tile


def test_cross_counts_overlap_against_your_own_cities():
    s = state(34)
    for site in [(78, 14), (75, 23)]:
        cross = s.city_cross(*site)
        expected = sum(n for _, n in s.overlap_with_own_cities(cross))
        text = render_map.render(s, "settle", site, 1)
        assert "%2d already inside one of your cities' radii" % expected in text


def test_cross_counts_disclaim_being_a_score():
    text = render_map.render(state(34), "settle", (78, 14), 1)
    assert "Counts, not a score" in text


# -- symbol unification ---------------------------------------------------


def test_no_glyph_is_reused_for_a_different_kind_of_fact():
    """A symbol means the same thing in every view.

    These are the collisions that actually existed and confused a real reader:
    '+' was both the --around site and your territory; a player-id digit meant
    'owns this tile' in settle but 'has a unit here' in military; '*' was both a
    resource and a worked tile; 'o' was both a lake and an unworked radius tile.
    """
    s = state(40)
    grids = dict((v, grid(40, v)) for v in render_map.VIEWS)
    tiles = dict(((t["x"], t["y"]), t) for t in LANDMARKS["t40_tiles"])

    # 'o' is a lake, and nothing else, anywhere.
    for view, g in grids.items():
        for pos, tile in tiles.items():
            if g.cell(*pos)[:1] == "o":
                assert tile.get("lake"), (view, pos)

    # A digit in the marker column always means a rival UNIT is standing there.
    rival_unit_positions = set(
        (u["x"], u["y"]) for u in LANDMARKS["t40_foreign_units"]
    )
    for view, g in grids.items():
        for pos in tiles:
            if g.marker(*pos).isdigit():
                assert pos in rival_unit_positions, (view, pos)

    # '+' is your territory, and nothing else.
    for view, g in grids.items():
        for pos, tile in tiles.items():
            if "+" in g.cell(*pos):
                assert tile.get("owner") == s.player_id, (view, pos)


@pytest.mark.parametrize("turn", [0, 34, 40])
def test_settle_marker_answers_can_i_found_here_for_every_tile(turn):
    """The marker column is one question with a complete, positive answer.

    'A' is marked rather than left blank because the failure directions are not
    symmetric: reading water as available is caught at once by the terrain glyph,
    while reading an available tile as blocked silently loses a site.
    """
    s = state(turn)
    g = grid(turn, "settle")
    actors = set((c["x"], c["y"]) for c in s.cities)
    actors |= set((c["x"], c["y"]) for c in s.foreign_cities)
    actors |= set((u["x"], u["y"]) for u in s.units if u["type"] == "UNIT_SETTLER")
    seen = set()
    for pos, tile in s.tiles.items():
        if pos in actors:
            continue
        marker = g.marker(*pos)
        seen.add(marker)
        blockers = s.found_blockers(pos)
        joined = " ".join(blockers)
        terrain_blocked = any(
            "water" in b or "peak" in b or "cannot hold a city" in b for b in blockers
        )
        if not blockers:
            assert marker == "A", (pos, "legal but not marked available")
        elif terrain_blocked:
            # Terrain OUTRANKS proximity and ownership. Ocean two tiles from a city
            # used to render 'x', which the legend promises means land you cannot
            # use - the grid was contradicting its own key.
            assert marker == " ", (pos, joined)
        elif "borders" in joined:
            assert marker == "]", pos
        else:
            assert "within Chebyshev" in joined or "already stands" in joined, joined
            assert marker == "x", pos
    assert "A" in seen, "every sample turn should have somewhere legal to settle"


def test_every_legal_tile_is_marked_not_just_the_ones_bordering_blocked_land():
    """'A' is on all 107 legal tiles at t34, including the interior ones.

    Marking only a frontier ring would make the availability answer depend on
    what a tile happens to neighbour, which is not what the column claims.
    """
    s = state(34)
    g = grid(34, "settle")
    legal = [p for p in s.tiles if not s.found_blockers(p)]
    interior = [
        p for p in legal
        if all(s.tiles.get(n) is not None and not s.found_blockers(n)
               for n in s.neighbours(*p))
    ]
    assert interior, "t34 should have legal tiles surrounded entirely by legal tiles"
    for pos in interior:
        assert g.marker(*pos) == "A", (pos, "interior legal tile left unmarked")


def test_actor_glyphs_outrank_the_availability_marker():
    """Counting 'A' undercounts legality by the tiles an actor stands on.

    At turn 0 there are 16 legal tiles but only 15 'A's - the settler's own tile
    shows 'S'. That is deliberate (the actor is the more urgent fact) and is why
    the settler's legality is spelled out in the YOUR SETTLERS block instead.
    """
    s = state(0)
    g = grid(0, "settle")
    legal = set(p for p in s.tiles if not s.found_blockers(p))
    settler = [(u["x"], u["y"]) for u in s.units if u["type"] == "UNIT_SETTLER"]
    assert len(settler) == 1 and settler[0] in legal
    marked = set(p for p in legal if g.marker(*p) == "A")
    assert marked == legal - set(settler)
    assert g.marker(*settler[0]) == "S"


def test_settle_reports_legality_of_the_tile_each_settler_stands_on():
    """The settler glyph covers the marker on the tile that matters most.

    "Can I just settle in place?" is the whole question on turn 0, and 'S' hides
    the answer, so it is stated in words instead of costing the grid a column.
    """
    text = render_map.render(state(0), "settle")
    assert "founding HERE: legal" in text

    # At turn 34 the settler stands in Lisbon, so it must say so - and say it in
    # a way that does not read as a nonsense self-reference.
    text = render_map.render(state(34), "settle")
    assert "founding HERE: BLOCKED" in text
    assert "a city already stands on this tile" in text


def test_improved_yields_are_marked_wherever_yields_are_shown():
    """Displayed yields include improvements, which flatters overlapping sites.

    WHEAT (76,16) reads 2/1/1 at turn 0 and 5/1/1 at turn 34 once Lisbon farms it.
    Comparing two candidate sites then compares improved tiles inside your borders
    against raw tiles outside them - so the site that costs you the most overlap
    looks the strongest. Base yield is not recoverable from the export, so the
    honest fix is to mark the affected tiles, not to pretend we can undo them.
    """
    s = state(34)
    assert s.tiles[(76, 16)]["yields"] == [5, 1, 1]
    assert state(0).tiles[(76, 16)]["yields"] == [2, 1, 1]

    text = render_map.render(s, "settle", (78, 15), 1)
    row = [l for l in text.split("\n") if l.startswith("  (76,16)")][0]
    assert row.rstrip().endswith("+"), row
    assert "ALREADY INCLUDES an improvement" in text

    # A site with no developed tiles in its cross gets neither mark nor note.
    clean = render_map.render(s, "settle", (79, 13), 1)
    assert "ALREADY INCLUDES an improvement" not in clean


def test_goody_huts_are_not_counted_as_improved_yield():
    """A goody hut lives in the `improvement` field but is not development.

    Turn 0 has one at (75,13) inside the settler's own cross. Marking it would fire
    the whole advisory on a turn when nothing has been developed at all.
    """
    s = state(0)
    hut = s.tiles[(75, 13)]
    assert hut["improvement"] == "IMPROVEMENT_GOODY_HUT"
    assert not render_map.yield_is_improved(hut)
    assert not any(
        render_map.yield_is_improved(s.tiles[p])
        for p in s.city_cross(75, 15) if p in s.tiles
    )
    assert "ALREADY INCLUDES" not in render_map.render(s, "settle", (75, 15), 1)


def test_roads_do_not_count_as_improved_yield():
    """CIV4RouteInfos.xml gives ROUTE_ROAD and ROUTE_RAILROAD no <Yields> at all.

    Roads are movement and connectivity; a roaded tile's displayed yield IS its raw
    yield, so marking it would flag tiles that need no interpretation. (Roads giving
    +1 commerce is Civ III, not BTS.)
    """
    s = state(34)
    roaded = [t for t in s.tiles.values()
              if t.get("route") and not t.get("improvement")]
    assert roaded, "turn 34 should have a roaded tile with no improvement on it"
    for tile in roaded:
        assert not render_map.yield_is_improved(tile), tile


def test_yields_view_warns_that_its_numbers_include_improvements():
    text = render_map.render(state(34), "yields")
    assert "DISPLAYED yields" in text
    rows = [l for l in text.split("\n") if l.startswith("  (76,16)")]
    assert rows and rows[0].rstrip().endswith("+"), rows


def test_around_a_water_tile_leads_with_the_verdict():
    """A tile that cannot ever hold a city must say so first, not last.

    It used to print coastal status, water status and the full advisory before
    concluding BLOCKED at the very bottom - a lot of authoritative output for a
    site that cannot exist.
    """
    s = state(0)
    lake = [p for p, t in s.tiles.items() if t.get("lake")][0]
    text = render_map.render(s, "settle", lake, 1)
    body = text.split("SITE (%d,%d)" % lake, 1)[1]
    assert body.lstrip().startswith("CANNOT EVER BE A CITY"), body[:200]


def test_around_a_water_tile_does_not_answer_questions_that_do_not_apply():
    """"coastal: no - landlocked" and "NO fresh water" are nonsense about a lake.

    The grid already has this rule - "the tile is itself water, so the question
    does not apply" - and the site report has to obey it too.
    """
    s = state(0)
    lake = [p for p, t in s.tiles.items() if t.get("lake")][0]
    header = render_map.render(s, "settle", lake, 1).split("SITE (%d,%d)" % lake, 1)[1]
    header = header.split("The 21 tiles", 1)[0]
    assert "landlocked" not in header, header
    assert "NO fresh water" not in header, header
    # The cross is still listed - it describes the neighbourhood, which is real.
    assert "The 21 tiles" in render_map.render(s, "settle", lake, 1)


def test_barbarian_owner_is_derived_from_the_player_count_not_hardcoded():
    """BARBARIAN_PLAYER is MAX_CIV_PLAYERS - 18 in unmodded BTS, 31 under Rhye's.

    Hardcoding 18 would silently mislabel barbarians under any mod that changes
    the player cap, so the rule is "at or above totalCivs and not a contact".
    """
    s = state(34)
    barb = [u["owner"] for u in s.foreign_units if s.is_barbarian(u["owner"])]
    assert barb, "turn 34 should have a barbarian unit in sight"
    assert all(o >= s.raw["game"]["totalCivs"] for o in barb)
    for contact in s.contacts:
        assert not s.is_barbarian(contact["playerId"])
    assert not s.is_barbarian(s.player_id)
    text = render_map.render(s, "military")
    assert "owner BARBARIANS" in text
    assert "barbarian or unmet" not in text


def test_brief_drops_the_legend_but_never_the_traps_or_omissions():
    """Stripping a legend by hand is how the TRAPS warnings get lost."""
    s = state(34)
    full = render_map.render(s, "settle")
    brief = render_map.render(s, "settle", brief=True)
    assert len(brief) < len(full)
    assert "LEGEND" not in brief
    assert "READING THE GRID" not in brief
    assert "--brief" in brief, "brief output must say how to get the key back"
    # The parts whose absence changes a decision stay.
    assert "THIS VIEW OMITS" in brief
    assert "TRAPS" in full


def test_yields_with_no_cities_still_presents_the_grid_as_the_point():
    """The per-city tables are what is missing, not the yield grid itself."""
    text = render_map.render(state(0), "yields")
    assert "GRID ABOVE IS STILL THE POINT" in text
    assert "nothing to allocate." not in text


def test_counts_separate_new_land_from_land_you_already_own():
    """Raw counts credit a site with tiles inside your existing cities' radii.

    At turn 34 (78,15) and (79,13) read 13 vs 12 workable land - near-identical -
    while the land actually NEW to the empire is 7 vs 11. The raw count inflates
    exactly the sites that overlap most, i.e. the ones that gain you least.
    """
    s = state(34)
    already = set()
    for city in s.cities:
        already.update(s.city_cross(city["x"], city["y"]))

    for site in [(78, 15), (79, 13), (74, 18)]:
        cross = s.city_cross(*site)
        new_land = len([
            p for p in cross
            if p not in already and p in s.tiles
            and s.tiles[p].get("plotType") not in ("PLOT_OCEAN", "PLOT_PEAK")
            and not render_map.is_dead_tile(s.tiles[p])
        ])
        new_res = len([
            p for p in cross
            if p not in already and p in s.tiles and s.tiles[p].get("bonus")
        ])
        text = render_map.render(s, "settle", site, 1)
        assert "NEW to your empire" in text, site
        assert "%2d land" % new_land in text, (site, new_land, text)
        assert "%2d with a resource" % new_res in text, (site, new_res)


def test_new_to_empire_block_is_absent_when_nothing_overlaps():
    """With no overlap the raw counts are already the new counts - saying it twice
    would be noise, and at turn 0 there are no cities at all."""
    assert "NEW to your empire" not in render_map.render(state(0), "settle", (75, 15), 1)


def test_fog_key_survives_brief_in_the_views_that_draw_fog():
    """Fog is the one symbol whose absence changes a decision rather than costing a
    lookup: a fogged tile reports no enemies whether or not any are there."""
    s = state(34)
    for view in ("military", "explore"):
        brief = render_map.render(s, view, brief=True)
        assert "LEGEND" not in brief, view
        assert "REVEALED BUT FOGGED" in brief, view
        assert "ONLY on visible tiles" in brief, view
    # settle draws no fog, so the reminder would be a lie there.
    assert "REVEALED BUT FOGGED" not in render_map.render(s, "settle", brief=True)


def test_landlocked_note_appears_only_when_it_changes_how_counts_read():
    """The counterweight has to sit beside the numbers it counterweights.

    An agent trial compared "17 workable land" at (78,13) against "15" at (78,14)
    and took the landlocked site. Coastal-ness was prose above the table while the
    land/water split was numbers inside it, which invites weighing the wrong thing.
    """
    s = state(34)
    landlocked = render_map.render(s, "settle", (78, 13), 1)
    coastal = render_map.render(s, "settle", (78, 14), 1)
    assert not s.is_coastal((78, 13))[0] and s.is_coastal((78, 14))[0]
    assert "NOT COASTAL - how to read the" in landlocked
    assert "NOT COASTAL - how to read the" not in coastal


def test_landlocked_note_does_not_claim_water_tiles_are_unworkable():
    """CvCity::canWork gates water on CvTeam::isWaterWork(), which TECH_FISHING
    sets for the WHOLE TEAM - not on the city being coastal. So a landlocked city
    does work its water tiles; what it loses is Harbour/Lighthouse/work boats.
    Saying otherwise would teach the reader a false rule."""
    text = render_map.render(state(34), "settle", (78, 13), 1)
    assert "they ARE workable" in text
    assert "Fishing" in text
    for false_claim in ("wasted", "unworkable", "cannot be worked", "useless"):
        assert false_claim not in text, false_claim


def test_landlocked_note_names_the_strategic_cost_and_leaves_the_call_open():
    text = render_map.render(state(34), "settle", (78, 13), 1)
    assert "naval unit production" in text
    assert "overseas" in text
    # Presents the trade-off; must not resolve it.
    assert "can outweigh" in text


def test_coastal_line_names_what_coastal_actually_buys():
    text = render_map.render(state(34), "settle", (78, 14), 1)
    assert "work boats" in text and "naval units" in text


def test_river_centre_caveat_appears_only_on_a_river_site():
    """A river is worth nothing extra on the tile a city STANDS on.

    CvPlot::calculateYield floors a city tile at YieldInfo iMinCity (2/1/1), which
    absorbs the river's +1 commerce - no land terrain has base commerce above 1.
    An agent trial paid a turn AND a wheat resource to move onto a river centre on
    the strength of the unqualified wording, so the bound is stated where the claim
    is made.
    """
    s = state(0)
    river = render_map.render(s, "settle", (76, 16), 1)
    lake = render_map.render(s, "settle", (75, 15), 1)
    assert s.tiles[(76, 16)].get("river")
    assert s.tiles[(75, 15)].get("freshWater") and not s.tiles[(75, 15)].get("river")

    assert "on a river - fresh water" in river
    assert "worth no more than a lake" in river
    assert "floors at 2/1/1" in river
    assert "WORKED tiles in the cross" in river
    # The caveat is about rivers, so it must not appear on a lake-fresh site.
    assert "worth no more than a lake" not in lake
    assert "fresh water, no river" in lake


def test_water_legend_bounds_what_a_river_is_worth():
    """The legend must not invite the extrapolation that flipped a ranking."""
    legend = render_map.render(state(34), "settle")
    legend = legend.split("LEGEND", 1)[1].split("THIS VIEW OMITS", 1)[0]
    assert "EQUIVALENT for farms and health" in legend
    assert "NOT to a city centre" in legend
    assert "far past this scope" in legend


def test_water_legend_spells_out_the_river_versus_lake_boundary():
    """'%' vs '&' is the one pair a reader cannot guess, so it is stated outright.

    Flood plains are deliberately not listed as a fresh-water source: CIV4Feature
    Infos gives them bRequiresRiver=1 and bAddsFreshWater=0, so they sit on a river
    rather than supplying water themselves.
    """
    text = render_map.render(state(34), "settle")
    legend = text.split("LEGEND", 1)[1].split("THIS VIEW OMITS", 1)[0]
    assert "sea + fresh water but NO river" in legend
    assert "sea + river (whether or not there is also a lake)" in legend
    assert "+1 commerce" in legend
    # Scoped to the water block: "flood plains" is still a legitimate FEATURE glyph,
    # it just must not be named as a source of fresh water.
    water_block = legend.split("    water", 1)[1].split("  TRAPS", 1)[0]
    assert "flood" not in water_block.lower(), water_block


def test_one_tile_off_the_coast_is_flagged_only_when_a_step_fixes_it():
    """Radius 1 only: beyond that you are re-siting, not nudging.

    Reports, does not judge - settling one off the coast is sometimes right, so
    the wording states the fact and hands the trade back to the reader.
    """
    s = state(34)
    # (78,13) is landlocked with coastal legal neighbours; (79,14) is coastal.
    assert not s.is_coastal((78, 13))[0]
    assert s.is_coastal((79, 14))[0]

    text = render_map.render(s, "settle", (78, 13), 1)
    assert "ONE TILE OFF THE COAST" in text
    for pos in s.coastal_one_step_away((78, 13))[:1]:
        assert "(%d,%d)" % pos in text

    assert "ONE TILE OFF THE COAST" not in render_map.render(s, "settle", (79, 14), 1)


def test_coastal_one_step_away_only_offers_legal_land():
    s = state(34)
    for site in [(78, 13), (75, 20), (70, 25)]:
        for pos in s.coastal_one_step_away(site):
            assert s.is_coastal(pos)[0], pos
            assert s.found_blockers(pos) == [], pos
            assert s.distance(site, pos) == 1, pos
        if s.is_coastal(site)[0]:
            assert s.coastal_one_step_away(site) == [], site


def header_groups(text):
    """Map rows between each repeated column header, top to bottom."""
    lines = text.split("\n")
    hdr = [
        i for i, l in enumerate(lines)
        if l.startswith("     ") and l.strip()
        and all(p.isdigit() for p in l.replace("|", " ").split())
    ]
    groups, run = [], 0
    for i in range(hdr[0] + 1, hdr[-1]):
        if i in hdr:
            groups.append(run)
            run = 0
        elif lines[i][:4].strip().isdigit():
            run += 1
    groups.append(run)
    return groups


def test_repeated_headers_use_a_fixed_stride_with_the_remainder_last():
    """A reader must be able to rely on "a header every N rows" without measuring.

    An earlier version spread the repeats evenly (23 rows -> 8, 7, 8) so that no
    group was short. That is worse: a varying gap is a rule you have to measure
    rather than one you can trust, and the short group is harmless at the bottom
    where the closing header already bounds it.
    """
    groups = header_groups(render_map.render(state(34), "settle"))
    assert len(groups) > 1, "a 23-row grid should repeat its header"
    for full in groups[:-1]:
        assert full == render_map.HEADER_EVERY, groups
    assert 0 < groups[-1] <= render_map.HEADER_EVERY, groups
    assert sum(groups) == 23


def test_short_grids_get_no_repeated_header():
    """Turn 0 is 7 rows - it never loses sight of the header, so adding one is noise."""
    assert header_groups(render_map.render(state(0), "settle")) == [7]


def test_around_hint_names_a_real_legal_tile():
    """An abstract 'X,Y' is a placeholder to skim past; a concrete site is a command."""
    for turn in (0, 34):
        s = state(turn)
        text = render_map.render(s, "settle")
        hint = [l for l in text.split("\n") if "e.g.  --view settle --around" in l]
        assert hint, turn
        coords = hint[0].split("--around")[1].strip()
        pos = tuple(int(v) for v in coords.split(","))
        assert pos in s.tiles, (turn, pos)
        assert s.found_blockers(pos) == [], (turn, pos, "hint must name a LEGAL tile")


def test_no_glyph_carries_two_unrelated_meanings():
    """The glyph set is audited, not merely tidy.

    Full cross-column uniqueness was considered and rejected: it would cost the
    mnemonic improvement letters (F farm, M mine, P pasture...) for no gain, since
    the column already disambiguates and every legend prints its `cell = [...]`
    map. What must hold is narrower and is what this pins - no glyph means two
    genuinely UNRELATED things. Reuse is allowed only where the two roles are the
    same concept seen from different columns, and each such pair is listed here
    deliberately so adding a new one is a conscious act.
    """
    related = {
        # ocean terrain / sea access: the same fact, read from two columns.
        "~": {("terrain", "TERRAIN_OCEAN"), ("water", "sea")},
        # a resource / a resource that is still unimproved.
        "*": {("resource", "any"), ("built", "unimproved resource")},
        # identical meaning in both columns that can show it.
        "?": {("go", "goody hut"), ("built", "IMPROVEMENT_GOODY_HUT")},
    }
    feature_glyphs = set(render_map.FEATURE_GLYPH.values())
    water_glyphs = set(g for g in render_map.WATER_GLYPH.values() if g.strip())
    terrain_glyphs = set(render_map.TERRAIN_GLYPH.values())

    overlap = feature_glyphs & water_glyphs
    assert not overlap, (
        "feature and water glyphs must not collide - they sit in adjacent columns "
        "of the same settle cell: %r" % sorted(overlap)
    )
    stray = (feature_glyphs & terrain_glyphs) - set(related)
    assert not stray, "feature/terrain collision: %r" % sorted(stray)

    # '~' is the only sanctioned terrain/water overlap.
    assert terrain_glyphs & water_glyphs == {"~"}
    assert render_map.FEATURE_GLYPH["FEATURE_ICE"] == "I", (
        "ice must not sit on '%' - that is the water column's both-waters glyph"
    )


def test_uppercase_relief_only_applies_to_letter_glyphs():
    """'-' and '~' have no uppercase, so hills would silently render as flat."""
    for terrain, glyph in render_map.TERRAIN_GLYPH.items():
        tile = {"terrain": terrain, "plotType": "PLOT_HILLS"}
        if glyph.isalpha():
            assert render_map.base_glyph(tile) == glyph.upper()
        else:
            with pytest.raises(AssertionError):
                render_map.base_glyph(tile)


def test_settle_marks_foreign_borders_as_unfoundable_without_a_digit():
    s = state(40)
    g = grid(40, "settle")
    foreign = [t for t in LANDMARKS["t40_tiles"]
               if t.get("owner") is not None and t["owner"] != s.player_id]
    assert foreign
    cities = dict(((c["x"], c["y"]), c) for c in s.foreign_cities)
    checked = 0
    for tile in foreign:
        pos = (tile["x"], tile["y"])
        if pos in cities:
            continue
        # Water inside a rival's border is still blank - terrain outranks ownership.
        if tile.get("plotType") in ("PLOT_OCEAN", "PLOT_PEAK"):
            assert g.marker(*pos) == " ", pos
            continue
        assert g.marker(*pos) == "]", pos
        assert s.found_blockers(pos), pos
        checked += 1
    assert checked, "expected some land inside a rival border"


def test_every_view_prints_the_shared_symbol_block():
    for view in render_map.VIEWS:
        text = render_map.render(state(40), view)
        assert "SHARED SYMBOLS" in text, view


def test_shared_legend_never_advertises_a_symbol_the_view_cannot_draw():
    """`settle` used to list "' revealed but FOGGED" above "this view omits fog".

    A legend entry for a glyph the view never emits is not harmless noise - it
    directly contradicts the omissions block three lines later, and a reader who
    trusts it will look for fog information that is not there.
    """
    fog_line = "'  revealed but FOGGED"
    territory_line = "+  your territory"
    worked_line = "#  worked by a citizen"
    for view in render_map.VIEWS:
        text = render_map.render(state(40), view)
        renderer = render_map.RENDERERS[view]
        legend = text.split("LEGEND", 1)[1].split("THIS VIEW OMITS", 1)[0]
        assert (fog_line in legend) == renderer.tracks_fog, view
        assert (territory_line in legend) == ("territory" in renderer.shows), view
        assert (worked_line in legend) == ("worked" in renderer.shows), view


def test_no_view_omits_something_its_legend_advertises():
    """Cross-check the two blocks against each other, for every view."""
    for view in render_map.VIEWS:
        text = render_map.render(state(40), view)
        legend = text.split("LEGEND", 1)[1].split("THIS VIEW OMITS", 1)[0]
        omits = text.split("THIS VIEW OMITS", 1)[1].split("\n\n", 1)[0]
        if "fog:" in omits or "fog " in omits:
            assert "FOGGED" not in legend, view


def test_worked_and_resource_glyphs_no_longer_collide():
    g = grid(40, "worker")
    tiles = dict(((t["x"], t["y"]), t) for t in LANDMARKS["t40_tiles"])
    s = state(40)
    worked = s.worked_tiles()
    for pos, tile in tiles.items():
        cell = g.cell(*pos)
        if cell[:1] == "#":
            assert pos in worked, pos
        if len(cell) > 3 and cell[3] == "*":
            assert tile.get("bonus") and not tile.get("improvement"), pos


# -- both sides of a fight ------------------------------------------------


def test_military_lists_your_units_as_well_as_rivals():
    s = state(40)
    text = render_map.render(s, "military")
    assert "RIVAL UNITS IN SIGHT" in text
    assert "YOUR UNITS" in text
    for unit in s.units:
        assert "(%d,%d) %s" % (unit["x"], unit["y"], unit["type"]) in text


def test_worker_warns_about_rival_units():
    """A worker sent to an unimproved resource is unarmed and slow."""
    s = state(40)
    text = render_map.render(s, "worker")
    assert s.foreign_units
    for unit in s.foreign_units:
        assert "(%d,%d) %s" % (unit["x"], unit["y"], unit["type"]) in text
    assert "DO NOT WALK A WORKER INTO THESE" in text


def test_worker_with_no_rivals_in_sight_says_fog_reports_nothing():
    s = state(0)
    assert not s.foreign_units
    text = render_map.render(s, "worker")
    assert "--view military" in text


# -- yields are the game's, not ours --------------------------------------


def test_jungle_yields_match_the_xml_derivation():
    """grass 2/0/0; jungle -1 food; hills -1 food +1 prod (CIV4YieldInfos).

    Checked against every unimproved, resource-free tile in the whole run, so
    this fails if the mod's export or this reading of it ever drifts.
    """
    seen = {}
    for path in all_samples():
        with open(path, encoding="utf-8") as handle:
            for tile in json.load(handle)["map"]["tiles"]:
                if tile.get("bonus") or tile.get("improvement") or tile.get("route"):
                    continue
                if tile["terrain"] != "TERRAIN_GRASS":
                    continue
                key = (tile.get("plotType", "PLOT_LAND"), tile.get("feature"))
                seen.setdefault(key, set()).add(tuple(tile["yields"]))
    assert seen[("PLOT_LAND", "FEATURE_JUNGLE")] == {(1, 0, 0)}
    assert seen[("PLOT_HILLS", "FEATURE_JUNGLE")] == {(0, 1, 0)}
    assert seen[("PLOT_HILLS", None)] == {(1, 1, 0)}


# -- fog ------------------------------------------------------------------


def fogged_and_visible_tiles():
    revealed = [(t["x"], t["y"]) for t in LANDMARKS["t40_tiles"]]
    visible = [(t["x"], t["y"]) for t in LANDMARKS["t40_tiles"] if t.get("visibleNow")]
    fogged = [p for p in revealed if p not in set(visible)]
    assert visible and fogged, "turn 40 should have both"
    return fogged, visible


@pytest.mark.parametrize("view", ["explore", "military"])
def test_fog_tracking_views_distinguish_three_states(view):
    """Flattening fogged into visible is the failure that gets a unit killed."""
    fogged, visible = fogged_and_visible_tiles()
    g = grid(40, view)
    occupied = set()
    for section in (LANDMARKS["t40_foreign_units"], LANDMARKS["t40_foreign_cities"]):
        occupied.update((e["x"], e["y"]) for e in section)
    for unit in state(40).units:
        occupied.add((unit["x"], unit["y"]))
    for city in state(40).cities:
        occupied.add((city["x"], city["y"]))

    marked = [p for p in fogged if p not in occupied]
    assert marked
    assert all(g.marker(*p) == "'" for p in marked)
    assert all(g.marker(*p) != "'" for p in visible if p not in occupied)


@pytest.mark.parametrize("view", ["settle", "yields", "worker"])
def test_non_fog_views_say_so_in_their_omissions(view):
    text = render_map.render(state(40), view)
    assert "THIS VIEW OMITS" in text


def test_unrevealed_renders_as_a_dot_not_as_empty():
    g = grid(40, "military")
    revealed = set((t["x"], t["y"]) for t in LANDMARKS["t40_tiles"])
    holes = [(x, y) for y in g.ys for x in g.xs if (x, y) not in revealed]
    assert holes, "turn 40's bounding box should contain unrevealed tiles"
    for x, y in holes:
        assert g.cell(x, y).strip() == "."


# -- military content -----------------------------------------------------

def test_foreign_city_and_units_are_drawn_and_listed():
    g = grid(40, "military")
    text = render_map.render(state(40), "military")
    for city in LANDMARKS["t40_foreign_cities"]:
        assert g.marker(city["x"], city["y"]) == "c"
        assert city["name"] in text
    for unit in LANDMARKS["t40_foreign_units"]:
        assert g.marker(unit["x"], unit["y"]) == str(unit["owner"])
        assert "(%d,%d) %s" % (unit["x"], unit["y"], unit["type"]) in text


def test_military_reports_distance_to_the_nearest_own_city():
    text = render_map.render(state(40), "military")
    assert "tiles from Lisbon" in text or "tiles from Oporto" in text


# -- yields ---------------------------------------------------------------


def test_yields_grid_prints_the_exported_numbers():
    g = grid(40, "yields")
    for tile in LANDMARKS["t40_tiles"]:
        cell = g.cell(tile["x"], tile["y"])
        assert cell[1:4] == "".join(str(v) for v in tile["yields"][:3])


def test_yields_totals_only_count_worked_tiles():
    s = state(40)
    text = render_map.render(s, "yields")
    for city in s.cities:
        expected = [0, 0, 0]
        for x, y in city["workedTiles"]:
            for i in range(3):
                expected[i] += s.tiles[(x, y)]["yields"][i]
        assert "%d food / %d prod / %d commerce" % tuple(expected) in text


# -- worker ---------------------------------------------------------------


def test_worker_lists_only_unimproved_resources_inside_a_city_radius():
    s = state(40)
    text = render_map.render(s, "worker")
    workable = set()
    for city in s.cities:
        workable.update(s.city_cross(city["x"], city["y"]))
    for pos in workable:
        tile = s.tiles.get(pos)
        if tile is None or not tile.get("bonus"):
            continue
        line = "  (%d,%d) %s" % (pos[0], pos[1], tile["bonus"])
        if tile.get("improvement"):
            assert line not in text
        else:
            assert line in text


def test_worker_does_not_claim_to_know_the_tech_tree():
    """The bonus -> build -> tech chain is the rules-lookup tool's job."""
    text = render_map.render(state(40), "worker")
    assert "CIV4BonusInfos.xml" in text and "CIV4BuildInfos.xml" in text


# -- geometry -------------------------------------------------------------


def test_axis_window_without_wrap_is_the_plain_span():
    assert render_map.axis_window([3, 5, 7], 20, False) == [3, 4, 5, 6, 7]


def test_axis_window_with_wrap_crosses_the_seam():
    """A region straddling x=0 must render contiguously, not span the whole map."""
    window = render_map.axis_window([0, 1, 2, 18, 19], 20, True)
    assert window == [18, 19, 0, 1, 2]


def test_axis_window_with_wrap_does_not_wrap_when_it_need_not():
    window = render_map.axis_window([5, 6, 7], 20, True)
    assert window == [5, 6, 7]


def test_distance_is_chebyshev_and_wraps_in_x():
    s = state(0)
    assert s.wrap_x and not s.wrap_y
    assert s.distance((0, 5), (2, 6)) == 2
    assert s.distance((1, 5), (s.width - 1, 5)) == 2


def test_city_cross_is_21_tiles_minus_corners():
    s = state(0)
    cross = s.city_cross(40, 20)
    assert len(cross) == 21
    assert (38, 18) not in cross and (42, 22) not in cross
    assert (38, 20) in cross and (40, 22) in cross


def test_min_city_range_blocks_a_square_not_a_circle():
    s = state(36)
    lisbon = LANDMARKS["t36_cities"]["Lisbon"]
    corner = (lisbon[0] + 2, lisbon[1] + 2)
    assert any("Chebyshev" in r for r in s.found_blockers(corner))
    outside = (lisbon[0] + 3, lisbon[1] + 2)
    assert not any("Chebyshev" in r for r in s.found_blockers(outside))


def test_water_and_peaks_are_reported_unfoundable():
    s = state(40)
    water = [(t["x"], t["y"]) for t in LANDMARKS["t40_tiles"]
             if t.get("plotType") == "PLOT_OCEAN"]
    peaks = [(t["x"], t["y"]) for t in LANDMARKS["t40_tiles"]
             if t.get("plotType") == "PLOT_PEAK"]
    assert water and peaks
    assert any("water" in r for r in s.found_blockers(water[0]))
    assert any("peak" in r for r in s.found_blockers(peaks[0]))


# -- output contract ------------------------------------------------------


@pytest.mark.parametrize("path", all_samples())
@pytest.mark.parametrize("view", render_map.VIEWS)
def test_every_view_renders_every_sample_turn(path, view):
    text = render_map.render(render_map.State(path), view)
    assert text.endswith("\n")
    assert "LEGEND" in text
    assert "THIS VIEW OMITS" in text
    assert "NORTH IS UP" in text


@pytest.mark.parametrize("view", render_map.VIEWS)
def test_header_echoes_the_invocation(view):
    text = render_map.render(state(40), view, (75, 15), 4)
    assert "turn_0040.json" in text
    assert "turn    40" in text
    assert "view    %s" % view in text
    assert "cropped around (75,15) radius 4" in text
    assert "84 x 52" in text


@pytest.mark.parametrize("view", render_map.VIEWS)
def test_grid_columns_line_up(view):
    g = Grid(render_map.render(state(40), view))
    # Every cell is closed by '|', and every COLUMN_GROUP-th boundary is doubled.
    # These are the anchors the grid exists to make checkable by eye, so they are
    # checked mechanically rather than trusted.
    for y in g.ys:
        row = g.rows[y]
        for i in range(len(g.xs)):
            start = g.offset(i)
            assert row[start:start + g.cell_width + 1].endswith("|"), (view, y, i, row)
            if i and i % render_map.COLUMN_GROUP == 0:
                assert row[start - 1] == "|", (view, y, i, "group boundary not doubled")


@pytest.mark.parametrize("view", render_map.VIEWS)
def test_omissions_always_point_somewhere(view):
    text = render_map.render(state(40), view)
    body = text.split("THIS VIEW OMITS", 1)[1].split("\n\n", 1)[0]
    entries = [l for l in body.split("\n") if l.strip()]
    assert entries
    # Every omission has to name where to go instead, or the block is just a
    # list of things the agent now cannot find.
    for line in entries:
        assert "->" in line, line
        assert line.split("->")[1].strip()


def test_turn0_header_counts_match_the_file():
    text = render_map.render(state(0), "settle")
    n = LANDMARKS["t0_revealed"]
    assert "%d tiles revealed, %d visible now" % (n, n) in text


# -- cli ------------------------------------------------------------------


def test_cli_renders_to_stdout(capsys):
    assert render_map.main([sample(0), "--view", "settle"]) == 0
    assert "civ4-advisor map render" in capsys.readouterr().out


def test_cli_rejects_an_unknown_view():
    with pytest.raises(SystemExit):
        render_map.main([sample(0), "--view", "nonsense"])


def test_cli_rejects_a_missing_file():
    with pytest.raises(SystemExit):
        render_map.main([os.path.join(SAMPLE_DIR, "turn_9999.json")])
