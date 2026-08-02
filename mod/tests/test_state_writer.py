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

# Every "nothing here" sentinel in the engine's exposed enums is -1 (CvEnums.h).
NO_FEATURE = -1
NO_BONUS = -1
NO_IMPROVEMENT = -1
NO_ROUTE = -1
NO_PLAYER = -1

YIELD_FOOD = 0
YIELD_PRODUCTION = 1
YIELD_COMMERCE = 2

NUM_CITY_PLOTS = 21

TECHS = ["TECH_AGRICULTURE", "TECH_MINING", "TECH_THE_WHEEL", "TECH_BRONZE_WORKING"]
CIVIC_OPTIONS = ["CIVICOPTION_GOVERNMENT", "CIVICOPTION_LEGAL", "CIVICOPTION_LABOR"]
CIVICS = ["CIVIC_DESPOTISM", "CIVIC_BARBARISM", "CIVIC_TRIBALISM"]
UNITS = ["UNIT_SCOUT", "UNIT_WARRIOR", "UNIT_WORKER", "UNIT_SETTLER"]
BUILDINGS = ["BUILDING_PALACE", "BUILDING_BARRACKS"]
PROJECTS = ["PROJECT_APOLLO_PROGRAM"]
PROCESSES = ["PROCESS_WEALTH", "PROCESS_RESEARCH"]
GAME_OPTIONS = ["GAMEOPTION_NO_BARBARIANS", "GAMEOPTION_RAGING_BARBARIANS",
                "GAMEOPTION_AGGRESSIVE_AI"]
VICTORIES = ["VICTORY_CONQUEST", "VICTORY_DOMINATION", "VICTORY_CULTURAL"]
TERRAINS = ["TERRAIN_GRASS", "TERRAIN_PLAINS", "TERRAIN_COAST", "TERRAIN_DESERT"]
FEATURES = ["FEATURE_FOREST", "FEATURE_FLOOD_PLAINS"]
BONUSES = ["BONUS_CORN", "BONUS_COPPER"]
IMPROVEMENTS = ["IMPROVEMENT_FARM", "IMPROVEMENT_GOODY_HUT"]
ROUTES = ["ROUTE_ROAD", "ROUTE_RAILROAD"]

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
    def __init__(self, activePlayer=PLAYER_ID, options=(1,), victories=(0, 2)):
        self._activePlayer = activePlayer
        self._options = options
        self._victories = victories

    def getTurnYear(self, n):
        return -4000 + n * 40

    def getGameSpeedType(self):
        return 0

    def getPlayerScore(self, i):
        assert i == PLAYER_ID, "score must be read for the exported player"
        return 129

    def getActivePlayer(self):
        return self._activePlayer

    def getHandicapType(self):
        return 1

    def countCivPlayersEverAlive(self):
        return 7

    def countCivPlayersAlive(self):
        raise AssertionError(
            "alive-now would reveal a civ's destruction before the player could "
            "know; totalCivs uses countCivPlayersEverAlive")

    def isOption(self, i):
        return i in self._options

    def isVictoryValid(self, i):
        return i in self._victories


