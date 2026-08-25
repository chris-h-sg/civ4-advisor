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
          collateral_damage_max_units=0, animal_combat=0, is_animal=False,
          hills_defense=0, free_promotions=(), off_promotions=(),
          class_attack_mods=(), class_defense_mods=(), flanking=(),
          combat_limit=100, city_attack=0, ignore_building_defense=False,
          bombard_rate=0, no_bad_goodies=False, first_strike_immune=False,
          collateral_immune=()):
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
      <UnitClassAttackMods>%s</UnitClassAttackMods>
      <UnitClassDefenseMods>%s</UnitClassDefenseMods>
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
      <iCityAttack>%d</iCityAttack>
      <bIgnoreBuildingDefense>%d</bIgnoreBuildingDefense>
      <iBombardRate>%d</iBombardRate>
      <bNoBadGoodies>%d</bNoBadGoodies>
      <bFirstStrikeImmune>%d</bFirstStrikeImmune>
      <UnitCombatCollateralImmunes>%s</UnitCombatCollateralImmunes>
      <iWithdrawalProb>0</iWithdrawalProb>
      <bNoDefensiveBonus>0</bNoDefensiveBonus>
      <bOnlyDefensive>%d</bOnlyDefensive>
      <bIgnoreTerrainCost>%d</bIgnoreTerrainCost>
      <iInterceptionProbability>%d</iInterceptionProbability>
      <iCollateralDamage>%d</iCollateralDamage>
      <iCollateralDamageLimit>%d</iCollateralDamageLimit>
      <iCollateralDamageMaxUnits>%d</iCollateralDamageMaxUnits>
      <iAnimalCombat>%d</iAnimalCombat>
      <bAnimal>%d</bAnimal>
      <iHillsDefense>%d</iHillsDefense>
      <iHillsAttack>0</iHillsAttack>
      <iCombatLimit>%d</iCombatLimit>
      <FlankingStrikes>%s</FlankingStrikes>
      <FreePromotions>%s</FreePromotions>
      <TerrainImpassables/>
      <FeatureImpassables/>
    </UnitInfo>""" % (
        type_key, unit_class, domain, combat, filler,
        "".join(
            "<UnitCombatMod><UnitCombatType>%s</UnitCombatType>"
            "<iUnitCombatMod>%d</iUnitCombatMod></UnitCombatMod>" % m
            for m in mods
        ),
        "".join(
            "<UnitClassAttackMod><UnitClassType>%s</UnitClassType>"
            "<iUnitClassMod>%d</iUnitClassMod></UnitClassAttackMod>" % m
            for m in class_attack_mods
        ),
        "".join(
            "<UnitClassDefenseMod><UnitClassType>%s</UnitClassType>"
            "<iUnitClassMod>%d</iUnitClassMod></UnitClassDefenseMod>" % m
            for m in class_defense_mods
        ),
        prereq, religion, corporation,
        "".join("<BonusType>%s</BonusType>" % b for b in bonuses),
        cost, moves, strength, first_strikes, city_defense, city_attack,
        1 if ignore_building_defense else 0, bombard_rate,
        1 if no_bad_goodies else 0, 1 if first_strike_immune else 0,
        # The real field is <iUnitCombatCollateralImmune>, not the b-prefixed
        # name the container's singular tag suggests - checking the wrong one
        # reports every siege unit as taking full collateral from its own kind.
        "".join(
            "<UnitCombatCollateralImmune><UnitCombatType>%s</UnitCombatType>"
            "<iUnitCombatCollateralImmune>1</iUnitCombatCollateralImmune>"
            "</UnitCombatCollateralImmune>" % c
            for c in collateral_immune
        ),
        1 if only_defensive else 0, 1 if ignore_terrain_cost else 0,
        interception, collateral_damage, collateral_damage_limit,
        collateral_damage_max_units, animal_combat, 1 if is_animal else 0,
        hills_defense, combat_limit,
        "".join(
            "<FlankingStrike><FlankingStrikeUnitClass>%s"
            "</FlankingStrikeUnitClass>"
            "<iFlankingStrength>%d</iFlankingStrength></FlankingStrike>" % f
            for f in flanking
        ),
        # off_promotions carry <bFreePromotion>0</bFreePromotion>: entries that
        # are present but explicitly turned OFF, which is what stops the parser
        # taking every PromotionType in the container.
        "".join(
            "<FreePromotion><PromotionType>%s</PromotionType>"
            "<bFreePromotion>%d</bFreePromotion></FreePromotion>" % (p, flag)
            for p, flag in ([(p, 1) for p in free_promotions]
                            + [(p, 0) for p in off_promotions])
        ),
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


def _handicap(type_key, research=100, goodies=(), **fields):
    body = "".join("<%s>%d</%s>" % (k, v, k) for k, v in sorted(fields.items()))
    # Repeats are the weighting - the real file has no probability field, just
    # a flat list with duplicates - so this is written as a list and the
    # fixtures below deliberately repeat entries.
    table = "".join("<GoodyType>%s</GoodyType>" % g for g in goodies)
    return """
    <HandicapInfo>
      <Type>%s</Type>
      <iResearchPercent>%d</iResearchPercent>
      <Goodies>%s</Goodies>
      %s
    </HandicapInfo>""" % (type_key, research, table, body)


def _goody(type_key, **fields):
    """A GoodyInfo block. Every field defaults to 0/NONE, as in the real file."""
    defaults = {
        "iGold": 0, "iGoldRand1": 0, "iGoldRand2": 0, "iMapOffset": 0,
        "iMapRange": 0, "iMapProb": 0, "iExperience": 0, "iHealing": 0,
        "iDamagePrereq": 0, "bTech": 0, "bBad": 0,
    }
    defaults.update((k, v) for k, v in fields.items() if k.startswith(("i", "b")))
    body = "".join("<%s>%s</%s>" % (k, v, k) for k, v in sorted(defaults.items()))
    return """
    <GoodyInfo>
      <Type>%s</Type>
      %s
      <UnitClass>%s</UnitClass>
      <BarbarianClass>%s</BarbarianClass>
      <iBarbarianUnitProb>%d</iBarbarianUnitProb>
      <iMinBarbarians>%d</iMinBarbarians>
    </GoodyInfo>""" % (
        type_key, body,
        fields.get("UnitClass", "NONE"), fields.get("BarbarianClass", "NONE"),
        fields.get("iBarbarianUnitProb", 0), fields.get("iMinBarbarians", 0),
    )


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
        # Shaped like BONUS_CORN: a bare +1 food of its own, and separately a
        # +2 on the farm improvement. The pair is the whole point - reporting
        # one and not the other is the bug this file exists to pin down.
        """<BonusInfo><Type>BONUS_TESTCORN</Type>
            <TechReveal>NONE</TechReveal>
            <TechCityTrade>TECH_ROOT_A</TechCityTrade>
            <YieldChanges>
              <iYieldChange>1</iYieldChange>
              <iYieldChange>0</iYieldChange>
              <iYieldChange>0</iYieldChange>
            </YieldChanges></BonusInfo>""",
    ])
    (vanilla / "Terrain" / "CIV4BonusInfos.xml").write_text(bonuses, encoding="latin-1")

    # Terrain, features and the per-yield table. Numbers match the real files
    # for the cases under test: grass 2 food, hills -1 food/+1 hammer, the
    # city floor at 2/1/1.
    terrains = "<Civ4TerrainInfos><TerrainInfos>%s</TerrainInfos></Civ4TerrainInfos>" % "".join([
        """<TerrainInfo><Type>TERRAIN_TESTGRASS</Type>
             <Yields><iYield>2</iYield><iYield>0</iYield><iYield>0</iYield></Yields>
             <RiverYieldChange>
               <iYield>0</iYield><iYield>0</iYield><iYield>1</iYield>
             </RiverYieldChange></TerrainInfo>""",
        # No <Yields> at all, exactly as desert and snow are written.
        """<TerrainInfo><Type>TERRAIN_TESTDESERT</Type></TerrainInfo>""",
        # Carries commerce of its own, so a tile can reach Financial's
        # 2-commerce threshold without needing two river-shaped terms.
        """<TerrainInfo><Type>TERRAIN_TESTCOAST</Type>
             <Yields><iYield>1</iYield><iYield>0</iYield><iYield>2</iYield></Yields>
           </TerrainInfo>""",
    ])
    (root / "Terrain" / "CIV4TerrainInfos.xml").write_text(terrains, encoding="latin-1")

    features = "<Civ4FeatureInfos><FeatureInfos>%s</FeatureInfos></Civ4FeatureInfos>" % "".join([
        """<FeatureInfo><Type>FEATURE_FOREST</Type>
             <YieldChanges>
               <iYieldChange>0</iYieldChange>
               <iYieldChange>1</iYieldChange>
               <iYieldChange>0</iYieldChange>
             </YieldChanges></FeatureInfo>""",
        """<FeatureInfo><Type>FEATURE_TESTJUNGLE</Type>
             <YieldChanges>
               <iYieldChange>-1</iYieldChange>
               <iYieldChange>0</iYieldChange>
               <iYieldChange>0</iYieldChange>
             </YieldChanges></FeatureInfo>""",
        # Shaped like FEATURE_FLOOD_PLAINS: a food yield change, and named by
        # NO build's FeatureStructs above - so no build removes it and it
        # survives whatever gets built on top. The stock files have exactly
        # one such feature, which is why "an improvement clears the feature"
        # looked like a safe simplification for as long as it did.
        """<FeatureInfo><Type>FEATURE_TESTFLOOD</Type>
             <YieldChanges>
               <iYieldChange>3</iYieldChange>
               <iYieldChange>0</iYieldChange>
               <iYieldChange>0</iYieldChange>
             </YieldChanges></FeatureInfo>""",
    ])
    (root / "Terrain" / "CIV4FeatureInfos.xml").write_text(features, encoding="latin-1")

    yields = "<Civ4YieldInfos><YieldInfos>%s</YieldInfos></Civ4YieldInfos>" % "".join([
        """<YieldInfo><Type>YIELD_FOOD</Type><iHillsChange>-1</iHillsChange>
             <iPeakChange>0</iPeakChange><iLakeChange>1</iLakeChange>
             <iMinCity>2</iMinCity></YieldInfo>""",
        """<YieldInfo><Type>YIELD_PRODUCTION</Type><iHillsChange>1</iHillsChange>
             <iPeakChange>0</iPeakChange><iLakeChange>0</iLakeChange>
             <iMinCity>1</iMinCity></YieldInfo>""",
        """<YieldInfo><Type>YIELD_COMMERCE</Type><iHillsChange>0</iHillsChange>
             <iPeakChange>0</iPeakChange><iLakeChange>0</iLakeChange>
             <iMinCity>1</iMinCity></YieldInfo>""",
    ])
    (root / "Terrain" / "CIV4YieldInfos.xml").write_text(yields, encoding="latin-1")

    # Shaped like the real IMPROVEMENT_FARM: no flat yield of its own, the
    # +1 irrigated, a bonus struct that BOTH adds yield and makes the tile
    # valid, and a late tech yield. Every one of those four is a term that
    # was dropped by some intermediate version of the parser.
    improvements = "<Civ4ImprovementInfos><ImprovementInfos>%s</ImprovementInfos></Civ4ImprovementInfos>" % "".join([
        """<ImprovementInfo>
             <Type>IMPROVEMENT_TESTFARM</Type>
             <PrereqNatureYields>
               <iYield>1</iYield><iYield>0</iYield><iYield>0</iYield>
             </PrereqNatureYields>
             <IrrigatedYieldChange>
               <iYield>1</iYield><iYield>0</iYield><iYield>0</iYield>
             </IrrigatedYieldChange>
             <bRequiresFlatlands>1</bRequiresFlatlands>
             <bFreshWaterMakesValid>1</bFreshWaterMakesValid>
             <bRequiresIrrigation>1</bRequiresIrrigation>
             <TerrainMakesValids>
               <TerrainMakesValid>
                 <TerrainType>TERRAIN_TESTGRASS</TerrainType>
                 <bMakesValid>1</bMakesValid>
               </TerrainMakesValid>
             </TerrainMakesValids>
             <BonusTypeStructs>
               <BonusTypeStruct>
                 <BonusType>BONUS_TESTCORN</BonusType>
                 <bBonusMakesValid>1</bBonusMakesValid>
                 <!-- Paired with bBonusMakesValid on every struct in both
                      real trees (checked); bBonusTrade is what actually
                      connects the resource to the trade network. -->
                 <bBonusTrade>1</bBonusTrade>
                 <YieldChanges>
                   <iYieldChange>2</iYieldChange>
                   <iYieldChange>0</iYieldChange>
                   <iYieldChange>0</iYieldChange>
                 </YieldChanges>
               </BonusTypeStruct>
             </BonusTypeStructs>
             <TechYieldChanges>
               <TechYieldChange>
                 <PrereqTech>TECH_SIMPLE</PrereqTech>
                 <TechYields>
                   <iYield>1</iYield><iYield>0</iYield><iYield>0</iYield>
                 </TechYields>
               </TechYieldChange>
             </TechYieldChanges>
           </ImprovementInfo>""",
        """<ImprovementInfo>
             <Type>IMPROVEMENT_TESTMINE</Type>
             <YieldChanges>
               <iYieldChange>0</iYieldChange>
               <iYieldChange>2</iYieldChange>
               <iYieldChange>0</iYieldChange>
             </YieldChanges>
             <bHillsMakesValid>1</bHillsMakesValid>
           </ImprovementInfo>""",
    ])
    (root / "Terrain" / "CIV4ImprovementInfos.xml").write_text(
        improvements, encoding="latin-1")

    # Financial, as the only trait with a yield effect, plus a leader carrying
    # it. The state file exports a leader and no traits, so this join is the
    # only route to "is this player FIN".
    (vanilla / "Civilizations").mkdir(parents=True, exist_ok=True)
    traits = "<Civ4TraitInfos><TraitInfos>%s</TraitInfos></Civ4TraitInfos>" % """
        <TraitInfo><Type>TRAIT_TESTFIN</Type>
          <ExtraYieldThresholds>
            <iExtraYieldThreshold>0</iExtraYieldThreshold>
            <iExtraYieldThreshold>0</iExtraYieldThreshold>
            <iExtraYieldThreshold>2</iExtraYieldThreshold>
          </ExtraYieldThresholds></TraitInfo>"""
    (vanilla / "Civilizations" / "CIV4TraitInfos.xml").write_text(
        traits, encoding="latin-1")

    (root / "Civilizations").mkdir(parents=True, exist_ok=True)
    leaders = "<Civ4LeaderHeadInfos><LeaderHeadInfos>%s</LeaderHeadInfos></Civ4LeaderHeadInfos>" % "".join([
        """<LeaderHeadInfo><Type>LEADER_TESTFIN</Type>
             <Traits><Trait><TraitType>TRAIT_TESTFIN</TraitType></Trait></Traits>
           </LeaderHeadInfo>""",
        """<LeaderHeadInfo><Type>LEADER_TESTPLAIN</Type><Traits/>
           </LeaderHeadInfo>""",
    ])
    (root / "Civilizations" / "CIV4LeaderHeadInfos.xml").write_text(
        leaders, encoding="latin-1")

    # A file present in BOTH trees, to prove BTS wins.
    for tree, marker in ((root, "BTS"), (vanilla, "VANILLA")):
        (tree / "GameInfo" / "CIV4CivicInfos.xml").write_text(
            "<Civ4CivicInfos><CivicInfos>"
            "<CivicInfo><Type>CIVIC_%s_ONLY</Type>"
            "<TechPrereq>TECH_SIMPLE</TechPrereq></CivicInfo>"
            "</CivicInfos></Civ4CivicInfos>" % marker,
            encoding="latin-1",
        )

    builds = "<Civ4BuildInfos><BuildInfos>%s</BuildInfos></Civ4BuildInfos>" % "".join([
        """
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
        </BuildInfo>""",
        # The improvement's tech lives HERE, not on the ImprovementInfo -
        # every stock ImprovementInfo has an empty <PrereqTech>.
        """
        <BuildInfo>
          <Type>BUILD_TESTFARM</Type>
          <PrereqTech>TECH_ROOT_A</PrereqTech>
          <ImprovementType>IMPROVEMENT_TESTFARM</ImprovementType>
          <FeatureStructs/>
        </BuildInfo>""",
    ])
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
        # The two sides of the animal matchup. On the real install UNIT_SCOUT is
        # the only unit with a non-zero iAnimalCombat, and exactly four units
        # are bAnimal.
        _unit("UNIT_SCOUTER", "TECH_ROOT_A", unit_class="UNITCLASS_SCOUTER",
              strength=1, animal_combat=100, no_bad_goodies=True),
        _unit("UNIT_BEASTIE", "TECH_ROOT_A", unit_class="UNITCLASS_BEASTIE",
              strength=2, combat="NONE", cost=0, is_animal=True),
        # Hills defence, ignored terrain cost and free promotions - three
        # fields the file parsed or ignored but never printed, each real on the
        # install (Archer +25% on hills; Explorer ignores terrain cost and
        # starts with Guerilla1 + Woodsman1). PROMOTION_OFF is present but
        # flagged off, so it must NOT be reported as free.
        _unit("UNIT_HILLMAN", "TECH_ROOT_A", unit_class="UNITCLASS_HILLMAN",
              hills_defense=25),
        # The two sides of a class counter, which the engine keeps in separate
        # containers: the Chariot's +100% applies only when IT attacks, the
        # Greek Phalanx's only when it DEFENDS. Same number, opposite advice.
        _unit("UNIT_RIDER", "TECH_ROOT_A", unit_class="UNITCLASS_RIDER",
              class_attack_mods=[("UNITCLASS_X", 100)]),
        _unit("UNIT_BLOCKER", "TECH_ROOT_A", unit_class="UNITCLASS_BLOCKER",
              class_defense_mods=[("UNITCLASS_RIDER", 100)]),
        # A capped-damage unit (the Catapult's 75) and a flanker. Flanking is
        # per target class, so UNIT_FLANKER must NOT read as flanking anything
        # other than the class it names.
        _unit("UNIT_SIEGE", "TECH_ROOT_A", unit_class="UNITCLASS_SIEGE",
              combat_limit=75, collateral_damage=100,
              collateral_damage_limit=50, collateral_damage_max_units=6,
              bombard_rate=8, collateral_immune=["UNITCOMBAT_SIEGE"]),
        # Carries the collateral LIMIT and MAX-UNITS but deals no collateral -
        # exactly the shape of a Knight, which reuses those two fields for
        # flanking damage. 25 units on the install look like this, so gating
        # the output on the limit would report every one of them as siege.
        _unit("UNIT_FLANKER", "TECH_ROOT_A", unit_class="UNITCLASS_FLANKER",
              flanking=[("UNITCLASS_SIEGE", 100)], first_strike_immune=True,
              collateral_damage_limit=100, collateral_damage_max_units=6),
        # The attacking half of the city matchup, and the building-defence
        # bypass. UNIT_DEFENDER above holds the defending half.
        _unit("UNIT_STORMER", "TECH_ROOT_A", unit_class="UNITCLASS_STORMER",
              city_attack=10, ignore_building_defense=True),
        _unit("UNIT_ROAMER", "TECH_ROOT_A", unit_class="UNITCLASS_ROAMER",
              ignore_terrain_cost=True,
              free_promotions=["PROMOTION_TESTER"],
              off_promotions=["PROMOTION_ARCHER_ONLY"]),
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

    # Ten-entry draw tables rather than the real twenty, so the arithmetic in
    # the assertions is checkable by eye. HARD carries 2 hostile entries (20%
    # raw), EASY none - the real spread between difficulties, in miniature.
    handicaps = "<Civ4HandicapInfos><HandicapInfos>%s</HandicapInfos></Civ4HandicapInfos>" % "".join([
        _handicap("HANDICAP_EASY", research=75, iAnimalAttackProb=85,
                  iAnimalBonus=-40, iFreeWinsVsBarbs=2,
                  iBarbarianCreationTurnsElapsed=35,
                  goodies=(["GOODY_TESTGOLD"] * 6 + ["GOODY_TESTMAP"] * 2
                           + ["GOODY_TESTXP", "GOODY_TESTWARRIOR"])),
        _handicap("HANDICAP_HARD", research=120, iAnimalAttackProb=90,
                  iAnimalBonus=-10, iFreeWinsVsBarbs=0,
                  iBarbarianCreationTurnsElapsed=20,
                  goodies=(["GOODY_TESTGOLD"] * 4 + ["GOODY_TESTMAP"] * 2
                           + ["GOODY_TESTXP", "GOODY_TESTWARRIOR"]
                           + ["GOODY_TESTBARBS"] * 2)),
    ])
    (root / "GameInfo" / "CIV4HandicapInfo.xml").write_text(handicaps, encoding="latin-1")

    # VANILLA-ONLY, exactly like CIV4BonusInfos.xml above and like the real
    # install: BTS ships no override, so a BTS-only lookup finds nothing.
    goodies = "<Civ4GoodyInfo><GoodyInfos>%s</GoodyInfos></Civ4GoodyInfo>" % "".join([
        _goody("GOODY_TESTGOLD", iGold=20, iGoldRand1=21, iGoldRand2=21),
        _goody("GOODY_TESTMAP", iMapRange=4, iMapProb=80),
        _goody("GOODY_TESTXP", iExperience=5),
        _goody("GOODY_TESTHEAL", iHealing=100, iDamagePrereq=60),
        # A combat, non-only-defensive unit: withheld before turn 20.
        _goody("GOODY_TESTWARRIOR", UnitClass="UNITCLASS_X"),
        _goody("GOODY_TESTBARBS", bBad=1, BarbarianClass="UNITCLASS_X",
               iBarbarianUnitProb=40, iMinBarbarians=2),
    ])
    (vanilla / "GameInfo" / "CIV4GoodyInfo.xml").write_text(
        goodies, encoding="latin-1")

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
               civilization=None, units=None, options=(),
               map_width=40, map_height=20, wrap_x=True,
               leader="LEADER_TEST", contacts=None, player_id=0):
    # Map dimensions default to a wrapping cylinder, matching the real setup -
    # `goody`'s distance check folds x around the map, and a non-wrapping
    # fixture would never exercise that path.
    state = {
        "meta": {"schemaVersion": 2},
        "game": {"gameTurn": turn, "handicap": handicap, "worldSize": world,
                 "gameSpeed": speed, "options": list(options),
                 "mapWidth": map_width, "mapHeight": map_height,
                 "wrapX": wrap_x, "wrapY": False},
        "player": {"leader": leader, "knownTechs": list(known),
                   "id": player_id,
                   "beakersPerTurn": rate,
                   "research": research or {}},
        "map": {"tiles": list(tiles)},
    }
    if contacts is not None:
        state["contacts"] = list(contacts)
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


def test_unit_parses_the_animal_combat_bonus_and_the_animal_flag(
        xml_root, tmp_path):
    """iAnimalCombat lives in its own field rather than <UnitCombatMods>, which
    is why it was missed: a trial hand-estimated a Scout's odds against a Lion
    and flagged the number as a guess, never having seen the +100%."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_SCOUTER"]["animal_combat"] == 100
    assert r.units["UNIT_SCOUTER"]["is_animal"] is False
    assert r.units["UNIT_BEASTIE"]["is_animal"] is True
    # The default, which is what nearly every unit in the real file carries.
    assert r.units["UNIT_TESTER"]["animal_combat"] == 0
    assert r.units["UNIT_TESTER"]["is_animal"] is False


