"""Tests for the mod's CvCustomEventManager, run outside Civ IV.

Loads the real mod source (never a copy) with the game API, AdvisorStateWriter
and CvAdvisorGameUtils shimmed, so the export-trigger and mode-gating logic can
be checked without launching the game or exercising the real (1800+ line)
state-extraction path, which test_state_writer.py already covers.

Scope is deliberately the export wiring only - which hook exports for whom, at
which turn number, gated on which LocalConfig.MODE - not AI_chooseProduction or
the external-process production spike (test_advisor_game_utils.py, itself
tracking spike code that is expected to be replaced). The three properties this
file exists to guard, each a real defect found live this session before the fix
landed:
  1. The human export (onGameStart/onLoadGame/onEndGameTurn) must be silent
     when MODE == 'opponent' - previously ran unconditionally.
  2. onBeginPlayerTurn fires at the END of the turn it names, same trap as
     onEndPlayerTurn (see CLAUDE.md) - a first version without the +1
     correction produced a turn_0000.json that already showed the AI's city
     founded, one turn ahead of its own filename.
  3. The active-player flip around the opponent's export (CyGame.setActivePlayer)
     must always restore the original active player, including when the export
     itself raises.

NOTE: like the other mod/tests files, this runs under Python 3 (developer
tooling) even though the code under test is Python 2.4. It verifies behavior
only and cannot catch 2.4 syntax violations; those still need review by eye.

    python mod/tests/test_custom_event_manager.py
"""
import os
import sys
import tempfile
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "mod", "Assets", "Python", "CvCustomEventManager.py")
GAME_UTILS_SRC = os.path.join(REPO, "mod", "Assets", "Python", "CvAdvisorGameUtils.py")

# _exportState calls _refreshStateWriter, which locates AdvisorStateWriter.py via
# LocalConfig.MOD_PYTHON_DIR and execfile()s it into the module's __dict__ -
# real production behavior we want exercised, not bypassed. execfile() (and
# the reload() fallback for when MOD_PYTHON_DIR is unset) are Python-2-only
# builtins, absent under Python 3 (this test's own runtime, like every other
# file in mod/tests/) - _execfileShim below is injected as a builtin into the
# exec'd module so both paths work exactly as they do in the embedded 2.4
# interpreter. loadModule() below always sets MOD_PYTHON_DIR to a temp
# directory holding this trivial stand-in, real enough on disk for the shim to
# read - full extraction behavior is test_state_writer.py's job.


def _execfileShim(path, globalsDict):
    """Python 3 stand-in for the Python 2 builtin execfile(). Same contract:
    compile and run the file's source with globalsDict as both globals and
    locals, so top-level def/assignment rebinds names in the caller's dict -
    exactly what _refreshStateWriter relies on to hot-reload AdvisorStateWriter
    in production."""
    with open(path) as f:
        source = f.read()
    exec(compile(source, path, "exec"), globalsDict)
_FAKE_STATE_WRITER_SOURCE = (
    "calls = []\n"
    "\n"
    "def getTurnFilePath(gameTurn, playerId):\n"
    "    return '/fake/turn_%04d.json' % gameTurn\n"
    "\n"
    "def buildState(gameTurn, playerId, trigger):\n"
    "    calls.append((gameTurn, playerId, trigger))\n"
    "    return {}\n"
    "\n"
    "def writeStateFile(path, state):\n"
    "    pass\n"
)

NO_TYPE = -1
LEADER_ALEXANDER = 100

