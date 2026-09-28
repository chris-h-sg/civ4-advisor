"""Tests for devtools/game_hooks/DevHooks.py, run outside Civ IV.

Runs under Python 3 with the game API and the Python-2 execfile builtin
shimmed, loading the file the way the mod's _runDevHook does (execfile with
DEV_HOOKS_DIR bound). Checks behaviour only; Python 2.4 syntax still needs
review by eye.

The property that matters most: the control file is one-shot. A control file
left in place would start autoplay on the next load of ANY save, including
someone's real game - which is how the first spike behaved.

    python devtools/tests/test_dev_hooks.py
"""
import os
import sys
import tempfile
import types
import unittest

HOOKS_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "game_hooks", "DevHooks.py")


def _execfile(path, globalsDict):
    with open(path) as f:
        exec(compile(f.read(), path, "exec"), globalsDict)


class FakeGame(object):
    def __init__(self):
        self.autoPlay = 0
        self.turn = 0

    def getGameTurn(self):
        return self.turn

    def getPlayerScore(self, i):
        return 100 + i

    def setAIAutoPlay(self, turns):
        self.autoPlay = turns

    def getAIAutoPlay(self):
        return self.autoPlay


class FakePlayer(object):
    def __init__(self, leader, team, human=False):
        self.leader, self.team, self.human = leader, team, human
        self.alive = True
        self.killed = []

    def isAlive(self):
        return self.alive

    def getLeaderType(self):
        return self.leader

    def getTeam(self):
        return self.team

    def isHuman(self):
        return self.human

    def getNumCities(self):
        return 0

    def getNumUnits(self):
        # Like the engine: removal empties the civ, but it stays isAlive()
        # until the end-of-turn check.
        return 0 if "units" in self.killed else 2

    def firstUnit(self, bReverse):
        return (None, 0)

    def killCities(self):
        self.killed.append("cities")

    def killUnits(self):
        self.killed.append("units")


class FakeGc(object):
    """Leader types are indices into LEADERS; getLeaderHeadInfo(i).getType()
    maps back to the key, as the real info classes do."""
    LEADERS = ["LEADER_JOAO", "LEADER_ALEXANDER", "LEADER_BOUDICA", "LEADER_PERICLES"]

    def __init__(self, game, players):
        self.game, self.players = game, players
        self.defines = {"TECH_COST_EXTRA_TEAM_MEMBER_MODIFIER": 50}

    def getDefineINT(self, name):
        return self.defines[name]

    def setDefineINT(self, name, value):
        self.defines[name] = value

    def getGame(self):
        return self.game

    def getMAX_CIV_PLAYERS(self):
        return len(self.players)

    def getPlayer(self, i):
        return self.players[i]

    def getLeaderHeadInfo(self, i):
        return types.SimpleNamespace(getType=lambda: self.LEADERS[i])


class DevHooksTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Mirror the repo layout: <devtools>/game_hooks/ and <devtools>/runs/.
        self.hooksDir = os.path.join(tmp.name, "game_hooks")
        self.runsDir = os.path.join(tmp.name, "runs")
        os.makedirs(self.hooksDir)
        os.makedirs(self.runsDir)
        self.control = os.path.join(self.runsDir, "control.py")
        # The hook keeps per-run state on sys for the life of the game
        # process; each test is a fresh "process".
        self.addCleanup(lambda: sys.__dict__.pop("_civ4AdvisorDevRun", None))

        self.game = FakeGame()
        self.players = [FakePlayer(0, 0, human=True), FakePlayer(1, 1), FakePlayer(2, 2), FakePlayer(3, 3)]
        gc = FakeGc(self.game, self.players)
        ext = types.ModuleType("CvPythonExtensions")
        ext.CyGlobalContext = lambda: gc
        sys.modules["CvPythonExtensions"] = ext
        self.printed = []
        util = types.ModuleType("CvUtil")
        util.pyPrint = self.printed.append
        sys.modules["CvUtil"] = util

    def loadHooks(self):
        ns = {"DEV_HOOKS_DIR": self.hooksDir, "execfile": _execfile}
        _execfile(HOOKS_SRC, ns)
        return ns

    def writeControl(self, text):
        with open(self.control, "w") as f:
            f.write(text)

    def test_no_control_file_does_nothing(self):
        self.loadHooks()["onLoadGame"]()

        self.assertEqual(self.game.autoPlay, 0)

    def test_control_file_starts_autoplay(self):
        self.writeControl("AUTOPLAY_TURNS = 7\n")

        self.loadHooks()["onLoadGame"]()

        self.assertEqual(self.game.autoPlay, 7)

    def test_control_file_is_consumed_so_the_next_load_is_untouched(self):
        self.writeControl("AUTOPLAY_TURNS = 7\n")
        self.loadHooks()["onLoadGame"]()
        self.game.autoPlay = 0

        self.loadHooks()["onLoadGame"]()

        self.assertEqual(self.game.autoPlay, 0)
        self.assertFalse(os.path.exists(self.control))
        self.assertTrue(os.path.exists(os.path.join(self.runsDir, "control.consumed.py")))

    def test_an_earlier_consumed_file_does_not_block_consuming_a_new_one(self):
        # Windows os.rename fails if the target exists.
        with open(os.path.join(self.runsDir, "control.consumed.py"), "w") as f:
            f.write("AUTOPLAY_TURNS = 1\n")
        self.writeControl("AUTOPLAY_TURNS = 3\n")

        self.loadHooks()["onLoadGame"]()

        self.assertEqual(self.game.autoPlay, 3)
        self.assertFalse(os.path.exists(self.control))

    def test_kill_leaders_removes_only_the_named_civ(self):
        self.writeControl("KILL_LEADERS = ['LEADER_PERICLES']\nAUTOPLAY_TURNS = 3\n")

        self.loadHooks()["onLoadGame"]()

        self.assertEqual(self.players[3].killed, ["cities", "units"])
        self.assertEqual([p.killed for p in self.players[:3]], [[], [], []])
        self.assertEqual(self.game.autoPlay, 3)

    def test_scores_are_written_at_load_and_each_round_end(self):
        scores = os.path.join(self.runsDir, "scores.csv")
        self.writeControl("KILL_LEADERS = ['LEADER_PERICLES']\nAUTOPLAY_TURNS = 3\nSCORES_FILE = %r\n" % scores)

        self.loadHooks()["onLoadGame"]()
        self.loadHooks()["onEndGameTurn"](0)   # a fresh load of the file, as the mod does

        with open(scores) as f:
            rows = f.read().splitlines()
        # Header, then Alexander and Boudica at turn 0 and turn 1. Not the human,
        # and not Pericles, who was removed but still reads isAlive().
        self.assertEqual(rows, ["turn,player,leader,score",
                                "0,1,LEADER_ALEXANDER,101", "0,2,LEADER_BOUDICA,102",
                                "1,1,LEADER_ALEXANDER,101", "1,2,LEADER_BOUDICA,102"])

    def test_defines_are_overridden_and_logged(self):
        gc = sys.modules["CvPythonExtensions"].CyGlobalContext()
        self.writeControl("DEFINES = {'TECH_COST_EXTRA_TEAM_MEMBER_MODIFIER': 0}\n")

        self.loadHooks()["onLoadGame"]()

        self.assertEqual(gc.defines["TECH_COST_EXTRA_TEAM_MEMBER_MODIFIER"], 0)
        self.assertIn("civ4-advisor devtools: define TECH_COST_EXTRA_TEAM_MEMBER_MODIFIER 50 -> 0",
                      self.printed)

    def test_round_end_writes_nothing_without_a_trial(self):
        self.loadHooks()["onEndGameTurn"](0)

        self.assertEqual(os.listdir(self.runsDir), [])

    def test_zero_turns_consumes_without_starting_autoplay(self):
        self.writeControl("AUTOPLAY_TURNS = 0\n")

        self.loadHooks()["onLoadGame"]()

        self.assertEqual(self.game.autoPlay, 0)
        self.assertFalse(os.path.exists(self.control))


if __name__ == "__main__":
    unittest.main()