def test_unit_view_prints_the_animal_bonus_beside_other_combat_mods(
        xml_root, tmp_path):
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    text = rules.view_unit(r, "UNIT_SCOUTER", state, False, None)
    assert "+100% vs animals" in text

    # The other side of the matchup, so a lookup on the animal answers the
    # same question rather than going silent.
    beast = rules.view_unit(r, "UNIT_BEASTIE", state, False, None)
    assert "counts as an animal" in beast

    # A unit with neither says nothing about animals at all - the field is
    # zero on nearly every unit, so printing it unconditionally is noise.
    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "animal" not in plain.lower()


def test_animal_view_names_the_bonus_holders_from_the_data(xml_root, tmp_path):
    """The holder is looked up, not hardcoded to UNIT_SCOUT. It is the only one
    on the stock install, but that is a fact about the data rather than a rule -
    a hardcoded name reads as an engine special case and goes wrong under a mod
    without anything to catch it."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    text = rules.view_unit(r, "UNIT_BEASTIE", state, False, None)
    assert "UNIT_SCOUTER" in text
    assert "UNIT_SCOUT" not in text.replace("UNIT_SCOUTER", "")

    # Give a second unit the bonus and both are named, with the verb agreeing.
    r.units["UNIT_TESTER"]["animal_combat"] = 50
    both = rules.view_unit(r, "UNIT_BEASTIE", state, False, None)
    assert "UNIT_SCOUTER, UNIT_TESTER have" in both

    # And with none, it falls back to the general statement rather than
    # printing an empty list.
    r.units["UNIT_TESTER"]["animal_combat"] = 0
    r.units["UNIT_SCOUTER"]["animal_combat"] = 0
    none = rules.view_unit(r, "UNIT_BEASTIE", state, False, None)
    assert "units with an animal combat bonus" in none


def test_unit_class_mods_are_parsed_and_keep_attack_apart_from_defence(
        xml_root, tmp_path):
    """A Chariot's +100% vs UNITCLASS_AXEMAN lives in <UnitClassAttackMods>,
    a different container from the <UnitCombatMods> the parser already read -
    so the unit's signature ability was printed nowhere. Attack and defence
    stay separate because they are opposite advice: the Chariot's bonus is a
    reason to attack, the Greek Phalanx's +100% vs chariots a reason to sit."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_RIDER"]["class_mods"]["attacking"] == [
        ("UNITCLASS_X", 100)]
    assert r.units["UNIT_RIDER"]["class_mods"]["defending vs"] == []
    assert r.units["UNIT_BLOCKER"]["class_mods"]["defending vs"] == [
        ("UNITCLASS_RIDER", 100)]
    assert r.units["UNIT_BLOCKER"]["class_mods"]["attacking"] == []

    attacker = rules.view_unit(r, "UNIT_RIDER", state, False, None)
    assert "+100% attacking UNITCLASS_X" in attacker
    assert "defending" not in attacker

    defender = rules.view_unit(r, "UNIT_BLOCKER", state, False, None)
    assert "+100% defending vs UNITCLASS_RIDER" in defender
    assert "attacking" not in defender

    # A unit with neither container gets no class-modifier line. Asserted on
    # the abilities wording rather than on "UNITCLASS" appearing anywhere:
    # SAME TECH ALSO UNLOCKS legitimately prints unit classes, so the bare
    # substring is not evidence of a modifier.
    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "attacking UNITCLASS" not in plain
    assert "defending vs UNITCLASS" not in plain


