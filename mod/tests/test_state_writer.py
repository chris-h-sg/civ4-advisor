"""Tests for the mod's AdvisorStateWriter, run outside Civ IV.

Loads the real mod source (never a copy) with the Python-2-only builtins and the
Cy* game API shimmed, so extraction and serialization can be checked without
launching the game. Catches structural mistakes - wrong sentinel, int-vs-bool,
schema drift, encoding bugs - before a round trip through an actual play session.

NOTE: this runs under **Python 3** (developer tooling, like harness/), even though
the code under test is Python 2.4. It therefore verifies behaviour only and cannot
catch 2.4 syntax violations; those still need review by eye.

    pip install jsonschema
    python mod/tests/test_state_writer.py
"""
import json
import os
import sys
import tempfile
import types
import unittest

import jsonschema

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "mod", "Assets", "Python", "AdvisorStateWriter.py")
SCHEMA = os.path.join(REPO, "schema", "state.schema.json")

NO_TECH = -1
NO_CIVIC = -1
COMMERCE_RESEARCH = 1

TECHS = ["TECH_AGRICULTURE", "TECH_MINING", "TECH_THE_WHEEL", "TECH_BRONZE_WORKING"]
CIVIC_OPTIONS = ["CIVICOPTION_GOVERNMENT", "CIVICOPTION_LEGAL", "CIVICOPTION_LABOR"]
CIVICS = ["CIVIC_DESPOTISM", "CIVIC_BARBARISM", "CIVIC_TRIBALISM"]
UNITS = ["UNIT_SCOUT", "UNIT_WARRIOR", "UNIT_WORKER", "UNIT_SETTLER"]
BUILDINGS = ["BUILDING_PALACE", "BUILDING_BARRACKS"]
PROJECTS = ["PROJECT_APOLLO_PROGRAM"]
PROCESSES = ["PROCESS_WEALTH", "PROCESS_RESEARCH"]

PLAYER_ID = 3
TEAM_ID = 7

# What CyCity.getProductionNeeded() returns when there is nothing to complete.
MAX_INT = 2147483647


class Info(object):
    def __init__(self, t):
        self._t = t

    def getType(self):
        return self._t


class Game(object):
    def getTurnYear(self, n):
        return -4000 + n * 40

    def getGameSpeedType(self):
        return 0

    def getPlayerScore(self, i):
        assert i == PLAYER_ID, "score must be read for the exported player"
        return 129


class Map(object):
    def getGridWidth(self):
        return 84

    def getGridHeight(self):
        return 52

    # Deliberately ints, not bools: the C++ bindings hand back 1/0 and the
    # serializer must still emit JSON true/false.
    def isWrapX(self):
        return 1

    def isWrapY(self):
        return 0


class Unit(object):
    def __init__(self, unitId, unitType=0, x=10, y=20, baseMoves=1,
                 damage=0, dead=False):
        self._id = unitId
        self._type = unitType
        self._x = x
        self._y = y
        self._baseMoves = baseMoves
        self._damage = damage
        self._dead = dead

    def getID(self):
        return self._id

    def getUnitType(self):
        return self._type

    def getX(self):
        return self._x

    def getY(self):
        return self._y

    def baseMoves(self):
        return self._baseMoves

    def movesLeft(self):
        # A tripwire, not an accessor: reading moves-remaining at our export
        # timing yields the turn that just ended, so the exporter must never
        # call this. Fails loudly if anyone reintroduces it.
        raise AssertionError("movesLeft() is meaningless at export time; use baseMoves()")

    def getDamage(self):
        return self._damage

    def isDead(self):
        return self._dead


