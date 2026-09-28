"""Tests for the parts of devtools/run_trial.py that don't need the game:
which turn files belong to a run, log parsing, and decision-log filtering.

    python devtools/tests/test_run_trial.py
"""
import datetime
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_trial  # noqa: E402

LOG = """load_module CvAppInterface
PY:civ4-advisor devtools: roster at load
  0 LEADER_BISMARCK team=0 human=1 cities=0 units=UNIT_SCOUT@1,14
  3 LEADER_PERICLES team=1 human=0 cities=0 units=UNIT_SETTLER@29,12
PY:civ4-advisor devtools: removed player 3 (LEADER_PERICLES)
PY:Player 3's alive status set to: 0
PY:civ4-advisor (opponent spike): AI_chooseTech ordering TECH_AGRICULTURE for player 1, via external process
PY:civ4-advisor (opponent spike): external process gave unusable tech key None, falling through
PY:civ4-advisor: state export FAILED at onBeginPlayerTurn
Traceback (most recent call last):
"""


class TurnFileTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = tmp.name

    def write(self, game, turn, mtime):
        d = os.path.join(self.state, game)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "turn_%04d.json" % turn)
        with open(path, "w") as f:
            f.write("{}")
        os.utime(path, (mtime, mtime))
        return path

    def test_only_files_written_during_the_run_count(self):
        launched = time.time()
        self.write("LEADER_ALEXANDER_1", 7, launched - 3600)
        self.write("LEADER_ALEXANDER_1", 0, launched + 5)
        self.write("LEADER_ALEXANDER_1", 1, launched + 9)

        self.assertEqual(sorted(run_trial.new_turn_files(self.state, launched)), [0, 1])

    def test_the_newest_file_wins_when_two_games_share_a_turn(self):
        launched = time.time()
        self.write("LEADER_ALEXANDER_1", 3, launched + 5)
        newer = self.write("LEADER_ALEXANDER_2", 3, launched + 50)

        self.assertEqual(run_trial.new_turn_files(self.state, launched)[3], newer)


class LogParsingTests(unittest.TestCase):

    def test_parse_log(self):
        parsed = run_trial.parse_log(LOG)

        self.assertEqual(len(parsed["roster"]), 1)
        self.assertIn("LEADER_PERICLES", parsed["roster"][0])
        self.assertEqual(parsed["deaths"], ["Player 3's alive status set to: 0"])
        self.assertEqual(len(parsed["tech_applied"]), 1)
        self.assertEqual(len(parsed["tech_fallbacks"]), 1)
        self.assertEqual(len(parsed["errors"]), 2)   # the FAILED line and the Traceback


class ScoreTests(unittest.TestCase):

    def test_read_scores_and_table(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scores.csv")
            with open(path, "w") as f:
                f.write("turn,player,leader,score\n")
                for t in range(0, 8):
                    f.write("%d,1,LEADER_ALEXANDER,%d\n" % (t, 10 * t))
                    f.write("%d,2,LEADER_BOUDICA,%d\n" % (t, 9 * t))
            scores = run_trial.read_scores(path)
            self.assertEqual(run_trial.last_score_turn(path), 7)

        md = "\n".join(run_trial.score_table(scores))

        self.assertIn("| Turn | Alexander | Boudica |", md)
        self.assertIn("| 5 | 50 | 45 |", md)
        self.assertIn("| 7 | 70 | 63 |", md)          # the last turn is always shown
        self.assertNotIn("| 6 |", md)
        self.assertIn("Alexander leads Boudica by 7 (70 vs 63)", md)

    def test_missing_scores_file(self):
        self.assertEqual(run_trial.last_score_turn("/nonexistent/scores.csv"), -1)
        self.assertIn("No scores recorded.", run_trial.score_table({}))


class TechCallTests(unittest.TestCase):

    def test_only_calls_since_launch_are_kept(self):
        launched = time.time()

        def stamp(offset):
            t = datetime.datetime.fromtimestamp(launched + offset, datetime.timezone.utc)
            return t.strftime("%Y-%m-%dT%H:%M:%SZ")

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"rawAnswer": "OLD", "timestamp": stamp(-600)}) + "\n")
                f.write("not json\n")
                f.write(json.dumps({"rawAnswer": "NEW", "timestamp": stamp(30)}) + "\n")

            calls = run_trial.tech_calls(path, launched)

        self.assertEqual([c["rawAnswer"] for c in calls], ["NEW"])


if __name__ == "__main__":
    unittest.main()