class Plot(object):
    """A map plot.

    The four accessors that return CURRENT truth regardless of fog - improvement,
    route, owner and the cached yield array - are tripwires that raise. The engine
    keeps a separate per-team remembered copy of the first three, and using the live
    getter instead would hand the player intelligence they do not have. Tests set
    the live and remembered values to different things, so a mix-up cannot pass.
    """

    def __init__(self, x=0, y=0, terrain=0, revealed=True, visible=False,
                 peak=False, hills=False, water=False, lake=False,
                 freshWater=False, river=False, feature=NO_FEATURE,
                 bonus=NO_BONUS, improvement=NO_IMPROVEMENT, route=NO_ROUTE,
                 owner=NO_PLAYER, yields=(1, 0, 0), none=False):
        self._x = x
        self._y = y
        self._terrain = terrain
        self._revealed = revealed
        self._visible = visible
        self._peak = peak
        self._hills = hills
        self._water = water
        self._lake = lake
        self._freshWater = freshWater
        self._river = river
        self._feature = feature
        self._bonus = bonus
        self._improvement = improvement
        self._route = route
        self._owner = owner
        self._yields = yields
        self._none = none
        self.revealedArgs = []
        self.visibleArgs = []
        self.bonusArgs = []
        self.revealedImprovementArgs = []
        self.revealedRouteArgs = []
        self.revealedOwnerArgs = []
        self.yieldArgs = []

    def isNone(self):
        return self._none

    def getX(self):
        return self._x

    def getY(self):
        return self._y

    def getTerrainType(self):
        return self._terrain

    def isRevealed(self, team, bDebug):
        self.revealedArgs.append((team, bDebug))
        return self._revealed

    def isVisible(self, team, bDebug):
        self.visibleArgs.append((team, bDebug))
        return self._visible

    def isPeak(self):
        return self._peak

    def isHills(self):
        return self._hills

    def isWater(self):
        return self._water

    def isLake(self):
        return self._lake

    def isFreshWater(self):
        return self._freshWater

    def isRiver(self):
        return self._river

    def getFeatureType(self):
        return self._feature

    def getBonusType(self, team):
        self.bonusArgs.append(team)
        return self._bonus

    def getRevealedImprovementType(self, team, bDebug):
        self.revealedImprovementArgs.append((team, bDebug))
        return self._improvement

    def getRevealedRouteType(self, team, bDebug):
        self.revealedRouteArgs.append((team, bDebug))
        return self._route

    def getRevealedOwner(self, team, bDebug):
        self.revealedOwnerArgs.append((team, bDebug))
        return self._owner

    def calculateYield(self, eYield, bDisplay):
        self.yieldArgs.append((eYield, bDisplay))
        return self._yields[eYield]

    def getImprovementType(self):
        raise AssertionError("live improvement leaks through fog; use getRevealedImprovementType")

    def getRouteType(self):
        raise AssertionError("live route leaks through fog; use getRevealedRouteType")

    def getOwner(self):
        raise AssertionError("live owner leaks through fog; use getRevealedOwner")

    def getYield(self, eYield):
        raise AssertionError("cached yield is the bDisplay=False variant; use calculateYield")

    def getPlotType(self):
        raise AssertionError(
            "PlotTypes.PLOT_* constants are unverified in the Python layer; "
            "use the isPeak/isHills/isWater predicates")

    def isBeingWorked(self):
        raise AssertionError(
            "live worked-status has no fog check and would leak rivals' tiles; "
            "worked tiles are read city-side from our own cities")

    def getWorkingCity(self):
        raise AssertionError("see isBeingWorked: worked tiles are read city-side")


def defaultPlots():
    """A small revealed patch: flat grass, a fogged hill, and a visible coast tile."""
    return [
        Plot(x=32, y=40, terrain=0, visible=True, yields=(2, 1, 2)),
        Plot(x=33, y=40, terrain=1, visible=True, hills=True, yields=(1, 2, 0)),
        Plot(x=34, y=40, terrain=2, water=True, yields=(1, 0, 2)),
    ]


