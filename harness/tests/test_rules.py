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
          first_strikes=0, city_defense=0, filler_lines=0,
          domain="DOMAIN_LAND", religion="NONE", corporation="NONE",
          only_defensive=False, ignore_terrain_cost=False, interception=0,
          collateral_damage=0, collateral_damage_limit=0,
          collateral_damage_max_units=0):
    # `filler_lines` pushes PrereqTech far from <Type>, reproducing the real
    # file's ~90-line gap that defeats `grep -A6`.
    filler = "\n".join("      <iFiller%d>0</iFiller%d>" % (i, i)
                       for i in range(filler_lines))
    return """
    <UnitInfo>
      <Type>%s</Type>
      <Class>%s</Class>
      <Domain>%s</Domain>
      <Combat>%s</Combat>
%s
      <UnitCombatMods>%s</UnitCombatMods>
      <PrereqTech>%s</PrereqTech>
      <PrereqReligion>%s</PrereqReligion>
      <PrereqCorporation>%s</PrereqCorporation>
      <BonusType>NONE</BonusType>
      <PrereqBonuses>%s</PrereqBonuses>
      <iCost>%d</iCost>
      <iMoves>%d</iMoves>
      <iCombat>%d</iCombat>
      <iFirstStrikes>%d</iFirstStrikes>
      <iCityDefense>%d</iCityDefense>
      <iWithdrawalProb>0</iWithdrawalProb>
      <bNoDefensiveBonus>0</bNoDefensiveBonus>
      <bOnlyDefensive>%d</bOnlyDefensive>
      <bIgnoreTerrainCost>%d</bIgnoreTerrainCost>
      <iInterceptionProbability>%d</iInterceptionProbability>
      <iCollateralDamage>%d</iCollateralDamage>
      <iCollateralDamageLimit>%d</iCollateralDamageLimit>
      <iCollateralDamageMaxUnits>%d</iCollateralDamageMaxUnits>
      <TerrainImpassables/>
      <FeatureImpassables/>
    </UnitInfo>""" % (
        type_key, unit_class, domain, combat, filler,
        "".join(
            "<UnitCombatMod><UnitCombatType>%s</UnitCombatType>"
            "<iUnitCombatMod>%d</iUnitCombatMod></UnitCombatMod>" % m
            for m in mods
        ),
        prereq, religion, corporation,
        "".join("<BonusType>%s</BonusType>" % b for b in bonuses),
        cost, moves, strength, first_strikes, city_defense,
        1 if only_defensive else 0, 1 if ignore_terrain_cost else 0,
        interception, collateral_damage, collateral_damage_limit,
        collateral_damage_max_units,
    )


