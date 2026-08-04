"""Tests for harness/rules.py.

These must not require a Civ IV install, so the XML is mocked the way
mod/tests/ mocks the Cy* API: small synthetic files with the same structure as
the real ones, written to tmp_path. Only `test_cost_matches_every_sample_turn`
and the tests marked `needs_install` touch anything real, and both skip cleanly
when what they need is absent.

The synthetic tech tree deliberately mirrors the shape that broke the first
implementation: an or-list with two branches that share a grandparent.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

import rules  # noqa: E402


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
SAMPLES = os.path.join(REPO_ROOT, "samples")


# ---------------------------------------------------------------------------
# Synthetic XML
# ---------------------------------------------------------------------------


def _tech(type_key, cost, or_reqs=(), and_reqs=(), flags=(), values=()):
    return """
    <TechInfo>
      <Type>%s</Type>
      <iCost>%d</iCost>
      <Era>ERA_ANCIENT</Era>
      <bTrade>1</bTrade>
      <bGoodyTech>1</bGoodyTech>
%s
%s
      <OrPreReqs>%s</OrPreReqs>
      <AndPreReqs>%s</AndPreReqs>
    </TechInfo>""" % (
        type_key,
        cost,
        "\n".join("      <%s>1</%s>" % (f, f) for f in flags),
        "\n".join("      <%s>%d</%s>" % (k, v, k) for k, v in values),
        "".join("<PrereqTech>%s</PrereqTech>" % t for t in or_reqs),
        "".join("<PrereqTech>%s</PrereqTech>" % t for t in and_reqs),
    )


def _unit(type_key, prereq, unit_class="UNITCLASS_X", strength=1, moves=1,
          cost=10, combat="UNITCOMBAT_MELEE", bonuses=(), mods=(),
          first_strikes=0, city_defense=0, filler_lines=0):
    # `filler_lines` pushes PrereqTech far from <Type>, reproducing the real
    # file's ~90-line gap that defeats `grep -A6`.
    filler = "\n".join("      <iFiller%d>0</iFiller%d>" % (i, i)
                       for i in range(filler_lines))
    return """
    <UnitInfo>
      <Type>%s</Type>
      <Class>%s</Class>
      <Combat>%s</Combat>
