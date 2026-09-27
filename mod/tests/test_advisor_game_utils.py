"""Tests for the mod's CvAdvisorGameUtils, run outside Civ IV.

Loads the real mod source (never a copy) with CvPythonExtensions, CvUtil and the
base CvGameUtils shimmed, so AI_chooseTech can be checked without launching the
game.

Two properties this file exists to guard:
1. MODE == 'advisor' (the shipped default - see LocalConfig.py.example) must
   leave AI_chooseTech byte-identical to the base game's own stock behavior,
   for EVERY player, not just ones matching the configured leader. See
   AI_OPPONENT_PLAN.md "Mode gating" - this is the test that section says
   should exist, not just be claimed.
2. THE RETURN-CONTRACT TRAP (AI_OPPONENT_PLAN.md "B2"): AI_chooseTech must
   return a TechTypes int on success, not a 1/0 boolean - CvPlayerAI does
   `eBestTech = (TechTypes)lResult` and only falls back to stock AI_bestTech()
   on NO_TECH (-1). A regression to `return True`/`return 1` here would
   silently order tech 0 in the real game; this file asserts the actual
   resolved int comes back.

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

NO_TECH = -1
TECH_POTTERY = 5
TECH_BRONZE_WORKING = 6

# String key -> resolved int, mirroring gc.getInfoTypeForString. Anything not
# listed here resolves to NO_TECH, same as an unrecognized key in the real game.
INFO_TYPES = {
    'TECH_POTTERY': TECH_POTTERY,
    'TECH_BRONZE_WORKING': TECH_BRONZE_WORKING,
    'LEADER_ALEXANDER': 100,
    'LEADER_HANNIBAL': 101,
}


class FakeTeam(object):
    def __init__(self, knownTechs=None):
        self._knownTechs = set(knownTechs or [])

    def isHasTech(self, techType):
        return techType in self._knownTechs


class FakePlayer(object):
    def __init__(self, leaderType, human=False, alive=True, team=0):
        self._leaderType = leaderType
        self._human = human
        self._alive = alive
        self._team = team

    def isAlive(self):
        return self._alive

    def isHuman(self):
        return self._human

    def getLeaderType(self):
        return self._leaderType

    def getTeam(self):
        return self._team


class FakeGc(object):
    def __init__(self, players, teams=None):
        self._players = players
        # playerId -> FakeTeam, keyed by getTeam() -> matches getTeam(teamId).
        self._teams = teams or {}

    def getInfoTypeForString(self, key):
        return INFO_TYPES.get(key, NO_TECH)

    def getMAX_PLAYERS(self):
        return len(self._players)

    def getPlayer(self, i):
        return self._players[i]

    def getTeam(self, teamId):
        return self._teams.get(teamId, FakeTeam())


class BaseCvGameUtilsCallRecorder(object):
    """Stand-in for the real base CvGameUtils.CvGameUtils.

    Records whether AI_chooseTech reached the base class, and with what
    argsList - that IS the "stock behavior, untouched" property under test,
    since the real base class's own body is what actually picks research for
    every player normally. Returns NO_TECH, matching the real base class's
    contract closely enough for these tests (a concrete value doesn't matter -
    what matters is that this stub, not our override, produced it).
    """

    def __init__(self):
        self.chooseTechCalls = []

    def AI_chooseTech(self, argsList):
        self.chooseTechCalls.append(argsList)
        return NO_TECH


def loadModule(players, teams=None, mode=None, leaderKey=None):
    """Exec the real mod source with the game API and LocalConfig shimmed."""
    gc = FakeGc(players, teams)

    fakeCvPythonExtensions = types.ModuleType("CvPythonExtensions")
    fakeCvPythonExtensions.CyGlobalContext = lambda: gc
    fakeCvPythonExtensions.OrderTypes = type("OrderTypes", (), {"ORDER_TRAIN": 0})
    sys.modules["CvPythonExtensions"] = fakeCvPythonExtensions

    pyPrintCalls = []
    fakeCvUtil = types.ModuleType("CvUtil")
    fakeCvUtil.pyPrint = lambda msg: pyPrintCalls.append(msg)
    sys.modules["CvUtil"] = fakeCvUtil

    fakeCvGameUtils = types.ModuleType("CvGameUtils")
    # The real module does `class CvAdvisorGameUtils(CvGameUtils.CvGameUtils)` and
    # `CvGameUtils.CvGameUtils.AI_chooseTech(self, argsList)` - both need the
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
        # No MOD_PYTHON_DIR configured: _decideTech's _repoRoot() then returns
        # None and _decideTech short-circuits before ever touching os.popen -
        # see the "no external process" tests below, which rely on exactly
        # this to keep these tests hermetic (no real subprocess spawned).
        sys.modules["LocalConfig"] = localConfig

    ns = {"__name__": "CvAdvisorGameUtils"}
    with open(SRC) as f:
        exec(compile(f.read(), SRC, "exec"), ns)
    ns["_testGc"] = gc
    ns["_testPyPrintCalls"] = pyPrintCalls
    return ns


class AdvisorPathUnchangedTests(unittest.TestCase):
    """MODE == 'advisor' (the shipped default) must never touch a player's tech."""

    def test_advisor_mode_falls_through_for_every_player(self):
        alexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False)
        ns = loadModule([alexander], mode='advisor', leaderKey='LEADER_ALEXANDER')
        utils = ns["CvAdvisorGameUtils"]()

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[0, False]])

    def test_missing_local_config_falls_through(self):
        # No LocalConfig at all is the "mod not configured on this machine" case
        # AI_OPPONENT_PLAN.md documents for the advisor's own LocalConfig story -
        # it must degrade the same way here, not raise.
        ns = loadModule([FakePlayer(1)], mode=None)
        utils = ns["CvAdvisorGameUtils"]()

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[0, False]])

    def test_advisor_mode_reaches_base_class_with_unmodified_argsList(self):
        # The property that actually matters: the base CvGameUtils sees exactly
        # what the engine passed it, unchanged - "byte-identical to stock" per
        # AI_OPPONENT_PLAN.md "Mode gating".
        ns = loadModule([FakePlayer(1)], mode='advisor')
        utils = ns["CvAdvisorGameUtils"]()
        argsList = [0, True]

        utils.AI_chooseTech(argsList)

        # CvAdvisorGameUtils has no __init__ of its own, so `utils` IS a
        # BaseCvGameUtilsCallRecorder instance - assert on it directly.
        self.assertEqual(utils.chooseTechCalls, [argsList])


