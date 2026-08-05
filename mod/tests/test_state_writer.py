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

# The engine sizes these from MAX_CIV_PLAYERS, with the barbarians occupying the
# one slot past the civs (CvDefines.h: MAX_PLAYERS is MAX_CIV_PLAYERS + 1,
# BARBARIAN_PLAYER is (PlayerTypes)MAX_CIV_PLAYERS). Kept small here so a full
# sweep is cheap, but with the same shape.
MAX_PLAYERS = 6
BARBARIAN_PLAYER = 5

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
# Index order matters: BONUS_INFOS below describes each of these in the same order.
BONUSES = ["BONUS_CORN", "BONUS_COPPER", "BONUS_GOLD", "BONUS_DYE"]
# (health, happiness) per bonus, as CIV4BonusInfos.xml carries them. Corn is a
# food resource, Copper a strategic one (a unit needs it - see UNIT_PREREQ_BONUS),
# Gold a luxury, and Dye a pure trade good that does nothing but sell.
BONUS_INFOS = [
    {"health": 1, "happiness": 0},
    {"health": 0, "happiness": 0},
    {"health": 0, "happiness": 1},
    {"health": 0, "happiness": 0},
]
# There is no bStrategic flag, so "strategic" is derived from units/buildings
# naming a bonus as a prerequisite. UNIT_WARRIOR (index 1) requires Copper
# outright; UNIT_SETTLER (index 3) lists Copper and Gold as OR-alternatives, so
# both count - and Gold lands in `strategic` rather than `happiness`, since
# unlocking something takes precedence.
UNIT_PREREQ_BONUS = {1: 1}
UNIT_PREREQ_OR_BONUSES = {3: [1, 2]}
BUILDING_PREREQ_BONUS = {}
NUM_PREREQ_OR_BONUSES = 4

# Building CLASSES, which is what wonder limits are a property of and what the
# wonders section reports - a civ's unique replacement shares its class.
BUILDING_CLASSES = ["BUILDINGCLASS_PALACE", "BUILDINGCLASS_BARRACKS",
                    "BUILDINGCLASS_PYRAMIDS", "BUILDINGCLASS_GREAT_LIBRARY",
                    "BUILDINGCLASS_HEROIC_EPIC"]
# iMaxGlobalInstances 1 marks a world wonder, iMaxPlayerInstances 1 a national
# one; -1 is "no limit" and is what an ordinary building carries.
WORLD_WONDER_CLASSES = (2, 3)
NATIONAL_WONDER_CLASSES = (4,)

MIN_WATER_SIZE_FOR_OCEAN = 10
IMPROVEMENTS = ["IMPROVEMENT_FARM", "IMPROVEMENT_GOODY_HUT"]
ROUTES = ["ROUTE_ROAD", "ROUTE_RAILROAD"]
LEADERS = ["LEADER_HATSHEPSUT", "LEADER_GANDHI", "LEADER_JULIUS_CAESAR",
           "LEADER_BARBARIAN"]
CIVILIZATIONS = ["CIVILIZATION_EGYPT", "CIVILIZATION_INDIA", "CIVILIZATION_ROME",
                 "CIVILIZATION_BARBARIAN"]
# Index order is the AttitudeTypes enum's, which is also the XML's (CvEnums.h).
ATTITUDES = ["ATTITUDE_FURIOUS", "ATTITUDE_ANNOYED", "ATTITUDE_CAUTIOUS",
             "ATTITUDE_PLEASED", "ATTITUDE_FRIENDLY"]

PLAYER_ID = 3
TEAM_ID = 7

# What CyCity.getProductionNeeded() returns when there is nothing to complete.
MAX_INT = 2147483647


def _raises(name, reason):
    def accessor(self, *args, **kwargs):
        raise AssertionError("%s: %s" % (name, reason))
    return accessor


def _forbid(cls, reason, names):
    """Make each whitespace-separated method name on cls raise AssertionError.

    These are the accessors the exporter must never call. The real Cy* objects
    answer all of them perfectly happily for any player, city or unit - a mock
    that raises is how the fog-of-war rules stay enforced rather than merely
    remembered, and it is what makes a leak fail a test instead of shipping.
    """
    for name in names.split():
        setattr(cls, name, _raises(name, reason))


class Info(object):
    def __init__(self, t):
        self._t = t

    def getType(self):
        return self._t


class BonusInfo(Info):
    """A bonus, plus the two XML fields that decide its health/happiness group.

    getNumUnitsWithBonus/getNumBuildingsWithBonus are tripwires: they are the
    obvious way to ask a bonus what it unlocks, and they DO NOT EXIST in the
    Python layer (confirmed against the BUG API reference - CvBonusInfo exposes
    no reverse index at all). Calling one would raise inside the game and lose
    the whole export, so the mock fails the same way rather than inventing them.
    """

    def __init__(self, t, health=0, happiness=0):
        Info.__init__(self, t)
        self._health = health
        self._happiness = happiness

    def getHealth(self):
        return self._health

    def getHappiness(self):
        return self._happiness


_forbid(BonusInfo, "CvBonusInfo has no reverse index in the Python API; sweep the "
        "unit and building infos for their prerequisite bonuses instead", """
    getNumUnitsWithBonus getNumBuildingsWithBonus""")


class BuildInfo(Info):
    """A unit or building info, carrying only its bonus prerequisites.

    Both forms are modelled because they mean different things: getPrereqAndBonus
    is one REQUIRED bonus, getPrereqOrBonuses(i) an array of alternatives any one
    of which suffices. The array is fixed-length with NO_BONUS in unused slots.
    """

    def __init__(self, t, prereqBonus=NO_BONUS, prereqOrBonuses=()):
        Info.__init__(self, t)
        self._prereqBonus = prereqBonus
        self._prereqOrBonuses = list(prereqOrBonuses)

    def getPrereqAndBonus(self):
        return self._prereqBonus

    def getPrereqOrBonuses(self, i):
        if i < len(self._prereqOrBonuses):
            return self._prereqOrBonuses[i]
        return NO_BONUS


class BuildingClassInfo(Info):
    """A building class and its instance limits.

    getMaxGlobalInstances 1 is a world wonder (one in the world),
    getMaxPlayerInstances 1 a national wonder (one per civ); -1 means no limit.
    """

    def __init__(self, t, maxGlobal=-1, maxPlayer=-1):
        Info.__init__(self, t)
        self._maxGlobal = maxGlobal
        self._maxPlayer = maxPlayer

    def getMaxGlobalInstances(self):
        return self._maxGlobal

    def getMaxPlayerInstances(self):
        return self._maxPlayer


