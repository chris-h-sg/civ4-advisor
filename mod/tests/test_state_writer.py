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

PLAYER_ID = 3
TEAM_ID = 7


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


class Player(object):
    def __init__(self, research=1):
        self._research = research
        self.researchRateArgs = []
        self.turnsLeftArgs = []

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

    def getCommercePercent(self, c):
        assert c == COMMERCE_RESEARCH
        return 100

    def getCivics(self, i):
        return i  # civic option i -> civic i


class Team(object):
    def isHasTech(self, i):
        return i in (0, 1)  # Agriculture + Mining only


class Gc(object):
    def __init__(self, player):
        self._player = player
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
        return Team()

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
        "reload": lambda m: m,
    }
    with open(SRC) as f:
        exec(compile(f.read(), SRC, "exec"), ns)
    ns["_testGc"] = gc
    ns["_testPlayer"] = player
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
        # units list would be indistinguishable from "player has no units".
        self.assertEqual(sorted(self.parsed.keys()), ["game", "meta", "player"])

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
        self.assertEqual(self.parsed["player"]["research"],
                         {"current": "TECH_MINING", "turnsLeft": 3, "sciencePercent": 100})

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


class NoResearchSelectedTests(unittest.TestCase):
    """Turn 0 of a new game: no tech has been chosen yet."""

    def setUp(self):
        self.mod = loadModule(Player(research=NO_TECH))
        self.parsed = json.loads(
            self.mod["toJson"](self.mod["buildState"](0, PLAYER_ID, "onGameStart"), 2))

    def test_current_and_turns_left_are_null(self):
        self.assertIsNone(self.parsed["player"]["research"]["current"])
        self.assertIsNone(self.parsed["player"]["research"]["turnsLeft"])

    def test_turns_left_is_not_queried_for_no_tech(self):
        self.assertEqual(self.mod["_testPlayer"].turnsLeftArgs, [])

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


class StateFilePathTests(unittest.TestCase):
    def test_returns_none_when_local_config_is_absent(self):
        self.assertIsNone(loadModule()["getStateFilePath"]())

    def test_returns_configured_path(self):
        mod = loadModule(localConfigPath=r"C:\somewhere\current_turn.json")
        self.assertEqual(mod["getStateFilePath"](), r"C:\somewhere\current_turn.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