class OpponentModeTargetingTests(unittest.TestCase):
    """Identity gating: without _decideTech ever succeeding (no MOD_PYTHON_DIR
    configured in these tests - see loadModule), every path here falls
    through to stock, so these only exercise WHO gets considered, not what
    happens on a successful external-process answer (see
    ExternalProcessNotInvokedTests and the return-contract test below for
    that)."""

    def test_matches_only_the_configured_leader(self):
        alexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False)
        other = FakePlayer(999, human=False)
        ns = loadModule([other, alexander], mode='opponent', leaderKey='LEADER_ALEXANDER')
        utils = ns["CvAdvisorGameUtils"]()

        # Matched player (id 1): falls through to stock because _decideTech
        # has no MOD_PYTHON_DIR to find the external script (returns None) -
        # a silent fall-through, not the "unusable key" pyPrint line, which
        # only fires when _decideTech returns a non-empty but invalid key.
        result = utils.AI_chooseTech([1, False])
        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[1, False]])

        # Unmatched player (id 0, wrong leader): also falls through, but for
        # a different reason (_advisorPlayerId never matches) - both land at
        # NO_TECH, so the real assertion these two cases together support is
        # that a matched player at least REACHES the _decideTech call path
        # rather than being filtered out identically to an unmatched one.
        # ns['_advisorPlayerId'] is the identity gate itself; call it
        # directly to confirm player 1 (Alexander) is who it resolves to.
        self.assertEqual(ns['_advisorPlayerId'](), 1)

    def test_human_player_with_matching_leader_is_never_targeted(self):
        # getLeaderType() alone isn't enough to identify "the AI civ" - a human
        # could in principle share a leader. isHuman() must gate too.
        humanAlexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=True)
        ns = loadModule([humanAlexander], mode='opponent', leaderKey='LEADER_ALEXANDER')
        utils = ns["CvAdvisorGameUtils"]()

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[0, False]])

    def test_dead_player_with_matching_leader_is_never_targeted(self):
        deadAlexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False, alive=False)
        ns = loadModule([deadAlexander], mode='opponent', leaderKey='LEADER_ALEXANDER')
        utils = ns["CvAdvisorGameUtils"]()

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[0, False]])

    def test_unset_leader_key_falls_through_even_in_opponent_mode(self):
        ns = loadModule([FakePlayer(1)], mode='opponent', leaderKey=None)
        utils = ns["CvAdvisorGameUtils"]()

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[0, False]])