%s
      <UnitCombatMods>%s</UnitCombatMods>
      <PrereqTech>%s</PrereqTech>
      <BonusType>NONE</BonusType>
      <PrereqBonuses>%s</PrereqBonuses>
      <iCost>%d</iCost>
      <iMoves>%d</iMoves>
      <iCombat>%d</iCombat>
      <iFirstStrikes>%d</iFirstStrikes>
      <iCityDefense>%d</iCityDefense>
      <iWithdrawalProb>0</iWithdrawalProb>
      <bNoDefensiveBonus>0</bNoDefensiveBonus>
      <TerrainImpassables/>
      <FeatureImpassables/>
    </UnitInfo>""" % (
        type_key, unit_class, combat, filler,
        "".join(
            "<UnitCombatMod><UnitCombatType>%s</UnitCombatType>"
            "<iUnitCombatMod>%d</iUnitCombatMod></UnitCombatMod>" % m
            for m in mods
        ),
        prereq,
        "".join("<BonusType>%s</BonusType>" % b for b in bonuses),
        cost, moves, strength, first_strikes, city_defense,
    )


def _handicap(type_key, research=100, **fields):
    body = "".join("<%s>%d</%s>" % (k, v, k) for k, v in sorted(fields.items()))
    return """
    <HandicapInfo>
      <Type>%s</Type>
      <iResearchPercent>%d</iResearchPercent>
      %s
    </HandicapInfo>""" % (type_key, research, body)


@pytest.fixture
def xml_root(tmp_path):
    """A minimal but structurally faithful two-tree install.

    Structured like the real one: a BTS tree that overrides most files, and a
    vanilla tree holding the ones BTS never changed. CIV4BonusInfos.xml is
    placed ONLY in vanilla, which is where it really lives - an agent trial
    followed the old BTS-only advice, found nothing, and fell back to grepping.
    """
    root = tmp_path / "install" / "Beyond the Sword" / "Assets" / "XML"
    for sub in ("Technologies", "Units", "GameInfo", "Buildings", "Terrain"):
        (root / sub).mkdir(parents=True)

    vanilla = tmp_path / "install" / "Assets" / "XML"
    for sub in ("Technologies", "Units", "GameInfo", "Terrain"):
        (vanilla / sub).mkdir(parents=True)

    # Vanilla-only: resources, carrying the TechReveal that decides whether a
    # resource prerequisite is even checkable yet.
    bonuses = "<Civ4BonusInfos><BonusInfos>%s</BonusInfos></Civ4BonusInfos>" % "".join([
        """<BonusInfo><Type>BONUS_HIDDEN</Type>
            <TechReveal>TECH_SIMPLE</TechReveal>
            <TechCityTrade>TECH_ROOT_A</TechCityTrade></BonusInfo>""",
        """<BonusInfo><Type>BONUS_PLAIN</Type>
            <TechReveal>NONE</TechReveal>
            <TechCityTrade>TECH_ROOT_A</TechCityTrade></BonusInfo>""",
    ])
    (vanilla / "Terrain" / "CIV4BonusInfos.xml").write_text(bonuses, encoding="latin-1")

    # A file present in BOTH trees, to prove BTS wins.
    for tree, marker in ((root, "BTS"), (vanilla, "VANILLA")):
        (tree / "GameInfo" / "CIV4CivicInfos.xml").write_text(
            "<Civ4CivicInfos><CivicInfos>"
            "<CivicInfo><Type>CIVIC_%s_ONLY</Type>"
            "<TechPrereq>TECH_SIMPLE</TechPrereq></CivicInfo>"
            "</CivicInfos></Civ4CivicInfos>" % marker,
            encoding="latin-1",
        )

    builds = "<Civ4BuildInfos><BuildInfos>%s</BuildInfos></Civ4BuildInfos>" % """
        <BuildInfo>
          <Type>BUILD_TESTMINE</Type>
          <PrereqTech>TECH_ROOT_A</PrereqTech>
          <ImprovementType>IMPROVEMENT_TESTMINE</ImprovementType>
          <FeatureStructs>
            <FeatureStruct>
              <FeatureType>FEATURE_FOREST</FeatureType>
              <PrereqTech>TECH_SIMPLE</PrereqTech>
              <iProduction>30</iProduction>
              <bRemove>1</bRemove>
            </FeatureStruct>
          </FeatureStructs>
        </BuildInfo>"""
    (root / "Units" / "CIV4BuildInfos.xml").write_text(builds, encoding="latin-1")

    buildings = "<Civ4BuildingInfos><BuildingInfos>%s</BuildingInfos></Civ4BuildingInfos>" % "".join([
        # Ordinary building: nested free experience, a positional commerce
        # modifier, and a tech prereq.
        """<BuildingInfo>
             <Type>BUILDING_TESTHOUSE</Type>
             <PrereqTech>TECH_SIMPLE</PrereqTech>
             <ObsoleteTech>NONE</ObsoleteTech>
             <Bonus>NONE</Bonus>
             <PrereqBonuses/>
             <iCost>90</iCost>
             <iHealth>2</iHealth>
             <DomainFreeExperiences>
               <DomainFreeExperience>
                 <DomainType>DOMAIN_LAND</DomainType>
                 <iExperience>3</iExperience>
               </DomainFreeExperience>
             </DomainFreeExperiences>
             <CommerceModifiers>
               <iCommerce>0</iCommerce>
               <iCommerce>25</iCommerce>
             </CommerceModifiers>
           </BuildingInfo>""",
        # World wonder: iMaxGlobalInstances 1 on its class.
        """<BuildingInfo>
             <Type>BUILDING_TESTWONDER</Type>
             <Strategy>TXT_KEY_BUILDING_TESTWONDER_STRATEGY</Strategy>
             <PrereqTech>TECH_ROOT_A</PrereqTech>
             <ObsoleteTech>NONE</ObsoleteTech>
             <Bonus>NONE</Bonus>
             <PrereqBonuses/>
             <iCost>500</iCost>
             <iGreatPeopleRateChange>2</iGreatPeopleRateChange>
             <bTeamShare>1</bTeamShare>
             <ObsoleteSafeCommerceChanges>
               <iCommerce>0</iCommerce>
               <iCommerce>0</iCommerce>
               <iCommerce>6</iCommerce>
             </ObsoleteSafeCommerceChanges>
           </BuildingInfo>""",
        # National wonder, and a coastal-gated building.
        """<BuildingInfo>
             <Type>BUILDING_TESTNATIONAL</Type>
             <PrereqTech>NONE</PrereqTech>
             <ObsoleteTech>TECH_ROOT_B</ObsoleteTech>
             <Bonus>NONE</Bonus>
             <PrereqBonuses/>
             <iCost>100</iCost>
             <bWater>1</bWater>
           </BuildingInfo>""",
        # A unique replacement: no class lists it as DefaultBuilding.
        """<BuildingInfo>
             <Type>BUILDING_TESTUNIQUE</Type>
             <PrereqTech>TECH_SIMPLE</PrereqTech>
             <ObsoleteTech>NONE</ObsoleteTech>
             <Bonus>NONE</Bonus>
             <PrereqBonuses/>
             <iCost>90</iCost>
           </BuildingInfo>""",
    ])
    (root / "Buildings" / "CIV4BuildingInfos.xml").write_text(
        buildings, encoding="latin-1")

    classes = "<Civ4BuildingClassInfos><BuildingClassInfos>%s</BuildingClassInfos></Civ4BuildingClassInfos>" % "".join([
        """<BuildingClassInfo><Type>BUILDINGCLASS_TESTHOUSE</Type>
             <iMaxGlobalInstances>-1</iMaxGlobalInstances>
             <iMaxTeamInstances>-1</iMaxTeamInstances>
             <iMaxPlayerInstances>-1</iMaxPlayerInstances>
             <DefaultBuilding>BUILDING_TESTHOUSE</DefaultBuilding>
           </BuildingClassInfo>""",
        """<BuildingClassInfo><Type>BUILDINGCLASS_TESTWONDER</Type>
             <iMaxGlobalInstances>1</iMaxGlobalInstances>
             <iMaxTeamInstances>-1</iMaxTeamInstances>
             <iMaxPlayerInstances>-1</iMaxPlayerInstances>
             <DefaultBuilding>BUILDING_TESTWONDER</DefaultBuilding>
           </BuildingClassInfo>""",
        """<BuildingClassInfo><Type>BUILDINGCLASS_TESTNATIONAL</Type>
             <iMaxGlobalInstances>-1</iMaxGlobalInstances>
             <iMaxTeamInstances>-1</iMaxTeamInstances>
             <iMaxPlayerInstances>1</iMaxPlayerInstances>
             <DefaultBuilding>BUILDING_TESTNATIONAL</DefaultBuilding>
           </BuildingClassInfo>""",
    ])
    (root / "Buildings" / "CIV4BuildingClassInfos.xml").write_text(
        classes, encoding="latin-1")

    # The game's own English strategy blurbs. Vanilla-only, like the real
    # install, and carrying both COLOR_ markup (strip) and a keyboard key
    # name (keep).
    strategy = ("<Civ4GameText><TEXT>"
                "<Tag>TXT_KEY_BUILDING_TESTWONDER_STRATEGY</Tag>"
                "<English>The [COLOR_BUILDING_TEXT]Test Wonder[COLOR_REVERT] "
                "unlocks every [COLOR_HIGHLIGHT_TEXT]Government[COLOR_REVERT] "
                "civic.</English>"
                "<French>Le Test.</French>"
                "</TEXT><TEXT>"
                "<Tag>TXT_KEY_HOTKEY_STRATEGY</Tag>"
                "<English>Press [CTRL] and [F12] together.</English>"
                "</TEXT></Civ4GameText>")
    (vanilla / "Text").mkdir(parents=True, exist_ok=True)
    (vanilla / "Text" / "CIV4GameText_Strategy.xml").write_text(
        strategy, encoding="latin-1")

    # The files that define positional array order. Index 1 is research and
    # index 2 culture, matching the real game.
    (root / "GameInfo" / "CIV4CommerceInfo.xml").write_text(
        "<Civ4CommerceInfo><CommerceInfos>"
        "<CommerceInfo><Type>COMMERCE_GOLD</Type></CommerceInfo>"
        "<CommerceInfo><Type>COMMERCE_RESEARCH</Type></CommerceInfo>"
        "<CommerceInfo><Type>COMMERCE_CULTURE</Type></CommerceInfo>"
        "<CommerceInfo><Type>COMMERCE_ESPIONAGE</Type></CommerceInfo>"
        "</CommerceInfos></Civ4CommerceInfo>", encoding="latin-1")
    (vanilla / "Terrain" / "CIV4YieldInfos.xml").write_text(
        "<Civ4YieldInfos><YieldInfos>"
        "<YieldInfo><Type>YIELD_FOOD</Type></YieldInfo>"
        "<YieldInfo><Type>YIELD_PRODUCTION</Type></YieldInfo>"
        "<YieldInfo><Type>YIELD_COMMERCE</Type></YieldInfo>"
        "</YieldInfos></Civ4YieldInfos>", encoding="latin-1")

    religions = ("<Civ4ReligionInfo><ReligionInfos>"
                 "<ReligionInfo><Type>RELIGION_TESTFAITH</Type>"
                 "<TechPrereq>TECH_LEFT</TechPrereq>"
                 "</ReligionInfo></ReligionInfos></Civ4ReligionInfo>")
    (root / "GameInfo" / "CIV4ReligionInfo.xml").write_text(
        religions, encoding="latin-1")

    # ROOT_A and ROOT_B are tech-tree roots. TARGET has two or-branches that
    # both lead back to ROOT_A - the shared-grandparent shape that broke the
    # first closure implementation.
    techs = "<Civ4TechInfos><TechInfos>%s</TechInfos></Civ4TechInfos>" % "".join([
        _tech("TECH_ROOT_A", 100),
        _tech("TECH_ROOT_B", 200),
        _tech("TECH_LEFT", 300, or_reqs=["TECH_ROOT_A"]),
        _tech("TECH_RIGHT", 400, and_reqs=["TECH_ROOT_A", "TECH_ROOT_B"]),
        _tech("TECH_TARGET", 500, or_reqs=["TECH_LEFT", "TECH_RIGHT"]),
        _tech("TECH_SIMPLE", 60, or_reqs=["TECH_ROOT_A"],
              flags=["bBridgeBuilding"], values=[("iWorkerSpeedModifier", 25)]),
    ])
    (root / "Technologies" / "CIV4TechInfos.xml").write_text(techs, encoding="latin-1")

    units = "<Civ4UnitInfos><UnitInfos>%s</UnitInfos></Civ4UnitInfos>" % "".join([
        _unit("UNIT_TESTER", "TECH_SIMPLE", strength=5, moves=1, cost=35,
              bonuses=["BONUS_COPPER", "BONUS_IRON", "NONE", "NONE"],
              mods=[("UNITCOMBAT_MELEE", 50)], filler_lines=90),
        _unit("UNIT_UNIQUE", "TECH_SIMPLE", unit_class="UNITCLASS_X"),
        _unit("UNIT_OTHER_CLASS", "TECH_SIMPLE", unit_class="UNITCLASS_Y"),
        _unit("UNIT_ELSEWHERE", "TECH_ROOT_B", unit_class="UNITCLASS_Z"),
        _unit("UNIT_DEFENDER", "TECH_ROOT_A", first_strikes=1, city_defense=50),
    ])
    (root / "Units" / "CIV4UnitInfos.xml").write_text(units, encoding="latin-1")

    handicaps = "<Civ4HandicapInfos><HandicapInfos>%s</HandicapInfos></Civ4HandicapInfos>" % "".join([
        _handicap("HANDICAP_EASY", research=75, iAnimalAttackProb=85,
                  iAnimalBonus=-40, iFreeWinsVsBarbs=2,
                  iBarbarianCreationTurnsElapsed=35),
        _handicap("HANDICAP_HARD", research=120, iAnimalAttackProb=90,
                  iAnimalBonus=-10, iFreeWinsVsBarbs=0,
                  iBarbarianCreationTurnsElapsed=20),
    ])
    (root / "GameInfo" / "CIV4HandicapInfo.xml").write_text(handicaps, encoding="latin-1")

    speeds = ("<Civ4GameSpeedInfo><GameSpeedInfos>"
              "<GameSpeedInfo><Type>GAMESPEED_NORMAL</Type>"
              "<iResearchPercent>100</iResearchPercent>"
              "<iTrainPercent>100</iTrainPercent></GameSpeedInfo>"
              "<GameSpeedInfo><Type>GAMESPEED_EPIC</Type>"
              "<iResearchPercent>150</iResearchPercent>"
              "<iTrainPercent>150</iTrainPercent></GameSpeedInfo>"
              "</GameSpeedInfos></Civ4GameSpeedInfo>")
    (root / "GameInfo" / "CIV4GameSpeedInfo.xml").write_text(speeds, encoding="latin-1")

    worlds = ("<Civ4WorldInfo><WorldInfos>"
              "<WorldInfo><Type>WORLDSIZE_DUEL</Type>"
              "<iResearchPercent>100</iResearchPercent></WorldInfo>"
              "<WorldInfo><Type>WORLDSIZE_STANDARD</Type>"
              "<iResearchPercent>130</iResearchPercent></WorldInfo>"
              "</WorldInfos></Civ4WorldInfo>")
    (root / "GameInfo" / "CIV4WorldInfo.xml").write_text(worlds, encoding="latin-1")

    return (str(root), str(vanilla))


@pytest.fixture
def config(tmp_path, xml_root):
    """A config.local.json pointing at the synthetic install."""
    path = tmp_path / "config.local.json"
    path.write_text(
        json.dumps({"civ4_install_path": str(tmp_path / "install")}),
        encoding="utf-8",
    )
    return str(path)


def make_state(tmp_path, known=(), handicap="HANDICAP_HARD",
               world="WORLDSIZE_STANDARD", speed="GAMESPEED_NORMAL", turn=34,
               rate=13, tiles=(), research=None):
    state = {
        "game": {"gameTurn": turn, "handicap": handicap, "worldSize": world,
                 "gameSpeed": speed},
        "player": {"leader": "LEADER_TEST", "knownTechs": list(known),
                   "beakersPerTurn": rate,
                   "research": research or {}},
        "map": {"tiles": list(tiles)},
    }
    path = tmp_path / ("turn_%04d.json" % turn)
    path.write_text(json.dumps(state), encoding="utf-8")
    return str(path), state


def build_rules(xml_root, state):
    return rules.Rules(xml_root, state["game"])


# ---------------------------------------------------------------------------
# Path resolution - the trap that motivated the tool
# ---------------------------------------------------------------------------


def test_resolver_rejects_a_vanilla_install_path(tmp_path):
    """A path without the BTS segment must fail rather than silently work.

    The install holds ~18 copies of every file and a naive search returns the
    vanilla one first. Every copy parses cleanly, so the wrong pick produces
    confident wrong answers - which is why this is an assert, not a preference.
    """
    vanilla = tmp_path / "install" / "Assets" / "XML"
    (vanilla / "Technologies").mkdir(parents=True)
    config = tmp_path / "config.local.json"
    config.write_text(json.dumps(
        {"civ4_install_path": str(tmp_path / "install" / "Assets" / "XML")}
    ), encoding="utf-8")

    with pytest.raises(rules.RulesError) as excinfo:
        rules.resolve_xml_root(str(config))
    assert "Beyond the Sword" in str(excinfo.value)


def test_missing_config_is_fatal_not_defaulted(tmp_path):
    with pytest.raises(rules.RulesError) as excinfo:
        rules.resolve_xml_root(str(tmp_path / "nope.json"))
    assert "config.local.json" in str(excinfo.value)


def test_resolved_root_contains_the_bts_segment(config, xml_root):
    bts, _vanilla = rules.resolve_xml_root(config)
    assert rules.BTS_XML_ROOT in bts


def test_bts_wins_when_a_file_exists_in_both_trees(config):
    """The engine loads the expansion's copy when there is one."""
    roots = rules.resolve_xml_root(config)
    text, _path, tree = rules.read_xml(roots, rules.CIVIC_FILE)
    assert tree == "BTS"
    assert "CIVIC_BTS_ONLY" in text
    assert "CIVIC_VANILLA_ONLY" not in text