class Map(object):
    def __init__(self, plots=None, width=84, height=52):
        if plots is None:
            plots = defaultPlots()
        self._plots = {}
        for plot in plots:
            self._plots[(plot.getX(), plot.getY())] = plot
        self._width = width
        self._height = height
        # One shared stand-in for everything the player has never seen, so a
        # full-grid scan doesn't allocate thousands of objects.
        self.unrevealed = Plot(revealed=False)
        self.lookups = []

    def getGridWidth(self):
        return self._width

    def getGridHeight(self):
        return self._height

    def plot(self, x, y):
        self.lookups.append((x, y))
        return self._plots.get((x, y), self.unrevealed)

    def plotByIndex(self, i):
        raise AssertionError("plot(x, y) gets the coordinates for free; plotByIndex needs two more calls")

    def getMapScriptName(self):
        return "Fractal"

    def getWorldSize(self):
        return 3

    def getClimate(self):
        return 3

    def getSeaLevel(self):
        return 1

    # Statistics of the GENERATED map, as opposed to the setup parameters above.
    # None of these is knowable to a player who hasn't explored, and all of them
    # sit temptingly close to the safe getters on the real CyMap.
    def getLandPlots(self):
        raise AssertionError("total land plots is the answer, not the parameter; use seaLevel")

    def getOwnedPlots(self):
        raise AssertionError("whole-map ownership census is not player-visible")

    def getNumBonuses(self, eBonus):
        raise AssertionError("whole-map resource census is not player-visible")

    def getNumBonusesOnLand(self, eBonus):
        raise AssertionError("whole-map resource census is not player-visible")

    def getNumAreas(self):
        raise AssertionError("continent count is not player-visible before exploring")

    def getNumLandAreas(self):
        raise AssertionError("continent count is not player-visible before exploring")

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
                 production=10, productionNeeded=60, none=False, worked=None):
        # index -> (x, y) for a worked city plot. A value of None or of a Plot
        # stands in for what getCityIndexPlot returns off the edge of the map.
        # Index 0 is the city centre, which is always worked.
        self._worked = worked
        if self._worked is None:
            self._worked = {0: (32, 40), 5: (33, 40), 9: (31, 40)}
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

    def isWorkingPlotByIndex(self, i):
        return i in self._worked

    def getCityIndexPlot(self, i):
        value = self._worked[i]
        if value is None or isinstance(value, Plot):
            return value
        return Plot(x=value[0], y=value[1])


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
    def __init__(self, player, cyMap=None, game=None):
        self._player = player
        # One shared instance so tests can inspect what was asked of it.
        self._team = Team()
        self._game = game
        if self._game is None:
            self._game = Game()
        self._map = cyMap
        if self._map is None:
            self._map = Map()
        self.playerLookups = []
        self.teamLookups = []

    def getGame(self):
        return self._game

    def getMap(self):
        return self._map

    def getNUM_CITY_PLOTS(self):
        return NUM_CITY_PLOTS

    def getTerrainInfo(self, i):
        return Info(TERRAINS[i])

    def getFeatureInfo(self, i):
        return Info(FEATURES[i])

    def getBonusInfo(self, i):
        return Info(BONUSES[i])

    def getImprovementInfo(self, i):
        return Info(IMPROVEMENTS[i])

    def getRouteInfo(self, i):
        return Info(ROUTES[i])

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

    def getWorldInfo(self, i):
        return Info(["WORLDSIZE_DUEL", "WORLDSIZE_TINY", "WORLDSIZE_SMALL",
                     "WORLDSIZE_STANDARD"][i])

    def getClimateInfo(self, i):
        return Info(["CLIMATE_TEMPERATE", "CLIMATE_TROPICAL", "CLIMATE_ARID",
                     "CLIMATE_ROCKY"][i])

    def getSeaLevelInfo(self, i):
        return Info(["SEALEVEL_LOW", "SEALEVEL_MEDIUM", "SEALEVEL_HIGH"][i])

    def getHandicapInfo(self, i):
        return Info(["HANDICAP_SETTLER", "HANDICAP_NOBLE", "HANDICAP_MONARCH"][i])

    def getNumGameOptionInfos(self):
        return len(GAME_OPTIONS)

    def getGameOptionInfo(self, i):
        return Info(GAME_OPTIONS[i])

    def getNumVictoryInfos(self):
        return len(VICTORIES)

    def getVictoryInfo(self, i):
        return Info(VICTORIES[i])

    def getUnitInfo(self, i):
        return Info(UNITS[i])

    def getBuildingInfo(self, i):
        return Info(BUILDINGS[i])

    def getProjectInfo(self, i):
        return Info(PROJECTS[i])

    def getProcessInfo(self, i):
        return Info(PROCESSES[i])


def loadModule(player=None, localConfigPath=None, cyMap=None, game=None):
    """Exec the real mod source with the game API and Python 2 builtins shimmed.

    localConfigPath=None leaves LocalConfig unimportable, which is the "not
    configured on this machine" case getStateFilePath has to tolerate.
    """
    player = player or Player()
    gc = Gc(player, cyMap=cyMap, game=game)

    fake = types.ModuleType("CvPythonExtensions")
    fake.CyGlobalContext = lambda: gc
    fake.TechTypes = type("TechTypes", (), {"NO_TECH": NO_TECH})
    fake.CivicTypes = type("CivicTypes", (), {"NO_CIVIC": NO_CIVIC})
    fake.CommerceTypes = type("CommerceTypes", (), {"COMMERCE_RESEARCH": COMMERCE_RESEARCH})
    fake.FeatureTypes = type("FeatureTypes", (), {"NO_FEATURE": NO_FEATURE})
    fake.BonusTypes = type("BonusTypes", (), {"NO_BONUS": NO_BONUS})
    fake.ImprovementTypes = type("ImprovementTypes", (), {"NO_IMPROVEMENT": NO_IMPROVEMENT})
    fake.RouteTypes = type("RouteTypes", (), {"NO_ROUTE": NO_ROUTE})
    fake.PlayerTypes = type("PlayerTypes", (), {"NO_PLAYER": NO_PLAYER})
    fake.YieldTypes = type("YieldTypes", (), {
        "YIELD_FOOD": YIELD_FOOD,
        "YIELD_PRODUCTION": YIELD_PRODUCTION,
        "YIELD_COMMERCE": YIELD_COMMERCE,
    })
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
    ns["_testMap"] = gc._map
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
        # contacts array would be indistinguishable from "player has met nobody".
        self.assertEqual(sorted(self.parsed.keys()),
                         ["cities", "game", "map", "meta", "player", "units"])

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