class Game(object):
    def __init__(self, activePlayer=PLAYER_ID, options=(1,), victories=(0, 2),
                 scriptData="", builtWonders=()):
        self._activePlayer = activePlayer
        self._options = options
        self._victories = victories
        self._scriptData = scriptData
        # Building-class indices completed anywhere in the world.
        self._builtWonders = builtWonders
        self.scriptDataSets = []
        self.buildingClassCreatedArgs = []

    def getScriptData(self):
        return self._scriptData

    def setScriptData(self, value):
        self.scriptDataSets.append(value)
        self._scriptData = value

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

    def getBuildingClassCreatedCount(self, i):
        self.buildingClassCreatedArgs.append(i)
        return i in self._builtWonders and 1 or 0


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

    def getPlotCity(self):
        raise AssertionError(
            "plot-side city lookup is live truth: CyCity.isRevealed is stricter "
            "than the tile being revealed, so this would surface cities founded "
            "under fog. Iterate each rival's city list instead")

    def isCity(self):
        raise AssertionError("see getPlotCity: foreign cities are read player-side")


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
    """A unit, ours or a rival's.

    `visible` and `invisible` only matter for rivals' units: ours are exported
    unconditionally. `plot=` overrides the plot the unit stands on, for the
    off-the-map case.
    """

    def __init__(self, unitId, unitType=0, x=10, y=20, baseMoves=1,
                 damage=0, dead=False, owner=PLAYER_ID, visualOwner=None,
                 visible=True, invisible=False, plot=None):
        self._id = unitId
        self._type = unitType
        self._x = x
        self._y = y
        self._baseMoves = baseMoves
        self._damage = damage
        self._dead = dead
        self._owner = owner
        self._visualOwner = visualOwner
        if self._visualOwner is None:
            self._visualOwner = owner
        self._invisible = invisible
        self._plot = plot
        if self._plot is None:
            self._plot = Plot(x=x, y=y, visible=visible)
        self.invisibleArgs = []

    def plot(self):
        return self._plot

    def getVisualOwner(self):
        # No team argument in the Python binding: it answers for the ACTIVE team.
        return self._visualOwner

    def getOwner(self):
        raise AssertionError(
            "a unit's true owner can differ from the one the game draws; "
            "use getVisualOwner so a hidden-nationality unit is never unmasked")

    def isInvisible(self, team, bDebug):
        self.invisibleArgs.append((team, bDebug))
        return self._invisible

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
                 production=10, productionNeeded=60, none=False, worked=None,
                 bonuses=(0, 1), coastal=False, buildings=(0,),
                 hammers=4, foodProduction=0):
        # The two halves of the city screen's production figure, modelled the way
        # the engine computes them: `hammers` is what a (bIgnoreFood=True) call
        # returns, and `foodProduction` is the extra additive term a food build
        # gets on top. Defaults are an ordinary build, where the two calls agree.
        self._hammers = hammers
        self._foodProduction = foodProduction
        # Building indices standing in this city. The Palace by default, which is
        # what a real capital carries from turn 0.
        self._buildings = buildings
        self.hasBuildingArgs = []
        # Bonus indices connected to THIS city. Membership only - quantity is an
        # empire-level fact and belongs on the player.
        self._bonuses = bonuses
        self._coastal = coastal
        self.coastalArgs = []
        self.hasBonusArgs = []
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
        # Mirrors CvCity::getProductionDifference: bIgnoreFood suppresses one
        # ADDITIVE term and leaves the hammer expression untouched, which is what
        # makes the two calls subtract cleanly. A mock returning one constant
        # regardless of its arguments cannot tell the two halves apart.
        self.productionDifferenceArgs.append((bIgnoreFood, bOverflow))
        if bIgnoreFood:
            return self._hammers
        return self._hammers + self._foodProduction

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

    def getNumBuilding(self, i):
        self.hasBuildingArgs.append(i)
        return i in self._buildings and 1 or 0

    def hasBuilding(self, i):
        # NOT a real CyCity method, despite the base game's own Python calling
        # pCity.hasBuilding() in eight places - those run against WorldBuilder
        # screens and getPlotCity() results. The live game raises
        # "AttributeError: 'CyCity' object has no attribute 'hasBuilding'" and
        # loses the whole export. Caught only by actually playing a turn, which
        # is why it is pinned here now.
        raise AssertionError(
            "CyCity has no hasBuilding(); the binding is isHasBuilding, itself a "
            "compatibility shim forwarding to getNumBuilding - use getNumBuilding")

    def getNumRealBuilding(self, i):
        raise AssertionError(
            "getNumRealBuilding excludes FREE buildings, and the Palace in the "
            "capital is free - use getNumBuilding, which counts real and free")

    def hasBonus(self, i):
        self.hasBonusArgs.append(i)
        return i in self._bonuses

    def isCoastal(self, minWaterSize):
        self.coastalArgs.append(minWaterSize)
        # An int, as the C++ binding returns: the exporter has to coerce it.
        return self._coastal and 1 or 0

    def isWorkingPlotByIndex(self, i):
        return i in self._worked

    def getCityIndexPlot(self, i):
        value = self._worked[i]
        if value is None or isinstance(value, Plot):
            return value
        return Plot(x=value[0], y=value[1])


class ForeignCity(object):
    """A rival's city: only what the game paints on its nameplate.

    Everything a city screen would show - stores, production, mood, worked tiles -
    raises. Those accessors exist on the real CyCity and answer happily for any
    city at all; the engine's own billboard code is what draws the line, gating the
    food and production bars on canBeSelected() while leaving name, size and the
    capital star ungated. This class is that line, made to fail loudly.
    """

    def __init__(self, cityId, name=u"Delhi", x=50, y=50, owner=1,
                 population=3, capital=False, revealed=True, none=False):
        self._id = cityId
        self._name = name
        self._x = x
        self._y = y
        self._owner = owner
        self._population = population
        self._capital = capital
        self._revealed = revealed
        self._none = none
        self.revealedArgs = []

    def isNone(self):
        return self._none

    def getID(self):
        return self._id

    def getOwner(self):
        return self._owner

    def isRevealed(self, team, bDebug):
        self.revealedArgs.append((team, bDebug))
        return self._revealed

    def getName(self):
        return self._name

    def getX(self):
        return self._x

    def getY(self):
        return self._y

    def getPopulation(self):
        return self._population

    def isCapital(self):
        return self._capital


_forbid(ForeignCity, "a rival's city shows only what is painted on its nameplate", """
    getFood foodDifference growthThreshold getProduction getProductionNeeded
    getCurrentProductionDifference isProductionUnit isProductionBuilding
    isProductionProject isProductionProcess getCulture getCultureThreshold
    happyLevel unhappyLevel goodHealth badHealth isWorkingPlotByIndex
    getCityIndexPlot hasBonus isCoastal getNumBuilding getNumRealBuilding""")


def _cursor(items, index):
    """Emulate the engine's (object, iterator) cursor pair, exhausting to None."""
    if index < len(items):
        return items[index], index + 1
    return None, index


class Player(object):
    def __init__(self, research=1, units=None, cities=None, bonuses=None,
                 nationalWonders=()):
        # bonus index -> how many the empire has connected. Corn and Copper by
        # default, so the strategic/health split is exercised without opting in.
        self._bonuses = bonuses
        if self._bonuses is None:
            self._bonuses = {0: 1, 1: 2}
        self._nationalWonders = nationalWonders
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

    def getNumAvailableBonuses(self, i):
        return self._bonuses.get(i, 0)

    def getBuildingClassCount(self, i):
        return i in self._nationalWonders and 1 or 0


class Team(object):
    """Our own team. met/atWar are keyed by the OTHER team's id."""

    def __init__(self, met=(), atWar=()):
        self._met = met
        self._atWar = atWar
        self.researchCostArgs = []
        self.researchProgressArgs = []
        self.metArgs = []
        self.atWarArgs = []

    def isHasTech(self, i):
        return i in (0, 1)  # Agriculture + Mining only

    def getResearchProgress(self, t):
        self.researchProgressArgs.append(t)
        return 42

    def getResearchCost(self, t):
        self.researchCostArgs.append(t)
        return 76

    def isHasMet(self, team):
        self.metArgs.append(team)
        return team in self._met

    def isAtWar(self, team):
        self.atWarArgs.append(team)
        # An int, as the C++ binding returns: the exporter has to coerce it.
        return team in self._atWar and 1 or 0


class RivalTeam(object):
    """Another team. Every accessor raises.

    Nothing needs one: contacts asks our own team about the relation, because
    CvTeam::meet sets makeHasMet on both sides so isHasMet is symmetric. This class
    exists so that if anyone ever reaches for gc.getTeam(theirTeam), the first
    thing they find is that a rival CyTeam is precisely the object that would hand
    over their techs and their research.
    """

    def __getattr__(self, name):
        raise AssertionError(
            "a rival CyTeam exposes their techs and research; ask our own team "
            "about the relation instead (isHasMet is symmetric) - reached %s" % name)