def test_vanilla_is_used_when_bts_does_not_ship_the_file(config):
    """BTS only ships files it CHANGES. CIV4BonusInfos.xml - which holds every
    resource's TechReveal - exists only in the base install, so a BTS-only
    resolver cannot reach it. A trial hit exactly this and fell back to grep."""
    roots = rules.resolve_xml_root(config)
    text, path, tree = rules.read_xml(roots, rules.BONUS_FILE)
    assert tree == "vanilla"
    assert "BONUS_HIDDEN" in text
    assert rules.BTS_XML_ROOT not in path


def test_a_file_in_neither_tree_is_reported_not_guessed(config):
    roots = rules.resolve_xml_root(config)
    with pytest.raises(rules.RulesError) as excinfo:
        rules.read_xml(roots, os.path.join("GameInfo", "CIV4Nonexistent.xml"))
    assert "not found in either tree" in str(excinfo.value)


def test_an_optional_missing_file_degrades_instead_of_raising(config):
    roots = rules.resolve_xml_root(config)
    text, path, tree = rules.read_xml(
        roots, os.path.join("GameInfo", "CIV4Nonexistent.xml"), required=False)
    assert (text, path, tree) == (None, None, None)


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_cost_truncates_at_each_step_not_once_at_the_end():
    """The engine applies each modifier in sequence, truncating each time.

    Chosen so the two orderings disagree: 100 x 1.15 x 1.15 is 132.25 in one
    float pass (-> 132) but 115 -> 132 stepwise. A value where they agree would
    let a wrong implementation pass.
    """
    # 100 -> 115 -> 132 stepwise; one float pass gives 132.25 -> 132 too, so
    # that pair agrees. This one does not: 10 -> 11 -> 12 stepwise, against
    # 10 x 1.15 x 1.15 = 13.2 -> 13 in a single pass.
    assert rules.research_cost(10, 115, 115, 100) == 12
    assert int(10 * 1.15 * 1.15) == 13
    assert rules.research_cost(100, 115, 115, 100) == 132