class GameSetupTests(unittest.TestCase):
    """The setup the player chose at game creation - legitimately known, and useful
    before exploring once joined against the XML (climate implies hills and desert,
    sea level implies how much water)."""

    def setUp(self):
        self.mod = loadModule()
        self.parsed = json.loads(
            self.mod["toJson"](self.mod["buildState"](5, PLAYER_ID, "onEndGameTurn"), 2))

    def test_map_generation_parameters(self):
        game = self.parsed["game"]
        self.assertEqual(game["mapScript"], "Fractal")
        self.assertEqual(game["worldSize"], "WORLDSIZE_STANDARD")
        self.assertEqual(game["climate"], "CLIMATE_ROCKY")
        self.assertEqual(game["seaLevel"], "SEALEVEL_MEDIUM")

    def test_difficulty(self):
        self.assertEqual(self.parsed["game"]["handicap"], "HANDICAP_NOBLE")

    def test_total_civs_counts_those_ever_alive(self):
        # countCivPlayersAlive raises on the mock: it shrinks when a civ is
        # destroyed, which the player would not necessarily know about.
        self.assertEqual(self.parsed["game"]["totalCivs"], 7)

    def test_only_enabled_options_are_listed(self):
        self.assertEqual(self.parsed["game"]["options"], ["GAMEOPTION_RAGING_BARBARIANS"])

    def test_no_options_enabled_is_an_empty_list(self):
        mod = loadModule(game=Game(options=()))
        parsed = json.loads(mod["toJson"](mod["buildState"](5, PLAYER_ID, "x"), 2))
        self.assertEqual(parsed["game"]["options"], [])

    def test_only_enabled_victories_are_listed(self):
        self.assertEqual(self.parsed["game"]["victories"],
                         ["VICTORY_CONQUEST", "VICTORY_CULTURAL"])

    def test_generated_map_statistics_are_never_read(self):
        # getLandPlots/getNumBonuses/getNumAreas/getOwnedPlots all sit next to the
        # safe getters on CyMap and all describe the map as GENERATED, including
        # everything the player has never seen. The mock raises on each; this test
        # exists so that stays true. seaLevel/climate are the honest substitutes:
        # a parameter the player chose, not the answer it produced.
        cyMap = self.mod["_testMap"]
        for name in ("getLandPlots", "getOwnedPlots", "getNumAreas", "getNumLandAreas"):
            self.assertRaises(AssertionError, getattr(cyMap, name))
        self.assertRaises(AssertionError, cyMap.getNumBonuses, 0)

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


def buildWith(units=None, cities=None, cyMap=None):
    """Export a turn for a player with the given units/cities/map, parsed back."""
    mod = loadModule(Player(units=units, cities=cities), cyMap=cyMap)
    return mod, json.loads(mod["toJson"](mod["buildState"](5, PLAYER_ID, "onEndGameTurn"), 2))


def buildTile(**kwargs):
    """Export a one-plot map and hand back that tile's exported dict."""
    cyMap = Map(plots=[Plot(x=1, y=2, **kwargs)], width=3, height=3)
    _, parsed = buildWith(cyMap=cyMap)
    return parsed["map"]["tiles"][0]


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
            "workedTiles": [[31, 40], [32, 40], [33, 40]],
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