def test_no_bad_goodies_first_strike_immunity_and_collateral_immunity(
        xml_root, tmp_path):
    """Three fields found by auditing the whole UnitInfo block rather than
    reacting to a question. The first matters most: only the Scout and Explorer
    carry bNoBadGoodies, so the hut that killed a trial's Warrior could not
    have killed a Scout - which is a fact about WHICH UNIT to send, and the
    goody-hut odds alone never say it."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    scout = rules.view_unit(r, "UNIT_SCOUTER", state, False, None)
    assert r.units["UNIT_SCOUTER"]["no_bad_goodies"] is True
    assert "never triggers a hostile result from a goody hut" in scout

    # Siege is immune to its own collateral, which is why massed catapults
    # do not grind each other down.
    assert r.units["UNIT_SIEGE"]["collateral_immune"] == ["UNITCOMBAT_SIEGE"]
    siege = rules.view_unit(r, "UNIT_SIEGE", state, False, None)
    assert "immune to collateral damage from UNITCOMBAT_SIEGE" in siege

    flanker = rules.view_unit(r, "UNIT_FLANKER", state, False, None)
    assert "immune to first strikes" in flanker

    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "goody hut" not in plain
    assert "immune" not in plain


def test_bombard_rate_is_reported_as_its_own_mechanic(xml_root, tmp_path):
    """Bombardment strips a CITY'S DEFENCE BONUS and is a third mechanic
    distinct from collateral damage (which hits units in a stack) and from
    iCityAttack (a combat modifier). The Catapult carries all three plus a
    combat limit, and listing any one of them alone misdescribes the unit."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_SIEGE"]["bombard_rate"] == 8
    assert r.units["UNIT_TESTER"]["bombard_rate"] == 0

    text = rules.view_unit(r, "UNIT_SIEGE", state, False, None)
    assert "bombards a city's defence bonus down by 8 points per turn" in text
    # All four siege facts present together, which is the point.
    assert "collateral damage" in text
    assert "cannot make the kill" in text

    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "bombard" not in plain


def test_collateral_damage_is_gated_on_dealing_it_not_on_the_limit(
        xml_root, tmp_path):
    """iCollateralDamageLimit and MaxUnits are non-zero on 25 units that deal
    NO collateral damage - flanking reuses the same two fields. Gating the
    output on the limit would report a Knight as a siege unit."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    siege = rules.view_unit(r, "UNIT_SIEGE", state, False, None)
    assert "collateral damage to up to 6 other units" in siege
    assert "each down to 50% health" in siege

    # Has the limit and the cap, deals none: must stay silent.
    flanker = rules.view_unit(r, "UNIT_FLANKER", state, False, None)
    assert r.units["UNIT_FLANKER"]["collateral_damage_limit"] == 100
    assert "collateral" not in flanker

    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "collateral" not in plain


def test_city_attack_and_building_defence_bypass_are_printed(
        xml_root, tmp_path):
    """iCityDefense was printed while iCityAttack was not, so the view showed
    one half of the assault matchup and hid the other. bIgnoreBuildingDefense
    is a unit flag about a BUILDING effect, so it names what it ignores rather
    than echoing the field name."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_STORMER"]["city_attack"] == 10
    assert r.units["UNIT_STORMER"]["ignore_building_defense"] is True

    text = rules.view_unit(r, "UNIT_STORMER", state, False, None)
    assert "+10% attacking cities" in text
    assert "ignores a city's building defence bonus" in text

    # The defending half still prints, and prints nothing about attacking.
    defender = rules.view_unit(r, "UNIT_DEFENDER", state, False, None)
    assert "+50% city defence" in defender
    assert "attacking cities" not in defender

    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "attacking cities" not in plain
    assert "building defence" not in plain


def test_combat_limit_prints_only_for_a_real_cap(xml_root, tmp_path):
    """iCombatLimit is 100 (no cap) on 83 units and 0 (non-combat) on 34, so
    printing it unconditionally would put a meaningless line on nearly every
    unit. Only six carry a real limit - and the Catapult's 75 is the one that
    matters early: siege damages a stack but cannot land the killing blow."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_SIEGE"]["combat_limit"] == 75
    assert r.units["UNIT_TESTER"]["combat_limit"] == 100

    capped = rules.view_unit(r, "UNIT_SIEGE", state, False, None)
    assert "damages only to 75% health" in capped
    assert "cannot make the kill" in capped

    # The default prints nothing rather than "damages only to 100%".
    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "damages only to" not in plain

    # Nor does a non-combat unit, whose strength 0 already says it.
    r.units["UNIT_TESTER"]["combat_limit"] = 0
    noncombat = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "damages only to" not in noncombat


def test_flanking_is_parsed_per_target_class_not_as_a_flat_stat(
        xml_root, tmp_path):
    """<FlankingStrikes> is a list of (class, strength) pairs. A bare sweep for
    <iFlankingStrength> finds the nested values and reads as though the unit
    flanked everything - a Horse Archer flanks catapults and trebuchets only."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_FLANKER"]["flanking"] == [("UNITCLASS_SIEGE", 100)]
    assert r.units["UNIT_TESTER"]["flanking"] == []

    text = rules.view_unit(r, "UNIT_FLANKER", state, False, None)
    assert "flanking strike vs UNITCLASS_SIEGE" in text
    # The named class, and no other - the whole point of parsing the pairs.
    assert "flanking strike vs UNITCLASS_X" not in text

    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "flanking" not in plain