def _promotion(type_key, prereq="NONE", prereq_or=(), tech="NONE",
               combat_percent=0, unit_combats=("UNITCOMBAT_MELEE",),
               feature_defense=(), terrain_double_move=(), is_leader=False,
               city_attack=0, withdrawal=0, collateral_damage_change=0,
               blitz=False, amphib=False, river=False, hills_attack=0,
               intercept_change=0):
    prereq_ors = list(prereq_or) + ["NONE"] * (2 - len(prereq_or))
    return """
    <PromotionInfo>
      <Type>%s</Type>
      <PromotionPrereq>%s</PromotionPrereq>
      <PromotionPrereqOr1>%s</PromotionPrereqOr1>
      <PromotionPrereqOr2>%s</PromotionPrereqOr2>
      <TechPrereq>%s</TechPrereq>
      <StateReligionPrereq>NONE</StateReligionPrereq>
      <bLeader>%d</bLeader>
      <bBlitz>%d</bBlitz>
      <bAmphib>%d</bAmphib>
      <bRiver>%d</bRiver>
      <iCombatPercent>%d</iCombatPercent>
      <iCityAttack>%d</iCityAttack>
      <iHillsAttack>%d</iHillsAttack>
      <iWithdrawalChange>%d</iWithdrawalChange>
      <iCollateralDamageChange>%d</iCollateralDamageChange>
      <iInterceptChange>%d</iInterceptChange>
      <FeatureDefenses>%s</FeatureDefenses>
      <TerrainDoubleMoves>%s</TerrainDoubleMoves>
      <UnitCombats>%s</UnitCombats>
    </PromotionInfo>""" % (
        type_key, prereq, prereq_ors[0], prereq_ors[1], tech,
        1 if is_leader else 0, 1 if blitz else 0, 1 if amphib else 0,
        1 if river else 0, combat_percent, city_attack, hills_attack,
        withdrawal, collateral_damage_change, intercept_change,
        "".join(
            "<FeatureDefense><FeatureType>%s</FeatureType>"
            "<iFeatureDefense>%d</iFeatureDefense></FeatureDefense>" % fd
            for fd in feature_defense
        ),
        "".join("<TerrainType>%s</TerrainType>" % t for t in terrain_double_move),
        "".join(
            "<UnitCombat><UnitCombatType>%s</UnitCombatType>"
            "<bUnitCombat>1</bUnitCombat></UnitCombat>" % c
            for c in unit_combats
        ),
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
        # An ORDINARY coastal building - TESTNATIONAL is also bWater, but a
        # national wonder short-circuits before the coastal gate is reached, so
        # it cannot exercise it.
        """<BuildingInfo>
             <Type>BUILDING_TESTPORT</Type>
             <PrereqTech>NONE</PrereqTech>
             <ObsoleteTech>NONE</ObsoleteTech>
             <Bonus>NONE</Bonus>
             <PrereqBonuses/>
             <iCost>60</iCost>
             <bWater>1</bWater>
           </BuildingInfo>""",
        # Gated on another building being present in the same city.
        """<BuildingInfo>
             <Type>BUILDING_TESTANNEX</Type>
             <PrereqTech>NONE</PrereqTech>
             <ObsoleteTech>NONE</ObsoleteTech>
             <Bonus>NONE</Bonus>
             <PrereqBonuses/>
             <PrereqBuildingClasses>
               <BuildingClassType>BUILDINGCLASS_TESTHOUSE</BuildingClassType>
             </PrereqBuildingClasses>
             <iCost>70</iCost>
           </BuildingInfo>""",
        # Another civ's unique building.
        """<BuildingInfo>
             <Type>BUILDING_THEIR_UNIQUE</Type>
             <PrereqTech>NONE</PrereqTech>
             <ObsoleteTech>NONE</ObsoleteTech>
             <Bonus>NONE</Bonus>
             <PrereqBonuses/>
             <iCost>90</iCost>
           </BuildingInfo>""",
        # iCost -1: placed by a great person, never produced by a city.
        """<BuildingInfo>
             <Type>BUILDING_TESTACADEMY</Type>
             <PrereqTech>NONE</PrereqTech>
             <ObsoleteTech>NONE</ObsoleteTech>
             <Bonus>NONE</Bonus>
             <PrereqBonuses/>
             <iCost>-1</iCost>
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
        # The gates `city` needs and the single lookups do not.
        _unit("UNIT_BOAT", "TECH_ROOT_A", unit_class="UNITCLASS_BOAT",
              domain="DOMAIN_SEA", cost=30),
        _unit("UNIT_ZEALOT", "TECH_ROOT_A", unit_class="UNITCLASS_ZEALOT",
              religion="RELIGION_TESTFAITH", cost=40),
        # Another civ's unique, replacing a class whose default is buildable.
        _unit("UNIT_THEIR_UNIQUE", "TECH_ROOT_A", unit_class="UNITCLASS_X"),
        # iCost 0: an animal, in the units file and never trained by a city.
        _unit("UNIT_CRITTER", "NONE", unit_class="UNITCLASS_CRITTER", cost=0),
        # The Settler shape: BTS blanks iCost to 0, vanilla holds the real
        # cost. Both trees must be consulted or the unit vanishes from `city`.
        _unit("UNIT_FREEBIE", "NONE", unit_class="UNITCLASS_FREEBIE", cost=0),
        # _promotable_promotions fixtures, one unit per gate it must enforce.
        _unit("UNIT_NO_COMBAT_CLASS", "NONE", combat="NONE"),
        _unit("UNIT_ONLY_DEFENSIVE", "NONE", only_defensive=True),
        _unit("UNIT_ONE_MOVE", "NONE", moves=1),
        _unit("UNIT_CANNOT_BOMBARD", "NONE", collateral_damage=0),
        _unit("UNIT_CAN_BOMBARD", "NONE", collateral_damage=1,
              collateral_damage_limit=50, collateral_damage_max_units=3),
        _unit("UNIT_CANNOT_INTERCEPT", "NONE", interception=0),
        _unit("UNIT_CAN_INTERCEPT", "NONE", interception=25),
    ])
    (root / "Units" / "CIV4UnitInfos.xml").write_text(units, encoding="latin-1")

    # The same file in vanilla, where UNIT_FREEBIE still carries its cost and
    # UNIT_TESTER carries an OLDER one that BTS re-priced - so the fallback has
    # to be zero-only rather than "prefer vanilla".
    vanilla_units = "<Civ4UnitInfos><UnitInfos>%s</UnitInfos></Civ4UnitInfos>" % "".join([
        _unit("UNIT_FREEBIE", "NONE", unit_class="UNITCLASS_FREEBIE", cost=100),
        _unit("UNIT_TESTER", "TECH_SIMPLE", cost=25),
        _unit("UNIT_CRITTER", "NONE", unit_class="UNITCLASS_CRITTER", cost=0),
    ])
    (vanilla / "Units" / "CIV4UnitInfos.xml").write_text(
        vanilla_units, encoding="latin-1")

    promotions = ("<Civ4PromotionInfos><PromotionInfos>%s</PromotionInfos>"
                 "</Civ4PromotionInfos>" % "".join([
        _promotion("PROMOTION_TESTER", combat_percent=10,
                  unit_combats=("UNITCOMBAT_MELEE", "UNITCOMBAT_ARCHER")),
        # An OR-prerequisite chain plus a tech gate, on the same promotion -
        # exercises REQUIRES' promotion/or/tech rendering together.
        _promotion("PROMOTION_ADVANCED", prereq_or=["PROMOTION_TESTER"],
                  tech="TECH_SIMPLE", combat_percent=20),
        # No numeric iCombatPercent-style effect - only the block-shaped
        # feature/terrain fields, which parse_promotions handles separately
        # from the flat _int_tag effects.
        _promotion("PROMOTION_TERRAIN", combat_percent=0,
                  feature_defense=[("FEATURE_FOREST", 25)],
                  terrain_double_move=["TERRAIN_HILL"]),
        # The _promotable_promotions cascade, one promotion per gate.
        _promotion("PROMOTION_LEADER_ONLY", is_leader=True),
        _promotion("PROMOTION_OFFENSIVE", city_attack=10),
        _promotion("PROMOTION_BLITZER", blitz=True),
        _promotion("PROMOTION_BOMBARDIER", collateral_damage_change=25),
        _promotion("PROMOTION_INTERCEPTOR", intercept_change=10),
        # The UNIT_JAPAN_SAMURAI/DRILL1/DRILL2 shape: ARCHER-only, so held
        # only via a free promotion on a MELEE unit; ARCHER_ONLY_CHILD
        # requires it and must inherit the same refusal rather than reading
        # "held, so its child is fine".
        _promotion("PROMOTION_ARCHER_ONLY", unit_combats=("UNITCOMBAT_ARCHER",)),
        _promotion("PROMOTION_ARCHER_ONLY_CHILD", prereq="PROMOTION_ARCHER_ONLY",
                  unit_combats=("UNITCOMBAT_MELEE", "UNITCOMBAT_ARCHER")),
    ]))
    (root / "Units" / "CIV4PromotionInfos.xml").write_text(
        promotions, encoding="latin-1")

    # Two civs: ours replaces nothing, theirs replaces UNITCLASS_X. Without
    # this file every civ's uniques read as available to everyone.
    civs = ("<Civ4CivilizationInfos><CivilizationInfos>"
            "<CivilizationInfo><Type>CIVILIZATION_MINE</Type>"
            "<Units/><Buildings/></CivilizationInfo>"
            "<CivilizationInfo><Type>CIVILIZATION_THEIRS</Type>"
            "<Units><Unit>"
            "<UnitClassType>UNITCLASS_X</UnitClassType>"
            "<UnitType>UNIT_THEIR_UNIQUE</UnitType>"
            "</Unit></Units>"
            "<Buildings><Building>"
            "<BuildingClassType>BUILDINGCLASS_TESTHOUSE</BuildingClassType>"
            "<BuildingType>BUILDING_THEIR_UNIQUE</BuildingType>"
            "</Building></Buildings>"
            "</CivilizationInfo>"
            "</CivilizationInfos></Civ4CivilizationInfos>")
    (root / "Civilizations").mkdir(parents=True, exist_ok=True)
    (root / "Civilizations" / "CIV4CivilizationInfos.xml").write_text(
        civs, encoding="latin-1")

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


def make_city(name="Testville", x=10, y=10, rate=13, coastal=False,
              buildings=(), bonuses=None, population=2, producing=None):
    """A city as the mod exports one, including the increment-5 fields."""
    city = {
        "name": name, "x": x, "y": y, "population": population,
        "productionPerTurn": rate, "coastal": coastal,
        "buildings": list(buildings),
        "bonuses": bonuses or {"strategic": [], "happiness": [], "health": []},
    }
    if producing:
        city["producing"] = producing
    return city


def make_state(tmp_path, known=(), handicap="HANDICAP_HARD",
               world="WORLDSIZE_STANDARD", speed="GAMESPEED_NORMAL", turn=34,
               rate=13, tiles=(), research=None, cities=None, wonders=None,
               civilization=None, units=None):
    state = {
        "meta": {"schemaVersion": 2},
        "game": {"gameTurn": turn, "handicap": handicap, "worldSize": world,
                 "gameSpeed": speed},
        "player": {"leader": "LEADER_TEST", "knownTechs": list(known),
                   "beakersPerTurn": rate,
                   "research": research or {}},
        "map": {"tiles": list(tiles)},
    }
    if civilization:
        state["player"]["civilization"] = civilization
    if cities is not None:
        state["cities"] = list(cities)
    if wonders is not None:
        state["wonders"] = wonders
    if units is not None:
        state["units"] = list(units)
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


def test_promotion_parses_flat_effects_and_unit_combats(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    promotion = build_rules(xml_root, state).promotions["PROMOTION_TESTER"]
    assert promotion["combat_percent"] == 10
    assert promotion["restricted_to_unit_combats"] == [
        "UNITCOMBAT_MELEE", "UNITCOMBAT_ARCHER"]
    assert promotion["prereq"] is None
    assert promotion["prereq_or"] == []
    assert promotion["tech"] is None


def test_promotion_parses_block_shaped_effects(xml_root, tmp_path):
    """FeatureDefenses/TerrainDoubleMoves are (name, value) or plain-name
    lists, not flat int tags like iCombatPercent - a different code path in
    parse_promotions from the _int_tag effects."""
    _, state = make_state(tmp_path)
    promotion = build_rules(xml_root, state).promotions["PROMOTION_TERRAIN"]
    assert promotion["feature_defense"] == [("FEATURE_FOREST", 25)]
    assert promotion["terrain_double_move"] == ["TERRAIN_HILL"]
    assert promotion["combat_percent"] == 0


def test_promotion_view_prints_only_nonzero_effects(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_promotion(r, "PROMOTION_TESTER", state, False, None)
    assert "+10% combat" in text
    # No hills/withdrawal/first-strike lines for a promotion that sets none.
    assert "hills" not in text.lower()


def test_promotion_view_lists_available_unit_combats(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_promotion(r, "PROMOTION_TESTER", state, False, None)
    assert "AVAILABLE TO" in text
    assert "UNITCOMBAT_MELEE" in text
    assert "UNITCOMBAT_ARCHER" in text


def test_promotion_view_renders_or_prereq_and_tech(xml_root, tmp_path):
    """REQUIRES must show both the promotion chain and the tech gate."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_promotion(r, "PROMOTION_ADVANCED", state, False, None)
    assert "PROMOTION_TESTER" in text
    assert "TECH_SIMPLE" in text


def test_promotion_view_renders_block_shaped_effects(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_promotion(r, "PROMOTION_TERRAIN", state, False, None)
    assert "+25% defence in FEATURE_FOREST" in text
    assert "double movement on TERRAIN_HILL" in text


def test_promotion_view_not_found_suggests_near_matches(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    with pytest.raises(rules.RulesError) as error:
        rules.view_promotion(r, "PROMOTION_TEST", state, False, None)
    assert "PROMOTION_TESTER" in str(error.value)


def test_promotion_view_states_what_it_omits(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_promotion(r, "PROMOTION_TESTER", state, False, None)
    assert "OMITS" in text
    assert "mod is loaded" in text


# ---------------------------------------------------------------------------
# _promotable_promotions / view_promotable - "what can this unit take next"
# ---------------------------------------------------------------------------


def test_promotable_excludes_already_held(xml_root, tmp_path):
    _, state = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER", "promotions": ["PROMOTION_TESTER"]}])
    r = build_rules(xml_root, state)
    available, blocked = rules._promotable_promotions(
        r, "UNIT_TESTER", {"PROMOTION_TESTER"}, set())
    assert "PROMOTION_TESTER" not in available
    assert ("PROMOTION_TESTER", "already held") in blocked


def test_promotable_excludes_leader_promotions(xml_root, tmp_path):
    """PROMOTION_LEADER-style Great General field promotions are never
    something a unit acquires through XP - CyUnit::canPromote's bLeader
    argument is only true for a Great General merge, never a normal pick."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    available, blocked = rules._promotable_promotions(
        r, "UNIT_TESTER", set(), set())
    assert "PROMOTION_LEADER_ONLY" not in available
    reasons = dict(blocked)
    assert "Great General" in reasons["PROMOTION_LEADER_ONLY"]


def test_promotable_gates_on_prereq_and_or_prereq(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    available, blocked = rules._promotable_promotions(
        r, "UNIT_TESTER", set(), set())
    assert "PROMOTION_TESTER" in available
    assert "PROMOTION_ADVANCED" not in available  # needs TESTER first

    available, _ = rules._promotable_promotions(
        r, "UNIT_TESTER", {"PROMOTION_TESTER"}, {"TECH_SIMPLE"})
    assert "PROMOTION_ADVANCED" in available


def test_promotable_gates_on_tech(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    available, blocked = rules._promotable_promotions(
        r, "UNIT_TESTER", {"PROMOTION_TESTER"}, set())
    reasons = dict(blocked)
    assert "PROMOTION_ADVANCED" not in available
    assert "TECH_SIMPLE" in reasons["PROMOTION_ADVANCED"]


def test_promotable_gates_on_unit_combat_class(xml_root, tmp_path):
    """PROMOTION_TESTER is offered only to MELEE/ARCHER; UNIT_ELSEWHERE's
    default UNITCOMBAT_MELEE is overridden to something else here."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    r.units["UNIT_ELSEWHERE"] = dict(
        r.units["UNIT_ELSEWHERE"], combat_class="UNITCOMBAT_NAVAL")
    available, blocked = rules._promotable_promotions(
        r, "UNIT_ELSEWHERE", set(), set())
    reasons = dict(blocked)
    assert "PROMOTION_TESTER" not in available
    assert "not offered to" in reasons["PROMOTION_TESTER"]


def test_promotable_a_unit_with_no_combat_class_gets_nothing(xml_root, tmp_path):
    """Combat=NONE (settlers, workers) means CyUnit.getUnitCombatType() is
    NO_UNITCOMBAT, which isPromotionValid refuses outright - checked after
    the prereq/tech/leader gates, so a promotion this unit was already
    ineligible for on other grounds keeps its own more specific reason."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    available, blocked = rules._promotable_promotions(
        r, "UNIT_NO_COMBAT_CLASS", set(), set())
    assert available == []
    reasons = dict(blocked)
    # Ungated by prereq/tech/leader and offered to some combat class - the
    # only thing standing between this unit and it is having no class at all.
    assert reasons["PROMOTION_TESTER"] == "this unit has no combat class"


def test_promotable_child_of_a_free_promotion_the_unit_would_not_qualify_for(
    xml_root, tmp_path
):
    """The UNIT_JAPAN_SAMURAI/DRILL1/DRILL2 shape, reproduced: a MELEE unit
    can hold an ARCHER-only promotion for free (granted at creation, bypasses
    the class check that a normally-earned promotion could never pass), but
    its CHILD is not exempt just because the parent is already held. An
    earlier draft of this cascade checked only "is the prereq held", which
    would have wrongly called PROMOTION_ARCHER_ONLY_CHILD available here."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    # UNIT_TESTER defaults to UNITCOMBAT_MELEE - never eligible for
    # PROMOTION_ARCHER_ONLY on its own merits, only "holding" it as if free.
    available, blocked = rules._promotable_promotions(
        r, "UNIT_TESTER", {"PROMOTION_ARCHER_ONLY"}, set())
    assert "PROMOTION_ARCHER_ONLY_CHILD" not in available
    reasons = dict(blocked)
    assert reasons["PROMOTION_ARCHER_ONLY_CHILD"] == (
        "held via a free promotion this unit would not otherwise qualify for")


def test_promotable_child_of_a_qualifying_prereq_is_available(xml_root, tmp_path):
    """The non-free case still works: an ARCHER unit holding
    PROMOTION_ARCHER_ONLY legitimately (it passes the class check on its own
    merits) makes the child available, same as any ordinary prereq chain."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    r.units["UNIT_ELSEWHERE"] = dict(
        r.units["UNIT_ELSEWHERE"], combat_class="UNITCOMBAT_ARCHER")
    available, _ = rules._promotable_promotions(
        r, "UNIT_ELSEWHERE", {"PROMOTION_ARCHER_ONLY"}, set())
    assert "PROMOTION_ARCHER_ONLY_CHILD" in available


def test_promotable_only_defensive_unit_is_refused_offensive_promotions(
    xml_root, tmp_path
):
    """Verbatim from isPromotionValid:241-252 - ALL seven fields, not a
    subset. An earlier draft of this cascade wrongly assumed three of the
    seven were covered elsewhere and left them out of the check."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    available, blocked = rules._promotable_promotions(
        r, "UNIT_ONLY_DEFENSIVE", set(), set())
    reasons = dict(blocked)
    for key in ("PROMOTION_OFFENSIVE", "PROMOTION_BLITZER"):
        assert key not in available
        assert reasons[key] == "this unit can only defend"


def test_promotable_one_move_unit_is_refused_blitz(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    available, blocked = rules._promotable_promotions(
        r, "UNIT_ONE_MOVE", set(), set())
    reasons = dict(blocked)
    assert "PROMOTION_BLITZER" not in available
    assert reasons["PROMOTION_BLITZER"] == "this unit has only 1 move"


def test_promotable_gates_collateral_damage_on_unit_capability(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    cannot, blocked = rules._promotable_promotions(
        r, "UNIT_CANNOT_BOMBARD", set(), set())
    assert "PROMOTION_BOMBARDIER" not in cannot
    assert dict(blocked)["PROMOTION_BOMBARDIER"] == (
        "this unit cannot deal collateral damage")

    can, _ = rules._promotable_promotions(
        r, "UNIT_CAN_BOMBARD", set(), set())
    assert "PROMOTION_BOMBARDIER" in can


def test_promotable_gates_interception_on_unit_capability(xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    cannot, blocked = rules._promotable_promotions(
        r, "UNIT_CANNOT_INTERCEPT", set(), set())
    assert "PROMOTION_INTERCEPTOR" not in cannot
    assert dict(blocked)["PROMOTION_INTERCEPTOR"] == "this unit cannot intercept"

    can, _ = rules._promotable_promotions(
        r, "UNIT_CAN_INTERCEPT", set(), set())
    assert "PROMOTION_INTERCEPTOR" in can


def test_view_promotable_reports_held_by_default_without_eligibility(
    xml_root, tmp_path
):
    """CAN TAKE NEXT / BLOCKED are opt-in (--eligible) - the default answers
    only "what does this unit have"."""
    _, state = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER", "promotions": ["PROMOTION_TESTER"]}])
    r = build_rules(xml_root, state)
    text = rules.view_promotable(r, 1, state, False, None)
    assert "ALREADY HAS" in text
    assert "+10% combat" in text
    assert "CAN TAKE NEXT" not in text
    assert "BLOCKED" not in text
    assert "pass --eligible" in text


def test_view_promotable_eligible_flag_adds_can_take_next_and_blocked(
    xml_root, tmp_path
):
    _, state = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER", "promotions": ["PROMOTION_TESTER"]}])
    r = build_rules(xml_root, state)
    text = rules.view_promotable(r, 1, state, False, None, eligible=True)
    assert "CAN TAKE NEXT" in text
    assert "BLOCKED" in text
    assert "PROMOTION_LEADER_ONLY" in text  # named among the blocked, with a reason


def test_view_promotable_held_blocks_omit_available_to_and_requires(
    xml_root, tmp_path
):
    """Both are moot for something the unit already has."""
    _, state = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER",
               "promotions": ["PROMOTION_ADVANCED"]}])
    r = build_rules(xml_root, state)
    text = rules.view_promotable(r, 1, state, False, None)
    assert "AVAILABLE TO" not in text
    assert "REQUIRES" not in text


def test_view_promotable_combined_effects_leads_the_output(xml_root, tmp_path):
    """The combined total is read before the per-promotion breakdown, not
    after it - it answers the usual question directly."""
    _, state = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER",
               "promotions": ["PROMOTION_TESTER", "PROMOTION_TERRAIN"]}])
    r = build_rules(xml_root, state)
    text = rules.view_promotable(r, 1, state, False, None)
    assert text.index("COMBINED EFFECTS") < text.index("ALREADY HAS")
    assert "+25% defence in FEATURE_FOREST" in text