class WorkedTilesTests(unittest.TestCase):
    def test_sorted_coordinates_including_the_city_centre(self):
        _, parsed = buildWith(cities=[City(0, worked={5: (33, 40), 0: (32, 40), 9: (31, 40)})])
        self.assertEqual(parsed["cities"][0]["workedTiles"],
                         [[31, 40], [32, 40], [33, 40]])

    def test_unworked_plots_are_skipped(self):
        _, parsed = buildWith(cities=[City(0, worked={0: (32, 40)})])
        self.assertEqual(parsed["cities"][0]["workedTiles"], [[32, 40]])

    def test_every_city_plot_index_is_examined(self):
        # All 21, from gc.getNUM_CITY_PLOTS() rather than a hardcoded 21.
        worked = {}
        for i in range(NUM_CITY_PLOTS):
            worked[i] = (i, 0)
        _, parsed = buildWith(cities=[City(0, worked=worked)])
        self.assertEqual(len(parsed["cities"][0]["workedTiles"]), NUM_CITY_PLOTS)

    def test_off_map_city_plots_are_skipped(self):
        # A city near the poles has city-plot indices that fall off the map;
        # the engine hands back an invalid plot (or nothing at all) for those.
        _, parsed = buildWith(cities=[City(0, worked={0: (32, 40), 3: None,
                                                      7: Plot(none=True)})])
        self.assertEqual(parsed["cities"][0]["workedTiles"], [[32, 40]])

    def test_no_worked_tiles_is_an_empty_list(self):
        _, parsed = buildWith(cities=[City(0, worked={})])
        self.assertEqual(parsed["cities"][0]["workedTiles"], [])


class MapScanTests(unittest.TestCase):
    def test_only_revealed_tiles_are_exported(self):
        cyMap = Map(plots=[Plot(x=0, y=0, revealed=True),
                           Plot(x=1, y=0, revealed=False),
                           Plot(x=2, y=1, revealed=True)],
                    width=3, height=2)
        _, parsed = buildWith(cyMap=cyMap)
        self.assertEqual([(t["x"], t["y"]) for t in parsed["map"]["tiles"]],
                         [(0, 0), (2, 1)])

    def test_whole_grid_is_scanned_in_row_major_order(self):
        cyMap = Map(plots=[], width=3, height=2)
        mod, _ = buildWith(cyMap=cyMap)
        self.assertEqual(mod["_testMap"].lookups,
                         [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)])

    def test_tiles_come_out_row_major(self):
        # Sorted output is what makes turn-to-turn diffs meaningful; row-major
        # also matches the engine's own plot indexing and reads like the map.
        cyMap = Map(plots=[Plot(x=2, y=1), Plot(x=0, y=1), Plot(x=1, y=0)],
                    width=3, height=2)
        _, parsed = buildWith(cyMap=cyMap)
        self.assertEqual([(t["x"], t["y"]) for t in parsed["map"]["tiles"]],
                         [(1, 0), (0, 1), (2, 1)])

    def test_revealed_check_uses_the_players_team_and_never_debug(self):
        # bDebug=True would bypass to full map truth whenever the game is in
        # debug mode - a silent, total fog-of-war failure.
        plot = Plot(x=0, y=0)
        buildWith(cyMap=Map(plots=[plot], width=1, height=1))
        self.assertEqual(plot.revealedArgs, [(TEAM_ID, False)])

    def test_no_revealed_tiles_is_an_empty_list_not_an_omission(self):
        _, parsed = buildWith(cyMap=Map(plots=[], width=2, height=2))
        self.assertEqual(parsed["map"], {"tiles": []})

    def test_export_bails_when_another_player_is_active(self):
        # calculateYield(bDisplay=True) silently reads the ACTIVE team's revealed
        # state, so exporting for anyone else would hand over the wrong player's
        # view of the map. There is no API to ask for a specific player's.
        mod = loadModule(game=Game(activePlayer=PLAYER_ID + 1))
        self.assertRaises(AssertionError, mod["buildState"], 5, PLAYER_ID, "onEndGameTurn")