def test_cost_applies_all_three_multipliers(xml_root, tmp_path):
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD",
                          world="WORLDSIZE_STANDARD", speed="GAMESPEED_NORMAL")
    r = build_rules(xml_root, state)
    # base 100 x speed 100% x world 130% x handicap 120%
    assert r.cost("TECH_ROOT_A") == 156
    assert (r.speed_pct, r.world_pct, r.handicap_pct) == (100, 130, 120)


def test_cost_changes_with_setup(xml_root, tmp_path):
    _, easy = make_state(tmp_path, handicap="HANDICAP_EASY",
                         world="WORLDSIZE_DUEL", turn=1)
    _, hard = make_state(tmp_path, handicap="HANDICAP_HARD",
                         world="WORLDSIZE_STANDARD", turn=2)
    assert build_rules(xml_root, easy).cost("TECH_ROOT_A") == 75
    assert build_rules(xml_root, hard).cost("TECH_ROOT_A") == 156


def test_unknown_setup_values_fall_back_to_100_percent(xml_root, tmp_path):
    _, state = make_state(tmp_path, handicap="HANDICAP_NEW",
                          world="WORLDSIZE_NEW", speed="GAMESPEED_NEW")
    assert build_rules(xml_root, state).cost("TECH_ROOT_A") == 100


@pytest.mark.parametrize("sample", sorted(
    os.path.basename(p) for p in
    (os.listdir(SAMPLES) if os.path.isdir(SAMPLES) else [])
    if os.path.isdir(os.path.join(SAMPLES, p))
))
def test_cost_matches_every_sample_turn(sample):
    """Cross-check the formula against the engine's own reported cost.

    `player.research.cost` is the engine's team cost with every modifier already
    applied, so any turn where a tech is being researched is a free test of the
    formula. Checking EVERY turn of EVERY sample rather than a handful means a
    future capture on a different speed or world size fails here instead of
    silently disagreeing in use.
    """
    try:
        xml_root = rules.resolve_xml_root()
    except rules.RulesError as exc:
        pytest.skip("no Civ IV install: %s" % exc)

    folder = os.path.join(SAMPLES, sample)
    turns = sorted(f for f in os.listdir(folder) if f.startswith("turn_"))
    if not turns:
        pytest.skip("%s has no turn files" % sample)

    checked = 0
    for name in turns:
        with open(os.path.join(folder, name), "rb") as handle:
            state = json.loads(handle.read().decode("utf-8"))
        research = state.get("player", {}).get("research") or {}
        current, engine_cost = research.get("current"), research.get("cost")
        if not current or not engine_cost:
            continue
        computed = rules.Rules(xml_root, state["game"]).cost(current)
        assert computed == engine_cost, (
            "%s/%s: %s computed %d, engine says %d"
            % (sample, name, current, computed, engine_cost)
        )
        checked += 1

    assert checked, "no turn in %s reported a research cost" % sample


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------


def test_closure_walks_the_whole_dag_not_one_level(xml_root, tmp_path):
    """The bug that shipped in the first draft: the walk stopped one level down.

    TECH_TARGET's real closure is all five other techs. The first version added
    a node then recursed on it, hit the already-seen guard at the top of the
    call, and returned - reporting 2 prerequisites while printing "full walk".
    """
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert rules.closure(r, "TECH_TARGET") == {
        "TECH_LEFT", "TECH_RIGHT", "TECH_ROOT_A", "TECH_ROOT_B",
    }