class Rival(object):
    """Another player. Everything the fog hides raises.

    Absent player slots are modelled as alive=False, which is all the exporter
    should ever ask of them.
    """

    def __init__(self, playerId, teamId=None, leader=1, civilization=1,
                 attitude=2, alive=True, barbarian=False, minor=False,
                 units=None, cities=None):
        self.playerId = playerId
        self._teamId = teamId
        if self._teamId is None:
            self._teamId = playerId
        self._leader = leader
        self._civilization = civilization
        self._attitude = attitude
        self._alive = alive
        self._barbarian = barbarian
        self._minor = minor
        self._units = units or []
        self._cities = cities or []
        self.attitudeArgs = []

    def isAlive(self):
        return self._alive

    def isBarbarian(self):
        return self._barbarian

    def isMinorCiv(self):
        return self._minor

    def getTeam(self):
        return self._teamId

    def getLeaderType(self):
        return self._leader

    def getCivilizationType(self):
        return self._civilization

    def AI_getAttitude(self, playerId):
        self.attitudeArgs.append(playerId)
        return self._attitude

    def firstUnit(self, bRev):
        return _cursor(self._units, 0)

    def nextUnit(self, cursor, bRev):
        return _cursor(self._units, cursor)

    def firstCity(self, bRev):
        return _cursor(self._cities, 0)

    def nextCity(self, cursor, bRev):
        return _cursor(self._cities, cursor)


_forbid(Rival, "a rival's private empire state, visible to the player only through "
        "espionage this schema does not model", """
    getGold calculateGoldRate calculateResearchRate calculateResearchModifier
    getCurrentResearch getResearchTurnsLeft getOverflowResearch getCommercePercent
    getCivics getNumCities getNumUnits getPower getCurrentEra""")


def absentPlayers(*rivals):
    """playerId -> Rival for a full player roster, unused slots marked dead."""
    roster = {}
    for i in range(MAX_PLAYERS):
        roster[i] = Rival(i, alive=False)
    for rival in rivals:
        roster[rival.playerId] = rival
    return roster


class Gc(object):
    def __init__(self, player, cyMap=None, game=None, rivals=None, team=None):
        self._player = player
        # One shared instance so tests can inspect what was asked of it.
        self._team = team
        if self._team is None:
            self._team = Team()
        # Player slots other than the exported one. Anything not named is a dead
        # slot, which is what the great majority of them are in a real game.
        self._rivals = rivals or {}
        self._deadSlot = Rival(-1, alive=False)
        self._rivalTeam = RivalTeam()
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
        return BonusInfo(BONUSES[i], **BONUS_INFOS[i])

    def getNumBonusInfos(self):
        return len(BONUSES)

    def getDefineINT(self, name):
        assert name in ("NUM_UNIT_PREREQ_OR_BONUSES",
                        "NUM_BUILDING_PREREQ_OR_BONUSES"), name
        return NUM_PREREQ_OR_BONUSES

    def getNumUnitInfos(self):
        return len(UNITS)

    def getNumBuildingInfos(self):
        return len(BUILDINGS)

    def getNumBuildingClassInfos(self):
        return len(BUILDING_CLASSES)

    def getBuildingClassInfo(self, i):
        return BuildingClassInfo(
            BUILDING_CLASSES[i],
            maxGlobal=(i in WORLD_WONDER_CLASSES) and 1 or -1,
            maxPlayer=(i in NATIONAL_WONDER_CLASSES) and 1 or -1)

    def getMIN_WATER_SIZE_FOR_OCEAN(self):
        return MIN_WATER_SIZE_FOR_OCEAN

    def getImprovementInfo(self, i):
        return Info(IMPROVEMENTS[i])

    def getRouteInfo(self, i):
        return Info(ROUTES[i])

    def getMAX_PLAYERS(self):
        # Includes the barbarian slot, which the foreign sections want.
        return MAX_PLAYERS

    def getPlayer(self, i):
        self.playerLookups.append(i)
        if i == PLAYER_ID:
            return self._player
        return self._rivals.get(i, self._deadSlot)

    def getTeam(self, i):
        self.teamLookups.append(i)
        if i == TEAM_ID:
            return self._team
        return self._rivalTeam

    def getEraInfo(self, i):
        return Info("ERA_ANCIENT")

    def getGameSpeedInfo(self, i):
        return Info("GAMESPEED_NORMAL")

    def getLeaderHeadInfo(self, i):
        return Info(LEADERS[i])

    def getCivilizationInfo(self, i):
        return Info(CIVILIZATIONS[i])

    def getAttitudeInfo(self, i):
        return Info(ATTITUDES[i])

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
        return BuildInfo(UNITS[i],
                         prereqBonus=UNIT_PREREQ_BONUS.get(i, NO_BONUS),
                         prereqOrBonuses=UNIT_PREREQ_OR_BONUSES.get(i, ()))

    def getBuildingInfo(self, i):
        return BuildInfo(BUILDINGS[i],
                         prereqBonus=BUILDING_PREREQ_BONUS.get(i, NO_BONUS))

    def getProjectInfo(self, i):
        return Info(PROJECTS[i])

    def getProcessInfo(self, i):
        return Info(PROCESSES[i])


def loadModule(player=None, stateDir=None, cyMap=None, game=None,
               rivals=None, team=None):
    """Exec the real mod source with the game API and Python 2 builtins shimmed.

    stateDir=None leaves LocalConfig unimportable, which is the "not configured
    on this machine" case getStateRootDir has to tolerate.
    """
    player = player or Player()
    gc = Gc(player, cyMap=cyMap, game=game, rivals=rivals, team=team)

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
    if stateDir is not None:
        localConfig = types.ModuleType("LocalConfig")
        localConfig.STATE_DIR = stateDir
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
    ns["_testRivalTeam"] = gc._rivalTeam
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

    def test_every_section_is_present(self):
        # No section is omitted any more, which is what lets an empty list mean
        # what it says: "contacts": [] is a player who has met nobody, not a
        # section that hasn't been written yet.
        self.assertEqual(sorted(self.parsed.keys()),
                         ["cities", "contacts", "foreignCities", "foreignUnits",
                          "game", "map", "meta", "player", "units", "wonders"])

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
        parsed = exportState(game=Game(options=()))[1]
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
        # The exported player is resolved first, once; every later lookup belongs
        # to the foreign sections sweeping the roster, and never asks for our own
        # slot again (they skip it before calling getPlayer at all).
        lookups = self.mod["_testGc"].playerLookups
        self.assertEqual(lookups[0], PLAYER_ID)
        self.assertNotIn(PLAYER_ID, lookups[1:])
        self.assertEqual(sorted(set(lookups[1:])),
                         [i for i in range(MAX_PLAYERS) if i != PLAYER_ID])


def renderState(**kwargs):
    """(module, pretty-printed JSON text) for one export. kwargs go to loadModule."""
    mod = loadModule(**kwargs)
    return mod, mod["toJson"](mod["buildState"](5, PLAYER_ID, "onEndGameTurn"), 2)


def exportState(**kwargs):
    """(module, re-parsed export) for one turn. kwargs go to loadModule."""
    mod, text = renderState(**kwargs)
    return mod, json.loads(text)