class City(object):
    """A city whose production kind is chosen by which of unit/building/project/
    process is not None. Defaults are a size-2 city building a Worker."""

    def __init__(self, cityId, name=u"Thebes", x=32, y=40, owner=PLAYER_ID,
                 unit=2, building=None, project=None, process=None,
                 production=10, productionNeeded=60, none=False):
        self._id = cityId
        self._name = name
        self._x = x
        self._y = y
        self._owner = owner
        self._unit = unit
        self._building = building
        self._project = project
        self._process = process
        self._production = production
        self._productionNeeded = productionNeeded
        self._none = none
        self.cultureArgs = []
        self.foodDifferenceArgs = []
        self.productionDifferenceArgs = []
        self.unhappyArgs = []
        self.badHealthArgs = []

    def isNone(self):
        return self._none

    def getID(self):
        return self._id

    def getName(self):
        return self._name

    def getOwner(self):
        return self._owner

    def getX(self):
        return self._x

    def getY(self):
        return self._y

    def getPopulation(self):
        return 2

    def getFood(self):
        return 14

    def foodDifference(self, bBottom):
        self.foodDifferenceArgs.append(bBottom)
        return 3

    def growthThreshold(self):
        return 24

    def isProductionUnit(self):
        return self._unit is not None

    def isProductionBuilding(self):
        return self._building is not None

    def isProductionProject(self):
        return self._project is not None

    def isProductionProcess(self):
        return self._process is not None

    def getProductionUnit(self):
        return self._unit

    def getProductionBuilding(self):
        return self._building

    def getProductionProject(self):
        return self._project

    def getProductionProcess(self):
        return self._process

    def getProduction(self):
        return self._production

    def getProductionNeeded(self):
        return self._productionNeeded

    def getCurrentProductionDifference(self, bIgnoreFood, bOverflow):
        self.productionDifferenceArgs.append((bIgnoreFood, bOverflow))
        return 4

    def getCulture(self, playerId):
        self.cultureArgs.append(playerId)
        return 12

    def getCultureThreshold(self):
        return 100

    def happyLevel(self):
        return 4

    def unhappyLevel(self, iExtra):
        self.unhappyArgs.append(iExtra)
        return 1

    def goodHealth(self):
        return 5

    def badHealth(self, bNoAngry):
        self.badHealthArgs.append(bNoAngry)
        return 2


def _cursor(items, index):
    """Emulate the engine's (object, iterator) cursor pair, exhausting to None."""
    if index < len(items):
        return items[index], index + 1
    return None, index


class Player(object):
    def __init__(self, research=1, units=None, cities=None):
        self._research = research
        self._units = units
        if self._units is None:
            self._units = [Unit(0, unitType=0), Unit(1, unitType=1)]
        self._cities = cities
        if self._cities is None:
            self._cities = [City(0)]
        self.researchRateArgs = []
        self.turnsLeftArgs = []
        self.researchModifierArgs = []

    def firstUnit(self, bRev):
        return _cursor(self._units, 0)

    def nextUnit(self, cursor, bRev):
        return _cursor(self._units, cursor)

    def firstCity(self, bRev):
        return _cursor(self._cities, 0)

    def nextCity(self, cursor, bRev):
        return _cursor(self._cities, cursor)

    def getTeam(self):
        return TEAM_ID

    def getCurrentEra(self):
        return 0

    def getLeaderType(self):
        return 0

    def getCivilizationType(self):
        return 0

    def getGold(self):
        return 4

    def calculateGoldRate(self):
        return -1  # deficit: must survive as a negative number

    def calculateResearchRate(self, t):
        self.researchRateArgs.append(t)
        return 11

    def getCurrentResearch(self):
        return self._research

    def getResearchTurnsLeft(self, t, overflow):
        self.turnsLeftArgs.append((t, overflow))
        return 3

    def getOverflowResearch(self):
        return 7

    def calculateResearchModifier(self, t):
        self.researchModifierArgs.append(t)
        return 130  # +30%, e.g. one met civ already knows the tech

    def getCommercePercent(self, c):
        assert c == COMMERCE_RESEARCH
        return 100

    def getCivics(self, i):
        return i  # civic option i -> civic i