def test_closure_prunes_known_techs_and_their_parents(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert rules.closure(r, "TECH_LEFT", known={"TECH_ROOT_A"}) == set()
    # TECH_LEFT satisfies TECH_TARGET's or-list, so the TECH_RIGHT branch is
    # not required at all - it is a road not taken, not a prerequisite.
    assert rules.closure(r, "TECH_TARGET", known={"TECH_LEFT"}) == set()
    # With neither branch held, both still count.
    assert rules.closure(r, "TECH_TARGET", known={"TECH_ROOT_A"}) == {
        "TECH_LEFT", "TECH_RIGHT", "TECH_ROOT_B",
    }


def test_closure_counts_a_shared_grandparent_once(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    needed = rules.closure(r, "TECH_TARGET")
    assert sorted(needed).count("TECH_ROOT_A") == 1


def test_closure_of_a_root_is_empty(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert rules.closure(r, "TECH_ROOT_A") == set()


def test_closure_terminates_on_a_cycle(xml_root, tmp_path):
    """No cycle exists in real BTS data, but a recursive walk without a guard
    turns a future data change into a hang rather than a wrong answer."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    r.techs["TECH_ROOT_A"]["or"] = ["TECH_TARGET"]
    assert "TECH_TARGET" in rules.closure(r, "TECH_TARGET")


def test_tree_marks_or_lists_and_hides_known(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    lines, hidden = rules.render_tree(
        r, "TECH_TARGET", known={"TECH_ROOT_A"}, show_known=False, max_depth=None
    )
    text = "\n".join(lines)
    assert "ANY ONE OF:" in text
    # TECH_ROOT_A is not rendered as a node to research, but it IS named as the
    # branch that closed TECH_LEFT's or-list - saying which prerequisite is
    # already met is the point of that line.
    assert "prerequisite met: TECH_ROOT_A" in text
    assert "TECH_ROOT_A  " not in text  # not as a priced tree node
    assert hidden[0] >= 1

    shown, _ = rules.render_tree(
        r, "TECH_TARGET", known={"TECH_ROOT_A"}, show_known=True, max_depth=None
    )
    assert "TECH_ROOT_A" in "\n".join(shown)
    assert "[have]" in "\n".join(shown)


def test_and_children_are_not_labelled_any_one_of(xml_root, tmp_path):
    """TECH_RIGHT needs BOTH roots. Rendering that as a choice would be the
    wrong-and-plausible failure the tool exists to prevent."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    lines, _ = rules.render_tree(r, "TECH_RIGHT", known=set(), show_known=False,
                                 max_depth=None)
    text = "\n".join(lines)
    assert "ANY ONE OF:" not in text
    assert "TECH_ROOT_A" in text and "TECH_ROOT_B" in text


def test_depth_truncates_the_tree_but_not_the_totals(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    lines, _ = rules.render_tree(r, "TECH_TARGET", known=set(), show_known=False,
                                 max_depth=1)
    text = "\n".join(lines)
    assert "--depth 1" in text
    assert "TECH_ROOT_B" not in text
    # The totals still cover the full walk - a partial total is a wrong number.
    assert len(rules.closure(r, "TECH_TARGET")) == 4


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_prereq_tech_is_found_far_from_the_type_tag(xml_root, tmp_path):
    """UNIT_TESTER has 90 filler lines between <Type> and <PrereqTech>, which is
    the real file's shape and precisely what defeats `grep -A6`."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_TESTER"]["prereq_tech"] == "TECH_SIMPLE"


def test_unit_parses_combat_fields_and_drops_none_bonuses(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    unit = build_rules(xml_root, state).units["UNIT_TESTER"]
    assert unit["strength"] == 5
    assert unit["moves"] == 1
    assert unit["cost"] == 35
    assert unit["combat_mods"] == [("UNITCOMBAT_MELEE", 50)]
    # The real PrereqBonuses list is padded with NONE entries.
    assert unit["prereq_bonuses"] == ["BONUS_COPPER", "BONUS_IRON"]


def test_blocks_report_their_line_number(xml_root, tmp_path):
    """The file:line pointer is why this parses with regex rather than
    ElementTree - a bare path still leaves the agent grepping."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_TESTER"]["line"] > 0
    assert r.techs["TECH_TARGET"]["line"] > 0
    assert r.units["UNIT_UNIQUE"]["line"] > r.units["UNIT_TESTER"]["line"]


def test_empty_prereq_containers_parse_as_empty(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.techs["TECH_ROOT_A"]["or"] == []
    assert r.techs["TECH_ROOT_A"]["and"] == []


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def test_unit_view_marks_have_and_need(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    need = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "[NEED]" in need

    state["player"]["knownTechs"] = ["TECH_SIMPLE"]
    have = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "[have]" in have


def test_unit_view_reports_siblings_with_their_class(xml_root, tmp_path):
    """The intel join: seeing a unique unit implies the same tech. Class is
    printed rather than asserting replacement - a hand-grep once put a
    TECH_HUNTING spearman in this list for the Axeman."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "UNIT_UNIQUE" in text
    assert "replaces this one" in text
    assert "UNIT_OTHER_CLASS" in text
    assert "UNIT_ELSEWHERE" not in text


def test_unit_view_states_what_it_omits(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "OMITS" in text
    assert "mod is loaded" in text
    # The SDK caveat: some movement and terrain rules have no XML row at all,
    # so silence about them is not a claim that none exist.
    assert "SDK" in text


def test_tech_view_never_ranks_the_routes(xml_root, tmp_path):
    """The decide-line. Route costs are presentation; sorting them, labelling
    one cheapest, or recommending one is deciding."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_TARGET", state, False, None)

    assert "ROUTE COST" in text
    assert "NOT ranked" in text
    for word in ("cheapest", "recommend", "best route", "should research"):
        assert word not in text.lower()

    # XML order, not cost order.
    assert text.index("via TECH_LEFT") < text.index("via TECH_RIGHT")


def test_tech_view_leads_with_the_actionable_total(xml_root, tmp_path):
    """A trial read "Prerequisites still needed: 62" as the cost of ARCHERY
    when the answer was 155. The number you act on now leads; the component is
    demoted. Same fix as run_history putting the walk before the straight line
    - when a caveat does not stick, change the layout."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_SIMPLE", state, False, None)

    total = text.index("TOTAL TO UNLOCK")
    component = text.index("of which prerequisites")
    assert total < component


def test_tech_view_estimates_turns_and_calls_it_an_extrapolation(xml_root, tmp_path):
    """Three of six trials divided cost by beakersPerTurn by hand, one three
    times in a session. The tool holds both numbers and now divides them - but
    a rate that moves is not a schedule, and the output has to say so."""
    _, state = make_state(tmp_path, rate=10,
                          research={"current": "TECH_ROOT_B", "turnsLeft": 4})
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_SIMPLE", state, False, None)

    # TECH_SIMPLE 60 + TECH_ROOT_A 100 = 160 priced at 156% -> 249 / 10 = 25
    assert "turns at 10 bpt" in text
    assert "+4 to finish TECH_ROOT_B first" in text
    assert "extrapolation" in text
    assert "Not a schedule" in text


def test_turns_estimate_rounds_up_and_handles_a_zero_rate():
    assert rules.turns_estimate(100, 16) == 7   # 6.25 -> 7, not 6
    assert rules.turns_estimate(96, 16) == 6
    assert rules.turns_estimate(100, 0) is None
    assert rules.turns_estimate(100, None) is None


def test_tech_view_does_not_present_a_union_total_as_the_cost(xml_root, tmp_path):
    """You walk one or-branch, so summing both overstates the real cost by the
    whole of the route not taken."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_TARGET", state, False, None)
    assert "would cover ALL 2 routes" in text
    assert "you pay one of" in text
    # The route lines are already all-in, so the union block must not also tell
    # the reader to add the target's own cost - that double-counts it.
    assert "all-in" in text
    assert "Add TECH_TARGET's own" not in text


def test_tech_view_labels_an_and_list_as_all_required(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_RIGHT", state, False, None)
    assert "ALL required" in text


def test_tech_view_reports_a_root_as_having_no_prereqs(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert "tech-tree root" in rules.view_tech(r, "TECH_ROOT_A", state, False, None)


def test_tech_view_resolves_every_category_not_just_units(xml_root, tmp_path):
    """Two trials filled civics, chopping and resource reveals in from memory
    because UNLOCKS printed only units - which the guide explicitly forbids.
    A tech with no unit used to render as if it did nothing at all."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_SIMPLE", state, False, None)

    assert "BUILDING_TESTHOUSE" in text
    assert "CIVIC_BTS_ONLY" in text
    assert "BONUS_HIDDEN" in text          # resources revealed
    assert "FEATURE_FOREST" in text        # nested FeatureStruct prereq
    assert "workers can build roads over rivers" in text   # bBridgeBuilding
    assert "+25% worker speed" in text


def test_nested_feature_prereqs_are_not_credited_to_the_wrong_tech(xml_root, tmp_path):
    """BUILD_TESTMINE gates on TECH_ROOT_A at the top level; removing forest
    inside it gates on TECH_SIMPLE. A flat index over PrereqTech would report
    TECH_SIMPLE as unlocking the whole build, which is wrong."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    simple = r.unlocked_by("TECH_SIMPLE")
    root_a = r.unlocked_by("TECH_ROOT_A")

    assert "BUILD_TESTMINE" in root_a.get("worker actions", [])
    assert "BUILD_TESTMINE" not in simple.get("worker actions", [])
    assert any("FEATURE_FOREST" in line for line in simple.get("feature work", []))


def test_feature_work_collapses_per_feature_not_per_build(xml_root, tmp_path):
    """Every improvement that can sit on forest carries its own identical
    FeatureStruct - on real data that is twelve lines all saying "you can chop
    forest now"."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    work = r.unlocked_by("TECH_SIMPLE")["feature work"]
    assert len(work) == 1
    assert "+30 hammers" in work[0]
    assert "1 worker build" in work[0]


def test_religion_is_presented_as_a_race_not_a_grant(xml_root, tmp_path):
    """The first team to the tech founds it; everyone later gets nothing.
    Listing it under UNLOCKS would state a guarantee the game does not make."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_LEFT", state, False, None)

    assert "IF YOU ARE FIRST" in text
    assert "RELIGION_TESTFAITH" in text
    assert "race, not a reward" in text
    unlocks = text.index("UNLOCKS")
    assert text.index("RELIGION_TESTFAITH") > unlocks


def test_unit_view_flags_a_resource_that_is_not_yet_revealed(xml_root, tmp_path):
    """The fact that changes the conclusion: copper's TechReveal is Bronze
    Working itself, so "you need copper" is not a check the player can perform
    before researching it. Without this the tool reads as "12 turns to Axemen"
    when the truth is "12 turns to find out whether Axemen exist for you"."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    r.units["UNIT_TESTER"]["prereq_bonuses"] = ["BONUS_HIDDEN"]

    text = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "NOT YET REVEALED" in text
    assert "TECH_SIMPLE" in text
    assert "not evidence you have none" in text


def test_unit_view_counts_a_revealed_resource_on_the_map(xml_root, tmp_path):
    _, state = make_state(tmp_path, known=["TECH_SIMPLE"], tiles=[
        {"x": 1, "y": 1, "bonus": "BONUS_HIDDEN"},
        {"x": 2, "y": 2, "bonus": "BONUS_HIDDEN"},
        {"x": 3, "y": 3},
    ])
    r = build_rules(xml_root, state)
    r.units["UNIT_TESTER"]["prereq_bonuses"] = ["BONUS_HIDDEN"]

    text = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "2 visible tiles" in text
    assert "NOT YET REVEALED" not in text


def test_unit_view_reports_a_connected_resource_as_met(xml_root, tmp_path):
    """The case the tool used to disclaim while holding the answer.

    `player.bonuses.counts` is the engine's connected-resource figure - the
    schema calls it "what the trade network actually delivers". Three of four
    agent trials hand-joined map.tiles against player.bonuses to recover it,
    one noting the tool did the negative case well and the positive not at all.
    """
    _, state = make_state(tmp_path, known=["TECH_SIMPLE"], tiles=[
        {"x": 5, "y": 5, "bonus": "BONUS_HIDDEN",
         "improvement": "IMPROVEMENT_TESTMINE", "route": "ROUTE_ROAD",
         "owner": 0},
    ])
    state["player"]["bonuses"] = {"counts": {"BONUS_HIDDEN": 2}}
    r = build_rules(xml_root, state)
    r.units["UNIT_TESTER"]["prereq_bonuses"] = ["BONUS_HIDDEN"]

    text = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "CONNECTED - 2 in your trade network" in text
    assert "you can build it today" in text
    assert "(5,5)" in text


def test_unit_view_names_the_gap_for_a_seen_but_unconnected_resource(
    xml_root, tmp_path
):
    """Visible is not usable. Which of borders / improvement / road is missing
    is the actionable part, so it is named per tile rather than implied."""
    _, state = make_state(tmp_path, known=["TECH_SIMPLE"], tiles=[
        {"x": 7, "y": 7, "bonus": "BONUS_HIDDEN"},
    ])
    state["player"]["bonuses"] = {"counts": {}}
    r = build_rules(xml_root, state)
    r.units["UNIT_TESTER"]["prereq_bonuses"] = ["BONUS_HIDDEN"]

    text = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "NOT connected" in text
    assert "outside your borders" in text
    assert "unimproved" in text
    assert "no road" in text


def test_unit_view_distinguishes_unrevealed_from_absent(xml_root, tmp_path):
    """Two different zeroes: one you cannot see, one you have looked for."""
    _, unrevealed = make_state(tmp_path, turn=1)
    r = build_rules(xml_root, unrevealed)
    r.units["UNIT_TESTER"]["prereq_bonuses"] = ["BONUS_HIDDEN"]
    hidden = rules.view_unit(r, "UNIT_TESTER", unrevealed, False, None)
    assert "NOT YET REVEALED" in hidden
    assert "or that you have some" in hidden

    _, revealed = make_state(tmp_path, known=["TECH_SIMPLE"], turn=2)
    r2 = build_rules(xml_root, revealed)
    r2.units["UNIT_TESTER"]["prereq_bonuses"] = ["BONUS_HIDDEN"]
    seen = rules.view_unit(r2, "UNIT_TESTER", revealed, False, None)
    assert "none on your map yet" in seen
    assert "keep exploring" in seen


def test_hammer_cost_scales_with_game_speed_and_not_handicap(xml_root, tmp_path):
    """CIV4GameSpeedInfo has iTrainPercent; CIV4HandicapInfo has only
    iAITrainPercent - AI-side. So difficulty does NOT change what a unit costs
    the player, unlike research. A trial quoted a raw iCost and said it was not
    confident the number matched the city screen; it was right to doubt."""
    _, normal = make_state(tmp_path, speed="GAMESPEED_NORMAL", turn=1)
    _, epic = make_state(tmp_path, speed="GAMESPEED_EPIC", turn=2)
    assert build_rules(xml_root, normal).train_pct == 100
    assert build_rules(xml_root, epic).train_pct == 150

    text = rules.view_unit(build_rules(xml_root, epic), "UNIT_TESTER",
                           epic, False, None)
    assert "52 hammers" in text          # 35 * 150%
    assert "game speed 150%" in text


def test_near_matches_finds_a_civ_prefixed_unique_unit(xml_root, tmp_path):
    """Unique units are civ-prefixed and inconsistently so, so an agent
    reasoning from the display name guesses UNIT_PRAETORIAN and misses. A trial
    did exactly that and fell back to grepping the XML."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    r.units["UNIT_ROME_PRAETORIAN"] = dict(
        r.units["UNIT_TESTER"], type="UNIT_ROME_PRAETORIAN",
        unit_class="UNITCLASS_SWORDSMAN")

    assert "UNIT_ROME_PRAETORIAN" in rules.near_matches(
        "UNIT_PRAETORIAN", r.units)

    with pytest.raises(rules.RulesError) as excinfo:
        rules.view_unit(r, "UNIT_PRAETORIAN", state, False, None)
    message = str(excinfo.value)
    assert "Did you mean" in message
    assert "UNIT_ROME_PRAETORIAN" in message
    assert "UNITCLASS_SWORDSMAN" in message


def test_unlocks_reports_categories_that_failed_to_load(xml_root, tmp_path):
    """A missing source must read as "not loaded", never as "empty" - the same
    rule the mod follows for unimplemented schema sections."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    del r.sources["buildings"]
    r.buildings = {}

    text = rules.view_tech(r, "TECH_SIMPLE", state, False, None)
    assert "NOT LOADED" in text
    assert "missing from UNLOCKS above, not empty" in text


def test_strategy_text_recovers_an_effect_no_data_field_carries(
    xml_root, tmp_path
):
    """The Pyramids' "access all Government civics" exists in NO building
    field - only in the game's English strategy blurb. Without it the EFFECTS
    list looks complete while missing the wonder's whole point."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTWONDER", state, False, None)

    assert "THE GAME'S OWN SUMMARY" in text
    assert "unlocks every Government civic" in text


def test_strategy_text_strips_colour_codes_but_keeps_key_names(xml_root, tmp_path):
    """[COLOR_*] is formatting; [CTRL] and [F12] are keyboard keys in hotkey
    help and are real content. A blanket bracket strip would mangle them."""
    assert rules.strip_game_markup(
        "The [COLOR_BUILDING_TEXT]Pyramids[COLOR_REVERT] rule."
    ) == "The Pyramids rule."
    assert rules.strip_game_markup(
        "Press [CTRL] and [F12] together."
    ) == "Press [CTRL] and [F12] together."


def test_strategy_text_takes_english_only(xml_root, tmp_path):
    """The same block carries French, German, Italian and Spanish siblings."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert "Le Test" not in r.strategy["TXT_KEY_BUILDING_TESTWONDER_STRATEGY"]
    assert "[CTRL]" in r.strategy["TXT_KEY_HOTKEY_STRATEGY"]


def test_a_building_without_strategy_text_says_so(xml_root, tmp_path):
    """Silence about the gap is the failure this block exists to prevent."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTHOUSE", state, False, None)

    assert "THE GAME'S OWN SUMMARY" not in text
    assert "no strategy text to fall back" in text
    assert "CAVEAT - THE EFFECTS LIST IS NOT EXHAUSTIVE" in text


def test_building_view_distinguishes_wonders_from_ordinary_buildings(
    xml_root, tmp_path
):
    """Wonder status comes from CIV4BuildingClassInfos, not the building block,
    and it changes the decision more than any effect: "50 hammers, build
    everywhere" and "500 hammers, one per world" are different objects."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    ordinary = rules.view_building(r, "BUILDING_TESTHOUSE", state, False, None)
    assert "ordinary building" in ordinary
    assert "WORLD WONDER" not in ordinary

    wonder = rules.view_building(r, "BUILDING_TESTWONDER", state, False, None)
    assert "WORLD WONDER - one in the entire world" in wonder

    national = rules.view_building(r, "BUILDING_TESTNATIONAL", state, False, None)
    assert "NATIONAL WONDER - one per player" in national


def test_world_wonder_states_the_race_it_cannot_check(xml_root, tmp_path):
    """Same class of fact as founding a religion: the export cannot see rival
    production, so silence is not evidence nobody else is building it."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTWONDER", state, False, None)

    assert "cannot see" in text
    assert "race you cannot check" in text
    assert "hammers to gold" in text

    ordinary = rules.view_building(r, "BUILDING_TESTHOUSE", state, False, None)
    assert "race you cannot check" not in ordinary