def buildWith(units=None, cities=None, cyMap=None):
    """Export a turn for a player with the given units/cities/map, parsed back."""
    return exportState(player=Player(units=units, cities=cities), cyMap=cyMap)


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

    def test_undamaged_units_omit_damage(self):
        # Field-level omission, as in map.tiles: unhurt is the documented default
        # and the usual case, and the rule is the same one foreignUnits follows.
        _, parsed = buildWith(units=[Unit(0, damage=0)])
        self.assertNotIn("damage", parsed["units"][0])

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
            "productionPerTurn": 4, "productionFromHammers": 4,
            "productionFromFood": 0, "culture": 12, "cultureThreshold": 100,
            "happy": 4, "unhappy": 1, "healthy": 5, "unhealthy": 2,
            "workedTiles": [[31, 40], [32, 40], [33, 40]],
            "buildings": ["BUILDING_PALACE"],
            "bonuses": {"strategic": ["BONUS_COPPER"], "happiness": [],
                        "health": ["BONUS_CORN"]},
            "coastal": False,
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
        # Both halves of the production bar: the total the city screen prints and
        # the hammers-only figure it draws underneath it. bOverflow stays True on
        # both, so the halves carry the same one-off overflow the total does.
        self.assertEqual(city.productionDifferenceArgs, [(False, True), (True, True)])
        self.assertEqual(city.unhappyArgs, [0])
        self.assertEqual(city.badHealthArgs, [False])

    def test_food_build_splits_production_into_halves(self):
        # A Settler or Worker converts the food surplus into hammers, so the total
        # the city screen shows is larger than the city's own hammer rate. The
        # split is the whole point of the two fields: while such a build is queued
        # nothing else in the file separates them, since the food is already inside
        # productionPerTurn and foodPerTurn reads 0.
        _, parsed = buildWith(cities=[City(0, hammers=7, foodProduction=6)])
        city = parsed["cities"][0]
        self.assertEqual(city["productionPerTurn"], 13)
        self.assertEqual(city["productionFromHammers"], 7)
        self.assertEqual(city["productionFromFood"], 6)

    def test_production_halves_always_sum_to_the_total(self):
        # The invariant the two fields are worth having: whatever the city is
        # doing, the halves account for the whole figure and neither is derived
        # by the harness. Disorder is the degenerate case - the engine returns 0
        # outright, so all three agree at zero rather than disagreeing.
        for hammers, food in ((4, 0), (7, 6), (0, 0), (0, 5)):
            _, parsed = buildWith(
                cities=[City(0, hammers=hammers, foodProduction=food)])
            city = parsed["cities"][0]
            self.assertEqual(
                city["productionFromHammers"] + city["productionFromFood"],
                city["productionPerTurn"])

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


class PlayerBonusTests(unittest.TestCase):
    """Empire-wide connected resources, grouped by what they do."""

    def bonuses(self, **kwargs):
        _, parsed = exportState(player=Player(**kwargs))
        return parsed["player"]["bonuses"]

    def test_grouped_by_effect(self):
        # Corn (health), Copper (a unit needs it), Gold (luxury), Dye (nothing).
        self.assertEqual(self.bonuses(bonuses={0: 1, 1: 1, 2: 1, 3: 1}), {
            "strategic": ["BONUS_COPPER", "BONUS_GOLD"],
            "happiness": [],
            "health": ["BONUS_CORN"],
            "counts": {"BONUS_CORN": 1, "BONUS_COPPER": 1, "BONUS_GOLD": 1,
                       "BONUS_DYE": 1},
        })

    def test_unlocking_something_outranks_being_a_luxury(self):
        # Gold has iHappiness 1 AND is an OR-prerequisite for the Settler. It is
        # filed under strategic, because that is the fact that changes what you
        # build - and it appears in exactly one group, never both.
        bonuses = self.bonuses(bonuses={2: 1})
        self.assertEqual(bonuses["strategic"], ["BONUS_GOLD"])
        self.assertEqual(bonuses["happiness"], [])

    def test_or_prerequisites_count_as_strategic(self):
        # getPrereqOrBonuses is an array of alternatives, any one of which
        # suffices; a resource named only there is still strategic.
        self.assertIn("BONUS_GOLD", self.bonuses(bonuses={2: 1})["strategic"])

    def test_pure_trade_goods_are_left_out_of_the_groups(self):
        # Dye unlocks nothing and has neither health nor happiness. It still
        # appears in counts, which is every connected resource.
        bonuses = self.bonuses(bonuses={3: 2})
        for group in ("strategic", "happiness", "health"):
            self.assertEqual(bonuses[group], [])
        self.assertEqual(bonuses["counts"], {"BONUS_DYE": 2})

    def test_unconnected_resources_are_absent(self):
        # A resource in the ground but unimproved or unroaded is not here; it is
        # in map.tiles. getNumAvailableBonuses is the trade network, not the map.
        bonuses = self.bonuses(bonuses={})
        self.assertEqual(bonuses["counts"], {})
        for group in ("strategic", "happiness", "health"):
            self.assertEqual(bonuses[group], [])

    def test_counts_are_the_quantity_not_a_boolean(self):
        self.assertEqual(self.bonuses(bonuses={1: 3})["counts"], {"BONUS_COPPER": 3})

    def test_groups_are_always_present_even_when_empty(self):
        # A fixed set of three, unlike the field-level omission in map.tiles:
        # "no strategic resources connected" is a fact worth stating.
        bonuses = self.bonuses(bonuses={})
        self.assertEqual(sorted(bonuses.keys()),
                         ["counts", "happiness", "health", "strategic"])

    def test_sorted_for_diffability(self):
        self.assertEqual(self.bonuses(bonuses={2: 1, 1: 1})["strategic"],
                         ["BONUS_COPPER", "BONUS_GOLD"])

    def test_counts_and_groups_describe_the_same_set(self):
        # Both come from one getNumAvailableBonuses pass, so they cannot drift.
        # Every grouped bonus must be in counts; counts may hold more, since
        # pure trade goods belong to no group.
        bonuses = self.bonuses(bonuses={0: 1, 1: 1, 2: 1, 3: 1})
        grouped = set()
        for group in ("strategic", "happiness", "health"):
            grouped.update(bonuses[group])
        self.assertTrue(grouped.issubset(set(bonuses["counts"])))
        self.assertEqual(set(bonuses["counts"]) - grouped, {"BONUS_DYE"})

    def test_availability_is_asked_once_per_bonus(self):
        # It used to be asked twice - once to group, once to count. Cheap either
        # way, but the two passes could disagree, which within one section would
        # be a contradiction rather than a slow export.
        calls = []
        player = Player(bonuses={0: 1, 1: 2})
        real = player.getNumAvailableBonuses

        def counting(i):
            calls.append(i)
            return real(i)

        player.getNumAvailableBonuses = counting
        exportState(player=player)
        self.assertEqual(sorted(calls), list(range(len(BONUSES))))

    def test_reverse_index_on_bonus_info_is_never_used(self):
        # getNumUnitsWithBonus/getNumBuildingsWithBonus are the obvious way to ask
        # a bonus what it unlocks and DO NOT EXIST in the Python layer - calling
        # one would raise inside the game and lose the whole export. The mock
        # raises so that reintroducing the shortcut fails here instead.
        mod = loadModule()
        info = mod["_testGc"].getBonusInfo(0)
        self.assertRaises(AssertionError, info.getNumUnitsWithBonus)
        self.assertRaises(AssertionError, info.getNumBuildingsWithBonus)