def test_unit_view_prints_hills_defence_and_ignored_terrain_cost(
        xml_root, tmp_path):
    """Both were readable in the XML and neither was printed: an Archer's +25%
    on hills, and the Explorer's ignored terrain cost - which was already
    parsed for the promotion cascade and simply never surfaced."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)

    hills = rules.view_unit(r, "UNIT_HILLMAN", state, False, None)
    assert "+25% defence on hills" in hills

    roamer = rules.view_unit(r, "UNIT_ROAMER", state, False, None)
    assert "ignores terrain movement cost" in roamer

    plain = rules.view_unit(r, "UNIT_TESTER", state, False, None)
    assert "hills" not in plain.lower()
    assert "terrain movement cost" not in plain


def test_free_promotions_are_parsed_and_the_off_flag_is_honoured(
        xml_root, tmp_path):
    """<FreePromotions> is a list of (promotion, flag) pairs, so a flat sweep
    of PromotionType would also collect entries explicitly turned off."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.units["UNIT_ROAMER"]["free_promotions"] == ["PROMOTION_TESTER"]
    assert r.units["UNIT_TESTER"]["free_promotions"] == []

    text = rules.view_unit(r, "UNIT_ROAMER", state, False, None)
    assert "starts with PROMOTION_TESTER" in text
    assert "PROMOTION_ARCHER_ONLY" not in text
    # Points at the subcommand that says what they do - a bare promotion name
    # is a name, not an explanation.
    assert "`rules.py promotion`" in text


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
    available, _blocked = rules._promotable_promotions(
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
    # Matched on the banner's own sentence rather than on "are NOT", which
    # `goody-hut-outcomes` made ambiguous: a field description in the same
    # view now reads "huts are NOT gated by it", so the loose matcher failed
    # on output that was entirely correct.
    assert "and are NOT" not in own
    assert "run without a TYPE" not in own


def test_handicap_view_explains_the_negative_bonus_sign(xml_root, tmp_path):
    """-40 reads as "animals are stronger" unless the sign is explained."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_handicap(r, "HANDICAP_EASY", state)
    assert "TO THE ANIMAL" in text
    assert "negative = weaker" in text


def test_handicap_view_carries_no_turn_window_advice(xml_root, tmp_path):
    """The advising-window scope is prompt guidance and has deliberately never
    been in code - the player may use this tool at any turn."""
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_handicap(r, "HANDICAP_HARD", state)
    assert "turns 0-50" not in text.lower()
    assert "0-50" not in text


def test_handicap_view_denies_that_its_turn_fields_gate_goody_huts(
        xml_root, tmp_path):
    """The exact false inference that cost a live trial its only unit.

    The agent read iBarbarianCreationTurnsElapsed off this block and concluded
    a hut was safe to pop for another 16 turns. Nothing in the output could
    contradict it, so the field's own description now carries the qualifier and
    OMITS points at the subcommand that actually answers the question.
    """
    _, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    text = rules.view_handicap(r, "HANDICAP_HARD", state)
    assert "MAP-SPAWNED" in text
    assert "huts are NOT gated by it" in text
    assert "rules.py goody" in text


# ---------------------------------------------------------------------------
# goody - what a hut can produce
# ---------------------------------------------------------------------------


def test_goody_view_weights_outcomes_by_their_repeats(xml_root, tmp_path):
    """The draw table has no probability field: multiplicity IS the weight.

    HARD's fixture table is 10 entries, 4 of them GOODY_TESTGOLD, so a correct
    reading is 40% and a set-based one would say 10%.
    """
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city(), make_city(name="Second")])
    r = build_rules(xml_root, state)
    text = rules.view_goody(r, None, state)
    assert "GOODY_TESTGOLD" in text
    # The share is the assertion now that the raw `Nx` column is gone: 4 of 10
    # entries is 40%, where a set-based reading would print 10%.
    assert "40.0%" in text


def test_goody_view_states_that_the_spawn_timer_does_not_gate_huts(
        xml_root, tmp_path):
    """The headline correction. iBarbarianCreationTurnsElapsed is 20 on HARD,
    and a hut can still turn hostile on turn 1."""
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=1,
                          cities=[make_city(), make_city(name="Second")])
    r = build_rules(xml_root, state)
    text = rules.view_goody(r, None, state)
    assert "iBarbarianCreationTurnsElapsed does NOT gate huts" in text
    assert "hostile on turn 1" in text


def test_goody_view_never_calls_a_hut_safe_or_unsafe(xml_root, tmp_path):
    """Presentation, not a verdict - the line every view in this module holds.

    Here it is load-bearing rather than stylistic: whether a specific hut is
    inside the one-city protection radius depends on which hut, and this view
    is given no plot. A verdict would have to invent that.
    """
    for turn, cities in ((1, []), (9, [make_city()]), (34, [make_city()])):
        _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=turn,
                              cities=cities)
        r = build_rules(xml_root, state)
        text = rules.view_goody(r, None, state).lower()
        assert "safe" not in text
        assert "unsafe" not in text
        assert "you should" not in text


def test_goody_view_renormalises_over_what_can_actually_be_drawn(
        xml_root, tmp_path):
    """The finding that makes this more than a table print.

    The engine RE-DRAWS when an outcome is ineligible rather than skipping it,
    so a blocked entry's weight lands on the rows that remain - including the
    hostile ones. At turn 9 the XP and free-warrior rows are both gated off, so
    the hostile share must be reported HIGHER than its raw 20%.
    """
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=9,
                          cities=[make_city(), make_city(name="Second")])
    r = build_rules(xml_root, state)
    text = rules.view_goody(r, None, state)

    assert "not before turn 10" in text          # GOODY_TESTXP
    assert "combat unit, not before turn 20" in text  # GOODY_TESTWARRIOR
    # 2 hostile of 10 raw = 20%; 8 entries remain eligible -> 2/8 = 25%.
    assert _hostile_chance(text) == 25.0
    assert "above the 20.0%" in text


def test_goody_view_excludes_hostile_rows_for_a_no_bad_goodies_unit(
        xml_root, tmp_path):
    """The interaction the ROADMAP asked for by name.

    The trial's Warrior died to a roll a Scout was immune to, and the
    distribution alone never says so. With such a unit named, the hostile rows
    are not merely unlikely - they cannot be drawn, and their weight
    redistributes onto the good outcomes.
    """
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city(), make_city(name="Second")])
    r = build_rules(xml_root, state)

    text = rules.view_goody(r, None, state, "UNIT_SCOUTER")
    assert "UNIT_SCOUTER can never draw a hostile result" in text
    assert "UNIT_SCOUTER carries bNoBadGoodies" in text

    # The headline must agree with the row-level exclusion rather than being
    # computed off the raw table - a hostile share of 20% printed beside
    # "cannot draw a hostile result" is the contradiction this guards.
    assert _hostile_chance(text) == 0.0

    # And a unit without the flag still gets the immunity stated, naming the
    # units that do carry it rather than passing over it in silence.
    other = rules.view_goody(r, None, state, "UNIT_TESTER")
    assert "UNIT_SCOUTER" in other
    assert "UNIT_TESTER can never draw" not in other
    assert _hostile_chance(other) > 0.0


def test_goody_view_always_names_the_immune_units_unprompted(
        xml_root, tmp_path):
    """The trial failed because nobody knew to ask, so the immunity cannot be
    gated behind the flag that requires knowing about it."""
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city(), make_city(name="Second")])
    r = build_rules(xml_root, state)
    text = rules.view_goody(r, None, state)
    assert "UNIT_SCOUTER" in text
    assert "cannot draw a hostile result" in text
    assert "--for-unit" in text


def test_goody_view_reports_the_one_city_protection_as_conditional(
        xml_root, tmp_path):
    """Blocked-within-N-tiles is not a flat exclusion - it depends which hut.

    So the row stays eligible (its weight is really drawn) and the condition is
    printed beside it, rather than being silently counted either way. It also
    ENDS at the second city, which is the opposite of what a player assumes.
    """
    _, one = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                        cities=[make_city()])
    r = build_rules(xml_root, one)
    text = rules.view_goody(r, None, one)
    assert "blocked within 7 tiles of your only city" in text

    _, two = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                        cities=[make_city(), make_city(name="Second")])
    both = rules.view_goody(r, None, two)
    assert "only city" not in both


def test_goody_view_does_not_claim_a_named_unit_is_undamaged(
        xml_root, tmp_path):
    """--popped-by takes a unit TYPE, which says nothing about that unit's
    damage - a healthy Warrior and a half-dead one are the same string.

    So the healing row must stay conditional rather than becoming CANNOT.
    Asserting an exclusion the tool cannot see is the exact failure mode this
    subcommand was built to remove, and it would also understate the hostile
    share by shrinking the eligible pool.
    """
    _, state = make_state(tmp_path, handicap="HANDICAP_EASY", turn=34,
                          cities=[make_city()])
    r = build_rules(xml_root, state)
    # GOODY_TESTHEAL is not in either fixture draw table, so drive the gate
    # directly rather than through a table that cannot reach it.
    reason = rules._goody_eligibility(
        r, r.goodies["GOODY_TESTHEAL"], state, r.units["UNIT_TESTER"])
    assert reason.startswith("conditional:")
    assert "60%" in reason


def test_goody_view_never_prints_the_conditional_sentinel(xml_root, tmp_path):
    """`conditional:` is an internal marker on the reason string, and stripping
    it is easy to break silently - the row would still render, just with a
    stray keyword in front of the prose."""
    for cities in ([], [make_city()], [make_city(), make_city(name="Second")]):
        _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                              cities=cities)
        r = build_rules(xml_root, state)
        assert "conditional:" not in rules.view_goody(r, None, state)


def test_goody_view_excludes_hostiles_with_no_cities_and_with_the_option_off(
        xml_root, tmp_path):
    """Two hard exclusions the engine really applies, and both surprise."""
    _, none = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                         cities=[])
    r = build_rules(xml_root, none)
    assert "you have no cities yet" in rules.view_goody(r, None, none)

    _, off = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                        cities=[make_city()],
                        options=["GAMEOPTION_NO_BARBARIANS"])
    assert "GAMEOPTION_NO_BARBARIANS is on" in rules.view_goody(r, None, off)


def test_goody_view_states_the_guaranteed_floor_not_just_the_probability(
        xml_root, tmp_path):
    """iBarbarianUnitProb is how many MORE, never whether any at all.

    The engine makes a second pass that ignores the roll until iMinBarbarians
    is met, so reading 40% as "40% chance of trouble" understates it to zero
    risk 60% of the time when the real floor is 2 units, guaranteed.
    """
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city(), make_city(name="Second")])
    r = build_rules(xml_root, state)
    text = rules.view_goody(r, None, state)
    assert "2+ UNITCLASS_X adjacent, guaranteed" in text
    # And the 40% must NOT appear on the row: printed beside a hostile outcome
    # it reads as the chance of being attacked, which is exactly backwards.
    hostile_row = [ln for ln in text.splitlines() if "TESTBARBS" in ln][0]
    assert "40" not in hostile_row


def test_goody_view_handles_a_difficulty_with_no_hostile_entries(
        xml_root, tmp_path):
    """EASY's table has none, and 0% must print as a number rather than as an
    absent section - "no hostile row" and "hostile row omitted" read alike."""
    _, state = make_state(tmp_path, handicap="HANDICAP_EASY", turn=34,
                          cities=[make_city()])
    r = build_rules(xml_root, state)
    assert _hostile_chance(rules.view_goody(r, None, state)) == 0.0


def test_goody_view_flags_a_type_that_is_not_this_games_own(xml_root, tmp_path):
    """Same trap as `handicap`: comparing difficulties is legitimate, but the
    reported rules are then not the ones in play."""
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city()])
    r = build_rules(xml_root, state)
    other = rules.view_goody(r, "HANDICAP_EASY", state)
    assert "and are NOT" in other and "HANDICAP_HARD" in other
    assert "and are NOT" not in rules.view_goody(r, None, state)


def test_goody_view_rejects_an_unknown_unit_and_handicap(xml_root, tmp_path):
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city()])
    r = build_rules(xml_root, state)
    with pytest.raises(rules.RulesError):
        rules.view_goody(r, None, state, "UNIT_NOPE")
    with pytest.raises(rules.RulesError):
        rules.view_goody(r, "HANDICAP_NOPE", state)


def _hut(x, y):
    """A revealed goody-hut tile, as the mod exports one."""
    return {"x": x, "y": y, "terrain": "TERRAIN_GRASS", "yields": [2, 0, 0],
            "improvement": "IMPROVEMENT_GOODY_HUT"}


def _hostile_chance(text):
    """The headline hostile figure, parsed out of a `goody` view.

    One helper rather than the same line-scan copied into every test: the
    headline's wording is the part most likely to be reworded, and three
    hand-rolled copies is three places to fix when it is.
    """
    line = [ln for ln in text.splitlines()
            if ln.startswith("HOSTILE CHANCE")]
    assert line, "no HOSTILE CHANCE line in:\n%s" % text
    return float(line[0].split()[-1].rstrip("%"))


def test_plot_distance_is_not_chebyshev(tmp_path):
    """The engine's plotDistance is `max + min/2` (CvGameCoreUtils.h:144).

    Chebyshev is a DIFFERENT metric (`stepDistance`) and the two diverge on
    every diagonal - at (3,3) the engine says 4 and Chebyshev 3. Using the
    wrong one misjudges the one-city hostile radius exactly at its boundary,
    which is where it gets asked. `render_map.distance` is deliberately the
    other metric, for a rule that really is a square box scan, so this is the
    guard against someone unifying them on the strength of the shared name.
    """
    _, state = make_state(tmp_path, map_width=40, map_height=20)
    for (a, b), expected in (
        (((0, 0), (3, 3)), 4),      # Chebyshev would say 3
        (((0, 0), (4, 4)), 6),      # Chebyshev would say 4
        (((0, 0), (7, 0)), 7),      # straight line: the two agree
        (((0, 0), (5, 2)), 6),
        (((0, 0), (0, 0)), 0),
    ):
        assert rules.plot_distance(state, a, b) == expected, (a, b)

    # x wraps on a cylinder, so the short way round counts.
    assert rules.plot_distance(state, (1, 5), (39, 5)) == 2
    # ...and y does not, wrapY being false.
    assert rules.plot_distance(state, (5, 1), (5, 19)) == 18


def test_goody_decides_the_one_city_radius_when_given_the_hut(
        xml_root, tmp_path):
    """The gate that governed the trial's hut, and the last one that kept the
    view from stating a definite hostile percentage.

    Measured from the HUT, not from the unit - `canReceiveGoody` takes the
    plot - so this needs the target tile rather than where the unit stands.
    """
    near, far = _hut(12, 10), _hut(30, 10)
    _, state = make_state(
        tmp_path, handicap="HANDICAP_HARD", turn=34,
        cities=[make_city(x=10, y=10)], tiles=[near, far],
        units=[{"id": 7, "type": "UNIT_TESTER", "x": 11, "y": 10}])
    r = build_rules(xml_root, state)

    # 2 tiles away, inside the radius of 7: hostiles are impossible, and the
    # view can now say so outright rather than as a condition.
    blocked = rules.view_goody(r, None, state, None, 7, (12, 10))
    assert "hut is 2 tiles from Testville, your only city" in blocked
    assert "conditional" not in blocked
    assert _hostile_chance(blocked) == 0.0

    # 20 tiles away, outside it: hostiles are live, and equally definite.
    # Parsed rather than matched as a substring - "20.0%" appears on row
    # shares too, so a substring test would pass on the blocked case as well.
    exposed = rules.view_goody(r, None, state, None, 7, (30, 10))
    assert "your only city" not in exposed
    assert _hostile_chance(exposed) == 20.0


def test_goody_radius_protection_ends_at_the_second_city(xml_root, tmp_path):
    """`8 - getNumCities()` stops applying at two cities, so founding one
    REMOVES this protection from every hut - the opposite of the intuition."""
    tiles = [_hut(12, 10)]
    for cities, expect_blocked in (
        ([make_city(x=10, y=10)], True),
        ([make_city(x=10, y=10), make_city(name="Second", x=20, y=10)], False),
    ):
        _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                              cities=cities, tiles=tiles)
        r = build_rules(xml_root, state)
        text = rules.view_goody(r, None, state, None, None, (12, 10))
        assert ("your only city" in text) is expect_blocked


def test_goody_decides_healing_from_the_units_own_damage(xml_root, tmp_path):
    """A unit id answers what a unit TYPE cannot: how hurt THIS unit is."""
    tiles = [_hut(12, 10)]
    hurt = {"id": 7, "type": "UNIT_TESTER", "x": 11, "y": 10, "damage": 70}
    whole = {"id": 8, "type": "UNIT_TESTER", "x": 11, "y": 10}
    _, state = make_state(tmp_path, handicap="HANDICAP_EASY", turn=34,
                          cities=[make_city()], tiles=tiles,
                          units=[hurt, whole])
    r = build_rules(xml_root, state)
    heal = r.goodies["GOODY_TESTHEAL"]

    # Undamaged: a decided CANNOT, naming both numbers.
    reason = rules._goody_eligibility(r, heal, state, r.units["UNIT_TESTER"],
                                      whole, None)
    assert "is at 0% damage, needs 60%" in reason
    # Damaged past the threshold: eligible outright.
    assert rules._goody_eligibility(r, heal, state, r.units["UNIT_TESTER"],
                                    hurt, None) is None


def test_goody_rejects_a_hut_coordinate_with_no_hut_on_it(xml_root, tmp_path):
    """A coordinate typo would otherwise produce a confident distance to the
    wrong tile - the failure mode this whole subcommand exists to remove."""
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city()], tiles=[_hut(12, 10)])
    r = build_rules(xml_root, state)
    with pytest.raises(rules.RulesError) as exc:
        rules.view_goody(r, None, state, None, None, (13, 10))
    assert "(12,10)" in str(exc.value)


def test_goody_rejects_a_unit_standing_on_the_hut(xml_root, tmp_path):
    """A unit ON a hut has already popped it, so this is never a real query -
    it means the caller passed the unit's tile instead of the hut's."""
    _, state = make_state(
        tmp_path, handicap="HANDICAP_HARD", turn=34,
        cities=[make_city()], tiles=[_hut(12, 10)],
        units=[{"id": 7, "type": "UNIT_TESTER", "x": 12, "y": 10}])
    r = build_rules(xml_root, state)
    with pytest.raises(rules.RulesError) as exc:
        rules.view_goody(r, None, state, None, 7, (12, 10))
    assert "already popped it" in str(exc.value)


def test_goody_lists_revealed_huts_when_none_is_named(xml_root, tmp_path):
    """An unlisted flag is a flag nobody uses, and the coordinate is sitting
    in the state file the caller already passed."""
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city()],
                          tiles=[_hut(12, 10), _hut(30, 4)])
    r = build_rules(xml_root, state)
    text = rules.view_goody(r, None, state)
    assert "REVEALED HUTS" in text
    assert "(12,10)" in text and "(30,4)" in text
    assert "--at X,Y" in text

    # And once one IS named, the listing and its OMITS line both go away
    # rather than advertising a decision already made.
    named = rules.view_goody(r, None, state, None, None, (12, 10))
    assert "REVEALED HUTS" not in named
    assert "that needs the hut's tile" not in named


def test_goody_states_the_assumption_behind_a_decided_answer(
        xml_root, tmp_path):
    """The figures hold for the board as it stands. Moving first is free, but
    founding a city on the way changes the very gate just resolved."""
    _, state = make_state(
        tmp_path, handicap="HANDICAP_HARD", turn=34,
        cities=[make_city(x=10, y=10)], tiles=[_hut(12, 10)],
        units=[{"id": 7, "type": "UNIT_TESTER", "x": 11, "y": 10}])
    r = build_rules(xml_root, state)
    text = rules.view_goody(r, None, state, None, 7, (12, 10))
    assert "1 tile away" in text          # singular, not "1 tiles"
    assert "board as it stands" in text


def test_goody_names_an_immune_unit_you_actually_have(xml_root, tmp_path):
    """Suggesting a Scout to someone who has none is advice, not a lookup - so
    it is named only when the state file shows one."""
    tiles = [_hut(12, 10)]
    warrior = {"id": 7, "type": "UNIT_TESTER", "x": 11, "y": 10}
    scout = {"id": 8, "type": "UNIT_SCOUTER", "x": 11, "y": 11}

    _, without = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                            cities=[make_city()], tiles=tiles, units=[warrior])
    r = build_rules(xml_root, without)
    assert "You have" not in rules.view_goody(r, None, without, None, 7, None)

    _, with_scout = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                               cities=[make_city()], tiles=tiles,
                               units=[warrior, scout])
    text = rules.view_goody(r, None, with_scout, None, 7, None)
    assert "You have UNIT_SCOUTER" in text
    assert "zero risk" in text


def test_real_install_hostile_counts_match_the_verified_table(tmp_path):
    """Pin the actual numbers, because this item's whole value is that they
    are right - a plausible wrong distribution is exactly what it replaces.

    Counted from the install rather than taken from the trial report: each
    handicap carries a flat 20-entry table, and the hostile entries rise one
    per difficulty. Monarch's 5 is the trial's own difficulty, where the agent
    reported "safe for 16 more turns".

    Skips cleanly with no install, like the sample cost cross-check above.
    """
    try:
        xml_root = rules.resolve_xml_root()
    except rules.RulesError as exc:
        pytest.skip("no Civ IV install: %s" % exc)

    expected = {
        "HANDICAP_SETTLER": 0, "HANDICAP_CHIEFTAIN": 1, "HANDICAP_WARLORD": 2,
        "HANDICAP_NOBLE": 3, "HANDICAP_PRINCE": 4, "HANDICAP_MONARCH": 5,
        "HANDICAP_EMPEROR": 6, "HANDICAP_IMMORTAL": 7, "HANDICAP_DEITY": 8,
    }
    _, state = make_state(tmp_path, handicap="HANDICAP_MONARCH", turn=34)
    r = rules.Rules(xml_root, state["game"])

    for handicap, hostile in sorted(expected.items()):
        table = r.handicaps[handicap]["goodies"]
        assert len(table) == 20, handicap
        bad = sum(1 for key in table if r.goodies[key]["bad"])
        assert bad == hostile, handicap

    # The guaranteed floor on each hostile outcome - what decides how bad one
    # actually is, since these land regardless of any roll.
    weak = r.goodies["GOODY_BARBARIANS_WEAK"]
    strong = r.goodies["GOODY_BARBARIANS_STRONG"]
    assert (weak["min_barbarians"], strong["min_barbarians"]) == (1, 2)

    # Exactly the Scout and the Explorer, on the real file.
    immune = sorted(u["type"] for u in r.units.values()
                    if u.get("no_bad_goodies"))
    assert immune == ["UNIT_EXPLORER", "UNIT_SCOUT"]


def test_goody_file_is_read_from_the_vanilla_tree(xml_root, tmp_path):
    """It is vanilla-only on the real install, like CIV4BonusInfos.xml, so a
    BTS-only resolver finds nothing - an agent trial hit exactly that for
    CIV4BonusInfos and fell back to grepping.

    Asserted on the loader rather than on the output: the view deliberately
    does not cite this file (nothing in it is left unprinted to go and read),
    so the fallback has to be checked where it actually happens.
    """
    _, state = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                          cities=[make_city()])
    r = build_rules(xml_root, state)
    assert r.sources["goodies"][1] == "vanilla"
    assert r.goodies, "the vanilla fallback loaded nothing"


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


def test_cli_goody_takes_the_handicap_from_state_and_a_unit_from_the_flag(
        xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(tmp_path, handicap="HANDICAP_HARD",
                               cities=[make_city()])
    assert rules.main(["goody", state_path, "--config", config]) == 0
    assert "HANDICAP_HARD" in capsys.readouterr().out

    # The unit is a FLAG, not TYPE: TYPE is the handicap here, exactly as for
    # `handicap`, so a unit passed positionally must not be silently accepted
    # as a difficulty.
    assert rules.main(["goody", state_path, "--config", config,
                       "--popped-by", "UNIT_SCOUTER"]) == 0
    assert "UNIT_SCOUTER" in capsys.readouterr().out


def test_cli_goody_accepts_for_unit_and_at(xml_root, tmp_path, config, capsys):
    """`goody` keeps TYPE for the handicap, so unlike `promotion` the id does
    NOT replace it - both may be given."""
    state_path, _ = make_state(
        tmp_path, handicap="HANDICAP_HARD", turn=34,
        cities=[make_city(x=10, y=10)], tiles=[_hut(12, 10)],
        units=[{"id": 7, "type": "UNIT_TESTER", "x": 11, "y": 10}])
    assert rules.main(["goody", state_path, "--config", config,
                       "--for-unit", "7", "--at", "12,10"]) == 0
    out = capsys.readouterr().out
    assert "id 7" in out and "(12,10)" in out

    assert rules.main(["goody", "HANDICAP_EASY", state_path, "--config",
                       config, "--for-unit", "7"]) == 0
    assert "HANDICAP_EASY" in capsys.readouterr().out


def test_cli_goody_explains_a_space_separated_coordinate(
        xml_root, tmp_path, config, capsys):
    """`--at 12 10` is the natural mistyping, and argparse alone reports it as
    "unrecognized arguments: 10" - naming neither the flag nor the comma."""
    state_path, _ = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                               cities=[make_city()], tiles=[_hut(12, 10)])
    assert rules.main(["goody", state_path, "--config", config,
                       "--at", "12", "10"]) == 2
    assert "--at 12,10" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        rules.main(["goody", state_path, "--config", config, "bogus", "extra"])


def test_cli_rejects_the_two_unit_flags_together(xml_root, tmp_path, config,
                                                 capsys):
    """Both name the popping unit; letting one win silently would answer about
    a different unit than the caller named in the other."""
    state_path, _ = make_state(tmp_path, handicap="HANDICAP_HARD", turn=34,
                               cities=[make_city()],
                               units=[{"id": 7, "type": "UNIT_TESTER",
                                       "x": 1, "y": 1}])
    assert rules.main(["goody", state_path, "--config", config,
                       "--popped-by", "UNIT_SCOUTER", "--for-unit", "7"]) == 2
    assert "both name the popping unit" in capsys.readouterr().err


def test_cli_rejects_at_outside_goody(xml_root, tmp_path, config, capsys):
    state_path, _ = make_state(tmp_path)
    assert rules.main(["handicap", state_path, "--config", config,
                       "--at", "1,1"]) == 2
    assert "only applies to `goody`" in capsys.readouterr().err


def test_cli_rejects_popped_by_outside_goody(xml_root, tmp_path, config, capsys):
    """It reads as a general "which unit is asking" flag, but only `goody`
    changes its answer based on one."""
    state_path, _ = make_state(tmp_path)
    assert rules.main(["handicap", state_path, "--config", config,
                       "--popped-by", "UNIT_SCOUTER"]) == 2
    assert "only applies to `goody`" in capsys.readouterr().err


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
    dominate the early game.

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


# ---------------------------------------------------------------------------
# Improvements - the yield model
#
# The headline case is grassland Corn, which the Ramesses trial got wrong: the
# agent had no lookup, extrapolated from memory, invented a Despotism yield
# penalty (a Civ3 mechanic absent from Civ4) and reported 4 food. The answer
# is 5. All three of the walkthrough's numbers are asserted here because they
# decompose differently and an implementation can get one right by luck.
# ---------------------------------------------------------------------------


def _grass_corn(**extra):
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS",
            "bonus": "BONUS_TESTCORN"}
    tile.update(extra)
    return tile


def test_grass_corn_unimproved_is_three_food(xml_root, tmp_path):
    """2 from grassland, +1 from the resource itself."""
    _path, state = make_state(tmp_path, tiles=[_grass_corn()])
    r = build_rules(xml_root, state)
    assert rules.nature_yield(r, _grass_corn(), state=state) == [3, 0, 0]


def test_grass_corn_farmed_without_fresh_water_is_five_food(xml_root, tmp_path):
    """THE regression. 2 grass + 1 corn + 2 farm-on-corn = 5, not 4.

    The dropped term is the improvement's per-resource BonusTypeStruct, which
    is the one an agent reasoning from memory does not know is separate from
    the resource's own yield.
    """
    tile = _grass_corn()
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    total, terms = rules.improvement_yield(
        r, tile, "IMPROVEMENT_TESTFARM", set(), (), state)
    assert total == [5, 0, 0]
    # The decomposition must actually show all three terms - a total that is
    # right by cancelling errors would still mislead the reader.
    labels = [name for name, _values in terms]
    assert "TERRAIN_TESTGRASS" in labels
    assert "BONUS_TESTCORN" in labels
    assert any("on BONUS_TESTCORN" in name for name in labels)


def test_grass_corn_farmed_with_fresh_water_is_six_food(xml_root, tmp_path):
    """The +1 is IrrigatedYieldChange - the farm has no flat yield at all."""
    tile = _grass_corn(freshWater=True)
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    total, _terms = rules.improvement_yield(
        r, tile, "IMPROVEMENT_TESTFARM", set(), (), state)
    assert total == [6, 0, 0]


def test_the_farm_has_no_flat_yield_of_its_own(xml_root, tmp_path):
    """Guards the nested-container bug directly.

    <YieldChanges> appears inside every BonusTypeStruct as well as at the top
    level of an ImprovementInfo. A non-anchored search matches the Corn
    struct's +2 first and reports it as the farm's own flat yield, which
    double-counts to 6 food on a dry Corn tile and 4 on bare grassland.
    """
    _path, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert not r.improvements["IMPROVEMENT_TESTFARM"]["yields"]
    assert r.improvements["IMPROVEMENT_TESTFARM"]["irrigated"] == [1, 0, 0]


def test_the_improvement_tech_comes_from_the_build_not_the_improvement(
        xml_root, tmp_path):
    """Every stock ImprovementInfo has an empty <PrereqTech>.

    Reading it returns None, which renders as "no tech needed" and is wrong
    for almost every improvement in the game. A raw scan of the block is
    worse still: it reaches into <TechYieldChanges> and returns the LATE tech
    (Biology for a Farm) as though it were the unlock.
    """
    _path, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert r.improvements["IMPROVEMENT_TESTFARM"]["tech"] is None
    build_key, tech = rules.build_for(r, "IMPROVEMENT_TESTFARM")
    assert build_key == "BUILD_TESTFARM"
    assert tech == "TECH_ROOT_A"


def test_a_resource_bypasses_the_terrain_restrictions(xml_root, tmp_path):
    """bBonusMakesValid is an early return ABOVE every other gate.

    The farm requires flatland and irrigation. Corn makes it valid, so a
    corn tile on hills with no fresh water is still legal - and getting this
    wrong is not academic, since resource tiles are exactly the ones worth
    asking about.
    """
    tile = _grass_corn(plotType="PLOT_HILLS")
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    assert rules.can_have_improvement(
        r, tile, "IMPROVEMENT_TESTFARM", set()) is None


def test_a_dry_tile_without_a_resource_fails_the_irrigation_gate(
        xml_root, tmp_path):
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS"}
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    why = rules.can_have_improvement(r, tile, "IMPROVEMENT_TESTFARM", set())
    assert why and "irrigation" in why


def test_the_prereq_nature_yield_gate_stops_a_farm_on_desert(xml_root, tmp_path):
    """PrereqNatureYields is tested against the BARE tile, not the improved one.

    Desert makes 0 food, the farm needs 1, so fresh water does not rescue it -
    the irrigated +1 is applied after this gate, not before.
    """
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTDESERT", "freshWater": True}
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    why = rules.can_have_improvement(r, tile, "IMPROVEMENT_TESTFARM", set())
    assert why and "bare tile" in why


def test_a_forest_does_not_block_a_mine_but_does_gate_it_on_a_tech(
        xml_root, tmp_path):
    """The trial's second wrong answer, and it is a REQUIREMENT not a refusal.

    canHaveImprovement never rejects for a feature; the mine is legal on a
    forested hill. What the forest costs is the per-feature tech inside
    BUILD_TESTMINE that clears it. The agent had seen both facts separately
    and joined neither.
    """
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS",
            "plotType": "PLOT_HILLS", "feature": "FEATURE_FOREST"}
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    assert rules.can_have_improvement(
        r, tile, "IMPROVEMENT_TESTMINE", set()) is None
    build_key, tech, feature = rules.clearing_requirement(
        r, tile, "IMPROVEMENT_TESTMINE")
    assert (build_key, tech, feature) == (
        "BUILD_TESTMINE", "TECH_SIMPLE", "FEATURE_FOREST")


def test_a_cleared_feature_does_not_contribute_its_yield(xml_root, tmp_path):
    """The forest's +1 hammer is gone once the mine stands on the tile."""
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS",
            "plotType": "PLOT_HILLS", "feature": "FEATURE_FOREST"}
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    total, terms = rules.improvement_yield(
        r, tile, "IMPROVEMENT_TESTMINE", set(), (), state)
    assert "FEATURE_FOREST" not in [name for name, _v in terms]
    # grass 2 food, hills -1 food +1 hammer, mine +2 hammers
    assert total == [1, 3, 0]