def test_building_view_always_warns_that_effects_are_incomplete(xml_root, tmp_path):
    """The Pyramid's any-civic effect has NO field in CIV4BuildingInfos.xml -
    it is SDK-implemented. A complete-looking EFFECTS list would invite exactly
    the wrong conclusion, the same authoritative-with-a-hole failure that made
    the units-only UNLOCKS block actively harmful."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTWONDER", state, False, None)

    assert "CAVEAT - THE EFFECTS LIST IS NOT EXHAUSTIVE" in text
    assert "NOT evidence the" in text
    assert "Civilopedia" in text


def test_building_effects_translate_positional_commerce_arrays(xml_root, tmp_path):
    """A Library's <iCommerce>0</iCommerce><iCommerce>25</iCommerce> means +25%
    SCIENCE only because index 1 is COMMERCE_RESEARCH - an order that lives in
    CIV4CommerceInfo.xml, not in the block. Guessing it is a silent
    mistranslation; a draft of this tool read a culture value as gold."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    assert r.commerce_order[1] == "COMMERCE_RESEARCH"
    assert r.commerce_order[2] == "COMMERCE_CULTURE"

    house = rules.view_building(r, "BUILDING_TESTHOUSE", state, False, None)
    assert "+25% research in this city" in house

    wonder = rules.view_building(r, "BUILDING_TESTWONDER", state, False, None)
    assert "+6 culture per turn" in wonder