class Team(object):
    def __init__(self):
        self.researchCostArgs = []
        self.researchProgressArgs = []

    def isHasTech(self, i):
        return i in (0, 1)  # Agriculture + Mining only

    def getResearchProgress(self, t):
        self.researchProgressArgs.append(t)
        return 42

    def getResearchCost(self, t):
        self.researchCostArgs.append(t)
        return 76


class Gc(object):
    def __init__(self, player):
        self._player = player
        # One shared instance so tests can inspect what was asked of it.
        self._team = Team()
        self.playerLookups = []
        self.teamLookups = []

    def getGame(self):
        return Game()

    def getMap(self):
        return Map()

    def getPlayer(self, i):
        self.playerLookups.append(i)
        return self._player

    def getTeam(self, i):
        self.teamLookups.append(i)
        return self._team

    def getEraInfo(self, i):
        return Info("ERA_ANCIENT")

    def getGameSpeedInfo(self, i):
        return Info("GAMESPEED_NORMAL")

    def getLeaderHeadInfo(self, i):
        return Info("LEADER_HATSHEPSUT")

    def getCivilizationInfo(self, i):
        return Info("CIVILIZATION_EGYPT")

    def getNumTechInfos(self):
        return len(TECHS)

    def getTechInfo(self, i):
        return Info(TECHS[i])

    def getNumCivicOptionInfos(self):
        return len(CIVIC_OPTIONS)

    def getCivicOptionInfo(self, i):
        return Info(CIVIC_OPTIONS[i])

    def getCivicInfo(self, i):
        return Info(CIVICS[i])

    def getUnitInfo(self, i):
        return Info(UNITS[i])

    def getBuildingInfo(self, i):
        return Info(BUILDINGS[i])

    def getProjectInfo(self, i):
        return Info(PROJECTS[i])

    def getProcessInfo(self, i):
        return Info(PROCESSES[i])


def loadModule(player=None, localConfigPath=None):
    """Exec the real mod source with the game API and Python 2 builtins shimmed.

    localConfigPath=None leaves LocalConfig unimportable, which is the "not
    configured on this machine" case getStateFilePath has to tolerate.
    """
    player = player or Player()
    gc = Gc(player)

    fake = types.ModuleType("CvPythonExtensions")
    fake.CyGlobalContext = lambda: gc
    fake.TechTypes = type("TechTypes", (), {"NO_TECH": NO_TECH})
    fake.CivicTypes = type("CivicTypes", (), {"NO_CIVIC": NO_CIVIC})
    fake.CommerceTypes = type("CommerceTypes", (), {"COMMERCE_RESEARCH": COMMERCE_RESEARCH})
    sys.modules["CvPythonExtensions"] = fake

    sys.modules.pop("LocalConfig", None)
    if localConfigPath is not None:
        localConfig = types.ModuleType("LocalConfig")
        localConfig.STATE_FILE_PATH = localConfigPath
        sys.modules["LocalConfig"] = localConfig

    ns = {
        "__name__": "AdvisorStateWriter",
        # Python 2 builtins the module legitimately relies on.
        "long": int,
        "basestring": str,
        "unicode": str,
    }
    with open(SRC) as f:
        exec(compile(f.read(), SRC, "exec"), ns)
    ns["_testGc"] = gc
    ns["_testPlayer"] = player
    ns["_testTeam"] = gc._team
    return ns