def test_a_feature_no_build_removes_keeps_its_yield_under_the_improvement(
        xml_root, tmp_path):
    """Whether the feature survives is per-BUILD data, not a property of the
    improvement.

    The bug this pins: `keeps_feature` asked the improvement's own
    bRequiresFeature - "does this improvement NEED a feature" - and used the
    answer for "does this build REMOVE the feature". Those agree for forest
    and jungle, which nearly every build lists in its FeatureStructs, and
    disagree for flood plains, which appear in no build's FeatureStructs at
    all. A Farm on real flood plains printed 1 food instead of 4, with the
    3-food term missing from the working entirely rather than mis-totalled.

    Both directions in one test on purpose. Keeping every feature is exactly
    as wrong as dropping every feature, and either half alone passes under
    the opposite error.

    The engine sweep cannot reach this: it checks tiles as they exist, and no
    sample tile has a real improvement standing on a feature. The error is
    only in the counterfactual "if you build" projection, so the coverage has
    to be synthetic.
    """
    # SURVIVES: no build names FEATURE_TESTFLOOD, so the farm stands on top
    # of it and the 3 food is still there.
    flood = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS",
             "feature": "FEATURE_TESTFLOOD", "freshWater": True}
    # CLEARED: BUILD_TESTMINE lists FEATURE_FOREST with bRemove, so the
    # forest's +1 hammer is gone once the mine stands.
    wooded = {"x": 6, "y": 6, "terrain": "TERRAIN_TESTGRASS",
              "plotType": "PLOT_HILLS", "feature": "FEATURE_FOREST"}
    _path, state = make_state(tmp_path, tiles=[flood, wooded])
    r = build_rules(xml_root, state)

    total, terms = rules.improvement_yield(
        r, flood, "IMPROVEMENT_TESTFARM", set(), (), state)
    assert "FEATURE_TESTFLOOD" in [name for name, _v in terms]
    # grass 2 food + flood 3 food + farm's irrigated +1 on fresh water
    assert total == [6, 0, 0]

    total, terms = rules.improvement_yield(
        r, wooded, "IMPROVEMENT_TESTMINE", set(), (), state)
    assert "FEATURE_FOREST" not in [name for name, _v in terms]
    # grass 2 food, hills -1 food +1 hammer, mine +2 hammers
    assert total == [1, 3, 0]