def test_building_reads_nested_free_experience(xml_root, tmp_path):
    """<DomainFreeExperiences> is nested the same way build feature prereqs
    are; a flat scan misses it, which is how a trial hand-derived Barracks."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTHOUSE", state, False, None)
    assert "+3 experience to new units built here (DOMAIN_LAND)" in text


def test_building_view_estimates_turns_per_city(xml_root, tmp_path):
    """Early production is wildly uneven - in the baseline run the same
    50-hammer building is 5 turns in one city and 25 in the other."""
    _, state = make_state(tmp_path)
    state["cities"] = [
        {"name": "Fast", "productionPerTurn": 10},
        {"name": "Slow", "productionPerTurn": 2},
        {"name": "Stalled", "productionPerTurn": 0},
    ]
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTHOUSE", state, False, None)

    assert "~9 turns in Fast (10 hpt)" in text
    assert "~45 turns in Slow (2 hpt)" in text
    assert "Stalled cannot build (0 hpt)" in text


def test_building_view_reports_city_placement_requirements(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTNATIONAL", state, False, None)
    assert "must be coastal" in text
    assert "OBSOLETE WITH  TECH_ROOT_B" in text


def test_unresolved_building_class_is_reported_not_guessed(xml_root, tmp_path):
    """A unique replacement is no class's DefaultBuilding, so the back-join
    fails. Silently calling it an ordinary building would be a guess."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTUNIQUE", state, False, None)
    assert "building class not resolved" in text