class ReturnContractAndValidationTests(unittest.TestCase):
    """Exercises _decideTech's result handling directly, bypassing the real
    os.popen call (which would need an actual external process and Civ4 API),
    by monkeypatching _decideTech on the loaded module namespace before
    calling AI_chooseTech. This is the only way to reach the "external
    process answered successfully" branch without a live game or a real
    ai-opponent/decide_tech.py subprocess."""

    def _utilsWithStubbedDecision(self, players, teams, techKey):
        ns = loadModule(players, teams, mode='opponent', leaderKey='LEADER_ALEXANDER')
        ns['_decideTech'] = lambda playerId: techKey
        # AI_chooseTech is defined as a method that calls the module-level
        # _decideTech - reassigning it on ns only works if the class method
        # looks it up via the module's globals at call time, which it does
        # (plain function call, not a bound reference captured at class
        # definition time).
        utils = ns["CvAdvisorGameUtils"]()
        return ns, utils

    def test_valid_unknown_tech_returns_the_resolved_int_not_a_bool(self):
        # THE RETURN-CONTRACT TRAP: must be TECH_POTTERY's actual resolved
        # int (5), never True/1 - see module docstring.
        alexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False, team=0)
        teams = {0: FakeTeam(knownTechs=[])}
        ns, utils = self._utilsWithStubbedDecision([alexander], teams, 'TECH_POTTERY')

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, TECH_POTTERY)
        self.assertIsInstance(result, int)
        self.assertNotIsInstance(result, bool)
        self.assertEqual(utils.chooseTechCalls, [])  # never fell through to stock

    def test_unresolvable_tech_key_falls_through(self):
        alexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False, team=0)
        teams = {0: FakeTeam(knownTechs=[])}
        ns, utils = self._utilsWithStubbedDecision([alexander], teams, 'TECH_NOT_A_REAL_KEY')

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[0, False]])

    def test_already_known_tech_falls_through(self):
        # is_error: false is not a validity check (AI_OPPONENT_PLAN.md item
        # D) - a fluent, well-formed, already-known tech must not be trusted.
        alexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False, team=0)
        teams = {0: FakeTeam(knownTechs=[TECH_POTTERY])}
        ns, utils = self._utilsWithStubbedDecision([alexander], teams, 'TECH_POTTERY')

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[0, False]])

    def test_empty_decision_falls_through(self):
        # _decideTech returning None/'' is the "external process failed or
        # gave no usable answer" case - same fall-through as an invalid key.
        alexander = FakePlayer(INFO_TYPES['LEADER_ALEXANDER'], human=False, team=0)
        teams = {0: FakeTeam(knownTechs=[])}
        ns, utils = self._utilsWithStubbedDecision([alexander], teams, None)

        result = utils.AI_chooseTech([0, False])

        self.assertEqual(result, NO_TECH)
        self.assertEqual(utils.chooseTechCalls, [[0, False]])


class ExternalProcessNotInvokedTests(unittest.TestCase):
    """Sanity check on the test harness itself: without MOD_PYTHON_DIR set,
    _decideTech must short-circuit before touching os.popen, so these tests
    never actually spawn a process. If this regressed, every other test in
    this file would risk hanging on a real subprocess call."""

    def test_decide_tech_returns_none_without_mod_python_dir(self):
        ns = loadModule([FakePlayer(1)], mode='opponent', leaderKey=None)
        self.assertIsNone(ns['_decideTech'](0))


if __name__ == "__main__":
    unittest.main()