def test_a_forest_suppresses_the_river_commerce_and_chopping_restores_it(
        xml_root, tmp_path):
    """Forest and jungle carry NO RiverYieldChange, and that is not a no-op.

    `calculateNatureYield` takes the river change from the FEATURE when one
    is present and from the terrain otherwise - they shadow rather than
    stack. Forest has none, so a forested riverside tile gets zero river
    commerce, and any build that clears the forest hands it back.

    Confirmed in the live sample before being asserted here: the baseline's
    forested riverside grassland exports `yields: [2,1,0]` - a river tile
    with no commerce at all.

    Worth pinning because the restored commerce arrives from a term the
    improvement itself does not produce. A Farm makes no commerce, yet
    farming this tile is +1 commerce; anyone reading the improvement's own
    yields to sanity-check that number would conclude the tool was wrong.
    """
    wooded = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS", "river": True,
              "feature": "FEATURE_FOREST"}
    bare = {"x": 6, "y": 6, "terrain": "TERRAIN_TESTGRASS", "river": True}
    _path, state = make_state(tmp_path, tiles=[wooded, bare])
    r = build_rules(xml_root, state)

    # The terrain's +1 commerce is shadowed away by the forest...
    assert rules.nature_yield(r, wooded, state=state) == [2, 1, 0]
    # ...and present on the identical tile without one.
    assert rules.nature_yield(r, bare, state=state) == [2, 0, 1]

    # A build that clears the forest restores it. The mine contributes only
    # hammers, so the commerce here can ONLY have come from the river.
    total, terms = rules.improvement_yield(
        r, wooded, "IMPROVEMENT_TESTMINE", set(), (), state)
    assert total[2] == 1
    assert ("river", [0, 0, 1]) in terms