def test_building_view_suggests_near_matches(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    with pytest.raises(rules.RulesError) as excinfo:
        rules.view_building(r, "BUILDING_TESTHOUS", state, False, None)
    assert "BUILDING_TESTHOUSE" in str(excinfo.value)


def test_cli_runs_a_building_lookup(xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(tmp_path)
    assert rules.main(
        ["building", "BUILDING_TESTWONDER", state_path, "--config", config]) == 0
    assert "WORLD WONDER" in capsys.readouterr().out


def test_a_known_route_removes_the_choice_entirely(xml_root, tmp_path):
    """Superseded the earlier "OPEN NOW" formatting: holding a route does not
    make it a cheap option, it means there is no longer a choice to present.
    The route block is skipped and the single actionable total is printed."""
    _, state = make_state(tmp_path, known=["TECH_LEFT"])
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_TARGET", state, False, None)

    assert "ALREADY MET via TECH_LEFT" in text
    assert "ROUTE COST" not in text
    assert "TECH_RIGHT" in text          # named as an alternative, not needed
    assert "alternative, not needed" in text  # exactly one alternative
    assert "TOTAL TO UNLOCK" in text


def test_a_satisfied_or_list_costs_nothing(xml_root, tmp_path):
    """Masonry needs Mining OR Mysticism. With Mining known the choice is made,
    so Mysticism is not a prerequisite and must not be counted. Unioning every
    branch regardless reported TECH_MYSTICISM as required for the Pyramids
    while the player had held Mining since turn 0."""
    _, state = make_state(tmp_path, known=["TECH_ROOT_A"])
    r = build_rules(xml_root, state)
    known = rules.effective_known(state)

    # TECH_TARGET needs LEFT or RIGHT; neither is held, so both still count.
    assert rules.closure(r, "TECH_TARGET", known)

    # TECH_LEFT needs only ROOT_A, which is held: nothing remains.
    assert rules.closure(r, "TECH_LEFT", known) == set()
    assert rules.or_satisfied(["TECH_ROOT_A", "TECH_ROOT_B"], known)
    assert not rules.or_satisfied(["TECH_ROOT_B"], known)


def test_a_satisfied_or_list_states_the_fact_and_drops_alternatives(
    xml_root, tmp_path
):
    """Once a branch is held there is no choice to present. Showing the
    alternatives priced, with turn estimates, reads as work still to do."""
    _, state = make_state(tmp_path, known=["TECH_ROOT_A"])
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_LEFT", state, False, None)

    assert "ALREADY MET via TECH_ROOT_A" in text
    assert "prerequisite met: TECH_ROOT_A" in text
    assert "ROUTE COST" not in text
    assert "(alternatives, not needed" not in text  # TECH_LEFT has one branch
    # And the single actionable total, not a multi-route caveat.
    assert "TOTAL TO UNLOCK" in text
    assert "would cover ALL" not in text


def test_a_branch_met_only_by_research_in_progress_says_arriving(
    xml_root, tmp_path
):
    """`effective_known` counts the in-progress tech so COSTS are right, but
    calling its branch "met" claims more than is true. Seen on the Aqueduct at
    t40: its only prereq is Writing, four turns from done, and the tree said
    "prerequisite met" three lines under "[RESEARCHING - 4 turns left]"."""
    _, state = make_state(tmp_path, research={"current": "TECH_ROOT_A",
                                              "turnsLeft": 4})
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_LEFT", state, False, None)

    assert "prerequisite arriving: TECH_ROOT_A [RESEARCHING - 4 turns left]" in text
    assert "prerequisite met:" not in text
    assert "SATISFIED ONCE RESEARCH COMPLETES" in text
    # Still costed as satisfied - you will hold it before this matters.
    assert rules.closure(r, "TECH_LEFT", rules.effective_known(state)) == set()


def test_a_branch_actually_held_still_says_met(xml_root, tmp_path):
    _, state = make_state(tmp_path, known=["TECH_ROOT_A"])
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_LEFT", state, False, None)

    assert "prerequisite met: TECH_ROOT_A" in text
    assert "arriving" not in text
    assert "ALREADY MET" in text


def test_an_unsatisfied_or_list_still_compares_routes(xml_root, tmp_path):
    """The satisfied-or rule must not suppress a real choice."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_TARGET", state, False, None)

    assert "ANY ONE suffices" in text
    assert "ROUTE COST" in text
    assert "ALREADY MET" not in text


def test_a_tech_in_progress_is_neither_have_nor_need(xml_root, tmp_path):
    """A tech being researched is not missing. BUILDING_LIBRARY at t40 marked
    TECH_WRITING [NEED] and priced a 638-beaker route while Writing sat at
    138/187 with four turns left - a wrong conclusion, not a formatting slip."""
    _, state = make_state(tmp_path, known=["TECH_ROOT_A"], research={
        "current": "TECH_SIMPLE", "turnsLeft": 4})
    r = build_rules(xml_root, state)
    text = rules.view_tech(r, "TECH_SIMPLE", state, False, None)

    assert "[RESEARCHING - 4 turns left]" in text
    assert "[NEED]" not in text
    # ...and it is not silently claimed as owned either.
    assert "TECH_SIMPLE" in text


def test_a_tech_in_progress_is_not_charged_for_again(xml_root, tmp_path):
    """Costing a downstream tech must treat the in-progress one as acquired -
    you will have it before anything beyond it is reachable."""
    _, state = make_state(tmp_path, research={"current": "TECH_LEFT",
                                              "turnsLeft": 2})
    r = build_rules(xml_root, state)
    known = rules.effective_known(state)

    assert "TECH_LEFT" in known
    assert "TECH_LEFT" not in rules.closure(r, "TECH_TARGET", known)


def test_an_any_one_of_header_is_never_left_dangling(xml_root, tmp_path):
    """When every branch is already known the header used to print with
    nothing beneath it, so the tree appeared to stop mid-branch."""
    _, state = make_state(tmp_path, known=["TECH_LEFT", "TECH_RIGHT"])
    r = build_rules(xml_root, state)
    lines, _ = rules.render_tree(r, "TECH_TARGET", known=set(state["player"]
                                 ["knownTechs"]), show_known=False,
                                 max_depth=None, state=state)
    text = "\n".join(lines)
    if "ANY ONE OF:" in text:
        after = text.split("ANY ONE OF:")[-1].strip()
        assert after, "ANY ONE OF: header with nothing under it"


def test_handicap_view_defaults_to_the_states_own(xml_root, tmp_path):
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD")
    r = build_rules(xml_root, state)
    text = rules.view_handicap(r, None, state)
    assert "HANDICAP_HARD" in text
    assert "iBarbarianCreationTurnsElapsed" in text


def test_handicap_view_flags_a_type_that_is_not_this_games_own(xml_root, tmp_path):
    """Comparing difficulties is legitimate, but the header then shows two and
    the one being reported is not the one in play."""
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD")
    r = build_rules(xml_root, state)

    other = rules.view_handicap(r, "HANDICAP_EASY", state)
    assert "NOT" in other and "HANDICAP_HARD" in other

    own = rules.view_handicap(r, None, state)
    assert "are NOT" not in own


def test_handicap_view_explains_the_negative_bonus_sign(xml_root, tmp_path):
    """-40 reads as "animals are stronger" unless the sign is explained."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_handicap(r, "HANDICAP_EASY", state)
    assert "TO THE ANIMAL" in text
    assert "negative = weaker" in text


def test_handicap_view_carries_no_turn_window_advice(xml_root, tmp_path):
    """The turn-50 scope is prompt guidance and has deliberately never been in
    code - the player may use this tool at any turn."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_handicap(r, "HANDICAP_HARD", state)
    assert "turns 0-50" not in text.lower()
    assert "0-50" not in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_runs_a_unit_lookup(xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(tmp_path)
    code = rules.main(["unit", "UNIT_TESTER", state_path, "--config", config])
    assert code == 0
    assert "UNIT_TESTER" in capsys.readouterr().out


def test_cli_handicap_takes_the_type_from_state_when_omitted(
    xml_root, tmp_path, config, capsys
):
    state_path, _ = make_state(tmp_path, handicap="HANDICAP_HARD")
    assert rules.main(["handicap", state_path, "--config", config]) == 0
    assert "HANDICAP_HARD" in capsys.readouterr().out


def test_cli_handicap_accepts_an_explicit_type(xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(tmp_path, handicap="HANDICAP_HARD")
    assert rules.main(
        ["handicap", "HANDICAP_EASY", state_path, "--config", config]
    ) == 0
    assert "HANDICAP_EASY" in capsys.readouterr().out


def test_cli_exits_2_on_an_unknown_type(xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(tmp_path)
    assert rules.main(["unit", "UNIT_NOPE", state_path, "--config", config]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_exits_2_on_a_missing_state_file(xml_root, tmp_path, config, capsys):
    assert rules.main(
        ["unit", "UNIT_TESTER", str(tmp_path / "nope.json"), "--config", config]
    ) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_names_the_missing_state_file_rather_than_misbinding_it(capsys):
    """State is mandatory: without it every cost is 1.0-4.5x wrong, and an
    optional good path is a path that does not get used.

    The failure mode this guards is subtler than a missing argument. TYPE is an
    optional positional, so argparse fills right-to-left and `rules.py unit
    UNIT_AXEMAN` binds the unit name to `state` - reporting "state file not
    found: UNIT_AXEMAN", an error naming the wrong argument.
    """
    assert rules.main(["unit", "UNIT_AXEMAN"]) == 2
    err = capsys.readouterr().err
    assert "needs both a TYPE and a state file" in err
    assert "UNIT_AXEMAN <state.json>" in err
