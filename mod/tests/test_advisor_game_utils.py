"""Tests for the mod's CvAdvisorGameUtils, run outside Civ IV.

Loads the real mod source (never a copy) with CvPythonExtensions, CvUtil and the
base CvGameUtils shimmed, so the AI_chooseProduction override can be checked
without launching the game.

The one property this file exists to guard: MODE == 'advisor' (the shipped
default - see LocalConfig.py.example) must leave AI_chooseProduction byte-
identical to the base game's own stock behavior, for EVERY city, not just ones
outside the configured leader. See AI_OPPONENT_PLAN.md "Mode gating" - this is
the test that section says should exist, not just be claimed.

NOTE: like test_state_writer.py, this runs under Python 3 (developer tooling)
even though the code under test is Python 2.4. It verifies behavior only and
cannot catch 2.4 syntax violations; those still need review by eye.

    python mod/tests/test_advisor_game_utils.py
"""
import os
import sys
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "mod", "Assets", "Python", "CvAdvisorGameUtils.py")

NO_TYPE = -1
UNIT_WARRIOR = 3
UNIT_SETTLER = 7
ORDER_TRAIN = 0

# String key -> resolved int, mirroring gc.getInfoTypeForString. Anything not
# listed here resolves to NO_TYPE, same as an unrecognized key in the real game.
INFO_TYPES = {
    'UNIT_WARRIOR': UNIT_WARRIOR,
    'LEADER_ALEXANDER': 100,
    'LEADER_HANNIBAL': 101,
}


class FakePlayer(object):
    def __init__(self, leaderType, human=False, alive=True):
        self._leaderType = leaderType
        self._human = human
        self._alive = alive

    def isAlive(self):
        return self._alive

    def isHuman(self):
        return self._human

    def getLeaderType(self):
        return self._leaderType


class FakeCity(object):
    """Records every call so a test can assert on override-vs-fallthrough."""

    def __init__(self, owner, name="Testopolis"):
        self._owner = owner
        self._name = name
        self.pushOrderCalls = []

    def getOwner(self):
        return self._owner

    def getName(self):
        return self._name

    def pushOrder(self, *args):
        self.pushOrderCalls.append(args)


class FakeGc(object):
    def __init__(self, players):
        self._players = players

    def getInfoTypeForString(self, key):
        return INFO_TYPES.get(key, NO_TYPE)

    def getMAX_PLAYERS(self):
        return len(self._players)

    def getPlayer(self, i):
        return self._players[i]


class BaseCvGameUtilsCallRecorder(object):
    """Stand-in for the real base CvGameUtils.CvGameUtils.

    Records whether AI_chooseProduction reached the base class, and with what
    argsList - that IS the "stock behavior, untouched" property under test, since
    the real base class's own body is what actually plays each city normally.
    """

    def __init__(self):
        self.chooseProductionCalls = []

    def AI_chooseProduction(self, argsList):
        self.chooseProductionCalls.append(argsList)
        return 0


def loadModule(players, mode=None, leaderKey=None):
    """Exec the real mod source with the game API and LocalConfig shimmed."""
    gc = FakeGc(players)

    fakeCvPythonExtensions = types.ModuleType("CvPythonExtensions")
    fakeCvPythonExtensions.CyGlobalContext = lambda: gc
    fakeCvPythonExtensions.OrderTypes = type("OrderTypes", (), {"ORDER_TRAIN": ORDER_TRAIN})
    sys.modules["CvPythonExtensions"] = fakeCvPythonExtensions

    pyPrintCalls = []
    fakeCvUtil = types.ModuleType("CvUtil")
    fakeCvUtil.pyPrint = lambda msg: pyPrintCalls.append(msg)
    sys.modules["CvUtil"] = fakeCvUtil

    fakeCvGameUtils = types.ModuleType("CvGameUtils")
    # The real module does `class CvAdvisorGameUtils(CvGameUtils.CvGameUtils)` and
    # `CvGameUtils.CvGameUtils.AI_chooseProduction(self, argsList)` - both need the
    # class object itself, not an instance, so expose the recorder class directly
    # rather than a pre-built instance.
    fakeCvGameUtils.CvGameUtils = BaseCvGameUtilsCallRecorder
    sys.modules["CvGameUtils"] = fakeCvGameUtils

    sys.modules.pop("LocalConfig", None)
    if mode is not None:
        localConfig = types.ModuleType("LocalConfig")
        localConfig.MODE = mode
        if leaderKey is not None:
            localConfig.AI_OPPONENT_PLAYER_KEY = leaderKey
        sys.modules["LocalConfig"] = localConfig

    ns = {"__name__": "CvAdvisorGameUtils"}
    with open(SRC) as f:
        exec(compile(f.read(), SRC, "exec"), ns)
    ns["_testGc"] = gc
    ns["_testPyPrintCalls"] = pyPrintCalls
    return ns