def test_a_late_tech_yield_only_counts_once_known(xml_root, tmp_path):
    tile = _grass_corn(freshWater=True)
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    without, _ = rules.improvement_yield(
        r, tile, "IMPROVEMENT_TESTFARM", set(), (), state)
    with_tech, _ = rules.improvement_yield(
        r, tile, "IMPROVEMENT_TESTFARM", {"TECH_SIMPLE"}, (), state)
    assert with_tech[0] == without[0] + 1


def test_financial_applies_only_above_its_threshold(xml_root, tmp_path):
    """FIN is +1 commerce on a tile ALREADY making 2, read from the XML.

    Asserted in both directions - a blanket +1 would pass a one-sided test.
    The river tile alone makes 1 commerce, which is below the threshold.
    """
    river = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS", "river": True}
    _path, state = make_state(tmp_path, tiles=[river])
    r = build_rules(xml_root, state)
    fin = ("TRAIT_TESTFIN",)
    below, _ = rules.improvement_yield(
        r, river, "IMPROVEMENT_TESTMINE", set(), fin, state)
    assert below[2] == 1, "1 commerce is below the threshold - no bonus"

    # A terrain carrying 2 commerce of its own, which is exactly the
    # threshold - the boundary is where an off-by-one would hide.
    rich = {"x": 6, "y": 6, "terrain": "TERRAIN_TESTCOAST"}
    _path, richer = make_state(tmp_path, tiles=[rich], turn=35)
    plain, _ = rules.improvement_yield(
        r, rich, "IMPROVEMENT_TESTMINE", set(), (), richer)
    boosted, _ = rules.improvement_yield(
        r, rich, "IMPROVEMENT_TESTMINE", set(), fin, richer)
    assert plain[2] >= 2, "fixture must reach the threshold to test the bonus"
    assert boosted[2] == plain[2] + 1


def test_traits_are_resolved_through_the_leader(xml_root, tmp_path):
    """`player.traits` does not exist in the schema - only `player.leader`."""
    _path, state = make_state(tmp_path, leader="LEADER_TESTFIN")
    r = build_rules(xml_root, state)
    assert rules.player_traits(r, state) == ("TRAIT_TESTFIN",)
    _path, plain = make_state(tmp_path, leader="LEADER_TESTPLAIN", turn=35)
    assert rules.player_traits(r, plain) == ()


def test_an_unmet_owner_yields_no_traits_and_says_so(xml_root, tmp_path):
    """An unmet rival's traits are genuinely unknown, not empty.

    The distinction matters: computing their tile as though they were
    traitless is a guess dressed as an answer.
    """
    _path, state = make_state(tmp_path, contacts=[])
    r = build_rules(xml_root, state)
    traits, known = rules.owner_traits(r, state, 7)
    assert traits == () and known is False


def test_a_met_rivals_traits_come_from_contacts(xml_root, tmp_path):
    _path, state = make_state(
        tmp_path, contacts=[{"playerId": 7, "leader": "LEADER_TESTFIN"}])
    r = build_rules(xml_root, state)
    traits, known = rules.owner_traits(r, state, 7)
    assert traits == ("TRAIT_TESTFIN",) and known is True


def test_a_peak_yields_nothing_whatever_is_under_it(xml_root, tmp_path):
    """calculateNatureYield returns 0 for an impassable plot before anything
    else. Dropping this clause was worth 76 wrong tiles in the sample sweep.
    """
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS",
            "plotType": "PLOT_PEAK"}
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    assert rules.nature_yield(r, tile, state=state) == [0, 0, 0]


def test_the_peak_zero_holds_in_the_view_not_just_nature_yield(
        xml_root, tmp_path):
    """The impassable early-out must be in BOTH accumulators.

    `nature_yield` and `improvement_yield` add up their terms independently,
    and the sample sweep only ever compares the first. So the view went on
    printing a peak's terrain yield - `2 food, 1 commerce` against the
    engine's `[0,0,0]` - with the sweep fully green. Caught by reading real
    output, which is why this asserts through the view rather than the
    function.
    """
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS",
            "plotType": "PLOT_PEAK", "river": True}
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    total, _terms = rules.nature_terms(r, tile, state)
    assert total == [0, 0, 0]
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "NOW           nothing" in text
    assert "impassable" in text


def test_deep_ocean_is_read_from_the_export_not_re_derived(xml_root, tmp_path):
    """`isPotentialCityWork` is not reconstructible from `map.tiles`.

    The engine tests every plot in the 21-tile cross including unrevealed
    ones; the export holds only revealed tiles. On the baseline sample two
    ocean tiles with identical revealed surroundings (zero land, differing
    only in how many neighbours are unrevealed) yield [0,0,0] and [1,0,1].
    So the tile's own exported yield settles it - guessing was wrong on 24
    tiles in one direction and 609 in the other.
    """
    barren = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTCOAST",
              "plotType": "PLOT_OCEAN", "yields": [0, 0, 0]}
    coastal = {"x": 6, "y": 6, "terrain": "TERRAIN_TESTCOAST",
               "plotType": "PLOT_OCEAN", "yields": [1, 0, 2]}
    _path, state = make_state(tmp_path, tiles=[barren, coastal])
    r = build_rules(xml_root, state)
    assert rules.nature_terms(r, barren, state)[0] == [0, 0, 0]
    assert rules.nature_terms(r, coastal, state)[0] == [1, 0, 2]


def test_a_goody_hut_is_not_treated_as_an_improvement_on_the_tile(
        xml_root, tmp_path):
    """A hut IS an ImprovementInfo, and emphatically not one for this view.

    Running it through improvement_yield clears the tile's feature - huts do
    not set bRequiresFeature - so a forested hut tile lost the forest's
    hammer and reported 1/1/0 against the engine's 1/2/0.
    """
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTGRASS",
            "feature": "FEATURE_FOREST",
            "improvement": "IMPROVEMENT_GOODY_HUT"}
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    text = rules.view_improvement(r, None, state, (5, 5))
    # 2 food from grass, 1 hammer from the forest that is still standing.
    assert "2 food, 1 hammers" in text


def test_a_city_centre_is_floored_at_two_one_one(xml_root, tmp_path):
    """iMinCity, found by sweeping the sample rather than from the XML.

    A city on a tile that would otherwise make less still shows 2/1/1,
    which is why a city on plains reads [2,1,1] and not [1,1,0].
    """
    tile = {"x": 5, "y": 5, "terrain": "TERRAIN_TESTDESERT"}
    _path, state = make_state(
        tmp_path, tiles=[tile], cities=[make_city(x=5, y=5)])
    r = build_rules(xml_root, state)
    assert rules.nature_yield(r, tile, state=state) == [2, 1, 1]


def test_a_never_scouted_tile_is_refused_rather_than_guessed(xml_root, tmp_path):
    """`map.tiles` holds every tile ever revealed, so absence means unscouted.

    Answering anything at all here - even the terrain - would be inventing
    information the player has never seen.
    """
    _path, state = make_state(tmp_path, tiles=[])
    r = build_rules(xml_root, state)
    with pytest.raises(rules.RulesError) as excinfo:
        rules.view_improvement(r, None, state, (5, 5))
    assert "never been scouted" in str(excinfo.value)