class CityBuildingTests(unittest.TestCase):
    """What already stands in the city - the prerequisite half of what it can build."""

    def buildings(self, **kwargs):
        _, parsed = buildWith(cities=[City(0, **kwargs)])
        return parsed["cities"][0]["buildings"]

    def test_lists_what_the_city_has(self):
        self.assertEqual(self.buildings(buildings=(0, 1)),
                         ["BUILDING_BARRACKS", "BUILDING_PALACE"])

    def test_capital_carries_the_palace(self):
        # What a real capital looks like on turn 0, and the first thing a live
        # capture should show.
        self.assertEqual(self.buildings(buildings=(0,)), ["BUILDING_PALACE"])

    def test_a_city_with_nothing_built_is_an_empty_list(self):
        # Honest and unambiguous: a newly founded non-capital really has nothing.
        self.assertEqual(self.buildings(buildings=()), [])

    def test_every_building_index_is_examined(self):
        city = City(0)
        buildWith(cities=[city])
        self.assertEqual(city.hasBuildingArgs, list(range(len(BUILDINGS))))

    def test_building_keys_not_building_class_keys(self):
        # The opposite choice from `wonders`, deliberately: there the limit is a
        # property of the class; here what matters is the actual building, since
        # a civ's unique replacement shares a class but not its effects.
        for name in self.buildings(buildings=(0, 1)):
            self.assertTrue(name.startswith("BUILDING_"), name)
            self.assertFalse(name.startswith("BUILDINGCLASS_"), name)

    def test_sorted_for_diffability(self):
        self.assertEqual(self.buildings(buildings=(1, 0)),
                         ["BUILDING_BARRACKS", "BUILDING_PALACE"])

    def test_cities_can_differ_from_each_other(self):
        _, parsed = buildWith(cities=[City(0, buildings=(0,)), City(1, buildings=())])
        self.assertEqual(parsed["cities"][0]["buildings"], ["BUILDING_PALACE"])
        self.assertEqual(parsed["cities"][1]["buildings"], [])

    def test_rivals_buildings_are_never_read(self):
        # foreignCities exports only what the nameplate shows; a rival's building
        # list is a city-screen internal. The mock raises if anyone reaches for it.
        city = ForeignCity(0)
        self.assertRaises(AssertionError, city.getNumBuilding, 0)

    def test_the_nonexistent_has_building_accessor_is_never_used(self):
        # CyCity has no hasBuilding(), though the base game's Python appears to
        # call it - those call sites are WorldBuilder/getPlotCity objects. Using
        # it raises in the live game and loses the entire export, which is how
        # this was found. Pinned so it cannot come back.
        city = City(0)
        self.assertRaises(AssertionError, city.hasBuilding, 0)

    def test_free_buildings_count(self):
        # getNumRealBuilding would exclude the Palace, which is a FREE building
        # in the capital - the single most expected entry in this field.
        city = City(0)
        buildWith(cities=[city])
        self.assertRaises(AssertionError, city.getNumRealBuilding, 0)


class CityBonusTests(unittest.TestCase):
    """Per-city connected resources: membership only, no counts."""

    def bonuses(self, **kwargs):
        _, parsed = buildWith(cities=[City(0, **kwargs)])
        return parsed["cities"][0]["bonuses"]

    def test_grouped_like_the_players(self):
        self.assertEqual(self.bonuses(bonuses=(0, 1)), {
            "strategic": ["BONUS_COPPER"],
            "happiness": [],
            "health": ["BONUS_CORN"],
        })

    def test_no_counts_on_a_city(self):
        # Quantity is an empire-level fact: a city either has the connection or
        # does not, and "two copper in this city" is not a thing the engine models.
        self.assertNotIn("counts", self.bonuses())

    def test_city_without_connections_gets_empty_groups(self):
        self.assertEqual(self.bonuses(bonuses=()),
                         {"strategic": [], "happiness": [], "health": []})

    def test_read_through_the_engines_own_connection_test(self):
        # hasBonus already folds in tech, improvement, route, war and trades -
        # every bonus index is asked, and the answer is the trade network's.
        city = City(0)
        buildWith(cities=[city])
        self.assertEqual(city.hasBonusArgs, list(range(len(BONUSES))))

    def test_cities_can_differ_from_each_other(self):
        # The whole point of the per-city section: one city connected to copper
        # and another not is the difference between building Axemen and not.
        _, parsed = buildWith(cities=[City(0, bonuses=(1,)), City(1, bonuses=())])
        self.assertEqual(parsed["cities"][0]["bonuses"]["strategic"], ["BONUS_COPPER"])
        self.assertEqual(parsed["cities"][1]["bonuses"]["strategic"], [])


class CityCoastalTests(unittest.TestCase):
    def test_coastal_city(self):
        _, parsed = buildWith(cities=[City(0, coastal=True)])
        self.assertIs(parsed["cities"][0]["coastal"], True)

    def test_inland_city(self):
        _, parsed = buildWith(cities=[City(0, coastal=False)])
        self.assertIs(parsed["cities"][0]["coastal"], False)

    def test_asks_with_the_engines_minimum_water_size(self):
        # NOT "is any neighbour water": the test is adjacency to a water body of
        # at least MIN_WATER_SIZE_FOR_OCEAN, so a city on a two-tile pond is not
        # coastal. Passing the define is what makes this the engine's own answer
        # rather than a hand-rolled approximation of it.
        city = City(0)
        buildWith(cities=[city])
        self.assertEqual(city.coastalArgs, [MIN_WATER_SIZE_FOR_OCEAN])


class WonderTests(unittest.TestCase):
    """What is gone (world) and what we have built (national)."""

    def wonders(self, builtWonders=(), nationalWonders=()):
        _, parsed = exportState(game=Game(builtWonders=builtWonders),
                                player=Player(nationalWonders=nationalWonders))
        return parsed["wonders"]

    def test_world_wonders_built_anywhere_are_listed(self):
        # The fact that cannot be derived from anything else in the file: whether
        # a wonder is still available depends on rivals we may never have met.
        self.assertEqual(self.wonders(builtWonders=(2,))["built"],
                         ["BUILDINGCLASS_PYRAMIDS"])

    def test_unbuilt_world_wonders_are_absent(self):
        self.assertEqual(self.wonders()["built"], [])

    def test_national_wonders_are_our_own(self):
        self.assertEqual(self.wonders(nationalWonders=(4,))["national"],
                         ["BUILDINGCLASS_HEROIC_EPIC"])

    def test_ordinary_buildings_are_in_neither_list(self):
        # Palace and Barracks have no instance limit at all (-1), so they are
        # not wonders and must not appear however many exist.
        wonders = self.wonders(builtWonders=(0, 1), nationalWonders=(0, 1))
        self.assertEqual(wonders["built"], [])
        self.assertEqual(wonders["national"], [])

    def test_world_and_national_lists_do_not_overlap(self):
        wonders = self.wonders(builtWonders=(2, 3), nationalWonders=(4,))
        self.assertEqual(wonders["built"],
                         ["BUILDINGCLASS_GREAT_LIBRARY", "BUILDINGCLASS_PYRAMIDS"])
        self.assertEqual(wonders["national"], ["BUILDINGCLASS_HEROIC_EPIC"])

    def test_building_classes_not_buildings(self):
        # The limit is a property of the class, and the class is what a civ's
        # unique replacement shares - a Ziggurat and a Courthouse are one class.
        for name in self.wonders(builtWonders=(2,))["built"]:
            self.assertTrue(name.startswith("BUILDINGCLASS_"), name)

    def test_sorted_for_diffability(self):
        self.assertEqual(self.wonders(builtWonders=(3, 2))["built"],
                         ["BUILDINGCLASS_GREAT_LIBRARY", "BUILDINGCLASS_PYRAMIDS"])

    def test_global_count_is_read_from_the_game_not_from_rivals(self):
        # A sweep of rivals' cities would need their city lists and would miss
        # wonders in cities we have never seen. The game-level counter is both
        # correct and public - the Info screen shows it to every player.
        mod, _ = exportState(game=Game(builtWonders=(2,)))
        # Asked only of the world-wonder classes: an unlimited building has no
        # global count worth reading, and a national wonder's count is per-player.
        self.assertEqual(mod["_testGc"].getGame().buildingClassCreatedArgs,
                         list(WORLD_WONDER_CLASSES))

    def test_no_wonder_owner_or_city_is_exported(self):
        # "This wonder is taken" is public; "Hammurabi built it in Babylon" is
        # not - the Info screen shows Unknown for an unmet builder. The section
        # is two flat lists of names precisely so there is nowhere to put one.
        wonders = self.wonders(builtWonders=(2,), nationalWonders=(4,))
        self.assertEqual(sorted(wonders.keys()), ["built", "national"])


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
        # Two getters silently answer for the ACTIVE team rather than for ours,
        # with no API to ask about a specific player: calculateYield(bDisplay=True)
        # for tile yields, and getVisualOwner() for foreign units. Exporting for
        # anyone else would hand over the wrong player's view, so buildState
        # refuses outright rather than producing a plausible-looking wrong file.
        mod = loadModule(game=Game(activePlayer=PLAYER_ID + 1))
        self.assertRaises(AssertionError, mod["buildState"], 5, PLAYER_ID, "onEndGameTurn")

    def test_the_guard_runs_before_anything_is_read(self):
        # It guards the whole export, not just the map, so it has to fire even if
        # the map section would never be reached.
        mod = loadModule(game=Game(activePlayer=PLAYER_ID + 1),
                         cyMap=Map(plots=[], width=0, height=0))
        self.assertRaises(AssertionError, mod["buildState"], 5, PLAYER_ID, "x")


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
        text = renderState(cyMap=cyMap)[1]
        tileLines = [ln for ln in text.split("\n") if '"terrain"' in ln]
        self.assertEqual(len(tileLines), 1)
        self.assertGreater(len(tileLines[0]), 88)
        json.loads(text)

    def test_marker_does_not_change_how_other_sections_render(self):
        # Raising the global inline width instead would have collapsed `research`
        # and rewritten every existing section.
        text = renderState()[1]
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
        text = renderState(cyMap=cyMap)[1]
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