class SerializerTests(unittest.TestCase):
    def setUp(self):
        self.mod = loadModule()
        self.toJson = self.mod["toJson"]

    def test_scalars(self):
        self.assertEqual(self.toJson(None), "null")
        self.assertEqual(self.toJson(True), "true")
        self.assertEqual(self.toJson(False), "false")
        self.assertEqual(self.toJson(0), "0")
        self.assertEqual(self.toJson(-7), "-7")

    def test_bools_not_emitted_as_ints(self):
        # bool is a subclass of int; the True/False checks must come first.
        self.assertEqual(self.toJson({"a": True}), '{"a": true}')

    def test_escapes_quotes_backslashes_and_whitespace(self):
        self.assertEqual(self.toJson({"a": 'q"\\ \n\t\r'}), '{"a": "q\\"\\\\ \\n\\t\\r"}')

    def test_escapes_control_characters(self):
        # Raw control characters are invalid inside JSON strings.
        self.assertEqual(self.toJson("\x01\x1f"), '"\\u0001\\u001f"')
        json.loads(self.toJson("\x01\x1f"))

    def test_non_ascii_passes_through_and_reparses(self):
        self.assertEqual(json.loads(self.toJson("K\u00f6ln")), "K\u00f6ln")

    def test_empty_containers(self):
        self.assertEqual(self.toJson({"a": [], "b": {}}, 2), '{"a": [], "b": {}}')

    def test_keys_sorted_for_deterministic_output(self):
        self.assertEqual(self.toJson({"b": 1, "a": 2, "c": 3}), '{"a": 2, "b": 1, "c": 3}')
        # Same content built in a different order must serialize identically.
        one, two = {}, {}
        for k in "abcdef":
            one[k] = 1
        for k in "fedcba":
            two[k] = 1
        self.assertEqual(self.toJson(one, 2), self.toJson(two, 2))

    def test_compact_mode_is_single_line(self):
        text = self.toJson({"a": {"b": [1, 2]}, "c": "x" * 200}, 0)
        self.assertNotIn("\n", text)

    def test_short_containers_stay_inline_when_pretty_printing(self):
        self.assertNotIn("\n", self.toJson({"a": 1, "b": 2}, 2))

    def test_long_containers_break_across_lines(self):
        text = self.toJson({"key": ["item-%d" % i for i in range(40)]}, 2)
        self.assertIn("\n", text)
        self.assertEqual(json.loads(text)["key"][0], "item-0")

    def test_container_holding_a_broken_child_also_breaks(self):
        # Parent looks short, but can't stay inline once a child is multi-line.
        text = self.toJson({"t": [{"x": 1, "y": 2, "name": "a" * 90}]}, 2)
        self.assertIn("\n", text)
        json.loads(text)

    def test_nesting_indentation_round_trips(self):
        value = {"a": {"b": {"c": [{"d": "x" * 80}, {"e": "y" * 80}]}}}
        self.assertEqual(json.loads(self.toJson(value, 2)), value)

    def test_non_string_keys_are_stringified(self):
        self.assertEqual(self.toJson({1: "a"}), '{"1": "a"}')

    def test_unsupported_type_raises(self):
        self.assertRaises(TypeError, self.toJson, object())