def test_a_fogged_tile_is_answered_with_a_staleness_note(xml_root, tmp_path):
    """Fogged is remembered, not unknown - the player HAS seen this terrain."""
    tile = _grass_corn(visibleNow=False)
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "NOT VISIBLE NOW" in text
    assert "5 food" in text


def test_the_tile_view_shows_a_total_and_its_decomposition(xml_root, tmp_path):
    """Both, per the brief: the working AND a clearly marked total.

    A bare number cannot be checked by the reader, which is how an invented
    term survived in the first place.
    """
    _path, state = make_state(tmp_path, tiles=[_grass_corn()],
                              known=("TECH_ROOT_A",))
    r = build_rules(xml_root, state)
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "IMPROVEMENT_TESTFARM" in text and "5 food" in text
    assert "+2 IMPROVEMENT_TESTFARM on BONUS_TESTCORN" in text
    # The status quo, against which the improvement's change is measured.
    assert "NOW" in text and "3 food" in text
    assert "(+2 food)" in text


# ---------------------------------------------------------------------------
# canBuild's own gates - beyond "can the tile hold this"
#
# canHaveImprovement answers whether a tile COULD carry an improvement.
# CvPlot::canBuild wraps it with gates that have nothing to do with terrain,
# and both of the ones below produced a confident "you can build this" on a
# tile where the game refuses. That is the worst failure mode available here:
# the reader has no way to doubt it.
# ---------------------------------------------------------------------------


def test_an_improvement_already_on_the_tile_is_not_offered_again(
        xml_root, tmp_path):
    tile = _grass_corn(improvement="IMPROVEMENT_TESTFARM")
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    # The tile can still HOLD it - that is not the question canBuild asks.
    assert rules.can_have_improvement(
        r, tile, "IMPROVEMENT_TESTFARM", set()) is None
    why = rules.build_blocker(r, tile, "IMPROVEMENT_TESTFARM", state)
    assert why and "already built" in why
    # It appears in the header as what is standing there, never as an option.
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "has IMPROVEMENT_TESTFARM" in text
    assert "IF YOU BUILD" not in text
    assert "NOTHING TO ADD" in text


def test_a_foreign_tile_offers_nothing_and_says_why(xml_root, tmp_path):
    """Culture, not terrain. The tile may be excellent and simply not yours.

    Reported as ownership rather than as "nothing can be built here", which
    reads as a property of the ground and is the wrong conclusion to draw.
    """
    tile = _grass_corn(owner=7, freshWater=True)
    _path, state = make_state(
        tmp_path, tiles=[tile], player_id=0,
        contacts=[{"playerId": 7, "leader": "LEADER_TESTPLAIN"}])
    r = build_rules(xml_root, state)
    why = rules.build_blocker(r, tile, "IMPROVEMENT_TESTFARM", state)
    assert why and "borders" in why
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "NOTHING BUILDABLE" in text and "borders" in text


def test_our_own_tile_is_not_treated_as_foreign(xml_root, tmp_path):
    tile = _grass_corn(owner=0, freshWater=True)
    _path, state = make_state(tmp_path, tiles=[tile], player_id=0)
    r = build_rules(xml_root, state)
    assert rules.build_blocker(r, tile, "IMPROVEMENT_TESTFARM", state) is None


def test_now_reports_the_improved_yield_on_an_improved_tile(xml_root, tmp_path):
    """`NOW` must mean what the tile yields TODAY.

    Reporting the bare-terrain figure understates the status quo and makes
    every alternative look better than it is - which on an already-working
    tile is exactly the shape of bad advice. The delta is measured against
    this, so getting it wrong corrupts every row below it too.
    """
    tile = _grass_corn(improvement="IMPROVEMENT_TESTFARM")
    _path, state = make_state(tmp_path, tiles=[tile])
    r = build_rules(xml_root, state)
    text = rules.view_improvement(r, None, state, (5, 5))
    now = [line for line in text.splitlines() if line.startswith("NOW")][0]
    assert "5 food" in now, now
    # Swapping the farm for the mine costs the farm's food rather than
    # appearing as a free gain.
    mine = [line for line in text.splitlines()
            if "IMPROVEMENT_TESTMINE" in line and "(" in line]
    if mine:
        assert "-" in mine[0].split("(")[-1]


# ---------------------------------------------------------------------------
# Resource connection
#
# On a resource tile the yield columns are nearly beside the point: one
# improvement puts the resource into your trade network and the rest leave it
# out, and a rival option can win on raw yield while costing you the resource
# entirely. `bBonusTrade` is the engine's own gate for this
# (CvPlot::updatePlotGroupBonus), so this is a lookup rather than a judgement.
# ---------------------------------------------------------------------------


def test_the_connecting_improvement_is_read_from_bonus_trade(
        xml_root, tmp_path):
    _path, state = make_state(tmp_path)
    r = build_rules(xml_root, state)
    assert rules.connecting_improvement(
        r, "BONUS_TESTCORN") == "IMPROVEMENT_TESTFARM"
    assert rules.connecting_improvement(r, "BONUS_PLAIN") is None
    assert rules.connecting_improvement(r, "") is None


def test_the_connector_is_flagged_and_listed_first(xml_root, tmp_path):
    """Ordering, not ranking.

    It is NOT a claim that the connector yields most - a Mine on Gems is
    -1 hammer - but that it is the only option that connects the resource at
    all. That is a different kind of fact and the one a reader scanning the
    list needs first.
    """
    _path, state = make_state(tmp_path, tiles=[_grass_corn(freshWater=True)],
                              known=("TECH_ROOT_A",))
    r = build_rules(xml_root, state)
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "BONUS_TESTCORN is CONNECTED by IMPROVEMENT_TESTFARM" in text
    assert "<- CONNECTS BONUS_TESTCORN" in text
    body = text.split("IF YOU BUILD")[1]
    rows = [line for line in body.splitlines()
            if line.startswith("  IMPROVEMENT_")]
    assert rows and "IMPROVEMENT_TESTFARM" in rows[0], rows


def test_a_non_connecting_option_says_it_leaves_the_resource_unconnected(
        xml_root, tmp_path):
    """The cost no yield column shows.

    Losing a strategic resource is not a yield trade - it can remove a whole
    unit line from what the empire can build - so it is stated on the row
    rather than left to be inferred from the connector's absence.
    """
    # On HILLS, so the mine is legal and there is a non-connecting row to
    # check. The corn's bBonusMakesValid keeps the farm legal here too
    # despite bRequiresFlatlands, so both options appear.
    tile = _grass_corn(plotType="PLOT_HILLS")
    _path, state = make_state(tmp_path, tiles=[tile],
                              known=("TECH_ROOT_A", "TECH_SIMPLE"))
    r = build_rules(xml_root, state)
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "IMPROVEMENT_TESTMINE" in text
    assert "leaves   BONUS_TESTCORN unconnected" in text


def test_replacing_the_connector_is_reported_as_a_loss(xml_root, tmp_path):
    """Stronger wording when the resource is connected RIGHT NOW.

    "leaves it unconnected" understates replacing a Pasture that is already
    feeding horses into the empire - that is an active loss, not a
    forgone gain.
    """
    tile = _grass_corn(improvement="IMPROVEMENT_TESTFARM", freshWater=True)
    _path, state = make_state(tmp_path, tiles=[tile],
                              known=("TECH_ROOT_A", "TECH_SIMPLE"))
    r = build_rules(xml_root, state)
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "already built" in text
    if "IF YOU BUILD" in text:
        assert "LOSES    BONUS_TESTCORN" in text


def test_the_city_trade_tech_is_surfaced_separately(xml_root, tmp_path):
    """A SECOND tech gate, checked by the engine before the improvement.

    Distinct from the build's own prereq and easy to miss because nothing
    else in the view mentions it. It is the whole of the player's stated
    exception: a Plantation on Spices connects it, but Calendar may be far
    enough off that the tile is better used otherwise in the meantime.
    """
    # TECH_ROOT_A is BONUS_TESTCORN's TechCityTrade. Not known here.
    _path, state = make_state(tmp_path, tiles=[_grass_corn(freshWater=True)],
                              known=())
    r = build_rules(xml_root, state)
    text = rules.view_improvement(r, None, state, (5, 5))
    assert "TECH_ROOT_A" in text and "before any city can work it" in text
    # Known, so the line goes away rather than nagging.
    _path, later = make_state(
        tmp_path, tiles=[_grass_corn(freshWater=True)], turn=35,
        known=("TECH_ROOT_A",))
    assert "before any city can work it" not in rules.view_improvement(
        r, None, later, (5, 5))


@pytest.mark.parametrize("sample", sorted(
    os.path.basename(p) for p in
    (os.listdir(SAMPLES) if os.path.isdir(SAMPLES) else [])
    if os.path.isdir(os.path.join(SAMPLES, p))
))
def test_tile_yields_match_the_engine_on_every_sample_tile(sample):
    """The whole yield model, checked against the engine's own numbers.

    Every other test in this file asserts behaviour the author reasoned out.
    This one asserts agreement with `map.tiles[].yields` - what the game
    itself computed and displayed - across every tile of every turn. It is
    the only check here that can catch a clause missing from the port
    entirely, and it earned that reputation: it found the impassable
    early-out (peaks reading terrain yield instead of [0,0,0]), the
    `iMinCity` city-centre floor, and the goody-hut-is-not-an-improvement
    case, all of which had passed the hand-written tests.

    Committed rather than left as scratch scaffolding because three separate
    code comments cite its counts as their justification. A one-off sweep
    that cannot be re-run is evidence nobody can check.

    Deliberately routed through the VIEW's code path (`nature_terms` /
    `improvement_yield`), not `nature_yield`. The two used to be separate
    accumulators and a fix applied to one missed the other; sweeping the
    path the view actually takes is what makes that class of divergence
    visible. See improvement_yield's INVARIANT comment.
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
        r = rules.Rules(xml_root, state.get("game") or {})
        known = rules.effective_known(state)
        traits = rules.player_traits(r, state)
        for tile in (state.get("map") or {}).get("tiles") or []:
            expected = tile.get("yields")
            if expected is None:
                continue
            existing = tile.get("improvement")
            if existing in rules.NOT_REAL_IMPROVEMENTS:
                existing = None
            if existing and existing in r.improvements:
                got, _terms = rules.improvement_yield(
                    r, tile, existing, known, traits, state)
            else:
                got, _terms = rules.nature_terms(r, tile, state, traits)
            assert got == expected, (
                "%s/%s (%s,%s) %s%s: engine says %s, we compute %s"
                % (sample, name, tile.get("x"), tile.get("y"),
                   tile.get("terrain"),
                   " + " + existing if existing else "",
                   expected, got)
            )
            checked += 1

    assert checked, "no tiles were checked in %s" % sample