def buildDiplomacy(rivals=(), met=(), atWar=()):
    """Export a turn with the given rival players, parsed back."""
    return exportState(rivals=absentPlayers(*rivals), team=Team(met=met, atWar=atWar))


class ContactsTests(unittest.TestCase):
    def test_met_rival(self):
        _, parsed = buildDiplomacy(
            rivals=[Rival(1, teamId=1, leader=1, civilization=1, attitude=3)],
            met=(1,))
        self.assertEqual(parsed["contacts"], [{
            "playerId": 1,
            "leader": "LEADER_GANDHI",
            "civilization": "CIVILIZATION_INDIA",
            "attitude": "ATTITUDE_PLEASED",
            "atWar": False,
        }])

    def test_unmet_rivals_are_absent(self):
        _, parsed = buildDiplomacy(rivals=[Rival(1, teamId=1)], met=())
        self.assertEqual(parsed["contacts"], [])

    def test_meeting_nobody_is_an_empty_list_not_an_omission(self):
        # Only honest because no section is omitted any more: while contacts was
        # unimplemented, [] and "not built yet" were indistinguishable.
        _, parsed = buildDiplomacy()
        self.assertEqual(parsed["contacts"], [])

    def test_barbarians_are_excluded_even_though_they_count_as_met(self):
        # THE trap in this section. The barbarian team declares war on every civ
        # team in CvGame::initDiplomacy, and CvTeam::declareWar calls meet() - so
        # isHasMet and isAtWar are both true for the barbarians from turn 0. A
        # loop written on isHasMet alone reports a barbarian contact, at war, in
        # every export from turn 1 onward.
        _, parsed = buildDiplomacy(
            rivals=[Rival(BARBARIAN_PLAYER, teamId=BARBARIAN_PLAYER, leader=3,
                          civilization=3, barbarian=True)],
            met=(BARBARIAN_PLAYER,), atWar=(BARBARIAN_PLAYER,))
        self.assertEqual(parsed["contacts"], [])

    def test_minor_civs_are_excluded_on_the_same_grounds(self):
        _, parsed = buildDiplomacy(
            rivals=[Rival(1, teamId=1, minor=True)], met=(1,), atWar=(1,))
        self.assertEqual(parsed["contacts"], [])

    def test_dead_rivals_are_excluded(self):
        # Matches the base game's own Foreign Advisor, which filters on isAlive.
        _, parsed = buildDiplomacy(rivals=[Rival(1, teamId=1, alive=False)], met=(1,))
        self.assertEqual(parsed["contacts"], [])

    def test_teammates_are_not_contacts(self):
        _, parsed = buildDiplomacy(rivals=[Rival(1, teamId=TEAM_ID)], met=(TEAM_ID,))
        self.assertEqual(parsed["contacts"], [])

    def test_at_war_is_a_json_bool_not_an_int(self):
        _, parsed = buildDiplomacy(rivals=[Rival(1, teamId=1)], met=(1,), atWar=(1,))
        self.assertIs(parsed["contacts"][0]["atWar"], True)
        _, parsed = buildDiplomacy(rivals=[Rival(1, teamId=1)], met=(1,))
        self.assertIs(parsed["contacts"][0]["atWar"], False)

    def test_attitude_is_read_toward_the_exported_player(self):
        rival = Rival(1, teamId=1, attitude=0)
        mod, parsed = buildDiplomacy(rivals=[rival], met=(1,))
        self.assertEqual(rival.attitudeArgs, [PLAYER_ID])
        self.assertEqual(parsed["contacts"][0]["attitude"], "ATTITUDE_FURIOUS")

    def test_relation_is_asked_of_our_own_team(self):
        # isHasMet is symmetric (CvTeam::meet calls makeHasMet on both sides), so
        # asking our own team means never fetching a rival CyTeam - the object
        # that would expose their techs and research.
        mod, _ = buildDiplomacy(rivals=[Rival(1, teamId=1)], met=(1,))
        self.assertEqual(mod["_testTeam"].metArgs, [1])
        self.assertEqual(mod["_testTeam"].atWarArgs, [1])
        self.assertEqual(mod["_testGc"].teamLookups, [TEAM_ID])

    def test_a_rival_team_object_is_never_fetched(self):
        # If one ever were, every accessor on it raises - see RivalTeam.
        mod, _ = buildDiplomacy(rivals=[Rival(1, teamId=1)], met=(1,))
        self.assertRaises(AssertionError, getattr, mod["_testRivalTeam"], "isHasTech")

    def test_rivals_private_state_is_never_read(self):
        # Gold, research, civics and the rest all answer happily on the real
        # CyPlayer for any player id. The mock raises on each; this test is what
        # keeps that true.
        rival = Rival(1, teamId=1)
        buildDiplomacy(rivals=[rival], met=(1,))
        for name in ("getGold", "calculateGoldRate", "getCurrentResearch",
                     "getNumCities", "getPower", "getCurrentEra"):
            self.assertRaises(AssertionError, getattr(rival, name))
        self.assertRaises(AssertionError, rival.getCivics, 0)

    def test_sorted_by_player_id(self):
        _, parsed = buildDiplomacy(
            rivals=[Rival(4, teamId=4), Rival(1, teamId=1), Rival(2, teamId=2)],
            met=(1, 2, 4))
        self.assertEqual([c["playerId"] for c in parsed["contacts"]], [1, 2, 4])