class TileTests(unittest.TestCase):
    def test_always_present_fields(self):
        tile = buildTile(terrain=1, yields=(2, 3, 4))
        self.assertEqual(tile, {"x": 1, "y": 2, "terrain": "TERRAIN_PLAINS",
                                "yields": [2, 3, 4]})

    def test_plain_flat_land_omits_plot_type(self):
        self.assertNotIn("plotType", buildTile())

    def test_peak(self):
        self.assertEqual(buildTile(peak=True)["plotType"], "PLOT_PEAK")

    def test_hills(self):
        self.assertEqual(buildTile(hills=True)["plotType"], "PLOT_HILLS")

    def test_water(self):
        self.assertEqual(buildTile(water=True)["plotType"], "PLOT_OCEAN")

    def test_lake_is_separate_from_plot_type(self):
        # Lakes and coastal sea are both TERRAIN_COAST and both PLOT_OCEAN;
        # nothing else in the tile distinguishes them.
        tile = buildTile(water=True, lake=True)
        self.assertEqual(tile["plotType"], "PLOT_OCEAN")
        self.assertIs(tile["lake"], True)

    def test_fresh_water_and_river(self):
        tile = buildTile(freshWater=True, river=True)
        self.assertIs(tile["freshWater"], True)
        self.assertIs(tile["river"], True)

    def test_defaults_are_omitted_not_written_as_false_or_null(self):
        tile = buildTile()
        for field in ("plotType", "lake", "freshWater", "river", "feature",
                      "bonus", "improvement", "route", "owner", "visibleNow"):
            self.assertNotIn(field, tile)

    def test_feature_and_bonus_are_xml_type_keys(self):
        tile = buildTile(feature=0, bonus=1)
        self.assertEqual(tile["feature"], "FEATURE_FOREST")
        self.assertEqual(tile["bonus"], "BONUS_COPPER")

    def test_bonus_is_read_through_the_team_aware_getter(self):
        # Team-aware so a resource the player lacks the revealing tech for stays
        # hidden - but NOT fog-aware, which is right: bonuses persist through fog.
        plot = Plot(x=1, y=2, bonus=0)
        buildWith(cyMap=Map(plots=[plot], width=3, height=3))
        self.assertEqual(plot.bonusArgs, [TEAM_ID])

    def test_improvement_route_and_owner_use_the_revealed_getters(self):
        # The live getters raise on the mock: they return current truth through
        # fog, which would hand the player intelligence they don't have.
        tile = buildTile(improvement=0, route=0, owner=1)
        self.assertEqual(tile["improvement"], "IMPROVEMENT_FARM")
        self.assertEqual(tile["route"], "ROUTE_ROAD")
        self.assertEqual(tile["owner"], 1)

    def test_revealed_getters_ask_for_the_players_team_and_never_debug(self):
        plot = Plot(x=1, y=2, improvement=0, route=0, owner=1)
        buildWith(cyMap=Map(plots=[plot], width=3, height=3))
        self.assertEqual(plot.revealedImprovementArgs, [(TEAM_ID, False)])
        self.assertEqual(plot.revealedRouteArgs, [(TEAM_ID, False)])
        self.assertEqual(plot.revealedOwnerArgs, [(TEAM_ID, False)])

    def test_unowned_tile_omits_owner_rather_than_exporting_the_sentinel(self):
        self.assertNotIn("owner", buildTile(owner=NO_PLAYER))

    def test_player_zero_owner_is_kept_not_treated_as_falsey(self):
        self.assertEqual(buildTile(owner=0)["owner"], 0)

    def test_goody_hut_arrives_as_a_revealed_improvement(self):
        self.assertEqual(buildTile(improvement=1)["improvement"], "IMPROVEMENT_GOODY_HUT")

    def test_visible_now_only_present_when_in_sight(self):
        self.assertIs(buildTile(visible=True)["visibleNow"], True)
        self.assertNotIn("visibleNow", buildTile(visible=False))

    def test_visibility_check_uses_the_players_team_and_never_debug(self):
        plot = Plot(x=1, y=2, visible=True)
        buildWith(cyMap=Map(plots=[plot], width=3, height=3))
        self.assertEqual(plot.visibleArgs, [(TEAM_ID, False)])

    def test_yields_are_the_displayed_ones_in_food_production_commerce_order(self):
        # bDisplay=True is what the map's yield icons and the tile mouseover both
        # pass, and it makes calculateYield use the revealed improvement/route/owner.
        plot = Plot(x=1, y=2, yields=(3, 2, 1))
        _, parsed = buildWith(cyMap=Map(plots=[plot], width=3, height=3))
        self.assertEqual(parsed["map"]["tiles"][0]["yields"], [3, 2, 1])
        self.assertEqual(plot.yieldArgs,
                         [(YIELD_FOOD, True), (YIELD_PRODUCTION, True), (YIELD_COMMERCE, True)])

    def test_all_zero_yields_are_still_exported(self):
        # A plot with no land in its city cross reports [0, 0, 0] whatever it is.
        # That is what the map shows, so it must survive as a real value.
        self.assertEqual(buildTile(water=True, yields=(0, 0, 0))["yields"], [0, 0, 0])