class AdvisorPathUnchangedTests(unittest.TestCase):
    """MODE == 'advisor' (the shipped default) must never touch a city's build."""

    def test_advisor_mode_falls_through_for_every_city(self):
        alexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False)
        ns = loadModule([alexander], mode='advisor', leaderKey='LEADER_ALEXANDER')
        utils = ns["CvAdvisorGameUtils"]()
        city = FakeCity(owner=0)

        result = utils.AI_chooseProduction([city])

        self.assertEqual(result, 0)
        self.assertEqual(city.pushOrderCalls, [])

    def test_missing_local_config_falls_through(self):
        # No LocalConfig at all is the "mod not configured on this machine" case
        # AI_OPPONENT_PLAN.md documents for the advisor's own LocalConfig story -
        # it must degrade the same way here, not raise.
        ns = loadModule([FakePlayer(1)], mode=None)
        utils = ns["CvAdvisorGameUtils"]()
        city = FakeCity(owner=0)

        result = utils.AI_chooseProduction([city])

        self.assertEqual(result, 0)
        self.assertEqual(city.pushOrderCalls, [])

    def test_advisor_mode_reaches_base_class_with_unmodified_argsList(self):
        # The property that actually matters: the base CvGameUtils sees exactly
        # what the engine passed it, unchanged - "byte-identical to stock" per
        # AI_OPPONENT_PLAN.md "Mode gating".
        ns = loadModule([FakePlayer(1)], mode='advisor')
        utils = ns["CvAdvisorGameUtils"]()
        city = FakeCity(owner=0)
        argsList = [city]

        utils.AI_chooseProduction(argsList)

        # CvAdvisorGameUtils has no __init__ of its own, so `utils` IS a
        # BaseCvGameUtilsCallRecorder instance - assert on it directly.
        self.assertEqual(utils.chooseProductionCalls, [argsList])


class OpponentModeTargetingTests(unittest.TestCase):
    """Sanity checks on the identity gating the advisor-path test above relies on
    being selective - if these failed, the advisor-path guarantee above would be
    vacuous (nothing would ever be a match to correctly skip)."""

    def test_matches_only_the_configured_leader(self):
        alexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False)
        other = FakePlayer(999, human=False)
        ns = loadModule([other, alexander], mode='opponent', leaderKey='LEADER_ALEXANDER')
        utils = ns["CvAdvisorGameUtils"]()

        matchedCity = FakeCity(owner=1)
        result = utils.AI_chooseProduction([matchedCity])
        self.assertEqual(result, 1)
        self.assertEqual(len(matchedCity.pushOrderCalls), 1)
        self.assertEqual(matchedCity.pushOrderCalls[0][:3], (ORDER_TRAIN, UNIT_WARRIOR, -1))

        unmatchedCity = FakeCity(owner=0)
        result = utils.AI_chooseProduction([unmatchedCity])
        self.assertEqual(result, 0)
        self.assertEqual(unmatchedCity.pushOrderCalls, [])

    def test_human_player_with_matching_leader_is_never_targeted(self):
        # getLeaderType() alone isn't enough to identify "the AI civ" - a human
        # could in principle share a leader. isHuman() must gate too.
        humanAlexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=True)
        ns = loadModule([humanAlexander], mode='opponent', leaderKey='LEADER_ALEXANDER')
        utils = ns["CvAdvisorGameUtils"]()
        city = FakeCity(owner=0)

        result = utils.AI_chooseProduction([city])

        self.assertEqual(result, 0)
        self.assertEqual(city.pushOrderCalls, [])

    def test_dead_player_with_matching_leader_is_never_targeted(self):
        deadAlexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False, alive=False)
        ns = loadModule([deadAlexander], mode='opponent', leaderKey='LEADER_ALEXANDER')
        utils = ns["CvAdvisorGameUtils"]()
        city = FakeCity(owner=0)

        result = utils.AI_chooseProduction([city])

        self.assertEqual(result, 0)
        self.assertEqual(city.pushOrderCalls, [])

    def test_unset_leader_key_falls_through_even_in_opponent_mode(self):
        ns = loadModule([FakePlayer(1)], mode='opponent', leaderKey=None)
        utils = ns["CvAdvisorGameUtils"]()
        city = FakeCity(owner=0)

        result = utils.AI_chooseProduction([city])

        self.assertEqual(result, 0)
        self.assertEqual(city.pushOrderCalls, [])


if __name__ == "__main__":
    unittest.main()