class ForeignUnitTests(unittest.TestCase):
    def rival(self, *units):
        return Rival(1, teamId=1, units=list(units))

    def test_visible_unit(self):
        _, parsed = buildDiplomacy(
            rivals=[self.rival(Unit(0, unitType=1, x=7, y=9, owner=1))])
        self.assertEqual(parsed["foreignUnits"],
                         [{"owner": 1, "type": "UNIT_WARRIOR", "x": 7, "y": 9}])

    def test_fogged_units_are_not_remembered(self):
        # Unlike cities. The engine keeps no record of where enemy units were, so
        # a unit vanishing between exports means "out of sight", not "destroyed".
        _, parsed = buildDiplomacy(rivals=[self.rival(Unit(0, owner=1, visible=False))])
        self.assertEqual(parsed["foreignUnits"], [])

    def test_invisible_units_are_skipped(self):
        _, parsed = buildDiplomacy(rivals=[self.rival(Unit(0, owner=1, invisible=True))])
        self.assertEqual(parsed["foreignUnits"], [])

    def test_visibility_checks_use_our_team_and_never_debug(self):
        unit = Unit(0, owner=1)
        buildDiplomacy(rivals=[self.rival(unit)])
        self.assertEqual(unit.plot().visibleArgs, [(TEAM_ID, False)])
        self.assertEqual(unit.invisibleArgs, [(TEAM_ID, False)])

    def test_dead_units_are_skipped(self):
        _, parsed = buildDiplomacy(rivals=[self.rival(Unit(0, owner=1, dead=True))])
        self.assertEqual(parsed["foreignUnits"], [])

    def test_units_off_the_map_are_skipped(self):
        _, parsed = buildDiplomacy(
            rivals=[self.rival(Unit(0, owner=1, plot=Plot(none=True)))])
        self.assertEqual(parsed["foreignUnits"], [])

    def test_barbarians_are_included(self):
        # They own real units and are the main military fact of turns 1-20. Only
        # contacts filters them out, and for its own specific reason.
        _, parsed = buildDiplomacy(
            rivals=[Rival(BARBARIAN_PLAYER, teamId=BARBARIAN_PLAYER, barbarian=True,
                          units=[Unit(0, unitType=1, owner=BARBARIAN_PLAYER)])])
        self.assertEqual(parsed["foreignUnits"][0]["owner"], BARBARIAN_PLAYER)

    def test_owner_is_the_one_the_game_draws(self):
        # getOwner raises on the mock: a hidden-nationality unit shows as
        # barbarian on the map, and the export must not be what unmasks it.
        _, parsed = buildDiplomacy(
            rivals=[self.rival(Unit(0, owner=1, visualOwner=BARBARIAN_PLAYER))])
        self.assertEqual(parsed["foreignUnits"][0]["owner"], BARBARIAN_PLAYER)

    def test_damage_is_exported_when_hurt_and_omitted_when_not(self):
        _, parsed = buildDiplomacy(rivals=[self.rival(Unit(0, owner=1, damage=40))])
        self.assertEqual(parsed["foreignUnits"][0]["damage"], 40)
        _, parsed = buildDiplomacy(rivals=[self.rival(Unit(0, owner=1))])
        self.assertNotIn("damage", parsed["foreignUnits"][0])

    def test_sorted_by_owner_then_position(self):
        _, parsed = buildDiplomacy(rivals=[
            Rival(2, teamId=2, units=[Unit(0, owner=2, x=1, y=1)]),
            Rival(1, teamId=1, units=[Unit(0, owner=1, x=5, y=9),
                                      Unit(1, owner=1, x=2, y=9),
                                      Unit(2, owner=1, x=8, y=3)]),
        ])
        self.assertEqual([(u["owner"], u["x"], u["y"]) for u in parsed["foreignUnits"]],
                         [(1, 8, 3), (1, 2, 9), (1, 5, 9), (2, 1, 1)])

    def test_identical_stacked_units_do_not_break_the_sort(self):
        # Two rows with equal sort keys must not make the sort compare the dicts.
        _, parsed = buildDiplomacy(rivals=[self.rival(
            Unit(0, unitType=1, owner=1, x=4, y=4),
            Unit(1, unitType=1, owner=1, x=4, y=4))])
        self.assertEqual(len(parsed["foreignUnits"]), 2)

    def test_no_visible_units_is_an_empty_list(self):
        _, parsed = buildDiplomacy()
        self.assertEqual(parsed["foreignUnits"], [])


class ForeignCityTests(unittest.TestCase):
    def rival(self, *cities):
        return Rival(1, teamId=1, cities=list(cities))

    def test_revealed_city(self):
        _, parsed = buildDiplomacy(
            rivals=[self.rival(ForeignCity(0, name=u"Delhi", x=38, y=46, owner=1,
                                           population=3))])
        self.assertEqual(parsed["foreignCities"],
                         [{"owner": 1, "name": "Delhi", "x": 38, "y": 46,
                           "population": 3}])

    def test_unrevealed_cities_are_absent(self):
        _, parsed = buildDiplomacy(
            rivals=[self.rival(ForeignCity(0, owner=1, revealed=False))])
        self.assertEqual(parsed["foreignCities"], [])

    def test_reveal_check_uses_our_team_and_never_debug(self):
        city = ForeignCity(0, owner=1)
        buildDiplomacy(rivals=[self.rival(city)])
        self.assertEqual(city.revealedArgs, [(TEAM_ID, False)])

    def test_capital_is_flagged_and_otherwise_omitted(self):
        # The star on the nameplate: CvCity::isStarCity is "return isCapital()",
        # exported for the renderer and gated on neither team nor visibility.
        _, parsed = buildDiplomacy(
            rivals=[self.rival(ForeignCity(0, owner=1, capital=True))])
        self.assertIs(parsed["foreignCities"][0]["capital"], True)
        _, parsed = buildDiplomacy(rivals=[self.rival(ForeignCity(0, owner=1))])
        self.assertNotIn("capital", parsed["foreignCities"][0])

    def test_invalid_cities_are_skipped(self):
        _, parsed = buildDiplomacy(rivals=[self.rival(
            ForeignCity(0, owner=1), ForeignCity(1, owner=1, none=True))])
        self.assertEqual(len(parsed["foreignCities"]), 1)

    def test_city_internals_are_never_read(self):
        # The engine's own billboard code draws this line: name, size and the
        # capital star are ungated, while the food and production bars beside
        # them are gated on canBeSelected(). Every internal raises on the mock.
        city = ForeignCity(0, owner=1)
        buildDiplomacy(rivals=[self.rival(city)])
        for name in ("getFood", "getProduction", "happyLevel", "goodHealth",
                     "isProductionUnit", "getCultureThreshold"):
            self.assertRaises(AssertionError, getattr(city, name))
        self.assertRaises(AssertionError, city.getCulture, 1)
        self.assertRaises(AssertionError, city.isWorkingPlotByIndex, 0)

    def test_plot_side_city_lookup_is_never_used(self):
        # isRevealed is a per-city flag and is STRICTER than the tile being
        # revealed: CvCity::init only reveals a new city to teams that can
        # currently SEE the plot. So a plot sweep calling getPlotCity() would
        # surface cities founded under fog that the player has never laid eyes
        # on. Both plot accessors raise; this is what keeps the section honest
        # if anyone tries to fold it into _buildMap for speed.
        mod, _ = buildDiplomacy(rivals=[self.rival(ForeignCity(0, owner=1))])
        plot = Plot()
        self.assertRaises(AssertionError, plot.getPlotCity)
        self.assertRaises(AssertionError, plot.isCity)

    def test_barbarian_cities_are_included(self):
        _, parsed = buildDiplomacy(rivals=[
            Rival(BARBARIAN_PLAYER, teamId=BARBARIAN_PLAYER, barbarian=True,
                  cities=[ForeignCity(0, owner=BARBARIAN_PLAYER, name=u"Hippus")])])
        self.assertEqual(parsed["foreignCities"][0]["owner"], BARBARIAN_PLAYER)

    def test_sorted_by_owner_then_position(self):
        _, parsed = buildDiplomacy(rivals=[
            Rival(2, teamId=2, cities=[ForeignCity(0, owner=2, x=1, y=1)]),
            Rival(1, teamId=1, cities=[ForeignCity(0, owner=1, x=5, y=9),
                                       ForeignCity(1, owner=1, x=8, y=3)]),
        ])
        self.assertEqual([(c["owner"], c["x"], c["y"]) for c in parsed["foreignCities"]],
                         [(1, 8, 3), (1, 5, 9), (2, 1, 1)])

    def test_unicode_city_name_round_trips(self):
        _, parsed = buildDiplomacy(
            rivals=[self.rival(ForeignCity(0, owner=1, name=u"Köln"))])
        self.assertEqual(parsed["foreignCities"][0]["name"], u"Köln")

    def test_no_revealed_cities_is_an_empty_list(self):
        _, parsed = buildDiplomacy()
        self.assertEqual(parsed["foreignCities"], [])