def test_view_promotable_no_combined_section_for_a_single_held_promotion(
    xml_root, tmp_path
):
    _, state = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER", "promotions": ["PROMOTION_TESTER"]}])
    r = build_rules(xml_root, state)
    text = rules.view_promotable(r, 1, state, False, None)
    assert "COMBINED" not in text


def test_view_promotable_unknown_id_names_the_problem(xml_root, tmp_path):
    _, state = make_state(tmp_path, units=[])
    r = build_rules(xml_root, state)
    with pytest.raises(rules.RulesError) as error:
        rules.view_promotable(r, 999, state, False, None)
    assert "999" in str(error.value)
    assert "intel" in str(error.value)


def test_cli_promotion_for_unit_runs(xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER", "promotions": []}])
    code = rules.main(
        ["promotion", state_path, "--for-unit", "1", "--config", config])
    assert code == 0
    assert "ALREADY HAS" in capsys.readouterr().out


def test_cli_promotion_for_unit_eligible_adds_can_take_next(
    xml_root, tmp_path, config, capsys
):
    state_path, _ = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER", "promotions": []}])
    code = rules.main(
        ["promotion", state_path, "--for-unit", "1", "--eligible",
         "--config", config])
    assert code == 0
    assert "CAN TAKE NEXT" in capsys.readouterr().out


def test_cli_eligible_requires_for_unit(xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(tmp_path)
    code = rules.main(
        ["promotion", "PROMOTION_TESTER", state_path, "--eligible",
         "--config", config])
    assert code == 2
    assert "only applies alongside --for-unit" in capsys.readouterr().err


def test_cli_promotion_for_unit_fetches_held_promotions_automatically(
    xml_root, tmp_path, config, capsys
):
    """The point of --for-unit over typing --promotion by hand: it reads
    units[].promotions itself and prints their full detail unprompted."""
    state_path, _ = make_state(
        tmp_path,
        units=[{"id": 1, "type": "UNIT_TESTER", "promotions": ["PROMOTION_TESTER"]}])
    code = rules.main(
        ["promotion", state_path, "--for-unit", "1", "--config", config])
    assert code == 0
    assert "+10% combat" in capsys.readouterr().out


def test_cli_promotion_for_unit_rejects_a_type_too(
    xml_root, tmp_path, config, capsys
):
    """--for-unit already answers the question - it doesn't also take a
    positional TYPE, put AFTER `state` so argparse can resolve it."""
    state_path, _ = make_state(tmp_path, units=[])
    code = rules.main(
        ["promotion", "PROMOTION_TESTER", state_path, "--for-unit", "1",
         "--config", config])
    assert code == 2
    assert "does not take a TYPE" in capsys.readouterr().err


def test_cli_for_unit_rejected_on_other_subjects(xml_root, tmp_path, config, capsys):
    """--for-unit's value sitting between TYPE and `state` is itself the
    ordering trap build_parser's comment documents (argparse cannot always
    backtrack a value-taking option around a positional) - put it after
    `state`, the same safe ordering used everywhere else in this file."""
    state_path, _ = make_state(tmp_path)
    code = rules.main(
        ["unit", "UNIT_TESTER", state_path, "--for-unit", "1", "--config", config])
    assert code == 2
    assert "only applies to" in capsys.readouterr().err


def test_promotion_view_single_type_has_no_combined_section(xml_root, tmp_path):
    """view_promotion looks up exactly one PROMOTION_ - totalling several
    held together on one unit is `promotion <state> --for-unit ID`
    (view_promotable) instead; see that function's own tests."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_promotion(r, "PROMOTION_TESTER", state, False, None)
    assert "COMBINED" not in text


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
    assert "this is a race" in text
    assert "hammers to gold" in text

    ordinary = rules.view_building(r, "BUILDING_TESTHOUSE", state, False, None)
    assert "this is a race" not in ordinary


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


def test_cli_runs_a_promotion_lookup(xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(tmp_path)
    code = rules.main(["promotion", "PROMOTION_TESTER", state_path,
                       "--config", config])
    assert code == 0
    assert "PROMOTION_TESTER" in capsys.readouterr().out


def test_cli_promotion_reports_a_missing_type_rather_than_misbinding(capsys):
    """Same right-to-left argparse trap unit/tech/building already guard."""
    assert rules.main(["promotion", "state.json"]) == 2


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


# ---------------------------------------------------------------------------
# Per-city buildability - `city`, and the gates only increment 5 can answer
# ---------------------------------------------------------------------------


def _city_state(tmp_path, wonders=None, cities=None, **kwargs):
    """A one-city game whose civ is ours, so uniques filter correctly."""
    cities = cities or [make_city(**kwargs)]
    return make_state(tmp_path, known=["TECH_ROOT_A"], cities=cities,
                      civilization="CIVILIZATION_MINE", wonders=wonders)[1]


def test_city_view_needs_a_city_that_exists(xml_root, tmp_path):
    state = _city_state(tmp_path, name="Lisbon")
    r = build_rules(xml_root, state)
    with pytest.raises(rules.RulesError) as excinfo:
        rules.view_city(r, "Nowhere", state)
    # The available names are in hand at the point of failure, so listing them
    # costs nothing - same argument as the near-match suggestions.
    assert "Lisbon" in str(excinfo.value)


def test_city_view_matches_a_name_case_insensitively(xml_root, tmp_path):
    state = _city_state(tmp_path, name="Lisbon")
    r = build_rules(xml_root, state)
    assert "Lisbon" in rules.view_city(r, "lisbon", state)


def test_a_sea_unit_is_blocked_in_a_landlocked_city(xml_root, tmp_path):
    """DOMAIN_SEA against cities[].coastal.

    Not derivable from map.tiles: the engine's test is adjacency to a water
    body of a minimum size, so "a neighbour is water" would call a city on a
    pond coastal. This is the gate that had a landlocked Lisbon listing a Work
    Boat as available.
    """
    inland = _city_state(tmp_path, name="Inland", coastal=False)
    r = build_rules(xml_root, inland)
    blockers = rules.unit_availability(
        r, "UNIT_BOAT", r.units["UNIT_BOAT"], inland["cities"][0], inland,
        rules.effective_known(inland), set(), set())
    assert any("not coastal" in b for b in blockers)

    port = _city_state(tmp_path, name="Port", coastal=True)
    assert rules.unit_availability(
        r, "UNIT_BOAT", r.units["UNIT_BOAT"], port["cities"][0], port,
        rules.effective_known(port), set(), set()) == []


def test_a_coastal_building_is_blocked_in_a_landlocked_city(xml_root, tmp_path):
    inland = _city_state(tmp_path, name="Inland", coastal=False)
    r = build_rules(xml_root, inland)
    blockers = rules.building_availability(
        r, "BUILDING_TESTPORT", r.buildings["BUILDING_TESTPORT"],
        inland["cities"][0], inland, rules.effective_known(inland), set(),
        set(), {})
    assert any("not coastal" in b for b in blockers)


def test_a_prereq_building_is_checked_against_this_city(xml_root, tmp_path):
    """cities[].buildings - per-city state held nowhere else in the export."""
    without = _city_state(tmp_path, name="Bare", buildings=[])
    r = build_rules(xml_root, without)
    blockers = rules.building_availability(
        r, "BUILDING_TESTANNEX", r.buildings["BUILDING_TESTANNEX"],
        without["cities"][0], without, rules.effective_known(without), set(),
        set(), {})
    assert any("BUILDINGCLASS_TESTHOUSE" in b for b in blockers)

    with_it = _city_state(tmp_path, name="Built",
                          buildings=["BUILDING_TESTHOUSE"])
    assert rules.building_availability(
        r, "BUILDING_TESTANNEX", r.buildings["BUILDING_TESTANNEX"],
        with_it["cities"][0], with_it, rules.effective_known(with_it), set(),
        set(), {}) == []


def test_an_already_built_building_says_so(xml_root, tmp_path):
    state = _city_state(tmp_path, buildings=["BUILDING_TESTHOUSE"])
    r = build_rules(xml_root, state)
    blockers = rules.building_availability(
        r, "BUILDING_TESTHOUSE", r.buildings["BUILDING_TESTHOUSE"],
        state["cities"][0], state, rules.effective_known(state), set(), set(),
        {})
    assert blockers == ["already built here"]


def test_a_world_wonder_already_built_is_gone_not_a_race(xml_root, tmp_path):
    """wonders.built - the field that was exported and read by nothing.

    NOT exercised by samples/baseline-early-game: `built` is [] in all 44
    files, so this branch is synthetic-only and that gap is recorded in
    harness/README.md rather than left to be discovered.
    """
    wonders = {"built": ["BUILDINGCLASS_TESTWONDER"], "national": []}
    state = _city_state(tmp_path, wonders=wonders)
    r = build_rules(xml_root, state)
    blockers = rules.building_availability(
        r, "BUILDING_TESTWONDER", r.buildings["BUILDING_TESTWONDER"],
        state["cities"][0], state, rules.effective_known(state), set(), set(),
        wonders)
    assert any("ALREADY BUILT" in b for b in blockers)


def test_a_national_wonder_you_hold_is_blocked(xml_root, tmp_path):
    wonders = {"built": [], "national": ["BUILDINGCLASS_TESTNATIONAL"]}
    state = _city_state(tmp_path, wonders=wonders)
    r = build_rules(xml_root, state)
    blockers = rules.building_availability(
        r, "BUILDING_TESTNATIONAL", r.buildings["BUILDING_TESTNATIONAL"],
        state["cities"][0], state, rules.effective_known(state), set(), set(),
        wonders)
    assert any("already have one" in b for b in blockers)


def test_other_civs_uniques_are_excluded_and_ours_are_not(xml_root, tmp_path):
    """Without this filter every civ's unique is tech-open for you.

    Measured on the real install at t43: 34 rows instead of 18, most of them
    units the player can never build.
    """
    state = _city_state(tmp_path)
    r = build_rules(xml_root, state)
    other_units, other_buildings = rules._unique_sets(r, state)
    assert "UNIT_THEIR_UNIQUE" in other_units
    assert "BUILDING_THEIR_UNIQUE" in other_buildings
    # Ours replaces nothing, so the generic stays available to us.
    assert "UNIT_TESTER" not in other_units


def test_your_own_unique_replaces_the_generic(xml_root, tmp_path):
    """The civ that HAS the override builds it and loses the class default."""
    state = _city_state(tmp_path)
    state["player"]["civilization"] = "CIVILIZATION_THEIRS"
    r = build_rules(xml_root, state)
    other_units, _ = rules._unique_sets(r, state)
    assert "UNIT_THEIR_UNIQUE" not in other_units
    # UNITCLASS_X's other members are replaced for this civ.
    assert "UNIT_TESTER" in other_units


def test_the_city_list_is_alphabetical_and_never_ranked(xml_root, tmp_path):
    """The no-ranking guarantee, in the same shape as the tech-route test.

    Cost order or available-first would each be an opinion about what to build;
    the tool's line is that the list is derived, not selected.
    """
    state = _city_state(tmp_path, name="Lisbon")
    r = build_rules(xml_root, state)
    text = rules.view_city(r, "Lisbon", state)

    for word in ("best", "recommend", "should build", "cheapest", "strongest",
                 "optimal", "priority"):
        assert word not in text.lower()

    section = text.split("UNITS")[1].split("BUILDINGS")[0]
    listed = [line.split()[0] for line in section.splitlines()
              if line.startswith("  UNIT_")]
    assert listed == sorted(listed)


def test_blocked_rows_stay_listed_with_the_reason(xml_root, tmp_path):
    """A buildable-only list reads as a shortlist and cannot answer what you
    are about to unlock, which is the question behind switching production."""
    state = _city_state(tmp_path, name="Lisbon", coastal=False)
    r = build_rules(xml_root, state)
    text = rules.view_city(r, "Lisbon", state)
    assert "BLOCKED" in text
    assert "UNIT_BOAT" in text


def test_untrainable_entries_are_not_listed_as_available(xml_root, tmp_path):
    """iCost <= 0 is animals and great-person builds - a city produces neither.

    Listing BUILDING_TESTACADEMY as "available, ~0 turns" was the first
    version, and it invited ordering something uncommandable.
    """
    state = _city_state(tmp_path, name="Lisbon")
    r = build_rules(xml_root, state)
    text = rules.view_city(r, "Lisbon", state)
    assert "UNIT_CRITTER" not in text
    assert "BUILDING_TESTACADEMY" not in text


def test_a_religion_gate_is_reported_as_unknown_not_as_met(xml_root, tmp_path):
    """Religion presence is not in the export at all.

    Calling a missionary available because the tech is open would be a
    confident wrong answer of exactly the kind this tool exists to prevent.
    """
    state = _city_state(tmp_path)
    r = build_rules(xml_root, state)
    blockers = rules.unit_availability(
        r, "UNIT_ZEALOT", r.units["UNIT_ZEALOT"], state["cities"][0], state,
        rules.effective_known(state), set(), set())
    assert blockers and "RELIGION_TESTFAITH" in blockers[0]
    assert "not in the export" in blockers[0]


def test_city_view_states_what_it_omits(xml_root, tmp_path):
    state = _city_state(tmp_path, name="Lisbon")
    r = build_rules(xml_root, state)
    text = rules.view_city(r, "Lisbon", state)
    assert "THIS OMITS" in text
    assert "cannot see rival production" in text
    assert rules.MOD_WARNING in text


def test_build_turns_exclude_a_city_the_gate_rules_out(xml_root, tmp_path):
    """The Lighthouse defect: `~5 turns in Lisbon` printed directly above
    `city must be coastal`, with Lisbon not coastal.

    Two lines of one block contradicting each other, with nothing in the
    output able to catch it. Excluded cities are NAMED, because a city missing
    with no explanation reads as a data problem.
    """
    state = make_state(
        tmp_path, known=["TECH_ROOT_A"], civilization="CIVILIZATION_MINE",
        cities=[make_city(name="Lisbon", rate=13, coastal=False),
                make_city(name="Oporto", x=20, rate=7, coastal=True)])[1]
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTPORT", state, False, None)

    assert "turns in Oporto" in text
    assert "turns in Lisbon" not in text
    assert "excluded: Lisbon is not coastal" in text


def test_build_turns_are_unchanged_for_an_ungated_building(xml_root, tmp_path):
    state = make_state(
        tmp_path, known=["TECH_ROOT_A"], civilization="CIVILIZATION_MINE",
        cities=[make_city(name="Lisbon", rate=13),
                make_city(name="Oporto", x=20, rate=7)])[1]
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTHOUSE", state, False, None)
    assert "turns in Lisbon" in text
    assert "turns in Oporto" in text
    assert "excluded" not in text


def test_a_site_gate_reports_which_of_your_cities_pass(xml_root, tmp_path):
    state = make_state(
        tmp_path, known=["TECH_ROOT_A"], civilization="CIVILIZATION_MINE",
        cities=[make_city(name="Lisbon", coastal=False),
                make_city(name="Oporto", x=20, coastal=True)])[1]
    r = build_rules(xml_root, state)
    text = rules.view_building(r, "BUILDING_TESTPORT", state, False, None)
    assert "must be coastal - yes: Oporto; no: Lisbon" in text


def test_cli_city_reports_a_missing_name_rather_than_misbinding(capsys):
    """`city` takes a plain name, so the missing-state guard cannot key off a
    TYPE prefix - a bare word is exactly what a city argument looks like."""
    assert rules.main(["city", "Lisbon"]) == 2
    err = capsys.readouterr().err
    assert "needs both a city name and a state file" in err
    assert "Lisbon <state.json>" in err


# ---------------------------------------------------------------------------
# Food builds - settlers and workers eat the food surplus
# ---------------------------------------------------------------------------


def test_a_food_build_adds_the_food_surplus_to_its_rate():
    """Settlers and workers are built with food AND hammers.

    Ground truth from the baseline run, Lisbon on consecutive turns:
        t42  UNIT_WARRIOR   foodPerTurn 6  productionPerTurn 7
        t43  UNIT_SETTLER   foodPerTurn 0  productionPerTurn 13   (= 6 + 7)
    Ignoring it roughly doubled the quoted time on the two builds that
    dominate turns 0-50.

    THE FALLBACK PATH, as are the four tests below it: these cities omit the
    increment-6 split deliberately. Since the baseline run was backfilled, no
    sample turn lacks the fields any more, so these synthetic cases are the
    ONLY coverage this branch has - it still runs for any capture predating the
    increment. See test_the_exported_split_* for the other path.
    """
    city = {"productionPerTurn": 7, "foodPerTurn": 6, "producing": "UNIT_WARRIOR"}
    assert rules.food_build_rate(city, {"food_production": True}) == (13, True)
    assert rules.food_build_rate(city, {"food_production": False}) == (7, False)


def test_food_already_in_the_rate_is_not_counted_twice():
    """foodPerTurn reads 0 exactly while a food build is in the queue, so the
    surplus is already inside productionPerTurn and must not be re-added."""
    city = {"productionPerTurn": 13, "foodPerTurn": 0,
            "producing": "UNIT_SETTLER"}
    assert rules.food_build_rate(city, {"food_production": True}) == (13, True)


def test_an_ordinary_build_is_flagged_when_the_rate_carries_food():
    """The same double-count in the other direction.

    At t43 Lisbon's 13 hpt includes the 6 food its settler is eating; reading
    that as a Warrior's rate overstates it by the whole surplus. The split is
    not recoverable from one file - Lisbon's hammers move 8 -> 2 across
    t37 -> t38 as worked tiles change - so it is flagged, not silently used.
    """
    city = {"productionPerTurn": 13, "foodPerTurn": 0,
            "producing": "UNIT_SETTLER"}
    rate, folded = rules.food_build_rate(city, {"food_production": False})
    assert rate == 13
    assert folded == "optimistic"


def test_a_starving_city_does_not_get_a_negative_food_bonus():
    city = {"productionPerTurn": 4, "foodPerTurn": -2, "producing": None}
    assert rules.food_build_rate(city, {"food_production": True}) == (4, False)


def test_the_food_note_is_stated_once_not_on_every_row(xml_root, tmp_path):
    state = _city_state(tmp_path, name="Lisbon", rate=13,
                        producing="UNIT_SETTLER")
    state["cities"][0]["foodPerTurn"] = 0
    r = build_rules(xml_root, state)
    text = rules.view_city(r, "Lisbon", state)
    assert text.count("a little optimistic") == 1


def test_the_exported_split_prices_an_ordinary_build_at_the_hammer_half():
    """Schema increment 6 closes the hole the "optimistic" flag papered over.

    Same Lisbon t43 state as the fallback tests above, plus the split the mod
    now exports. A Warrior's rate is the hammer half exactly - 7, not the 13
    that includes the Settler's food - and it is a fact rather than an estimate,
    so nothing is flagged.

    These numbers were written synthetically, from the engine's own t42/t43
    figures, before any capture carried the fields - and the re-exported
    turn_0043 then came back with exactly this split (hammers 7, food 6),
    confirming the reconstruction. Kept as a unit test because it pins
    food_build_rate directly; the sample exercises the same path end to end.
    """
    city = {"productionPerTurn": 13, "foodPerTurn": 0,
            "producing": "UNIT_SETTLER",
            "productionFromHammers": 7, "productionFromFood": 6}
    assert rules.food_build_rate(city, {"food_production": False}) == (7, False)
    assert rules.food_build_rate(city, {"food_production": True}) == (13, True)


def test_the_exported_split_still_adds_a_surplus_the_city_is_not_yet_eating():
    """A food build queued in a city currently building something ordinary.

    `productionFromFood` is 0 because no food build is running yet, so the
    surplus is still in foodPerTurn and growing the city - a Settler started
    here would take it. Same arithmetic as the fallback, reached from the
    hammer half rather than from a total that has to be decomposed.
    """
    city = {"productionPerTurn": 7, "foodPerTurn": 6,
            "producing": "UNIT_WARRIOR",
            "productionFromHammers": 7, "productionFromFood": 0}
    assert rules.food_build_rate(city, {"food_production": True}) == (13, True)
    assert rules.food_build_rate(city, {"food_production": False}) == (7, False)


def test_the_exported_split_drops_the_optimistic_caveat(xml_root, tmp_path):
    """The flag exists only for the inference, so it must not survive the fix.

    The header line is what a reader sees; asserting on food_build_rate alone
    would leave it possible for the caveat to keep printing beside numbers that
    no longer need it.
    """
    state = _city_state(tmp_path, name="Lisbon", rate=13,
                        producing="UNIT_SETTLER")
    city = state["cities"][0]
    city["foodPerTurn"] = 0
    city["productionFromHammers"] = 7
    city["productionFromFood"] = 6
    r = build_rules(xml_root, state)
    text = rules.view_city(r, "Lisbon", state)
    assert "optimistic" not in text


def test_a_starving_city_gets_no_food_bonus_from_the_exported_split():
    """The engine clamps the food term at 0 (std::max in getProductionDifference),
    so a starving city exports productionFromFood 0 and the halves still sum."""
    city = {"productionPerTurn": 4, "foodPerTurn": -2, "producing": None,
            "productionFromHammers": 4, "productionFromFood": 0}
    assert rules.food_build_rate(city, {"food_production": True}) == (4, False)


def _printed_turns(text, unit_type):
    """Pull the '~N turns' figure `view_city` printed for one unit row.

    The row is `  UNIT_X   <cost>  available, ~N turns[ (+food, growth stops)]`;
    parsed rather than re-deriving the number, since the point is to check what
    a reader actually sees.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(unit_type + " "):
            continue
        assert "~" in line, "no turn estimate printed for %s: %r" % (unit_type, line)
        return int(line.split("~", 1)[1].split()[0])
    raise AssertionError("%s not found in:\n%s" % (unit_type, text))


@pytest.mark.parametrize(
    "turn, city_name, unit_type, expected_turns, food_marked", [
        # t43 Lisbon is mid-UNIT_SETTLER: hammers=7, food=6 (already drawn),
        # productionPerTurn=13. An ORDINARY unit must be priced at the hammer
        # half alone, never the inflated total.
        ("turn_0043.json", "Lisbon", "UNIT_WARRIOR", 3, False),   # 15 / 7 -> 3
        ("turn_0043.json", "Lisbon", "UNIT_CHARIOT", 5, False),   # 30 / 7 -> 5
        # The food build itself gets hammers + food = the full total.
        ("turn_0043.json", "Lisbon", "UNIT_SETTLER", 8, True),    # 100 / 13 -> 8
        # t39 Lisbon is mid-UNIT_WARRIOR (ordinary): hammers=5, food=0 drawn,
        # but foodPerTurn=6 is a real surplus sitting UNCLAIMED. A hypothetical
        # food build here must add that surplus on top of the hammer rate,
        # taking it from foodPerTurn rather than the (zero) exported food half.
        ("turn_0039.json", "Lisbon", "UNIT_SETTLER", 10, True),   # 100 / (5+6) -> 10
        ("turn_0039.json", "Lisbon", "UNIT_WORKER", 6, True),     # 60 / (5+6) -> 6
        ("turn_0039.json", "Lisbon", "UNIT_WARRIOR", 3, False),   # 15 / 5 -> 3
    ])
def test_turn_estimates_use_the_right_half_of_the_exported_split(
        xml_root, turn, city_name, unit_type, expected_turns, food_marked):
    """End-to-end: the printed '~N turns' figure, not just food_build_rate's
    return value, against a real sample turn that carries the increment-6
    split.

    Closes a real gap: prior tests pinned food_build_rate() in isolation and
    the caveat-suppression in view_city separately, but nothing chained the
    rate all the way through turns_estimate() to the number a reader actually
    sees, on real captured data rather than a synthetic one-city fixture.
    Hand-computed expectations are in the parametrize table; this only checks
    the tool reproduces them.
    """
    try:
        xml_root_path = rules.resolve_xml_root()
    except rules.RulesError as exc:
        pytest.skip("no Civ IV install: %s" % exc)

    path = os.path.join(SAMPLES, "baseline-early-game", turn)
    if not os.path.isfile(path):
        pytest.skip("%s is absent" % turn)
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)

    r = rules.Rules(xml_root_path, state["game"])
    text = rules.view_city(r, city_name, state)

    assert _printed_turns(text, unit_type) == expected_turns
    for line in text.splitlines():
        if line.strip().startswith(unit_type + " "):
            assert ("(+food, growth stops)" in line) == food_marked
            break


def test_a_settler_cost_blanked_by_bts_falls_back_to_vanilla(xml_root, tmp_path):
    """BTS sets UNIT_SETTLER's <iCost> to 0 while vanilla holds the real 100.

    Taken literally the 0 looked like an animal or great-person build, and the
    `city` view dropped the single most important early build from the list.
    The engine's own number settles it: cities[].productionNeeded reads 100 on
    every turn Lisbon builds one.

    Narrow on purpose - BTS genuinely re-prices units (a Chariot is 25 in
    vanilla, 30 in BTS), so only a ZERO falls through.
    """
    state = _city_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_FREEBIE"]["cost"] == 100
    assert r.units["UNIT_FREEBIE"].get("cost_from_vanilla") is True
    # A unit BTS re-priced keeps the BTS value, not vanilla's.
    assert r.units["UNIT_TESTER"]["cost"] == 35


def test_a_unit_costing_zero_in_both_trees_stays_unbuildable(xml_root, tmp_path):
    """A genuine 0 marks something a city never trains - that is the filter
    that keeps animals out of the list."""
    state = _city_state(tmp_path, name="Lisbon")
    r = build_rules(xml_root, state)
    assert r.units["UNIT_CRITTER"]["cost"] == 0
    assert "UNIT_CRITTER" not in rules.view_city(r, "Lisbon", state)


def test_a_tech_being_researched_does_not_make_things_available(xml_root, tmp_path):
    """`city` is the one view that must NOT use effective_known.

    That set folds in the tech in progress, which is right when costing a route
    and wrong here. On the baseline at t43 Masonry sits at 4/124 with 7 turns
    left, and folding it in reported the Pyramids, the Great Wall and Walls as
    available NOW - three world/ordinary builds the city could not start.
    """
    state = _city_state(tmp_path, name="Lisbon")
    # TECH_SIMPLE is not known; it is being researched.
    state["player"]["knownTechs"] = ["TECH_ROOT_A"]
    state["player"]["research"] = {"current": "TECH_SIMPLE", "turnsLeft": 7}
    r = build_rules(xml_root, state)
    text = rules.view_city(r, "Lisbon", state)

    row = [l for l in text.splitlines() if "BUILDING_TESTHOUSE" in l][0]
    assert "BLOCKED" in row
    assert "available" not in row
    assert "RESEARCHING NOW" in text
    assert "7 turns left" in text


def test_the_researching_label_is_only_for_the_current_tech(xml_root, tmp_path):
    state = _city_state(tmp_path, name="Lisbon")
    state["player"]["knownTechs"] = ["TECH_ROOT_A"]
    state["player"]["research"] = {"current": "TECH_SIMPLE", "turnsLeft": 7}
    r = build_rules(xml_root, state)
    text = rules.view_city(r, "Lisbon", state)
    # TECH_ROOT_B gates UNIT_ELSEWHERE and is not being researched.
    elsewhere = [l for l in text.splitlines() if "TECH_ROOT_B" in l]
    assert elsewhere and all("RESEARCHING" not in l for l in elsewhere)


@pytest.mark.parametrize("sample", sorted(
    os.path.basename(p) for p in
    (os.listdir(SAMPLES) if os.path.isdir(SAMPLES) else [])
    if os.path.isdir(os.path.join(SAMPLES, p))
))
def test_the_production_halves_sum_on_every_sample_turn_that_has_them(sample):
    """The increment-6 invariant, swept over the sample runs.

    NOTE ON WHAT THIS PROVES. In samples/baseline-early-game only turn_0040 and
    turn_0043 hold genuine exported values; the other 41 city-bearing turns are
    backfilled with `hammers = productionPerTurn - food`, so the sum assertion
    below is true BY CONSTRUCTION there and is a real check only on the two
    genuine turns (and on any future capture). See samples/README.md's second
    provenance caveat. The sweep is kept over everything anyway, because the
    other two assertions - non-negativity and food-only-on-unit-builds - are
    NOT vacuous on derived rows, and because a fresh full run should have to
    pass all three.

    On the genuine turns a sum mismatch would mean the mod's two
    getCurrentProductionDifference calls had disagreed about the hammer half,
    which is the one way the exported split could be wrong.
    """
    folder = os.path.join(SAMPLES, sample)
    turns = sorted(f for f in os.listdir(folder) if f.startswith("turn_"))
    if not turns:
        pytest.skip("%s has no turn files" % sample)

    checked = 0
    for name in turns:
        with open(os.path.join(folder, name), encoding="utf-8") as handle:
            state = json.load(handle)
        for city in state.get("cities") or []:
            if "productionFromHammers" not in city:
                continue
            hammers = city["productionFromHammers"]
            food = city["productionFromFood"]
            total = city["productionPerTurn"]
            assert hammers + food == total, (
                "%s %s: %d + %d != %d" % (name, city["name"], hammers, food, total))
            # Neither half is ever negative: the engine clamps the food term at
            # std::max(0, ...) and a hammer rate cannot go below zero.
            assert hammers >= 0 and food >= 0, "%s %s" % (name, city["name"])
            # A building or an empty queue can never draw food.
            producing = city.get("producing") or ""
            if food > 0:
                assert producing.startswith("UNIT_"), (
                    "%s %s: food half %d on a non-unit build %r"
                    % (name, city["name"], food, producing))
            checked += 1

    if not checked:
        pytest.skip("%s predates schema increment 6" % sample)


def test_the_backfill_derivation_reproduces_the_genuine_turns():
    """The check that is NOT vacuous: derive the split, compare to real exports.

    turn_0040 and turn_0043 are the only turns of the baseline run whose
    increment-6 fields came from the mod rather than from the backfill, so they
    are the only place the derivation can be checked against ground truth. This
    pins the formula that produced the other 41 turns: if someone re-runs the
    backfill with a changed rule, or edits a derived value by hand, the two
    genuine turns stop agreeing with it and this fails.

    Recomputed from workedTiles + population here rather than trusting the
    stored numbers, which is the whole point - reading the fields back and
    comparing them to themselves would prove nothing.
    """
    folder = os.path.join(SAMPLES, "baseline-early-game")
    if not os.path.isdir(folder):
        pytest.skip("baseline-early-game sample is absent")

    # bFood units per CIV4UnitInfos.xml; food consumption is 2/pop while no
    # city is unhealthy, which holds throughout this run.
    bfood = {"UNIT_SETTLER", "UNIT_WORKER"}
    checked = 0
    for name in ("turn_0040.json", "turn_0043.json"):
        with open(os.path.join(folder, name), encoding="utf-8") as handle:
            state = json.load(handle)
        tiles = {(t["x"], t["y"]): t for t in state["map"]["tiles"]}
        for city in state["cities"]:
            tile_food = sum(tiles[(x, y)]["yields"][0]
                            for x, y in city["workedTiles"])
            producing = city.get("producing") or ""
            food = (max(0, tile_food - 2 * city["population"])
                    if producing in bfood else 0)
            hammers = city["productionPerTurn"] - food
            assert food == city["productionFromFood"], (
                "%s %s food: derived %d, exported %d"
                % (name, city["name"], food, city["productionFromFood"]))
            assert hammers == city["productionFromHammers"], (
                "%s %s hammers: derived %d, exported %d"
                % (name, city["name"], hammers, city["productionFromHammers"]))
            checked += 1

    assert checked == 4, "expected 4 genuine city rows, checked %d" % checked


@pytest.mark.parametrize("sample", sorted(
    os.path.basename(p) for p in
    (os.listdir(SAMPLES) if os.path.isdir(SAMPLES) else [])
    if os.path.isdir(os.path.join(SAMPLES, p))
))
def test_nothing_is_available_without_its_tech_on_any_sample_turn(sample):
    """The invariant that caught the effective_known bug, as a test.

    `city` reported the Pyramids, the Great Wall and Walls as available at t43
    while Masonry was still 4/124 with seven turns left. Nothing in the output
    contradicted it - the rows were indistinguishable from genuinely available
    ones - and no unit test covered it, because the synthetic fixture happened
    not to have a tech in progress.

    What found it was sweeping every turn of a real run and asserting one
    property. That is cheap, so it runs over every sample rather than a chosen
    turn: a future capture that breaks it fails here instead of quietly
    advising someone to build something they cannot.
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
        with open(os.path.join(folder, name), encoding="utf-8") as handle:
            state = json.load(handle)
        cities = state.get("cities") or []
        if not cities:
            continue
        r = rules.Rules(xml_root, state.get("game") or {})
        # Strictly what the player has - NOT effective_known, which is the
        # whole point of the assertion.
        known = set((state.get("player") or {}).get("knownTechs") or [])
        for city in cities:
            text = rules.view_city(r, city["name"], state)
            for line in text.splitlines():
                if "available" not in line:
                    continue
                key = line.strip().split()[0]
                entry = r.buildings.get(key) or r.units.get(key)
                if entry is None:
                    continue
                tech = entry.get("tech") or entry.get("prereq_tech")
                assert not (tech and tech != "NONE" and tech not in known), (
                    "%s/%s: %s listed available in %s but needs %s, which is "
                    "not known" % (sample, name, key, city["name"], tech)
                )
                checked += 1

    assert checked, "no available rows were checked in %s" % sample