class TileRenderingTests(unittest.TestCase):
    def test_each_tile_is_one_line_however_wide(self):
        # Tiles are a long homogeneous table: the point is to scan down a column
        # of alike lines. Most real tiles exceed the normal inline width, so
        # without the _Record marker the section comes out as a ragged mix.
        cyMap = Map(plots=[Plot(x=0, y=0, terrain=3, visible=True, hills=True,
                                lake=True, freshWater=True, river=True,
                                feature=1, bonus=0, improvement=0, route=1,
                                owner=2, yields=(9, 9, 9))],
                    width=1, height=1)
        mod = loadModule(cyMap=cyMap)
        text = mod["toJson"](mod["buildState"](5, PLAYER_ID, "onEndGameTurn"), 2)
        tileLines = [ln for ln in text.split("\n") if '"terrain"' in ln]
        self.assertEqual(len(tileLines), 1)
        self.assertGreater(len(tileLines[0]), 88)
        json.loads(text)

    def test_marker_does_not_change_how_other_sections_render(self):
        # Raising the global inline width instead would have collapsed `research`
        # and rewritten every existing section.
        mod = loadModule()
        text = mod["toJson"](mod["buildState"](5, PLAYER_ID, "onEndGameTurn"), 2)
        self.assertIn('"research": {\n', text)

    def test_record_without_leading_keys_is_plain_sorted(self):
        mod = loadModule()
        record = mod["_Record"]()
        record["b"], record["a"] = 1, 2
        self.assertEqual(mod["toJson"](record, 2), '{"a": 2, "b": 1}')

    def test_leading_keys_come_first_then_the_rest_sorted(self):
        mod = loadModule()
        record = mod["_Record"](("x", "y"))
        for key in ("terrain", "y", "bonus", "x"):
            record[key] = key
        self.assertEqual(mod["toJson"](record, 2),
                         '{"x": "x", "y": "y", "bonus": "bonus", "terrain": "terrain"}')

    def test_absent_leading_keys_are_skipped(self):
        # Normal, not exceptional: tile fields are omitted at their defaults.
        mod = loadModule()
        record = mod["_Record"](("x", "missing", "y"))
        record["y"], record["x"] = 2, 1
        self.assertEqual(mod["toJson"](record, 2), '{"x": 1, "y": 2}')

    def test_tiles_lead_with_their_coordinates(self):
        cyMap = Map(plots=[Plot(x=4, y=7, terrain=1, bonus=0, visible=True)],
                    width=8, height=8)
        mod = loadModule(cyMap=cyMap)
        text = mod["toJson"](mod["buildState"](5, PLAYER_ID, "onEndGameTurn"), 2)
        tileLine = [ln for ln in text.split("\n") if '"terrain"' in ln][0]
        self.assertTrue(tileLine.strip().startswith('{"x": 4, "y": 7, '), tileLine)

    def test_key_order_is_still_deterministic(self):
        # Diffability needs a FIXED key order, not an alphabetical one - the point
        # of sorting in the first place, given Python 2.4 dicts have no insertion order.
        mod = loadModule()
        one, two = mod["_Record"](("x", "y")), mod["_Record"](("x", "y"))
        for key in ("terrain", "x", "river", "y"):
            one[key] = 1
        for key in ("y", "river", "x", "terrain"):
            two[key] = 1
        self.assertEqual(mod["toJson"](one, 2), mod["toJson"](two, 2))


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

    def test_map_section(self):
        self.assertSectionValid("map")

    def test_fully_populated_tile_validates(self):
        # The default fixture leans on omitted defaults; make sure a tile that
        # actually carries every optional field satisfies the schema too.
        cyMap = Map(plots=[Plot(x=0, y=0, terrain=3, visible=True, hills=True,
                                lake=True, freshWater=True, river=True,
                                feature=1, bonus=0, improvement=0, route=1,
                                owner=2, yields=(3, 2, 1))],
                    width=1, height=1)
        mod = loadModule(cyMap=cyMap)
        parsed = json.loads(mod["toJson"](mod["buildState"](5, PLAYER_ID, "x"), 2))
        sub = dict(self.schema["properties"]["map"])
        sub["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        jsonschema.Draft202012Validator(sub).validate(parsed["map"])

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