INFO_TYPES = {
    'LEADER_ALEXANDER': LEADER_ALEXANDER,
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


class FakeGame(object):
    """Records every setActivePlayer call, in order, so a test can assert the
    flip-then-restore sequence rather than just the final value."""

    def __init__(self, activePlayerId, gameTurn=0):
        self._activePlayerId = activePlayerId
        self._gameTurn = gameTurn
        self.setActivePlayerCalls = []

    def getActivePlayer(self):
        return self._activePlayerId

    def getGameTurn(self):
        return self._gameTurn

    def setActivePlayer(self, playerId, bForceHotSeat):
        self.setActivePlayerCalls.append((playerId, bForceHotSeat))
        self._activePlayerId = playerId


class FakeGc(object):
    def __init__(self, players, game):
        self._players = players
        self._game = game

    def getInfoTypeForString(self, key):
        return INFO_TYPES.get(key, NO_TYPE)

    def getMAX_PLAYERS(self):
        return len(self._players)

    def getPlayer(self, i):
        return self._players[i]

    def getGame(self):
        return self._game


class FakeBaseEventManager(object):
    """Stand-in for CvEventManager.CvEventManager - records that the base
    method ran (the "base behavior preserved" property CLAUDE.md requires of
    every override) without doing anything real."""

    def onGameStart(self, argsList):
        pass

    def onLoadGame(self, argsList):
        return "base-onLoadGame-result"

    def onBeginPlayerTurn(self, argsList):
        return "base-onBeginPlayerTurn-result"

    def onEndGameTurn(self, argsList):
        pass


def loadModule(players, game, tmpDir, mode=None, leaderKey=None):
    """Exec the real mod source with the game API, AdvisorStateWriter and
    CvAdvisorGameUtils shimmed. AdvisorStateWriter is faked rather than the
    real module (unlike CvAdvisorGameUtils, loaded for real) - its own
    extraction logic is test_state_writer.py's job; this file only needs to
    see WHICH (gameTurn, playerId, trigger) it was called with, read back from
    sys.modules["AdvisorStateWriter"].calls after each hook call. tmpDir is a
    real directory _FAKE_STATE_WRITER_SOURCE is written into - see the
    execfile discussion above for why a real file on disk is required."""
    gc = FakeGc(players, game)

    fakeCvPythonExtensions = types.ModuleType("CvPythonExtensions")
    fakeCvPythonExtensions.CyGlobalContext = lambda: gc
    sys.modules["CvPythonExtensions"] = fakeCvPythonExtensions

    pyPrintCalls = []
    fakeCvUtil = types.ModuleType("CvUtil")
    fakeCvUtil.pyPrint = lambda msg: pyPrintCalls.append(msg)
    sys.modules["CvUtil"] = fakeCvUtil

    fakeCvEventManager = types.ModuleType("CvEventManager")
    fakeCvEventManager.CvEventManager = FakeBaseEventManager
    sys.modules["CvEventManager"] = fakeCvEventManager

    # A placeholder module so `import AdvisorStateWriter` at the top of
    # CvCustomEventManager.py succeeds; _refreshStateWriter then execfile()s
    # the real-on-disk stand-in into this same module's __dict__ before every
    # export, exactly as production does to AdvisorStateWriter.py itself -
    # afterward sys.modules["AdvisorStateWriter"].calls holds every
    # (gameTurn, playerId, trigger) buildState was invoked with. calls starts
    # as [] here too, since a gated-off hook never calls _exportState at all,
    # so execfile never runs and never binds it.
    sys.modules.pop("AdvisorStateWriter", None)
    placeholderStateWriter = types.ModuleType("AdvisorStateWriter")
    placeholderStateWriter.calls = []
    sys.modules["AdvisorStateWriter"] = placeholderStateWriter
    stateWriterPath = os.path.join(tmpDir, "AdvisorStateWriter.py")
    with open(stateWriterPath, "w") as f:
        f.write(_FAKE_STATE_WRITER_SOURCE)

    sys.modules.pop("LocalConfig", None)
    localConfig = types.ModuleType("LocalConfig")
    localConfig.MOD_PYTHON_DIR = tmpDir
    if mode is not None:
        localConfig.MODE = mode
        if leaderKey is not None:
            localConfig.AI_OPPONENT_PLAYER_KEY = leaderKey
    sys.modules["LocalConfig"] = localConfig

    # CvAdvisorGameUtils loaded for real (not faked): opponentModeActive/
    # advisorModeActive/_advisorPlayerId are exactly what this file's mode-
    # gating and player-matching tests exercise, and test_advisor_game_utils.py
    # already separately guards CvAdvisorGameUtils in isolation.
    sys.modules.pop("CvAdvisorGameUtils", None)
    gameUtilsNs = {"__name__": "CvAdvisorGameUtils", "__builtins__": __builtins__}
    fakeCvGameUtilsBase = types.ModuleType("CvGameUtils")
    fakeCvGameUtilsBase.CvGameUtils = object
    sys.modules["CvGameUtils"] = fakeCvGameUtilsBase
    with open(GAME_UTILS_SRC) as f:
        exec(compile(f.read(), GAME_UTILS_SRC, "exec"), gameUtilsNs)
    gameUtilsModule = types.ModuleType("CvAdvisorGameUtils")
    gameUtilsModule.__dict__.update(gameUtilsNs)
    sys.modules["CvAdvisorGameUtils"] = gameUtilsModule

    sys.modules.pop("CvCustomEventManager", None)
    # execfile/reload: Python-2-only builtins the real embedded interpreter
    # provides natively - see the module-level comment above _execfileShim.
    ns = {
        "__name__": "CvCustomEventManager",
        "__builtins__": __builtins__,
        "execfile": _execfileShim,
        "reload": lambda module: _execfileShim(stateWriterPath, module.__dict__),
    }
    with open(SRC) as f:
        exec(compile(f.read(), SRC, "exec"), ns)
    ns["_testGc"] = gc
    ns["_testGame"] = game
    ns["_testPyPrintCalls"] = pyPrintCalls
    return ns


class _LoadModuleTestCase(unittest.TestCase):
    """Common tmpDir plumbing (see loadModule's docstring for why a real
    on-disk AdvisorStateWriter.py stand-in is needed) and a load() wrapper
    that hands back the manager plus the calls list to assert on."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def load(self, players, game, mode=None, leaderKey=None):
        ns = loadModule(players, game, self._tmp.name, mode=mode, leaderKey=leaderKey)
        manager = ns["CvCustomEventManager"]()
        return manager, sys.modules["AdvisorStateWriter"]


class HumanExportModeGatingTests(_LoadModuleTestCase):
    """The human-facing export (onGameStart/onLoadGame/onEndGameTurn) must be
    silent whenever MODE == 'opponent' - this used to run unconditionally."""

    def test_on_game_start_exports_in_advisor_mode(self):
        game = FakeGame(activePlayerId=0, gameTurn=0)
        manager, stateWriter = self.load([FakePlayer(1)], game, mode='advisor')

        manager.onGameStart([])

        self.assertEqual(stateWriter.calls, [(0, 0, 'onGameStart')])

    def test_on_game_start_silent_in_opponent_mode(self):
        game = FakeGame(activePlayerId=0, gameTurn=0)
        manager, stateWriter = self.load([FakePlayer(1)], game, mode='opponent', leaderKey=None)

        manager.onGameStart([])

        self.assertEqual(stateWriter.calls, [])

    def test_on_end_game_turn_exports_in_advisor_mode(self):
        game = FakeGame(activePlayerId=0, gameTurn=0)
        manager, stateWriter = self.load([FakePlayer(1)], game, mode='advisor')

        manager.onEndGameTurn([5])

        # +1: onEndGameTurn reports the turn that just finished - see CLAUDE.md.
        self.assertEqual(stateWriter.calls, [(6, 0, 'onEndGameTurn')])

    def test_on_end_game_turn_silent_in_opponent_mode(self):
        game = FakeGame(activePlayerId=0, gameTurn=0)
        manager, stateWriter = self.load([FakePlayer(1)], game, mode='opponent', leaderKey=None)

        manager.onEndGameTurn([5])

        self.assertEqual(stateWriter.calls, [])

    def test_both_mode_runs_human_export_too(self):
        game = FakeGame(activePlayerId=0, gameTurn=0)
        manager, stateWriter = self.load([FakePlayer(1)], game, mode='both', leaderKey=None)

        manager.onGameStart([])

        self.assertEqual(stateWriter.calls, [(0, 0, 'onGameStart')])


class OpponentExportTargetingTests(_LoadModuleTestCase):
    """The AI-opponent export must target only the configured leader, and only
    when opponent mode is active - the advisor's own export is a separate,
    independently-gated call (see HumanExportModeGatingTests above)."""

    def test_on_game_start_exports_configured_leader_in_opponent_mode(self):
        alexander = FakePlayer(LEADER_ALEXANDER, human=False)
        game = FakeGame(activePlayerId=0, gameTurn=0)
        manager, stateWriter = self.load([alexander], game, mode='opponent', leaderKey='LEADER_ALEXANDER')

        manager.onGameStart([])

        self.assertEqual(stateWriter.calls, [(0, 0, 'onGameStart')])

    def test_on_game_start_silent_when_no_leader_configured(self):
        alexander = FakePlayer(LEADER_ALEXANDER, human=False)
        game = FakeGame(activePlayerId=0, gameTurn=0)
        manager, stateWriter = self.load([alexander], game, mode='opponent', leaderKey=None)

        manager.onGameStart([])

        self.assertEqual(stateWriter.calls, [])

    def test_on_begin_player_turn_exports_only_the_matching_player(self):
        alexander = FakePlayer(LEADER_ALEXANDER, human=False)
        other = FakePlayer(999, human=False)
        game = FakeGame(activePlayerId=0, gameTurn=5)
        manager, stateWriter = self.load([other, alexander], game, mode='opponent', leaderKey='LEADER_ALEXANDER')

        # Player 1 (alexander) matches; player 0 (other) does not.
        manager.onBeginPlayerTurn([5, 1])
        manager.onBeginPlayerTurn([5, 0])

        # +1: onBeginPlayerTurn fires at the END of the turn it names, same as
        # onEndGameTurn - see CLAUDE.md "onBeginPlayerTurn/onEndPlayerTurn do
        # not bound the player's actual interactive turn". A first version of
        # this fix without the +1 produced a turn_0000.json that already
        # showed the AI's city founded - this assertion is what would have
        # caught that live defect before it shipped.
        self.assertEqual(stateWriter.calls, [(6, 1, 'onBeginPlayerTurn')])

    def test_on_begin_player_turn_ignores_human_with_matching_leader(self):
        humanAlexander = FakePlayer(LEADER_ALEXANDER, human=True)
        game = FakeGame(activePlayerId=0, gameTurn=5)
        manager, stateWriter = self.load([humanAlexander], game, mode='opponent', leaderKey='LEADER_ALEXANDER')

        manager.onBeginPlayerTurn([5, 0])

        self.assertEqual(stateWriter.calls, [])

    def test_both_hooks_return_the_base_class_result_unchanged(self):
        # onLoadGame/onBeginPlayerTurn must hand back exactly what the base
        # class returned, per this file's own "base behavior preserved" rule.
        game = FakeGame(activePlayerId=0, gameTurn=0)
        manager, _ = self.load([FakePlayer(1)], game, mode='advisor')

        self.assertEqual(manager.onLoadGame([]), "base-onLoadGame-result")
        self.assertEqual(manager.onBeginPlayerTurn([0, 0]), "base-onBeginPlayerTurn-result")


class ActivePlayerFlipTests(_LoadModuleTestCase):
    """CyGame.setActivePlayer is flipped to the opponent for the duration of
    their export, then restored - including when the export itself raises,
    since a stuck active player would be a real, visible bug (see
    CvCustomEventManager._maybeExportOpponentTurn)."""

    def test_active_player_is_flipped_then_restored(self):
        alexander = FakePlayer(LEADER_ALEXANDER, human=False)
        game = FakeGame(activePlayerId=0, gameTurn=5)
        manager, _ = self.load([alexander], game, mode='opponent', leaderKey='LEADER_ALEXANDER')

        manager.onBeginPlayerTurn([5, 0])

        self.assertEqual(game.setActivePlayerCalls, [(0, False), (0, False)])
        self.assertEqual(game.getActivePlayer(), 0)

    def test_active_player_is_restored_even_if_export_raises(self):
        alexander = FakePlayer(LEADER_ALEXANDER, human=False)
        game = FakeGame(activePlayerId=0, gameTurn=5)
        manager, stateWriter = self.load([alexander], game, mode='opponent', leaderKey='LEADER_ALEXANDER')

        def raisingBuildState(gameTurn, playerId, trigger):
            raise RuntimeError("simulated export failure")
        stateWriter.buildState = raisingBuildState

        manager.onBeginPlayerTurn([5, 0])  # must not raise - "never crash the game"

        self.assertEqual(game.getActivePlayer(), 0)


if __name__ == "__main__":
    unittest.main()