class BuildStateTests(unittest.TestCase):
    def setUp(self):
        self.mod = loadModule()
        self.state = self.mod["buildState"](5, PLAYER_ID, "onEndGameTurn")
        self.parsed = json.loads(self.mod["toJson"](self.state, 2))

    def test_only_implemented_sections_are_present(self):
        # Unimplemented sections are omitted, never emitted empty - an empty
        # map object would be indistinguishable from "player has revealed nothing".
        self.assertEqual(sorted(self.parsed.keys()),
                         ["cities", "game", "meta", "player", "units"])

    def test_meta(self):
        self.assertEqual(self.parsed["meta"], {"schemaVersion": 1, "trigger": "onEndGameTurn"})

    def test_year_follows_the_passed_turn_not_the_live_one(self):
        # onEndGameTurn labels state for the upcoming turn, so the year has to
        # be derived from that turn rather than from getGameTurnYear().
        self.assertEqual(self.parsed["game"]["gameTurn"], 5)
        self.assertEqual(self.parsed["game"]["year"], -3800)

    def test_map_wrap_flags_are_json_bools(self):
        self.assertIs(self.parsed["game"]["wrapX"], True)
        self.assertIs(self.parsed["game"]["wrapY"], False)

    def test_game_types_are_xml_type_keys(self):
        self.assertEqual(self.parsed["game"]["era"], "ERA_ANCIENT")
        self.assertEqual(self.parsed["game"]["gameSpeed"], "GAMESPEED_NORMAL")

    def test_player_identity_and_economy(self):
        self.assertEqual(self.parsed["player"]["id"], PLAYER_ID)
        self.assertEqual(self.parsed["player"]["leader"], "LEADER_HATSHEPSUT")
        self.assertEqual(self.parsed["player"]["civilization"], "CIVILIZATION_EGYPT")
        self.assertEqual(self.parsed["player"]["gold"], 4)
        self.assertEqual(self.parsed["player"]["goldPerTurn"], -1)
        self.assertEqual(self.parsed["player"]["score"], 129)

    def test_beakers_use_the_no_tech_sentinel(self):
        # calculateResearchRate(NO_TECH) means "current research", and returns the
        # modifier-inclusive rate that matches the game UI - not raw slider commerce.
        self.assertEqual(self.mod["_testPlayer"].researchRateArgs, [NO_TECH])
        self.assertEqual(self.parsed["player"]["beakersPerTurn"], 11)

    def test_research(self):
        self.assertEqual(self.parsed["player"]["research"], {
            "current": "TECH_MINING",
            # 42 banked + 7 overflow * 130% modifier = 42 + 9
            "progress": 51,
            "cost": 76,
            "turnsLeft": 3,
            "sciencePercent": 100,
        })

    def test_research_progress_and_cost_are_read_for_the_current_tech(self):
        self.assertEqual(self.mod["_testTeam"].researchProgressArgs, [1])
        self.assertEqual(self.mod["_testTeam"].researchCostArgs, [1])
        self.assertEqual(self.mod["_testPlayer"].researchModifierArgs, [1])

    def test_research_progress_credits_modifier_scaled_overflow(self):
        # The game's own research bar adds overflow from the previously completed
        # tech, scaled by the research modifier. Without it, progress would
        # understate what the player sees and contradict turnsLeft, which
        # already credits it.
        self.assertEqual(self.parsed["player"]["research"]["progress"], 42 + (7 * 130) // 100)

    def test_research_cost_is_the_team_cost_not_the_raw_xml_cost(self):
        # getTechInfo(t).getResearchCost() would be the unscaled XML number, before
        # handicap/game-speed/world-size scaling - not what the game displays.
        self.assertEqual(self.parsed["player"]["research"]["cost"], 76)
        self.assertEqual(self.mod["_testGc"].teamLookups, [TEAM_ID])

    def test_turns_left_asks_for_the_overflow_inclusive_count(self):
        # bOverflow=False would disagree with the number the game displays.
        self.assertEqual(self.mod["_testPlayer"].turnsLeftArgs, [(1, True)])

    def test_known_techs_come_from_the_team(self):
        self.assertEqual(self.parsed["player"]["knownTechs"],
                         ["TECH_AGRICULTURE", "TECH_MINING"])
        self.assertEqual(self.mod["_testGc"].teamLookups, [TEAM_ID])

    def test_civics_map_option_to_civic(self):
        self.assertEqual(self.parsed["player"]["civics"], {
            "CIVICOPTION_GOVERNMENT": "CIVIC_DESPOTISM",
            "CIVICOPTION_LEGAL": "CIVIC_BARBARISM",
            "CIVICOPTION_LABOR": "CIVIC_TRIBALISM",
        })

    def test_state_is_built_for_the_requested_player(self):
        self.assertEqual(self.mod["_testGc"].playerLookups, [PLAYER_ID])


def buildWith(units=None, cities=None):
    """Export a turn for a player with the given units/cities, parsed back."""
    mod = loadModule(Player(units=units, cities=cities))
    return mod, json.loads(mod["toJson"](mod["buildState"](5, PLAYER_ID, "onEndGameTurn"), 2))


class UnitTests(unittest.TestCase):
    def test_fields(self):
        _, parsed = buildWith(units=[Unit(4, unitType=2, x=7, y=9, damage=35)])
        self.assertEqual(parsed["units"], [
            {"id": 4, "type": "UNIT_WORKER", "x": 7, "y": 9,
             "moves": 1, "damage": 35},
        ])

    def test_sorted_by_id_regardless_of_iteration_order(self):
        _, parsed = buildWith(units=[Unit(9), Unit(2), Unit(5)])
        self.assertEqual([u["id"] for u in parsed["units"]], [2, 5, 9])

    def test_dead_units_are_skipped(self):
        _, parsed = buildWith(units=[Unit(1), Unit(2, dead=True), Unit(3)])
        self.assertEqual([u["id"] for u in parsed["units"]], [1, 3])

    def test_no_units_is_an_empty_list_not_an_omission(self):
        # An empty list here is honest: this player really has no units. (It's
        # unimplemented SECTIONS that get omitted, not empty implemented ones.)
        _, parsed = buildWith(units=[])
        self.assertEqual(parsed["units"], [])

    def test_moves_is_the_per_turn_total_in_whole_moves(self):
        # baseMoves() is already in displayed moves - no MOVE_DENOMINATOR division.
        _, parsed = buildWith(units=[Unit(0, baseMoves=2)])
        self.assertEqual(parsed["units"][0]["moves"], 2)

    def test_moves_left_is_never_read(self):
        # It is unusable at our export timing: the per-turn reset happens in
        # CvUnit::doTurn(), which runs after onEndGameTurn has already written the
        # file, so movesLeft() describes the turn that just ended. The mock raises
        # if it is touched. Seen live: a warrior that had moved reported 0.
        _, parsed = buildWith(units=[Unit(0)])
        self.assertNotIn("movesLeft", parsed["units"][0])


class CityTests(unittest.TestCase):
    def test_fields(self):
        _, parsed = buildWith(cities=[City(6, name=u"Thebes", x=32, y=40)])
        self.assertEqual(parsed["cities"], [{
            "id": 6, "name": "Thebes", "x": 32, "y": 40,
            "population": 2, "food": 14, "foodPerTurn": 3, "growthThreshold": 24,
            "producing": "UNIT_WORKER", "production": 10, "productionNeeded": 60,
            "productionPerTurn": 4, "culture": 12, "cultureThreshold": 100,
            "happy": 4, "unhappy": 1, "healthy": 5, "unhealthy": 2,
        }])

    def test_sorted_by_id(self):
        _, parsed = buildWith(cities=[City(3), City(1), City(2)])
        self.assertEqual([c["id"] for c in parsed["cities"]], [1, 2, 3])

    def test_invalid_and_foreign_cities_are_skipped(self):
        _, parsed = buildWith(cities=[City(1), City(2, none=True), City(3, owner=PLAYER_ID + 1)])
        self.assertEqual([c["id"] for c in parsed["cities"]], [1])

    def test_culture_is_read_for_the_owner(self):
        # getCulture is per-player within a city; the owner's share is what counts
        # against cultureThreshold for the next border pop.
        city = City(0)
        buildWith(cities=[city])
        self.assertEqual(city.cultureArgs, [PLAYER_ID])

    def test_derived_rates_use_the_arguments_the_city_screen_uses(self):
        city = City(0)
        buildWith(cities=[city])
        self.assertEqual(city.foodDifferenceArgs, [True])
        self.assertEqual(city.productionDifferenceArgs, [(False, True)])
        self.assertEqual(city.unhappyArgs, [0])
        self.assertEqual(city.badHealthArgs, [False])

    def test_unicode_city_name_round_trips(self):
        # City names are the first game-supplied strings in the export; they come
        # back as wstrings, so the whole document goes unicode.
        _, parsed = buildWith(cities=[City(0, name=u"Köln-İstanbul — 京")])
        self.assertEqual(parsed["cities"][0]["name"], "Köln-İstanbul — 京")


class CityProductionTests(unittest.TestCase):
    """`producing` picks the XML Type key for whichever order kind is active."""

    def producing(self, **kwargs):
        _, parsed = buildWith(cities=[City(0, unit=None, **kwargs)])
        return parsed["cities"][0]

    def test_unit(self):
        _, parsed = buildWith(cities=[City(0, unit=3)])
        self.assertEqual(parsed["cities"][0]["producing"], "UNIT_SETTLER")

    def test_building(self):
        self.assertEqual(self.producing(building=1)["producing"], "BUILDING_BARRACKS")

    def test_project(self):
        self.assertEqual(self.producing(project=0)["producing"], "PROJECT_APOLLO_PROGRAM")

    def test_process(self):
        self.assertEqual(self.producing(process=0)["producing"], "PROCESS_WEALTH")

    def test_nothing_queued_is_null(self):
        self.assertIsNone(self.producing()["producing"])

    def test_production_needed_is_null_when_nothing_is_queued(self):
        # getProductionNeeded() returns MAX_INT for an empty queue; exporting that
        # would read as a real, absurdly expensive build.
        city = self.producing(productionNeeded=MAX_INT)
        self.assertIsNone(city["productionNeeded"])

    def test_production_needed_is_null_for_a_process(self):
        # Same MAX_INT sentinel: a process converts hammers forever, never completes.
        city = self.producing(process=1, productionNeeded=MAX_INT)
        self.assertEqual(city["producing"], "PROCESS_RESEARCH")
        self.assertIsNone(city["productionNeeded"])


class NoResearchSelectedTests(unittest.TestCase):
    """Turn 0 of a new game: no tech has been chosen yet."""

    def setUp(self):
        self.mod = loadModule(Player(research=NO_TECH))
        self.parsed = json.loads(
            self.mod["toJson"](self.mod["buildState"](0, PLAYER_ID, "onGameStart"), 2))

    def test_current_progress_cost_and_turns_left_are_null(self):
        research = self.parsed["player"]["research"]
        self.assertIsNone(research["current"])
        self.assertIsNone(research["progress"])
        self.assertIsNone(research["cost"])
        self.assertIsNone(research["turnsLeft"])

    def test_nothing_is_queried_for_no_tech(self):
        # Asking the engine about NO_TECH is the kind of thing that returns a
        # sentinel rather than raising, so don't ask at all.
        self.assertEqual(self.mod["_testPlayer"].turnsLeftArgs, [])
        self.assertEqual(self.mod["_testTeam"].researchProgressArgs, [])
        self.assertEqual(self.mod["_testTeam"].researchCostArgs, [])

    def test_science_percent_still_reported(self):
        self.assertEqual(self.parsed["player"]["research"]["sciencePercent"], 100)

    def test_beakers_still_reported(self):
        self.assertEqual(self.parsed["player"]["beakersPerTurn"], 11)


class SchemaConformanceTests(unittest.TestCase):
    """Each implemented section must satisfy its subschema in schema/state.schema.json.

    Whole-file validation deliberately isn't asserted: the schema requires sections
    the mod doesn't build yet. Swap this for a full-document check once every
    section is implemented.
    """

    def setUp(self):
        self.mod = loadModule()
        self.parsed = json.loads(
            self.mod["toJson"](self.mod["buildState"](5, PLAYER_ID, "onEndGameTurn"), 2))
        with open(SCHEMA) as f:
            self.schema = json.load(f)

    def assertSectionValid(self, section):
        sub = dict(self.schema["properties"][section])
        sub["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        errors = [e.message
                  for e in jsonschema.Draft202012Validator(sub).iter_errors(self.parsed[section])]
        self.assertEqual(errors, [], "%s section: %s" % (section, "; ".join(errors)))

    def test_schema_itself_is_well_formed(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_meta_section(self):
        self.assertSectionValid("meta")

    def test_game_section(self):
        self.assertSectionValid("game")

    def test_player_section(self):
        self.assertSectionValid("player")

    def test_units_section(self):
        self.assertSectionValid("units")

    def test_cities_section(self):
        self.assertSectionValid("cities")

    def test_process_city_section_still_validates(self):
        # The null productionNeeded branch has to satisfy the schema too.
        mod = loadModule(Player(cities=[City(0, unit=None, process=0,
                                             productionNeeded=MAX_INT)]))
        parsed = json.loads(mod["toJson"](mod["buildState"](5, PLAYER_ID, "x"), 2))
        sub = dict(self.schema["properties"]["cities"])
        sub["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        jsonschema.Draft202012Validator(sub).validate(parsed["cities"])

    def test_committed_example_still_validates(self):
        with open(os.path.join(REPO, "schema", "state.example.json")) as f:
            example = json.load(f)
        jsonschema.Draft202012Validator(self.schema).validate(example)


class WriteStateFileTests(unittest.TestCase):
    def setUp(self):
        self.mod = loadModule()
        self.tempDir = tempfile.mkdtemp()
        self.path = os.path.join(self.tempDir, "nested", "current_turn.json")

    def write(self, state):
        self.mod["writeStateFile"](self.path, state)
        with open(self.path, "rb") as f:
            return f.read()

    def test_creates_missing_directories(self):
        self.write({"a": 1})
        self.assertTrue(os.path.exists(self.path))

    def test_output_is_parseable_and_newline_terminated(self):
        raw = self.write({"a": 1})
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(json.loads(raw.decode("utf-8")), {"a": 1})

    def test_writes_utf8_without_line_ending_translation(self):
        # Binary mode: bytes on disk are exactly what was serialized, so Windows
        # doesn't turn \n into \r\n and non-ASCII survives as UTF-8.
        raw = self.write({"name": "K\u00f6ln", "note": "a\nb"})
        self.assertNotIn(b"\r\n", raw)
        self.assertEqual(json.loads(raw.decode("utf-8"))["name"], "K\u00f6ln")

    def test_overwrites_an_existing_file(self):
        self.write({"a": 1})
        self.assertEqual(json.loads(self.write({"b": 2}).decode("utf-8")), {"b": 2})

    def test_leaves_no_temp_file_behind(self):
        self.write({"a": 1})
        leftovers = [n for n in os.listdir(os.path.dirname(self.path)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_none_path_is_a_silent_no_op(self):
        # A machine without LocalConfig.py must not export, and must not crash.
        self.mod["writeStateFile"](None, {"a": 1})

    def test_real_state_round_trips(self):
        state = self.mod["buildState"](5, PLAYER_ID, "onEndGameTurn")
        self.assertEqual(json.loads(self.write(state).decode("utf-8"))["game"]["gameTurn"], 5)

    def test_accented_city_name_survives_the_whole_write_path(self):
        # A renamed city is the realistic way non-ASCII reaches the file: the name
        # is a wstring, which makes the entire rendered document unicode and sends
        # it down writeStateFile's encode branch.
        mod = loadModule(Player(cities=[City(0, name=u"Köln")]))
        mod["writeStateFile"](self.path, mod["buildState"](5, PLAYER_ID, "onEndGameTurn"))
        with open(self.path, "rb") as f:
            raw = f.read()
        self.assertIn(u"Köln".encode("utf-8"), raw)
        self.assertEqual(json.loads(raw.decode("utf-8"))["cities"][0]["name"], u"Köln")


class StateFilePathTests(unittest.TestCase):
    def test_returns_none_when_local_config_is_absent(self):
        self.assertIsNone(loadModule()["getStateFilePath"]())

    def test_returns_configured_path(self):
        mod = loadModule(localConfigPath=r"C:\somewhere\current_turn.json")
        self.assertEqual(mod["getStateFilePath"](), r"C:\somewhere\current_turn.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