class DiplomacyRenderingTests(unittest.TestCase):
    """The three sections are homogeneous tables, so each row is one line - the
    same reason map tiles are. An attitude change then shows up as a one-line
    diff rather than one line buried inside a seven-line object."""

    def render(self, rivals=(), met=(), atWar=()):
        return renderState(rivals=absentPlayers(*rivals),
                           team=Team(met=met, atWar=atWar))[1]

    def test_a_contact_is_one_line_despite_being_over_the_inline_width(self):
        text = self.render(rivals=[Rival(2, teamId=2, leader=2, civilization=2)],
                           met=(2,))
        lines = [ln for ln in text.split("\n") if '"attitude"' in ln]
        self.assertEqual(len(lines), 1)
        self.assertGreater(len(lines[0]), 88)
        self.assertTrue(lines[0].strip().startswith('{"playerId": 2, '), lines[0])
        json.loads(text)

    def test_foreign_rows_lead_with_their_coordinates(self):
        text = self.render(rivals=[Rival(1, teamId=1,
                                         units=[Unit(0, owner=1, x=7, y=9)],
                                         cities=[ForeignCity(0, owner=1, x=3, y=4)])])
        # `"owner"` and `"type"` together are unique to a foreign-unit row: our
        # own units carry a type but no owner, and tiles carry an owner but no type.
        unitLine = [ln for ln in text.split("\n")
                    if '"owner"' in ln and '"type"' in ln][0]
        # Likewise `"owner"` with `"population"`: our own cities have a population
        # but no owner field, and theirs are the only ones rendered on one line.
        cityLine = [ln for ln in text.split("\n")
                    if '"owner"' in ln and '"population"' in ln][0]
        # Containment rather than startswith: a section short enough to fit inline
        # keeps its rows on the same line as the section key, which is fine - the
        # claim being tested is the key order inside a row.
        self.assertIn('{"x": 7, "y": 9, ', unitLine)
        self.assertIn('{"x": 3, "y": 4, ', cityLine)


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
    """Mod output must satisfy the WHOLE of schema/state.schema.json.

    Section-by-section validation was the rule while sections were still being
    omitted; now that every one is built, the document validates as a document -
    which also means the schema's top-level `required` and
    `additionalProperties: false` finally bite.
    """

    def setUp(self):
        with open(SCHEMA) as f:
            self.schema = json.load(f)
        self.validator = jsonschema.Draft202012Validator(self.schema)

    def assertValid(self, parsed):
        errors = ["%s: %s" % ("/".join(str(p) for p in e.absolute_path), e.message)
                  for e in self.validator.iter_errors(parsed)]
        self.assertEqual(errors, [], "; ".join(errors))

    def export(self, **kwargs):
        return exportState(**kwargs)[1]

    def test_schema_itself_is_well_formed(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_default_export_validates_as_a_whole_document(self):
        self.assertValid(self.export())

    def test_fully_populated_export_validates(self):
        # The default fixture leans heavily on omitted defaults. This one carries
        # every optional field there is: a tile with all of them set, a damaged
        # unit, met rivals, visible foreign units and a revealed capital.
        cyMap = Map(plots=[Plot(x=0, y=0, terrain=3, visible=True, hills=True,
                                lake=True, freshWater=True, river=True,
                                feature=1, bonus=0, improvement=0, route=1,
                                owner=2, yields=(3, 2, 1))],
                    width=1, height=1)
        parsed = self.export(
            player=Player(units=[Unit(0, damage=55)]),
            cyMap=cyMap,
            team=Team(met=(1, 2), atWar=(2,)),
            rivals=absentPlayers(
                Rival(1, teamId=1, leader=1, civilization=1, attitude=4,
                      units=[Unit(0, unitType=1, owner=1, damage=30)],
                      cities=[ForeignCity(0, owner=1, capital=True)]),
                Rival(2, teamId=2, leader=2, civilization=2, attitude=0),
                Rival(BARBARIAN_PLAYER, teamId=BARBARIAN_PLAYER, barbarian=True,
                      units=[Unit(0, unitType=1, owner=BARBARIAN_PLAYER)])))
        self.assertValid(parsed)
        # Guard against the fixture silently going empty and validating vacuously.
        self.assertEqual(len(parsed["contacts"]), 2)
        self.assertEqual(len(parsed["foreignUnits"]), 2)
        self.assertEqual(len(parsed["foreignCities"]), 1)

    def test_process_city_export_still_validates(self):
        # The null productionNeeded branch has to satisfy the schema too.
        self.assertValid(self.export(
            player=Player(cities=[City(0, unit=None, process=0,
                                       productionNeeded=MAX_INT)])))

    def test_no_research_selected_export_still_validates(self):
        self.assertValid(self.export(player=Player(research=NO_TECH)))

    def test_committed_example_still_validates(self):
        with open(os.path.join(REPO, "schema", "state.example.json")) as f:
            example = json.load(f)
        self.assertValid(example)

    def test_an_extra_top_level_section_would_be_rejected(self):
        # additionalProperties: false only started biting once whole-document
        # validation replaced the per-section checks; make sure it does.
        parsed = self.export()
        parsed["surprise"] = 1
        self.assertRaises(AssertionError, self.assertValid, parsed)


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
        self.assertIsNone(loadModule()["getStateRootDir"]())
        self.assertIsNone(loadModule()["getTurnFilePath"](5, PLAYER_ID))

    def test_returns_configured_root_dir(self):
        mod = loadModule(stateDir=r"C:\somewhere")
        self.assertEqual(mod["getStateRootDir"](), r"C:\somewhere")

    def test_turn_file_path_is_leader_and_game_id_folder_plus_turn_file(self):
        # LEADER_HATSHEPSUT is Player()'s default; a pre-existing scriptData
        # value stands in for an ID a prior export already wrote.
        mod = loadModule(stateDir=r"C:\somewhere", game=Game(scriptData="12345"))
        self.assertEqual(mod["getTurnFilePath"](5, PLAYER_ID),
                         os.path.join(r"C:\somewhere", "LEADER_HATSHEPSUT_12345", "turn_0005.json"))

    def test_same_game_resolves_to_the_same_folder_across_turns(self):
        # The whole point of persisting an ID: reloading the same game later
        # must land in the folder its earlier turns are already in.
        game = Game(scriptData="777")
        mod = loadModule(stateDir=r"C:\somewhere", game=game)
        turn1 = mod["getTurnFilePath"](1, PLAYER_ID)
        turn2 = mod["getTurnFilePath"](2, PLAYER_ID)
        self.assertEqual(os.path.dirname(turn1), os.path.dirname(turn2))

    def test_different_game_id_gets_a_different_folder(self):
        mod = loadModule(stateDir=r"C:\somewhere", game=Game(scriptData="1"))
        other = loadModule(stateDir=r"C:\somewhere", game=Game(scriptData="2"))
        self.assertNotEqual(mod["getTurnFilePath"](1, PLAYER_ID),
                            other["getTurnFilePath"](1, PLAYER_ID))

    def test_generates_and_persists_an_id_when_scriptdata_is_empty(self):
        # A brand-new game has never had its scriptData set; the first export
        # must generate an ID AND write it back via setScriptData, so every
        # later export (and every later load of the save) sees the same one.
        game = Game(scriptData="")
        mod = loadModule(stateDir=r"C:\somewhere", game=game)
        path = mod["getTurnFilePath"](1, PLAYER_ID)
        self.assertEqual(len(game.scriptDataSets), 1)
        generatedId = game.scriptDataSets[0]
        self.assertTrue(generatedId)
        self.assertEqual(path, os.path.join(r"C:\somewhere",
                         "LEADER_HATSHEPSUT_%s" % generatedId, "turn_0001.json"))

    def test_does_not_regenerate_an_id_once_one_exists(self):
        game = Game(scriptData="existing-id")
        mod = loadModule(stateDir=r"C:\somewhere", game=game)
        mod["getTurnFilePath"](1, PLAYER_ID)
        mod["getTurnFilePath"](2, PLAYER_ID)
        self.assertEqual(game.scriptDataSets, [])
        self.assertEqual(game.getScriptData(), "existing-id")


if __name__ == "__main__":
    unittest.main(verbosity=2)
