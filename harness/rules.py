"""Look up game rules in the Civ IV XML, against a given turn's state.

The other two tools point at the game's XML for rules questions and stop there.
Fifteen agent trials then re-derived the same facts by hand, hitting the same
three traps every time:

  * ~18 copies of each XML file exist in the install, and a naive `find` returns
    the VANILLA `Assets/XML/...` before the Beyond the Sword one. Sixteen of the
    rest are mod copies - Final Frontier's "units" are spaceships. A wrong-file
    hit is silent and plausible. (But vanilla is not simply wrong: an expansion
    ships only the files it CHANGES, so resources live there and nowhere else.
    See BTS_XML_ROOT below - the rule is BTS-first, vanilla-fallback.)
  * `grep -A6` does not reach `PrereqTech`. It sits ~90 lines into a UnitInfo
    block. Two trials fell back to writing Python regex.
  * `CIV4HandicapInfo.xml` is as load-bearing as unit prereqs in the early game,
    and `game.handicap` is already in every state export.

And the error this exists to prevent, from a previous session: asserting from
memory that a Roman Archer implies Bronze Working. It implies ARCHERY - Bronze
Working is the Axeman. Confident, plausible, wrong, and it reached a committed
file before anyone caught it. Building this module the same failure recurred
four more times, each caught only by reading the XML: "Axeman is +100% vs melee"
(it is 50), "a Chariot cannot cross jungle" (not in the unit XML at all), a
worked example asserting a tech cycle that does not exist, and a Pyramid commerce
value read as gold when the positional array made it culture.

WHAT THIS TOOL IS FOR: reverse and transitive lookups, which is what XML is bad
at. "Which tech does UNIT_AXEMAN need, and what does THAT need" is a closure
walk across a file that stores only single hops. Forward lookups the agent greps
fine on its own, and this deliberately does not grow into a query language.

THE LINE IT MUST NOT CROSS: resolving what a unit requires is presentation.
Answering "what should I research" is deciding. So this prints route costs side
by side and never sorts them, never labels one "cheapest", and never recommends.

Subcommands - `unit`, `tech`, `building`, `promotion`, `city`, `handicap`,
`goody` - each taking a state file, because game speed, world size and
difficulty multiply tech costs and an unpriced answer is 1.0-4.5x wrong.

Run it directly with the system Python; stdlib only, no setup:

    python harness/rules.py unit UNIT_AXEMAN samples/baseline-early-game/turn_0043.json
"""

import argparse
import bisect
import json
import math
import os
import re
import sys

# An expansion only ships the files it CHANGES; the engine loads the BTS copy
# when one exists and falls back to the base install otherwise. So the rule is
# BTS-first, vanilla-fallback - not "vanilla is always wrong", which is what an
# earlier version of this file (and of AGENT_GUIDE.md) asserted.
#
# Measured on the real install: BTS overrides most of what this tool reads, but
# `Terrain/CIV4BonusInfos.xml` - which holds every resource's TechReveal - is
# vanilla-ONLY, as is GameInfo/CIV4GoodyInfo.xml. An agent trial needed
# TechReveal, followed the BTS-only advice, found nothing, and fell back to
# grepping. The mod copies under Mods/ stay excluded either way: those are the
# genuinely wrong ones (Final Frontier's "units" are spaceships).
BTS_XML_ROOT = os.path.join("Beyond the Sword", "Assets", "XML")
VANILLA_XML_ROOT = os.path.join("Assets", "XML")

TECH_FILE = os.path.join("Technologies", "CIV4TechInfos.xml")
UNIT_FILE = os.path.join("Units", "CIV4UnitInfos.xml")
PROMOTION_FILE = os.path.join("Units", "CIV4PromotionInfos.xml")
BUILDING_FILE = os.path.join("Buildings", "CIV4BuildingInfos.xml")
CIVIC_FILE = os.path.join("GameInfo", "CIV4CivicInfos.xml")
HANDICAP_FILE = os.path.join("GameInfo", "CIV4HandicapInfo.xml")
GAMESPEED_FILE = os.path.join("GameInfo", "CIV4GameSpeedInfo.xml")
WORLD_FILE = os.path.join("GameInfo", "CIV4WorldInfo.xml")
BUILD_FILE = os.path.join("Units", "CIV4BuildInfos.xml")
# Vanilla-only on the measured install, exactly like CIV4BonusInfos.xml - BTS
# ships no override, so a BTS-only search finds nothing. What each goody
# outcome DOES; which outcomes a difficulty can draw is the <Goodies> table
# inside CIV4HandicapInfo.xml, not here.
GOODY_FILE = os.path.join("GameInfo", "CIV4GoodyInfo.xml")
BUILDING_CLASS_FILE = os.path.join("Buildings", "CIV4BuildingClassInfos.xml")
COMMERCE_FILE = os.path.join("GameInfo", "CIV4CommerceInfo.xml")
YIELD_FILE = os.path.join("Terrain", "CIV4YieldInfos.xml")
IMPROVEMENT_FILE = os.path.join("Terrain", "CIV4ImprovementInfos.xml")
TERRAIN_FILE = os.path.join("Terrain", "CIV4TerrainInfos.xml")
FEATURE_FILE = os.path.join("Terrain", "CIV4FeatureInfos.xml")
# Vanilla-only on the measured install, like CIV4BonusInfos.xml. Reached only
# for Financial: the state file exports `player.leader` but no traits, so the
# leader -> trait -> yield-threshold join happens here rather than being read.
TRAIT_FILE = os.path.join("Civilizations", "CIV4TraitInfos.xml")
LEADER_FILE = os.path.join("Civilizations", "CIV4LeaderHeadInfos.xml")
PROJECT_FILE = os.path.join("GameInfo", "CIV4ProjectInfo.xml")
RELIGION_FILE = os.path.join("GameInfo", "CIV4ReligionInfo.xml")
# Maps each civ to the unit/building types that replace a class for them only.
# Needed by `city`: without it every other civ's unique unit is tech-open for
# you and the list is 34 rows instead of 18, most of them unbuildable forever.
CIVILIZATION_FILE = os.path.join("Civilizations", "CIV4CivilizationInfos.xml")
# Vanilla-only on the measured install - BTS did not change resources.
BONUS_FILE = os.path.join("Terrain", "CIV4BonusInfos.xml")
# The game's own one-line pitch for a building, keyed from <Strategy>. This is
# the only place an SDK-implemented effect is written down in English - the
# Pyramids' "access all Government civics" appears nowhere in the data fields.
STRATEGY_FILE = os.path.join("Text", "CIV4GameText_Strategy.xml")

# Tech-block booleans that are real, player-visible abilities. These are
# EFFECTS, not entries in another file, so nothing reverse-indexes them and a
# tech carrying only these would otherwise render as doing nothing at all.
# `bTrade`/`bGoodyTech` are deliberately absent: nearly every tech sets them,
# so printing them is noise that buries the meaningful flags.
TECH_ABILITY_FLAGS = (
    ("bBridgeBuilding", "workers can build roads over rivers"),
    ("bIrrigation", "farms can be chained from fresh water"),
    ("bIgnoreIrrigation", "farms can be built without a water source"),
    ("bWaterWork", "cities can work water tiles"),
    ("bMapTrading", "world maps can be traded"),
    ("bTechTrading", "technologies can be traded"),
    ("bGoldTrading", "gold can be traded"),
    ("bOpenBordersTrading", "open borders agreements become available"),
    ("bDefensivePactTrading", "defensive pacts become available"),
    ("bPermanentAllianceTrading", "permanent alliances become available"),
    ("bVassalTrading", "vassal states become available"),
    ("bRiverTrade", "trade routes can run along rivers"),
    ("bExtraWaterSeeFrom", "ships see one tile further"),
    ("bMapCentering", "the map can be re-centred"),
    ("bMapVisible", "the whole map becomes visible"),
)

# Numeric tech-block effects, printed only when non-zero.
TECH_ABILITY_VALUES = (
    ("iFeatureProductionModifier", "%+d%% production from chopping features"),
    ("iWorkerSpeedModifier", "%+d%% worker speed"),
    ("iTradeRoutes", "%+d trade route per city"),
    ("iHealth", "%+d health in every city"),
    ("iHappiness", "%+d happiness in every city"),
)

# These files are not UTF-8; they carry accented leader/unit names in a
# single-byte encoding. Decoding strictly as UTF-8 raises on the real install.
XML_ENCODING = "latin-1"

# Handicap fields worth printing, in the order they are printed, with what each
# one actually means. The set is deliberately narrow: barbarian and animal rules
# only, because those are the ones that changed two trials' conclusions and the
# ones whose names do not explain themselves.
#
# iAnimalBonus/iBarbarianBonus are the trap. The value is negative and applies
# TO THE ATTACKER - a -40 animal is weaker than its raw strength, not stronger.
# Read as a bonus for the barbarian, the sign is exactly backwards.
ANIMAL_FIELDS = (
    ("iAnimalAttackProb", "% chance an animal attacks an adjacent unit"),
    ("iAnimalBonus", "combat modifier applied TO THE ANIMAL (negative = weaker)"),
    ("iUnownedTilesPerGameAnimal", "one animal per N unowned tiles"),
)
BARBARIAN_FIELDS = (
    # "no barbarians before turn N" is how this field was read in a live trial,
    # and it cost a unit: it bounds MAP SPAWNS only, and a goody hut can hand
    # you a hostile warband on turn 1. The qualifier is not decoration.
    ("iBarbarianCreationTurnsElapsed", "no MAP-SPAWNED barbarians before this "
                                       "turn (huts are NOT gated by it)"),
    ("iBarbarianCityCreationTurnsElapsed", "no barbarian cities before this turn"),
    ("iUnownedTilesPerBarbarianUnit", "one barbarian per N unowned land tiles"),
    ("iUnownedWaterTilesPerBarbarianUnit", "one per N unowned water tiles"),
    ("iUnownedTilesPerBarbarianCity", "one barbarian city per N unowned tiles"),
    ("iBarbarianCityCreationProb", "% chance per check"),
    ("iBarbarianBonus", "combat modifier applied TO THE BARBARIAN"),
    ("iBarbarianDefenders", "defenders in a new barbarian city"),
    ("iFreeWinsVsBarbs", "first N losses vs barbs/animals are negated"),
)


# Engine constants behind `goody`, none of them in the XML this module parses.
#
# NUM_DO_GOODY_ATTEMPTS is why this is not a twenty-row table print:
# `CvPlayer::doGoody` re-draws an ineligible outcome rather than skipping it,
# up to this many times, so a blocked entry's weight lands on the rows that
# remain - hostile included. All ten can fail, and the hut is then consumed for
# nothing (its goody is removed BEFORE the loop), which is why the eligible
# shares deliberately sum short of 100%. Derivation in REFERENCES.md.
NUM_DO_GOODY_ATTEMPTS = 10          # GlobalDefines.xml, same in both trees

# Both in ELAPSED game turns, from `canReceiveGoody`. They are what make the
# early game the WORST case for a hut rather than the safest.
GOODY_EXPERIENCE_MIN_TURNS = 10
GOODY_COMBAT_UNIT_MIN_TURNS = 20

# `canReceiveGoody` refuses a hostile result within `8 - getNumCities()` tiles
# of your city while you have exactly one - so 7, and the check stops applying
# at two. Founding a second city REMOVES this protection from every hut.
GOODY_BARB_SAFE_RADIUS_AT_ONE_CITY = 8

# Printed at the foot of every view. One copy, because four hand-maintained
# copies of the same caveat is how one of them quietly drifts.
MOD_WARNING = "Vanilla BTS rules only - wrong if a gameplay mod is loaded."

# How many techs beyond what you know a blocked row may sit before it is
# horizon noise rather than a blocker. 1 means "the tech you could finish next".
# Measured at t43 on the baseline: of 64 tech-blocked units, 13 are one tech
# away and 8 need twenty-one - the far tail is Battleships and Airships, which
# buried the four rows that mattered under 453 lines of output.
NEAR_TECH_HORIZON = 1

# Blockers that no amount of research clears soon, and that the tech-distance
# cut therefore cannot see: religion presence and corporations are both
# tech-open at t43 while being eras away in practice. Marked with a prefix
# rather than matched on prose, so rewording a message cannot silently change
# which rows are listed.
OUT_OF_SCOPE = "[later] "


class RulesError(Exception):
    """Anything that should exit non-zero with a message rather than a traceback."""


# ---------------------------------------------------------------------------
# Locating the XML
# ---------------------------------------------------------------------------


def find_repo_root(start=None):
    """Walk up from this file looking for config.local.json's directory."""
    here = os.path.abspath(start or os.path.dirname(__file__))
    while True:
        if os.path.isfile(os.path.join(here, "config.local.json.example")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        here = parent


def resolve_xml_root(config_path=None):
    """Return the install's two XML roots as (bts_root, vanilla_root).

    Deliberately not a search. `find -iname CIV4UnitInfos.xml` returns 18 hits
    on this install, and every one of them parses cleanly, so a wrong pick
    produces confident wrong answers rather than an error. The paths are
    composed from config and then ASSERTED, which keeps the Mods/ copies out.

    A missing config is fatal rather than defaulted: falling back to a guessed
    install path would reintroduce exactly the silent-wrong-ruleset failure this
    function exists to prevent.
    """
    if config_path is None:
        config_path = os.path.join(find_repo_root(), "config.local.json")
    if not os.path.isfile(config_path):
        raise RulesError(
            "config.local.json not found at %s\n"
            "Copy config.local.json.example and set civ4_install_path to your "
            "Civ IV install." % config_path
        )
    try:
        with open(config_path, "r") as handle:
            config = json.load(handle)
    except ValueError as exc:
        raise RulesError("config.local.json is not valid JSON: %s" % exc)

    install = config.get("civ4_install_path")
    if not install:
        raise RulesError("config.local.json has no civ4_install_path")

    bts_root = os.path.join(install, BTS_XML_ROOT)
    vanilla_root = os.path.join(install, VANILLA_XML_ROOT)
    if BTS_XML_ROOT not in bts_root:
        raise RulesError("resolved XML root is not a Beyond the Sword path: %s" % bts_root)
    if not os.path.isdir(bts_root):
        raise RulesError(
            "Beyond the Sword XML not found at %s\n"
            "Expected <civ4_install_path>/%s" % (bts_root, BTS_XML_ROOT)
        )
    return bts_root, vanilla_root


def read_xml(roots, relative, required=True):
    """Read `relative` from the BTS tree, falling back to vanilla.

    Returns (text, path, tree) where `tree` is "BTS" or "vanilla", because
    which tree a fact came from is worth printing: a vanilla-sourced answer is
    still correct for a BTS game (the engine reads it the same way), but it
    means BTS did not change that data, which is a fact about the answer.

    `required=False` returns (None, None, None) for a genuinely absent file,
    so an optional source does not turn into a crash.
    """
    bts_root, vanilla_root = roots
    for root, tree in ((bts_root, "BTS"), (vanilla_root, "vanilla")):
        path = os.path.join(root, relative)
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                return handle.read().decode(XML_ENCODING), path, tree
    if not required:
        return None, None, None
    raise RulesError(
        "XML file not found in either tree: %s\n"
        "  looked in %s\n  and       %s" % (relative, bts_root, vanilla_root)
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
#
# Regex rather than ElementTree, for one measured reason: the line number of each
# block is part of the output. The whole point of printing `CIV4UnitInfos.xml:1234`
# is that `grep -A6` does not reach PrereqTech, so an agent that wants the detail
# needs to jump to the block, not re-find it. ElementTree discards source
# positions (iterparse can recover them, but only per-element and not for the
# block start). These files are also machine-generated and flat, which is the
# case where regex is safe.


def _tag(block, name, default=None):
    match = re.search(r"<%s>(.*?)</%s>" % (name, name), block, re.S)
    return match.group(1).strip() if match else default


def _int_tag(block, name, default=0):
    raw = _tag(block, name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _list_tag(block, container, item="PrereqTech"):
    """Return the items inside <container>, or [] if absent or self-closing."""
    match = re.search(r"<%s>(.*?)</%s>" % (container, container), block, re.S)
    if not match:
        return []
    return re.findall(r"<%s>(.*?)</%s>" % (item, item), match.group(1), re.S)


def iter_blocks(text, tag):
    """Yield (type_key, block_text, line_number) for each <tag> element.

    The line number is found by bisecting a precomputed newline index rather
    than by counting newlines from the start of the file per block, which is
    quadratic in file size and was the single largest cost in startup: on the
    1.1MB CIV4BuildingInfos.xml the counting alone measured 159ms against
    31ms for the whole parse. Every subcommand pays this on every
    invocation, and the tool is run once per turn.
    """
    newlines = [match.start() for match in re.finditer("\n", text)]
    for match in re.finditer(r"<%s>.*?</%s>" % (tag, tag), text, re.S):
        block = match.group(0)
        type_key = _tag(block, "Type")
        if type_key:
            yield type_key, block, bisect.bisect_right(newlines, match.start()) + 1


def parse_techs(text):
    techs = {}
    for key, block, line in iter_blocks(text, "TechInfo"):
        abilities = []
        for flag, description in TECH_ABILITY_FLAGS:
            if _int_tag(block, flag) == 1:
                abilities.append(description)
        for field, template in TECH_ABILITY_VALUES:
            value = _int_tag(block, field)
            if value:
                abilities.append(template % value)
        techs[key] = {
            "type": key,
            "cost": _int_tag(block, "iCost"),
            "era": _tag(block, "Era"),
            "line": line,
            "or": _list_tag(block, "OrPreReqs"),
            "and": _list_tag(block, "AndPreReqs"),
            "abilities": abilities,
            "free_units": _tag(block, "FirstFreeUnitClass"),
            "free_techs": _int_tag(block, "iFirstFreeTechs"),
        }
    return techs


def parse_units(text):
    units = {}
    for key, block, line in iter_blocks(text, "UnitInfo"):
        combat_mods = []
        mods_block = re.search(r"<UnitCombatMods>(.*?)</UnitCombatMods>", block, re.S)
        if mods_block:
            for mod in re.finditer(
                r"<UnitCombatType>(.*?)</UnitCombatType>\s*"
                r"<iUnitCombatMod>(-?\d+)</iUnitCombatMod>",
                mods_block.group(1),
                re.S,
            ):
                combat_mods.append((mod.group(1).strip(), int(mod.group(2))))

        # Modifiers against a specific unit CLASS, which are a different
        # container from the <UnitCombatMods> above and were invisible until
        # someone asked what a Chariot does: its +100% vs UNITCLASS_AXEMAN is
        # the unit's whole point and printed nowhere. Three containers, because
        # the engine distinguishes attacking from defending and from both:
        # a Chariot's bonus applies only when IT attacks, while a Greek
        # Phalanx's +100% vs chariots applies only when it DEFENDS. Collapsing
        # them into one line would invert exactly the fact that decides whether
        # to attack or wait.
        class_mods = {}
        for container, label in (
            ("UnitClassAttackMods", "attacking"),
            ("UnitClassDefenseMods", "defending vs"),
            ("UnitClassMods", "vs"),
        ):
            found = []
            mods_block = re.search(r"<%s>(.*?)</%s>" % (container, container),
                                   block, re.S)
            if mods_block:
                for mod in re.finditer(
                    r"<UnitClassType>(.*?)</UnitClassType>\s*"
                    r"<iUnitClassMod>(-?\d+)</iUnitClassMod>",
                    mods_block.group(1),
                    re.S,
                ):
                    value = int(mod.group(2))
                    if value:
                        found.append((mod.group(1).strip(), value))
            class_mods[label] = found

        # Immunity to another class's collateral damage, per source class.
        # Every siege unit is immune to siege collateral - so a stack of
        # catapults does not grind itself down, which is why massed siege
        # works at all. Nested pairs like the flanking block below; a first
        # pass at this checked <bUnitCombatCollateralImmune> and found nothing,
        # because the real field is <iUnitCombatCollateralImmune>.
        collateral_immune = []
        immune_block = re.search(
            r"<UnitCombatCollateralImmunes>(.*?)</UnitCombatCollateralImmunes>",
            block, re.S)
        if immune_block:
            for entry in re.finditer(
                r"<UnitCombatType>(.*?)</UnitCombatType>\s*"
                r"<iUnitCombatCollateralImmune>(\d)</iUnitCombatCollateralImmune>",
                immune_block.group(1),
                re.S,
            ):
                if entry.group(2) == "1":
                    collateral_immune.append(entry.group(1).strip())

        # Flanking is per TARGET CLASS, not a flat unit stat: a Horse Archer
        # gets a flanking strike against catapults and trebuchets specifically,
        # and against nothing else. A bare <iFlankingStrength> sweep finds the
        # nested values and reads as though the unit flanked everything - which
        # is what a first pass at this did.
        flanking = []
        flank_block = re.search(r"<FlankingStrikes>(.*?)</FlankingStrikes>",
                                block, re.S)
        if flank_block:
            for strike in re.finditer(
                r"<FlankingStrikeUnitClass>(.*?)</FlankingStrikeUnitClass>\s*"
                r"<iFlankingStrength>(-?\d+)</iFlankingStrength>",
                flank_block.group(1),
                re.S,
            ):
                flanking.append((strike.group(1).strip(), int(strike.group(2))))

        prereq_bonuses = [
            bonus
            for bonus in _list_tag(block, "PrereqBonuses", "BonusType")
            if bonus != "NONE"
        ]

        # Promotions the unit is BUILT with, which is a different fact from the
        # ones it can earn and the only reason an Explorer starts able to cross
        # jungle at full speed. The <bFreePromotion> flag is checked rather than
        # taking every PromotionType in the block: the container is a list of
        # (promotion, flag) pairs, so a flat list would also collect any entry
        # explicitly turned OFF. 18 units carry these on the real install.
        free_promotions = []
        free_block = re.search(r"<FreePromotions>(.*?)</FreePromotions>",
                               block, re.S)
        if free_block:
            for entry in re.finditer(
                r"<PromotionType>(.*?)</PromotionType>\s*"
                r"<bFreePromotion>(\d)</bFreePromotion>",
                free_block.group(1),
                re.S,
            ):
                if entry.group(2) == "1":
                    free_promotions.append(entry.group(1).strip())
        bonus_type = _tag(block, "BonusType")
        religion = _tag(block, "PrereqReligion")
        corporation = _tag(block, "PrereqCorporation")

        units[key] = {
            "type": key,
            "line": line,
            # bFood: this unit is built with food AND hammers. Settlers and
            # workers convert the city's whole food surplus into production, so
            # the city stops growing and the build finishes much faster. See
            # food_build_rate().
            "food_production": _int_tag(block, "bFood") == 1,
            # DOMAIN_SEA needs a coastal city - the gate that let a landlocked
            # Lisbon list a Work Boat as available.
            "domain": _tag(block, "Domain"),
            "religion": religion if religion and religion != "NONE" else None,
            "corporation": (corporation
                            if corporation and corporation != "NONE" else None),
            # "NONE" normalized to None - settlers/workers/etc. carry literal
            # <Combat>NONE</Combat>, and CvGameCoreUtils::isPromotionValid
            # refuses every promotion outright when getUnitCombatType() is
            # NO_UNITCOMBAT (see _promotable_promotions).
            "combat_class": (lambda c: c if c and c != "NONE" else None)(
                _tag(block, "Combat")),
            "strength": _int_tag(block, "iCombat"),
            "moves": _int_tag(block, "iMoves"),
            # A percentage bonus against <bAnimal> units only, and the reason a
            # Scout survives a Lion far more often than raw strength 1 vs 2
            # suggests. It is an ordinary combat modifier that happens to live
            # in its own field rather than in <UnitCombatMods>, which is why it
            # was missing here: a trial hand-estimated those odds and flagged
            # the number as a guess - the one unconfident answer it gave all
            # session. Measured on the install, UNIT_SCOUT is the ONLY unit
            # carrying a non-zero value, and exactly four units are bAnimal
            # (lion, bear, panther, wolf).
            "animal_combat": _int_tag(block, "iAnimalCombat"),
            # Marks this unit as one the modifier above applies against, so the
            # view can say which side of that matchup it is on.
            "is_animal": _int_tag(block, "bAnimal") == 1,
            "cost": _int_tag(block, "iCost"),
            "prereq_tech": _tag(block, "PrereqTech"),
            "bonus_type": bonus_type if bonus_type != "NONE" else None,
            "prereq_bonuses": prereq_bonuses,
            "unit_class": _tag(block, "Class"),
            "combat_mods": combat_mods,
            "class_mods": class_mods,
            "flanking": flanking,
            "collateral_immune": collateral_immune,
            "free_promotions": free_promotions,
            # Cannot draw a HOSTILE result from a goody hut. Only the Scout and
            # the Explorer carry it, and it is the single most decision-relevant
            # field in the file for turns 0-50: the hut that killed a trial's
            # warrior could not have killed a scout. Directly relevant to
            # `goody-hut-outcomes`, whose whole subject is that roll.
            "no_bad_goodies": _int_tag(block, "bNoBadGoodies") == 1,
            # Immune to the defender's first strikes - the mounted line's
            # answer to archers and drill promotions. 9 units, several early
            # (Egyptian War Chariot, Horse Archer, Knight).
            "first_strike_immune": _int_tag(block, "bFirstStrikeImmune") == 1,
            # The damage ceiling a unit can inflict, as a percentage. 100 is
            # the default and means no cap; 0 marks a non-combat unit. Only six
            # units in the file carry a real limit, and UNIT_CATAPULT (75) is
            # the one that matters before turn 50: siege damages a stack but
            # CANNOT land the killing blow, so "the catapult will finish it"
            # is a plausible, wrong plan the raw strength number invites.
            "combat_limit": _int_tag(block, "iCombatLimit"),
            "first_strikes": _int_tag(block, "iFirstStrikes"),
            "city_defense": _int_tag(block, "iCityDefense"),
            # Percentage points of a city's DEFENCE BONUS knocked down per
            # bombarding turn - a third, separate mechanic from collateral
            # damage (which hits units in a stack) and from iCityAttack (a
            # combat modifier). A Catapult's 8 means roughly three turns to
            # strip a 25% culture bonus before the assault, which is the whole
            # reason siege leads a stack rather than following it. 12 units,
            # Catapult being the early one; naval bombardment shares the field.
            "bombard_rate": _int_tag(block, "iBombardRate"),
            # The attacking half of the same matchup, and printed alongside
            # iCityDefense because showing one without the other is worse than
            # showing neither: a Swordsman's +10% vs cities is exactly the
            # question "should this unit lead the assault" turns on. Five units,
            # four of them early (Swordsman and three uniques).
            "city_attack": _int_tag(block, "iCityAttack"),
            # A UNIT flag about a BUILDING effect: the city's walls-type
            # defence bonus does not apply against this attacker. Named in the
            # output rather than echoed as a field name, since "ignores
            # building defence" assumes the reader knows which buildings.
            # Nothing before Gunpowder carries it - Musketman is the earliest.
            "ignore_building_defense": (
                _int_tag(block, "bIgnoreBuildingDefense") == 1),
            # The archer line's signature bonus, and absent from the output
            # until someone asked why an Archer on a hill was not reported as
            # stronger. Four units carry it (Archer, Longbowman and two of
            # their uniques), all at 25; iHillsAttack exists in the schema and
            # is zero on every unit in the file, so it is parsed but never
            # printed unless a mod sets one.
            "hills_defense": _int_tag(block, "iHillsDefense"),
            "hills_attack": _int_tag(block, "iHillsAttack"),
            "withdrawal": _int_tag(block, "iWithdrawalProb"),
            "no_defensive_bonus": _int_tag(block, "bNoDefensiveBonus") == 1,
            "terrain_impassable": _list_tag(block, "TerrainImpassables", "TerrainType"),
            "feature_impassable": _list_tag(block, "FeatureImpassables", "FeatureType"),
            # `only_defensive` and `interception` are read for
            # _promotable_promotions' isPromotionValid cascade
            # (CvGameCoreUtils.cpp) and not surfaced in `unit`'s own output -
            # interception is air combat, far outside the advising window.
            "only_defensive": _int_tag(block, "bOnlyDefensive") == 1,
            "ignore_terrain_cost": _int_tag(block, "bIgnoreTerrainCost") == 1,
            "interception": _int_tag(block, "iInterceptionProbability"),
            # All three are needed together to deal collateral damage, which is
            # the cascade's own test at _promotable_promotions and the reason
            # the view gates on `collateral_damage` rather than on the limit:
            # 25 units carry a non-zero limit and max-units while dealing NO
            # collateral, because flanking damage reuses the same two fields.
            # Gating on the limit would report a Knight as a siege unit.
            "collateral_damage": _int_tag(block, "iCollateralDamage"),
            "collateral_damage_limit": _int_tag(block, "iCollateralDamageLimit"),
            "collateral_damage_max_units": _int_tag(block, "iCollateralDamageMaxUnits"),
        }
    return units


def _named_int_pairs(block, container, item, name_field, value_field):
    """(name, value) pairs from a <container><item><name_field/><value_field/>
    ...</item></container> block - the shape TerrainDefenses/FeatureAttacks/
    UnitCombatMods and friends all share, in CIV4UnitInfos.xml and
    CIV4PromotionInfos.xml alike."""
    match = re.search(r"<%s>(.*?)</%s>" % (container, container), block, re.S)
    if not match:
        return []
    pairs = []
    for entry in re.finditer(r"<%s>(.*?)</%s>" % (item, item), match.group(1), re.S):
        name = _tag(entry.group(1), name_field)
        value = _int_tag(entry.group(1), value_field)
        if name:
            pairs.append((name, value))
    return pairs


def parse_promotions(text):
    """PROMOTION_ entries: what CyUnit.isHasPromotion(i) means when it's true.

    Mirrors parse_units' shape - a flat dict of nonzero/named effects plus the
    prerequisite chain - because a promotion IS a small unit-modifier bundle in
    the same XML family (CIV4PromotionInfos.xml sits in Units/, beside
    CIV4UnitInfos.xml), not a different kind of thing needing new machinery.
    """
    promotions = {}
    for key, block, line in iter_blocks(text, "PromotionInfo"):
        prereq = _tag(block, "PromotionPrereq")
        prereq_or = [
            p for p in (_tag(block, "PromotionPrereqOr1"),
                       _tag(block, "PromotionPrereqOr2"))
            if p and p != "NONE"
        ]
        tech = _tag(block, "TechPrereq")
        promotions[key] = {
            "type": key,
            "line": line,
            "prereq": prereq if prereq and prereq != "NONE" else None,
            "prereq_or": prereq_or,
            "tech": tech if tech and tech != "NONE" else None,
            # Great General field promotions (PROMOTION_LEADER and friends) -
            # isPromotionValid's bLeader argument is never true for a normal
            # unit picking a promotion via XP, so these are excluded outright
            # by _promotable_promotions rather than evaluated against the
            # unit-combat-class/isOnlyDefensive/etc. checks that follow.
            "is_leader": _int_tag(block, "bLeader") == 1,
            # Flat +N%/+N modifiers, printed only when nonzero - see view_promotion.
            "combat_percent": _int_tag(block, "iCombatPercent"),
            "city_attack": _int_tag(block, "iCityAttack"),
            "city_defense": _int_tag(block, "iCityDefense"),
            "hills_attack": _int_tag(block, "iHillsAttack"),
            "hills_defense": _int_tag(block, "iHillsDefense"),
            "withdrawal": _int_tag(block, "iWithdrawalChange"),
            "first_strikes": _int_tag(block, "iFirstStrikesChange"),
            "chance_first_strikes": _int_tag(block, "iChanceFirstStrikesChange"),
            "moves": _int_tag(block, "iMovesChange"),
            "visibility": _int_tag(block, "iVisibilityChange"),
            "intercept_change": _int_tag(block, "iInterceptChange"),
            "collateral_protection": _int_tag(block, "iCollateralDamageProtection"),
            "collateral_damage_change": _int_tag(block, "iCollateralDamageChange"),
            "pillage": _int_tag(block, "iPillageChange"),
            "experience_percent": _int_tag(block, "iExperiencePercent"),
            "same_tile_heal": _int_tag(block, "iSameTileHealChange"),
            "adjacent_tile_heal": _int_tag(block, "iAdjacentTileHealChange"),
            "neutral_heal": _int_tag(block, "iNeutralHealChange"),
            "enemy_heal": _int_tag(block, "iEnemyHealChange"),
            "always_heal": _int_tag(block, "bAlwaysHeal") == 1,
            "hills_double_move": _int_tag(block, "bHillsDoubleMove") == 1,
            "amphib": _int_tag(block, "bAmphib") == 1,
            "river": _int_tag(block, "bRiver") == 1,
            "blitz": _int_tag(block, "bBlitz") == 1,
            "immune_to_first_strikes": _int_tag(block, "bImmuneToFirstStrikes") == 1,
            # Terrain/feature bonuses and double-moves, and which unit-combat
            # classes this promotion is even offered to - all (name, value)
            # or plain-name lists, since a unit answering isHasPromotion(i)
            # true has already passed every prerequisite; what's useful here
            # is what the promotion DOES and where it needs a unit combat
            # class it does not already carry.
            "terrain_attack": _named_int_pairs(
                block, "TerrainAttacks", "TerrainAttack", "TerrainType", "iTerrainAttack"),
            "terrain_defense": _named_int_pairs(
                block, "TerrainDefenses", "TerrainDefense", "TerrainType", "iTerrainDefense"),
            "feature_attack": _named_int_pairs(
                block, "FeatureAttacks", "FeatureAttack", "FeatureType", "iFeatureAttack"),
            "feature_defense": _named_int_pairs(
                block, "FeatureDefenses", "FeatureDefense", "FeatureType", "iFeatureDefense"),
            "terrain_double_move": _list_tag(block, "TerrainDoubleMoves", "TerrainType"),
            "feature_double_move": _list_tag(block, "FeatureDoubleMoves", "FeatureType"),
            "unit_combat_mods": _named_int_pairs(
                block, "UnitCombatMods", "UnitCombatMod", "UnitCombatType", "iUnitCombatMod"),
            "domain_mods": _named_int_pairs(
                block, "DomainMods", "DomainMod", "DomainType", "iDomainMod"),
            "restricted_to_unit_combats": _list_tag(
                block, "UnitCombats", "UnitCombatType"),
        }
    return promotions


def parse_simple(text, tag, tech_field="PrereqTech", extra=()):
    """Parse blocks that gate on a single tech field.

    `tech_field` differs by file and the inconsistency is real: buildings and
    units use <PrereqTech>, civics, religions and projects use <TechPrereq>.
    Getting it wrong yields an empty index rather than an error, so each caller
    names its own field.
    """
    entries = {}
    for key, block, line in iter_blocks(text, tag):
        entry = {"type": key, "line": line, "tech": _tag(block, tech_field)}
        for name in extra:
            entry[name] = _tag(block, name)
        entries[key] = entry
    return entries


def parse_builds(text):
    """Worker actions, including the nested per-feature prerequisites.

    BUILD_MINE gates on TECH_MINING at the top level, but inside
    <FeatureStructs> each feature carries its OWN <PrereqTech>: removing
    FEATURE_FOREST needs TECH_BRONZE_WORKING (for 30 hammers), jungle needs
    TECH_IRON_WORKING. So "Bronze Working lets you chop forest" is a nested
    prereq, and a flat index over PrereqTech would instead report Bronze
    Working as unlocking BUILD_MINE - which is wrong, Mining does that.

    An agent trial supplied chopping from memory because the tool showed
    nothing; this is the structure that has to be walked to avoid that.
    """
    builds = {}
    for key, block, line in iter_blocks(text, "BuildInfo"):
        features = []
        structs = re.search(r"<FeatureStructs>(.*?)</FeatureStructs>", block, re.S)
        if structs:
            for struct in re.finditer(r"<FeatureStruct>(.*?)</FeatureStruct>",
                                      structs.group(1), re.S):
                body = struct.group(1)
                features.append({
                    "feature": _tag(body, "FeatureType"),
                    "tech": _tag(body, "PrereqTech"),
                    "production": _int_tag(body, "iProduction"),
                    "remove": _int_tag(body, "bRemove") == 1,
                })
        builds[key] = {
            "type": key,
            "line": line,
            "tech": _tag(block, "PrereqTech"),
            "improvement": _tag(block, "ImprovementType"),
            "route": _tag(block, "RouteType"),
            "features": features,
        }
    return builds


def parse_ordered_types(text, tag):
    """The Type keys of `tag`, in file order.

    Several building fields are POSITIONAL arrays with no labels: a Library's
    <CommerceModifiers> is just <iCommerce>0</iCommerce><iCommerce>25</iCommerce>,
    and it means +25% science only because index 1 is COMMERCE_RESEARCH. That
    order lives in CIV4CommerceInfo.xml, not in the block, so it is read rather
    than hardcoded - guessing it is a silent, plausible mistranslation.
    """
    return [key for key, _block, _line in iter_blocks(text, tag)]


def _wrap(text, width):
    """Wrap to `width`, stdlib-only and without pulling in textwrap's defaults."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = word if not current else current + " " + word
    if current:
        lines.append(current)
    return lines


def _plain(type_key):
    """`COMMERCE_CULTURE` -> `culture`. Presentation only.

    Everywhere else this tool prints XML keys verbatim, because they are what
    you grep for and what the state JSON joins on. Commerce and yield names are
    the exception: they appear inside effect sentences, where a raw key reads
    as jargon in the middle of English.
    """
    for prefix in ("COMMERCE_", "YIELD_"):
        if type_key.startswith(prefix):
            return type_key[len(prefix):].lower()
    return type_key


def _commerce_list(block, container, order):
    """Label a positional <iCommerce> array using the resolved order."""
    match = re.search(r"<%s>(.*?)</%s>" % (container, container), block, re.S)
    if not match:
        return []
    values = re.findall(r"<iCommerce>(-?\d+)</iCommerce>", match.group(1))
    labelled = []
    for index, raw in enumerate(values):
        value = int(raw)
        if value and index < len(order):
            labelled.append((order[index], value))
    return labelled


def _yield_list(block, container, order):
    match = re.search(r"<%s>(.*?)</%s>" % (container, container), block, re.S)
    if not match:
        return []
    values = re.findall(r"<iYield>(-?\d+)</iYield>", match.group(1))
    labelled = []
    for index, raw in enumerate(values):
        value = int(raw)
        if value and index < len(order):
            labelled.append((order[index], value))
    return labelled


def _without_nested(block, *containers):
    """`block` with the named container blocks removed entirely.

    Needed because these files nest a container under the SAME name inside a
    child struct. An ImprovementInfo's own <YieldChanges> and the <YieldChanges>
    inside each of its <BonusTypeStruct>s are indistinguishable to a
    non-anchored search, and re.S makes the first match win regardless of
    depth - so reading a Farm's own yields returns the Corn struct's +2 food
    instead of the correct "Farm has no flat yield of its own".

    That is not a hypothetical: it produced 6 food for a farmed Corn tile
    during development, one short of the 4 the original trial reported and
    equally wrong. Strip the children, then scan.
    """
    for container in containers:
        block = re.sub(r"<%s>.*?</%s>" % (container, container), "", block, flags=re.S)
    return block


def _yield_triplet(block, container, item=r"iYield(?:Change)?"):
    """A [food, production, commerce] triplet from `container`, or None.

    The three yields are a POSITIONAL array here, same as the commerce arrays
    _yield_list handles, but the terrain/feature/improvement files want the
    zeroes kept: the arithmetic adds triplets together, and a labelled
    sparse list would have to be re-densified at every call site.

    None rather than [0,0,0] when the container is absent, because that
    distinction is real in these files - CIV4TerrainInfos omits <Yields>
    entirely for desert and snow, and the caller needs to know it read
    "nothing here" rather than "explicitly zero" when reconciling against
    a source that lists the field.

    The inner tag is NOT the same across files and this bit three times
    during development: <Yields> holds <iYield>, <YieldChanges> holds
    <iYieldChange>, and Financial's <ExtraYieldThresholds> holds
    <iExtraYieldThreshold>. Guessing wrong returns None rather than raising,
    so the symptom is a silently missing term - a jungle that fails to
    subtract its food, or a Financial leader who gets no commerce - not an
    error. Hence `item` is an explicit parameter for anything unusual rather
    than an ever-widening default pattern.
    """
    match = re.search(r"<%s>(.*?)</%s>" % (container, container), block, re.S)
    if not match:
        return None
    body = match.group(1)
    values = re.findall(r"<%s>(-?\d+)</%s>" % (item, item), body)
    if not values:
        return None
    triplet = [int(raw) for raw in values[:3]]
    while len(triplet) < 3:
        triplet.append(0)
    return triplet


def parse_buildings(text, commerce_order=(), yield_order=()):
    """Buildings and wonders - one file, one block shape, different behaviour.

    The wonder distinction is NOT in this file: it comes from
    CIV4BuildingClassInfos.xml, where iMaxGlobalInstances 1 means one per world
    and iMaxPlayerInstances 1 means one per player (a national wonder). That
    matters more to a decision than any effect, so it leads the output.

    Free experience is nested in <DomainFreeExperiences>, the same shape as the
    per-feature build prereqs - a flat scan misses it, which is how an agent
    trial ended up hand-deriving "Barracks gives +3 XP" from raw XML.
    """
    buildings = {}
    for key, block, line in iter_blocks(text, "BuildingInfo"):
        experience = []
        domains = re.search(r"<DomainFreeExperiences>(.*?)</DomainFreeExperiences>",
                            block, re.S)
        if domains:
            for entry in re.finditer(
                r"<DomainFreeExperience>(.*?)</DomainFreeExperience>",
                domains.group(1), re.S,
            ):
                amount = _int_tag(entry.group(1), "iExperience")
                if amount:
                    experience.append((_tag(entry.group(1), "DomainType"), amount))

        prereq_buildings = _list_tag(block, "PrereqBuildingClasses",
                                     "BuildingClassType")
        bonus = _tag(block, "Bonus")
        religion = _tag(block, "PrereqReligion")
        holy_city = _tag(block, "HolyCity")
        corporation = _tag(block, "PrereqCorporation")
        buildings[key] = {
            "type": key,
            "line": line,
            "religion": religion if religion and religion != "NONE" else None,
            "holy_city": holy_city if holy_city and holy_city != "NONE" else None,
            "corporation": (corporation
                            if corporation and corporation != "NONE" else None),
            "strategy_key": _tag(block, "Strategy"),
            "tech": _tag(block, "PrereqTech"),
            "cost": _int_tag(block, "iCost"),
            "obsolete": _tag(block, "ObsoleteTech"),
            "bonus": bonus if bonus and bonus != "NONE" else None,
            "prereq_bonuses": [b for b in
                               _list_tag(block, "PrereqBonuses", "BonusType")
                               if b != "NONE"],
            "prereq_buildings": [b for b in prereq_buildings if b != "NONE"],
            "health": _int_tag(block, "iHealth"),
            "happiness": _int_tag(block, "iHappiness"),
            "great_people": _int_tag(block, "iGreatPeopleRateChange"),
            "great_person": _tag(block, "GreatPeopleUnitClass"),
            "free_experience": experience,
            "water": _int_tag(block, "bWater") == 1,
            "river": _int_tag(block, "bRiver") == 1,
            "team_share": _int_tag(block, "bTeamShare") == 1,
            "commerce_changes": (
                _commerce_list(block, "CommerceChanges", commerce_order)
                + _commerce_list(block, "ObsoleteSafeCommerceChanges",
                                 commerce_order)),
            "commerce_modifiers": _commerce_list(block, "CommerceModifiers",
                                                 commerce_order),
            "yield_changes": _yield_list(block, "YieldChanges", yield_order),
            "yield_modifiers": _yield_list(block, "YieldModifiers", yield_order),
        }
    return buildings


def strip_game_markup(text):
    """Remove the game's colour codes, keeping everything else intact.

    Only the COLOR_ family is stripped. The same square-bracket syntax also
    carries KEYBOARD KEYS in hotkey help - [CTRL], [SHIFT], [F12], [ESC] - and
    those are real content, so a blanket `\\[[A-Z_0-9]+\\]` strip would quietly
    mangle them. Measured on the file: 1220 COLOR_ tags against ~25 key names.
    """
    text = re.sub(r"\[COLOR_[A-Z_0-9]*\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_strategy_text(text):
    """TXT_KEY -> the English strategy line, markup stripped.

    English only, and taken from the bare <English> element: the same file
    carries French, German, Italian and Spanish siblings, and <Description>
    entries elsewhere nest theirs as <English><Text>. Strategy uses the bare
    form throughout (checked: 408 entries, none nested, none multi-line).
    """
    entries = {}
    for match in re.finditer(r"<TEXT>(.*?)</TEXT>", text, re.S):
        block = match.group(1)
        tag = _tag(block, "Tag")
        english = re.search(r"<English>(.*?)</English>", block, re.S)
        if tag and english:
            cleaned = strip_game_markup(english.group(1))
            if cleaned:
                entries[tag] = cleaned
    return entries


def parse_building_classes(text):
    """The wonder markers, plus the class -> default building back-reference.

    BuildingInfo does not name its own class, so the join runs the other way
    via <DefaultBuilding>. That works for standard buildings and NOT for unique
    replacements (the Incan Terrace replaces a Granary and is no class's
    default), so those resolve to an unknown class - reported, not guessed.
    """
    classes = {}
    for key, block, line in iter_blocks(text, "BuildingClassInfo"):
        classes[key] = {
            "type": key,
            "line": line,
            "default": _tag(block, "DefaultBuilding"),
            "max_global": _int_tag(block, "iMaxGlobalInstances", -1),
            "max_team": _int_tag(block, "iMaxTeamInstances", -1),
            "max_player": _int_tag(block, "iMaxPlayerInstances", -1),
        }
    return classes


def parse_civilizations(text):
    """Per-civ unit and building overrides: which class each civ replaces.

    Only `city` needs this, and it needs it to be honest rather than merely
    tidy. Every civ's unique unit sits in CIV4UnitInfos.xml with an ordinary
    PrereqTech, so a tech-open filter alone reports UNIT_ROME_PRAETORIAN as
    available to Portugal - 34 rows instead of 18 at t43, most of them things
    the player can never build. A unit is yours if no OTHER civ overrides its
    class with it; your own overrides stay, and the class default drops out
    when you override it, which is what "replaces" means.
    """
    civs = {}
    for key, block, line in iter_blocks(text, "CivilizationInfo"):
        units = {}
        for entry in re.finditer(
            r"<UnitClassType>(.*?)</UnitClassType>\s*<UnitType>(.*?)</UnitType>",
            block, re.S,
        ):
            if entry.group(2) != "NONE":
                units[entry.group(1).strip()] = entry.group(2).strip()
        buildings = {}
        for entry in re.finditer(
            r"<BuildingClassType>(.*?)</BuildingClassType>\s*"
            r"<BuildingType>(.*?)</BuildingType>",
            block, re.S,
        ):
            if entry.group(2) != "NONE":
                buildings[entry.group(1).strip()] = entry.group(2).strip()
        civs[key] = {
            "type": key,
            "line": line,
            "units": units,
            "buildings": buildings,
        }
    return civs


def parse_bonuses(text):
    """Resources, with the tech that REVEALS each one.

    TechReveal is the field that changes a conclusion: copper is revealed by
    TECH_BRONZE_WORKING itself, so "you need copper for an Axeman" is not a
    check the player can perform before researching it. TechCityTrade is the
    separate tech that lets a city actually use the resource once connected.
    """
    bonuses = {}
    for key, block, line in iter_blocks(text, "BonusInfo"):
        bonuses[key] = {
            "type": key,
            "line": line,
            "reveal": _tag(block, "TechReveal"),
            "city_trade": _tag(block, "TechCityTrade"),
            # The resource's own contribution to the BARE tile, before any
            # improvement - Corn's +1 food is here, its +2-with-a-Farm is in
            # the Farm's BonusTypeStructs. `improvement --at` needs both and
            # they are easy to conflate: the trial that prompted this item
            # reported 4 food for a farmed Corn tile, which is what dropping
            # one of the two terms produces.
            "yields": _yield_triplet(block, "YieldChanges"),
        }
    return bonuses


def parse_terrains(text):
    """Terrain base yields, plus the river yield change it carries.

    <Yields> is ABSENT rather than zeroed on desert, snow and the three
    non-terrain entries, so `yields` is None for those and the caller treats
    it as all-zero. Hills and peaks are not terrains at all - they are a
    plotType - so their hammer does not come from this file; see
    parse_yield_info.

    <HillsYieldChange> is deliberately NOT read, here or in parse_features.
    calculateNatureYield does consult it (shadowed by the feature's own when
    one is present, exactly like the river term), but it is EMPTY on every
    terrain and every feature in both trees - checked, not assumed - so
    reading it would add an accumulator branch no stock data can reach and
    no test could cover. A mod that sets it would need the branch restored
    alongside the field.
    """
    terrains = {}
    for key, block, line in iter_blocks(text, "TerrainInfo"):
        terrains[key] = {
            "type": key,
            "line": line,
            "yields": _yield_triplet(block, "Yields"),
            "river": _yield_triplet(block, "RiverYieldChange"),
        }
    return terrains


def parse_features(text):
    """Feature yield CHANGES, applied on top of the terrain's own yields.

    Jungle is -1 food, forest +1 production, flood plains +3 food. The river
    and hills changes shadow the terrain's when a feature is present rather
    than stacking with them - see nature_yield, which mirrors the engine's
    own ternary.
    """
    features = {}
    for key, block, line in iter_blocks(text, "FeatureInfo"):
        features[key] = {
            "type": key,
            "line": line,
            "yields": _yield_triplet(block, "YieldChanges"),
            "river": _yield_triplet(block, "RiverYieldChange"),
            "no_improvement": _int_tag(block, "bNoImprovement") == 1,
        }
    return features


def parse_yield_info(text):
    """Where the hills hammer actually comes from.

    Not obvious, and worth stating because looking for it in CIV4TerrainInfos
    finds nothing: TERRAIN_HILL exists there but carries no <Yields>, since
    hills are a plotType layered over a real terrain. The hills and lake
    changes are per-YIELD properties and live here instead, as does the
    city-centre floor.

    <iPeakChange> is deliberately not read: it is 0 for all three yields,
    and a peak short-circuits to [0,0,0] via _impassable before any
    accumulation, so the column is unreachable twice over. Reading it would
    make `_yield_change_for(rules, y, "peak")` look available and correct
    while silently contributing nothing.
    """
    info = {}
    for key, block, line in iter_blocks(text, "YieldInfo"):
        info[key] = {
            "type": key,
            "line": line,
            "hills": _int_tag(block, "iHillsChange"),
            "lake": _int_tag(block, "iLakeChange"),
            # The floor under a city-centre tile: 2 food / 1 hammer /
            # 1 commerce. See _city_floor.
            "min_city": _int_tag(block, "iMinCity"),
        }
    return info


def parse_traits(text):
    """Leader traits, only for the yield effect Financial has.

    <ExtraYieldThresholds> is a positional triplet like every other yield
    array: Financial's entry is 2 in the COMMERCE slot, meaning "a tile
    already producing 2+ commerce gets +1". Read rather than hardcoded
    because the threshold and the column are both data - hardcoding "+1
    commerce on 2+" bakes in a rule the file is entitled to change.
    """
    traits = {}
    for key, block, line in iter_blocks(text, "TraitInfo"):
        traits[key] = {
            "type": key,
            "line": line,
            "yield_thresholds": _yield_triplet(
                block, "ExtraYieldThresholds", "iExtraYieldThreshold"),
        }
    return traits


def parse_leaders(text):
    """Leader -> trait keys. The state file exports `player.leader` and no
    traits at all, so this join is the only route to "is this player FIN".
    """
    leaders = {}
    for key, block, line in iter_blocks(text, "LeaderHeadInfo"):
        leaders[key] = {
            "type": key,
            "line": line,
            "traits": re.findall(r"<TraitType>(\w+)</TraitType>", block),
        }
    return leaders


def parse_improvements(text):
    """Improvements, in full - yields, legality flags and per-resource structs.

    Replaces a parse_simple stub that read only type/line/tech, which is why
    `rules.py` could say a Farm needs Agriculture and nothing whatsoever
    about what one produces.

    The three yield sources are separate and all three are needed to get
    Farm-on-Corn right:
      * `yields`        - the improvement's own flat change. Farm has NONE.
      * `irrigated`     - added when the tile is irrigated. Farm's +1 food.
      * bonus structs   - per-resource. Corn's +2 food on a Farm.
    Dropping the third is the documented failure this item exists to fix.

    `bonus_makes_valid` is not merely a legality flag: in canHaveImprovement
    it is an early `return true` ABOVE the flatlands, irrigation and
    nature-yield gates, so a resource that validates an improvement bypasses
    all of them. That is why a Farm is legal on dry Corn, and on hill Corn
    despite bRequiresFlatlands.

    Two flags are deliberately NOT read. `bCarriesIrrigation` matters only
    for the irrigation CHAIN, which is out of scope (see the view's OMITS).
    `bGoody` would duplicate NOT_REAL_IMPROVEMENTS, and having both a flag
    and a named list with only the list live is worse than either alone -
    the flag reads as the thing keeping huts out of the view, and is not.
    """
    improvements = {}
    for key, block, line in iter_blocks(text, "ImprovementInfo"):
        bonus_structs = {}
        structs = re.search(r"<BonusTypeStructs>(.*?)</BonusTypeStructs>",
                            block, re.S)
        if structs:
            for struct in re.finditer(r"<BonusTypeStruct>(.*?)</BonusTypeStruct>",
                                      structs.group(1), re.S):
                body = struct.group(1)
                bonus_type = _tag(body, "BonusType")
                if not bonus_type:
                    continue
                bonus_structs[bonus_type] = {
                    "bonus": bonus_type,
                    "makes_valid": _int_tag(body, "bBonusMakesValid") == 1,
                    "trade": _int_tag(body, "bBonusTrade") == 1,
                    "yields": _yield_triplet(body, "YieldChanges"),
                }

        terrain_valid = {}
        for struct in re.finditer(r"<TerrainMakesValid>(.*?)</TerrainMakesValid>",
                                  block, re.S):
            body = struct.group(1)
            name = _tag(body, "TerrainType")
            if name:
                terrain_valid[name] = _int_tag(body, "bMakesValid") == 1

        feature_valid = {}
        for struct in re.finditer(r"<FeatureMakesValid>(.*?)</FeatureMakesValid>",
                                  block, re.S):
            body = struct.group(1)
            name = _tag(body, "FeatureType")
            if name:
                feature_valid[name] = _int_tag(body, "bMakesValid") == 1

        tech_yields = []
        for struct in re.finditer(r"<TechYieldChange>(.*?)</TechYieldChange>",
                                  block, re.S):
            body = struct.group(1)
            tech = _tag(body, "PrereqTech")
            if tech:
                tech_yields.append({
                    "tech": tech,
                    "yields": _yield_triplet(body, "TechYields"),
                })

        # The improvement's OWN fields only - see _without_nested. Both
        # BonusTypeStructs and TechYieldChanges contain same-named yield
        # containers, and both are parsed separately above.
        own = _without_nested(block, "BonusTypeStructs", "TechYieldChanges")

        improvements[key] = {
            "type": key,
            "line": line,
            # ALWAYS None in the stock files, and kept only so a mod that
            # sets it is not silently ignored. The tech that unlocks an
            # improvement lives on its BUILD, not here - see build_for.
            #
            # Read from `own` rather than `block` because each
            # <TechYieldChange> carries its own <PrereqTech>: a raw scan
            # returns TECH_BIOLOGY for a Farm (its late +1 food) and reads
            # exactly like a real answer, which is worse than the None it
            # actually is.
            "tech": _tag(own, "PrereqTech"),
            "yields": _yield_triplet(own, "YieldChanges"),
            "irrigated": _yield_triplet(own, "IrrigatedYieldChange"),
            "prereq_nature": _yield_triplet(own, "PrereqNatureYields"),
            "tech_yields": tech_yields,
            "bonus_structs": bonus_structs,
            "terrain_valid": terrain_valid,
            "feature_valid": feature_valid,
            "requires_flatlands": _int_tag(block, "bRequiresFlatlands") == 1,
            "hills_makes_valid": _int_tag(block, "bHillsMakesValid") == 1,
            "fresh_water_makes_valid": _int_tag(block, "bFreshWaterMakesValid") == 1,
            "no_fresh_water": _int_tag(block, "bNoFreshWater") == 1,
            "river_side_makes_valid": _int_tag(block, "bRiverSideMakesValid") == 1,
            "requires_river_side": _int_tag(block, "bRequiresRiverSide") == 1,
            "requires_irrigation": _int_tag(block, "bRequiresIrrigation") == 1,
            "requires_feature": _int_tag(block, "bRequiresFeature") == 1,
            "water": _int_tag(block, "bWater") == 1,
            # canBuild gates on both: a tile already carrying this (or
            # something that upgrades into it) refuses, and foreign culture
            # refuses everything except bOutsideBorders. See build_blocker.
            "upgrade": _tag(own, "ImprovementUpgrade"),
            "outside_borders": _int_tag(own, "bOutsideBorders") == 1,
        }
    return improvements


def parse_percent_table(text, tag, field="iResearchPercent"):
    table = {}
    for key, block, _line in iter_blocks(text, tag):
        table[key] = _int_tag(block, field, 100)
    return table


def parse_handicap(text):
    handicaps = {}
    for key, block, line in iter_blocks(text, "HandicapInfo"):
        entry = {"type": key, "line": line}
        for name, _desc in ANIMAL_FIELDS + BARBARIAN_FIELDS:
            entry[name] = _int_tag(block, name)
        entry["iResearchPercent"] = _int_tag(block, "iResearchPercent", 100)
        # The goody-hut draw table: 20 <GoodyType> entries WITH REPEATS, and
        # the repeats are the weighting - there is no probability field
        # anywhere. Order is meaningless (the engine draws a uniform index),
        # but multiplicity is everything, so this is a list and never a set.
        entry["goodies"] = _list_tag(block, "Goodies", "GoodyType")
        handicaps[key] = entry
    return handicaps


def parse_goodies(text):
    """What each goody outcome does, from the vanilla-only CIV4GoodyInfo.xml.

    Only the fields that decide an OUTCOME or gate ELIGIBILITY are kept; the
    art/sound fields are noise here. `bad` is the field the whole subcommand
    turns on: it is what `bNoBadGoodies` units are immune to, and it is set on
    exactly the two GOODY_BARBARIANS_* entries.
    """
    goodies = {}
    # `line` is deliberately not kept, unlike every other parser here: nothing
    # cites this file, because the view prints everything in it that bears on a
    # decision and a citation is for what was NOT printed (see README).
    for key, block, _line in iter_blocks(text, "GoodyInfo"):
        unit_class = _tag(block, "UnitClass")
        barb_class = _tag(block, "BarbarianClass")
        goodies[key] = {
            "type": key,
            "gold": _int_tag(block, "iGold"),
            # Two independent rolls, each 0..N-1, both ADDED to iGold. So the
            # range is iGold .. iGold + (r1-1) + (r2-1), not iGold + r1 + r2.
            "gold_rand1": _int_tag(block, "iGoldRand1"),
            "gold_rand2": _int_tag(block, "iGoldRand2"),
            "map_range": _int_tag(block, "iMapRange"),
            "map_prob": _int_tag(block, "iMapProb"),
            "experience": _int_tag(block, "iExperience"),
            "healing": _int_tag(block, "iHealing"),
            "damage_prereq": _int_tag(block, "iDamagePrereq"),
            "tech": _int_tag(block, "bTech") == 1,
            "bad": _int_tag(block, "bBad") == 1,
            "unit_class": unit_class if unit_class != "NONE" else None,
            "barb_class": barb_class if barb_class != "NONE" else None,
            # The guaranteed floor. These units ALWAYS appear once this outcome
            # is drawn - the engine makes a second pass that ignores its
            # per-plot probability roll until the floor is met.
            #
            # That roll (iBarbarianUnitProb, 20/40) is deliberately not parsed:
            # it governs how many EXTRA barbarians appear, but printed beside a
            # hostile outcome it reads as the chance of being attacked, which
            # is exactly backwards. A test asserts it stays off the row.
            "min_barbarians": _int_tag(block, "iMinBarbarians"),
        }
    return goodies


# ---------------------------------------------------------------------------
# Tech cost
# ---------------------------------------------------------------------------


def research_cost(base, speed_pct, world_pct, handicap_pct):
    """The engine's real tech cost for this game's setup.

    VERIFIED against four techs in samples/baseline-early-game (Emperor,
    Standard, Normal), exact on all four:

        TECH_AGRICULTURE       60 -> 93     TECH_THE_WHEEL          60 -> 93
        TECH_ANIMAL_HUSBANDRY 100 -> 156    TECH_WRITING           120 -> 187

    Truncation is applied at EACH step, not once at the end. The two orderings
    agree on most values and diverge on some, which is how a wrong version
    survives a small test - `test_cost_matches_every_sample_turn` checks every
    turn of every sample rather than these four.

    The met-civs-know-tech discount is deliberately absent: it applies to the
    research RATE, not the cost, and is already inside `player.beakersPerTurn`.
    """
    cost = base * speed_pct // 100
    cost = cost * world_pct // 100
    cost = cost * handicap_pct // 100
    return cost


class Rules(object):
    """The XML, parsed, plus the cost multipliers for one game's setup."""

    def __init__(self, roots, game):
        self.roots = roots
        self.xml_root = roots[0]
        tech_text, self.tech_path, _ = read_xml(roots, TECH_FILE)
        unit_text, self.unit_path, _ = read_xml(roots, UNIT_FILE)
        handicap_text, self.handicap_path, _ = read_xml(roots, HANDICAP_FILE)
        speed_text, _, _ = read_xml(roots, GAMESPEED_FILE)
        world_text, _, _ = read_xml(roots, WORLD_FILE)

        self.techs = parse_techs(tech_text)
        self.units = parse_units(unit_text)
        self.handicaps = parse_handicap(handicap_text)
        self._fill_inherited_unit_costs()

        # Everything a tech reveals. Each source is optional so a partial
        # install degrades to a stated omission rather than a crash; `sources`
        # records which ones actually loaded and from which tree, and the
        # UNLOCKS block prints that so a gap is never silent.
        self.sources = {}

        # Positional array order, resolved from the files that define it -
        # loaded first because parse_buildings needs both.
        self.commerce_order = self._load(
            COMMERCE_FILE, None,
            lambda text: parse_ordered_types(text, "CommerceInfo"), default=[])
        self.yield_order = self._load(
            YIELD_FILE, None,
            lambda text: parse_ordered_types(text, "YieldInfo"), default=[])

        self.buildings = self._load(
            BUILDING_FILE, "buildings",
            lambda text: parse_buildings(text, self.commerce_order,
                                         self.yield_order))
        self.building_path = self.sources.get("buildings", (None, None))[0]
        self.promotions = self._load(PROMOTION_FILE, "promotions", parse_promotions)
        self.promotion_path = self.sources.get("promotions", (None, None))[0]
        self.strategy = self._load(STRATEGY_FILE, "strategy", parse_strategy_text)
        self.building_classes = self._load(
            BUILDING_CLASS_FILE, None, parse_building_classes)
        self.builds = self._load(BUILD_FILE, "builds", parse_builds)
        self.bonuses = self._load(BONUS_FILE, "bonuses", parse_bonuses)
        self.civics = self._load(
            CIVIC_FILE, "civics",
            lambda text: parse_simple(text, "CivicInfo", "TechPrereq",
                                      ("CivicOptionType",)))
        self.religions = self._load(
            RELIGION_FILE, "religions",
            lambda text: parse_simple(text, "ReligionInfo", "TechPrereq"))
        self.projects = self._load(
            PROJECT_FILE, "projects",
            lambda text: parse_simple(text, "ProjectInfo", "TechPrereq"))
        self.improvements = self._load(
            IMPROVEMENT_FILE, "improvements", parse_improvements)
        self.terrains = self._load(TERRAIN_FILE, "terrains", parse_terrains)
        self.features = self._load(FEATURE_FILE, "features", parse_features)
        self.yield_info = self._load(YIELD_FILE, None, parse_yield_info)
        self.traits = self._load(TRAIT_FILE, "traits", parse_traits)
        self.leaders = self._load(LEADER_FILE, "leaders", parse_leaders)
        self.civilizations = self._load(
            CIVILIZATION_FILE, "civilizations", parse_civilizations)
        self.goodies = self._load(GOODY_FILE, "goodies", parse_goodies)
        self.goody_path = self.sources.get("goodies", (None, None))[0]

        # A building does not name its own class, so the wonder lookup joins
        # backwards through <DefaultBuilding>.
        self.class_of_building = dict(
            (entry["default"], key)
            for key, entry in self.building_classes.items()
            if entry["default"]
        )

        speeds = parse_percent_table(speed_text, "GameSpeedInfo")
        worlds = parse_percent_table(world_text, "WorldInfo")
        trains = parse_percent_table(speed_text, "GameSpeedInfo", "iTrainPercent")

        self.train_pct = trains.get(game.get("gameSpeed"), 100)
        self.speed_pct = speeds.get(game.get("gameSpeed"), 100)
        self.world_pct = worlds.get(game.get("worldSize"), 100)
        handicap = self.handicaps.get(game.get("handicap"), {})
        self.handicap_pct = handicap.get("iResearchPercent", 100)
        self.setup = game

    def _fill_inherited_unit_costs(self):
        """Recover a cost that BTS blanked and vanilla still holds.

        BTS sets UNIT_SETTLER's <iCost> to 0 while vanilla carries the real
        100, and the game charges 100 - `cities[].productionNeeded` reads 100
        on every turn Lisbon builds one, which is the engine's own number and
        settles it. Taken literally, the 0 made the Settler look like an
        animal or a great-person build and the `city` view dropped it from the
        list entirely: the single most important early-game build, missing.

        Deliberately narrow. BTS genuinely re-prices units (a Chariot is 25 in
        vanilla and 30 in BTS), so BTS-first stays right and only a ZERO falls
        through to vanilla - measured, that is exactly one unit in the file.
        A cost of 0 in both trees is left alone: that is a real "not trained by
        a city" marker, which is what filters animals out.
        """
        zeroed = [key for key, unit in self.units.items()
                  if not unit.get("cost")]
        if not zeroed:
            return
        text, _path, tree = read_xml(self.roots, UNIT_FILE, required=False)
        if text is None or tree != "BTS":
            return
        vanilla_path = os.path.join(self.roots[1], UNIT_FILE)
        if not os.path.isfile(vanilla_path):
            return
        with open(vanilla_path, "rb") as handle:
            fallback = parse_units(handle.read().decode(XML_ENCODING))
        for key in zeroed:
            inherited = (fallback.get(key) or {}).get("cost") or 0
            if inherited > 0:
                self.units[key]["cost"] = inherited
                self.units[key]["cost_from_vanilla"] = True

    def _load(self, relative, name, parse, default=None):
        """Parse an optional XML source, recording which tree answered.

        Every optional source is loaded through here so "absent file" has one
        behaviour rather than four hand-written variants: an empty result plus
        no entry in `sources`, which is what lets the OMITS block distinguish
        "not loaded" from "genuinely empty". `name` is None for sources nothing
        reports on (the positional-array orders).
        """
        text, path, tree = read_xml(self.roots, relative, required=False)
        if text is None:
            return {} if default is None else default
        if name:
            self.sources[name] = (path, tree)
        return parse(text)

    def unlocked_by(self, tech_type):
        """Everything this tech makes available, by category.

        The reverse index is the whole point: XML stores one hop forward from
        each entry, so "what does this tech give me" means scanning every file.
        Two agent trials filled this in from memory when the tool printed only
        units - TECH_BRONZE_WORKING rendered as four units (three of them other
        civs' uniques) and nothing about copper, chopping or Slavery.
        """
        found = {}

        def collect(name, table):
            hits = sorted(k for k, v in table.items() if v.get("tech") == tech_type)
            if hits:
                found[name] = hits

        collect("units", dict(
            (k, {"tech": v["prereq_tech"]}) for k, v in self.units.items()))
        collect("buildings", self.buildings)
        collect("civics", self.civics)
        collect("projects", self.projects)
        collect("improvements", self.improvements)

        # Worker actions: top-level prereq, plus the nested per-feature ones.
        actions = sorted(k for k, v in self.builds.items()
                         if v.get("tech") == tech_type)
        if actions:
            found["worker actions"] = actions
        # Collapsed per feature, not per build. Every improvement that can sit
        # on forest carries its own identical FeatureStruct, so listing them
        # raw prints twelve near-identical lines that all say one thing:
        # "this tech lets you chop forest". The build count is kept because
        # "via 12 worker builds" is the honest scope of the ability.
        by_feature = {}
        for key, build in sorted(self.builds.items()):
            for feature in build["features"]:
                if feature["tech"] != tech_type:
                    continue
                verb = "remove" if feature["remove"] else "work"
                slot = by_feature.setdefault(
                    (verb, feature["feature"], feature["production"]), [])
                slot.append(key)
        feature_work = []
        for (verb, feature, production), builds in sorted(by_feature.items()):
            note = "%s %s" % (verb, feature)
            if production:
                note += " for +%d hammers" % production
            note += " (%d worker build%s)" % (
                len(builds), "" if len(builds) == 1 else "s")
            feature_work.append(note)
        if feature_work:
            found["feature work"] = feature_work

        revealed = sorted(k for k, v in self.bonuses.items()
                          if v.get("reveal") == tech_type)
        if revealed:
            found["resources revealed"] = revealed
        tradeable = sorted(k for k, v in self.bonuses.items()
                           if v.get("city_trade") == tech_type)
        if tradeable:
            found["resources usable"] = tradeable

        return found

    def cost(self, tech_type):
        entry = self.techs.get(tech_type)
        if entry is None:
            return 0
        return research_cost(
            entry["cost"], self.speed_pct, self.world_pct, self.handicap_pct
        )


# ---------------------------------------------------------------------------
# Closure walk
# ---------------------------------------------------------------------------


def closure(rules, tech_type, known=(), _seen=None):
    """Every tech required by `tech_type` that is not already known.

    Walks the full DAG. Depth was the obvious worry and turned out to be the
    wrong one: the whole tree is 92 techs and the largest full closure measured
    is 14, with early-game targets at 1-7. So there is no cutoff to defend, and
    a TRUNCATED closure is precisely the confident-but-incomplete answer this
    tool exists to prevent.

    A known tech prunes the branch beneath it - if you have Masonry you do not
    need Masonry's prerequisites either.

    A SATISFIED or-list contributes nothing. Masonry needs Mining OR Mysticism;
    with Mining known the choice is already made, so Mysticism is not required
    and must not be counted. Unioning every or-branch regardless overstated the
    cost of anything routed through a satisfied list - on the real sample it
    reported TECH_MYSTICISM as a prerequisite of the Pyramids when the player
    had held Mining since turn 0.
    """
    if _seen is None:
        _seen = set()
    entry = rules.techs.get(tech_type)
    if entry is None or tech_type in known:
        return _seen

    branches = list(entry["and"])
    if entry["or"] and not or_satisfied(entry["or"], known):
        branches.extend(entry["or"])

    for parent in branches:
        # The `_seen` check belongs HERE, on the child, not at the top of the
        # call on `tech_type`. Testing it against the node just added made every
        # recursive call return immediately, so the walk stopped one level down
        # and TECH_MONARCHY reported 2 prerequisites instead of 7 - while still
        # printing the words "full walk".
        if parent not in known and parent not in _seen:
            _seen.add(parent)
            closure(rules, parent, known, _seen)
    return _seen


def or_satisfied(or_list, known):
    """True when any branch of an or-list is already held.

    The distinction that makes a satisfied or-list different from an unsatisfied
    one: there is no longer a choice to present, only a fact to state.
    """
    return any(branch in known for branch in or_list)


def render_tree(rules, tech_type, known, show_known, max_depth, lines=None,
                depth=0, path=(), hidden=None, state=None):
    """Indented prerequisite tree. Returns (lines, hidden_count).

    Repeated nodes are printed at each place they appear rather than collapsed
    to a back-reference: several routes share Mysticism, and a collapsed tree is
    harder to read than the JSON it is meant to save you reading. The distinct
    count in the summary carries the fact instead.
    """
    if lines is None:
        lines = []
    if hidden is None:
        hidden = [0]

    entry = rules.techs.get(tech_type)
    if entry is None:
        lines.append("%s%s   [NOT IN XML]" % ("  " * depth, tech_type))
        return lines, hidden

    # A cycle guard that has never fired on real BTS data - Monotheism needs
    # Masonry and Polytheism, not Monarchy, so the tree is a genuine DAG. Kept
    # because a recursive walk without one turns a data change into a hang.
    if tech_type in path:
        lines.append("%s%s   [CYCLE - stopped]" % ("  " * depth, tech_type))
        return lines, hidden

    # A tech in progress is pruned from COSTS but never hidden from the tree:
    # it is the one line whose status the reader most needs to see.
    current = researching(state) if state else None
    in_progress = tech_type == current
    have = tech_type in known and not in_progress
    if have and not show_known:
        hidden[0] += 1
        return lines, hidden

    if in_progress:
        mark = "  " + _tech_status(tech_type, known, state)
    else:
        mark = "  [have]" if have else ""
    lines.append(
        "%s%-26s %5d%s" % ("  " * depth, tech_type, rules.cost(tech_type), mark)
    )

    if max_depth is not None and depth >= max_depth:
        if entry["and"] or entry["or"]:
            lines.append("%s... (--depth %d)" % ("  " * (depth + 1), max_depth))
        return lines, hidden

    for parent in entry["and"]:
        render_tree(rules, parent, known, show_known, max_depth, lines,
                    depth + 1, path + (tech_type,), hidden, state)

    if entry["or"]:
        # A satisfied or-list is a fact, not a choice. Once any branch is held
        # the alternatives are irrelevant, and printing them under ANY ONE OF
        # invites reading an unneeded tech as required - on the real sample the
        # Pyramids showed TECH_MYSTICISM as a live branch, priced and routed,
        # while the player had held the other branch (Mining) since turn 0.
        met = [b for b in entry["or"] if b in known]
        if met:
            if show_known:
                for parent in entry["or"]:
                    render_tree(rules, parent, known, show_known, max_depth,
                                lines, depth + 1, path + (tech_type,), hidden,
                                state)
            else:
                # A branch met only by the tech in progress is not held yet, and
                # saying "met" flatly would claim more than is true - visible on
                # the Aqueduct at t40, whose prereq is Writing with four turns
                # left. `known` is `effective_known`, so it counts for COSTING;
                # the wording has to keep the distinction the status carries.
                described = []
                for branch in met:
                    status = _tech_status(branch, known, state)
                    described.append(branch if status == "[have]"
                                     else "%s %s" % (branch, status))
                pending = any(b == researching(state) for b in met)
                lines.append("%s(prerequisite %s: %s)"
                             % ("  " * (depth + 1),
                                "arriving" if pending else "met",
                                ", ".join(described)))
            return lines, hidden

        # Children are rendered into a scratch list first so the ANY ONE OF
        # header is only emitted if something survives pruning. Emitting it up
        # front left a dangling header with nothing beneath it.
        multi = len(entry["or"]) > 1
        child_depth = depth + 2 if multi else depth + 1
        children = []
        for parent in entry["or"]:
            render_tree(rules, parent, known, show_known, max_depth, children,
                        child_depth, path + (tech_type,), hidden, state)
        if children:
            if multi:
                lines.append("%sANY ONE OF:" % ("  " * (depth + 1)))
            lines.extend(children)

    return lines, hidden


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def near_matches(needle, candidates, limit=5):
    """Type keys that look like what was asked for.

    Every unique unit is civ-prefixed and inconsistently so - UNIT_ROME_
    PRAETORIAN, UNIT_MAYA_HOLKAN, UNIT_NATIVE_AMERICA_DOG_SOLDIER - so an agent
    reasoning from the DISPLAY name guesses UNIT_PRAETORIAN and misses. A trial
    did exactly that and fell back to grepping the XML, which is the behaviour
    this tool exists to replace. The candidates are already parsed and in
    memory at the point of failure, so suggesting them costs nothing.
    """
    needle = needle.upper()
    stem = needle.split("_", 1)[-1] if "_" in needle else needle
    hits = [key for key in candidates
            if needle in key or (len(stem) > 3 and stem in key)]
    return sorted(hits)[:limit]


def _not_found(kind, asked, candidates, path, example, annotate=None):
    suggestions = near_matches(asked, candidates)
    message = "%s not found in %s" % (asked, path)
    if suggestions:
        lines = []
        for key in suggestions:
            note = annotate(candidates[key]) if annotate else ""
            lines.append("  %-36s %s" % (key, note) if note else "  %s" % key)
        message += "\nDid you mean:\n" + "\n".join(lines)
    else:
        message += "\nTypes look like %s. %d %s entries are loaded." % (
            example, len(candidates), kind)
    return RulesError(message)


def turns_estimate(cost, rate):
    """Whole turns to accumulate `cost` beakers at `rate` per turn.

    Three of six agent trials divided cost by beakersPerTurn by hand, one doing
    it three times in a single session. The tool already requires the state
    file and therefore holds both numbers; declining to divide them did not
    prevent the arithmetic, it just moved it somewhere untested.

    It is an extrapolation at the CURRENT rate, not a schedule - the rate moves
    as cities grow and the science slider changes - and every caller prints
    that caveat beside the figure.
    """
    if not rate or rate <= 0:
        return None
    return int(math.ceil(float(cost) / float(rate)))


def _rate_of(state):
    return (state.get("player") or {}).get("beakersPerTurn") or 0


def researching(state):
    """The tech currently being researched, or None.

    Distinct from knownTechs and NOT foldable into it: a tech in progress is
    neither had nor un-had. Treating it as simply missing is what made a
    BUILDING_LIBRARY lookup at t40 report TECH_WRITING as [NEED] and price a
    638-beaker route, when Writing was 138/187 with four turns left.
    """
    if not state:
        return None
    return ((state.get("player") or {}).get("research") or {}).get("current")


def effective_known(state):
    """Techs to treat as acquired when costing what is still ahead of you.

    Includes the tech in progress: you will have it before anything downstream
    is reachable, so charging for it again overstates every route through it.
    Kept separate from `knownTechs` so the tree can still LABEL it as in
    progress rather than silently claiming you have it.
    """
    known = set((state.get("player") or {}).get("knownTechs") or [])
    current = researching(state)
    if current:
        known.add(current)
    return known


def _tech_status(tech_type, known, state):
    """`[have]`, `[NEED]`, or the in-progress case with its turns left.

    The in-progress check comes FIRST because `known` here is usually
    `effective_known`, which deliberately contains the tech being researched -
    testing membership first would report it as owned and lose the distinction
    this function exists to draw.
    """
    if tech_type == researching(state):
        left = (((state or {}).get("player") or {}).get("research")
                or {}).get("turnsLeft")
        if left:
            return "[RESEARCHING - %d turns left]" % left
        return "[RESEARCHING]"
    if tech_type in known:
        return "[have]"
    return "[NEED]"


def _turns_line(cost, state, indent="  "):
    """`~12 turns at 16 bpt (+4 to finish TECH_WRITING first)`, or nothing."""
    rate = _rate_of(state)
    turns = turns_estimate(cost, rate)
    if turns is None:
        return None
    research = (state.get("player") or {}).get("research") or {}
    pending = research.get("turnsLeft")
    current = research.get("current")
    suffix = ""
    if pending and current:
        suffix = " (+%d to finish %s first)" % (pending, current)
    return "%s~%d turns at %d bpt%s" % (indent, turns, rate, suffix)


STATE_SCHEMA_VERSION = 2


def load_state(path):
    if not os.path.isfile(path):
        raise RulesError("state file not found: %s" % path)
    try:
        with open(path, "rb") as handle:
            state = json.loads(handle.read().decode("utf-8"))
    except ValueError as exc:
        raise RulesError("state file is not valid JSON: %s" % exc)
    # This tool DOES read coordinates - `goody --at` and `improvement --at`
    # both take one - so the y-axis inversion in schemaVersion 2 bites here
    # exactly as it does in render_map: a v1 file would silently answer
    # about the tile mirrored north-south. It would matter even if nothing
    # here read a coordinate, since a stale file should fail the same way at
    # every harness entry point rather than succeed against the wrong
    # schema. Kept in sync with
    # render_map.py's and run_history.py's copies rather than imported, since
    # these are deliberately standalone scripts. See CLAUDE.md and
    # AdvisorStateWriter._invertY for what changed 1 -> 2.
    version = (state.get("meta") or {}).get("schemaVersion")
    if version != STATE_SCHEMA_VERSION:
        raise RulesError(
            "%s: schemaVersion %r, expected %d - re-export it, or migrate it"
            " the way samples/baseline-early-game/ was migrated."
            % (path, version, STATE_SCHEMA_VERSION)
        )
    return state


def state_summary(state):
    game = state.get("game", {})
    player = state.get("player", {})
    return "%s, turn %s, %s / %s / %s" % (
        player.get("leader", "?"),
        game.get("gameTurn", "?"),
        game.get("handicap", "?"),
        game.get("worldSize", "?"),
        game.get("gameSpeed", "?"),
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _relative(path, xml_root):
    return os.path.relpath(path, xml_root)


def _resource_status(rules, bonus_type, state, known):
    """Where this resource stands for the player: hidden, seen, or connected.

    Three states, and the tool used to answer only the first two. The reveal
    case is what makes a prerequisite uncheckable - copper's TechReveal is
    TECH_BRONZE_WORKING itself, so "an Axeman needs copper" cannot be tested
    before researching it, and the honest answer is "N turns to find out
    WHETHER Axemen exist for you".

    CONNECTED is the case that was missing, and it is the one that decides
    whether you can build the unit today. `player.bonuses.counts` is the
    engine's own answer - the schema calls it "what the trade network actually
    delivers" - so the tool held it all along while printing "Not checked
    here". Three of four agent trials hand-joined map.tiles against
    player.bonuses to recover it; one noted the tool did the negative case well
    and the positive case not at all.
    """
    entry = rules.bonuses.get(bonus_type)
    if entry is None:
        return ["%s: not in CIV4BonusInfos.xml (not loaded?)" % bonus_type]

    player = state.get("player") or {}
    bonuses = player.get("bonuses") or {}
    connected = (bonuses.get("counts") or {}).get(bonus_type)
    reveal = entry.get("reveal")
    tiles = (state.get("map") or {}).get("tiles") or []
    visible = [t for t in tiles if t.get("bonus") == bonus_type]

    if connected:
        lines = ["%s: CONNECTED - %d in your trade network"
                 % (bonus_type, connected)]
        owned = [t for t in visible if t.get("improvement") and t.get("owner") is not None]
        if owned:
            where = ", ".join("(%d,%d)" % (t["x"], t["y"]) for t in owned[:3])
            lines.append("  improved and worked at %s" % where)
        lines.append("  this prerequisite is MET - you can build it today.")
        return lines

    if reveal and reveal != "NONE" and reveal not in known:
        return ["%s: NOT YET REVEALED - needs %s" % (bonus_type, reveal),
                "  until then it is invisible on your map, so 0 visible",
                "  is not evidence you have none - or that you have some."]

    if not visible:
        return ["%s: revealed by your techs, but none on your map yet"
                % bonus_type,
                "  keep exploring - fog hides the rest."]

    # Seen but not connected: the gap is borders, an improvement, or a road.
    lines = ["%s: %d visible tile%s, but NOT connected"
             % (bonus_type, len(visible), "" if len(visible) == 1 else "s")]
    for tile in visible[:3]:
        gaps = []
        if tile.get("owner") is None:
            gaps.append("outside your borders")
        if not tile.get("improvement"):
            gaps.append("unimproved")
        if not tile.get("route"):
            gaps.append("no road")
        lines.append("  (%d,%d): %s" % (tile["x"], tile["y"],
                                        ", ".join(gaps) if gaps else "check trade route"))
    if len(visible) > 3:
        lines.append("  ... and %d more" % (len(visible) - 3))
    return lines


# ---------------------------------------------------------------------------
# Tile yields and improvement legality
#
# Both functions below are transcriptions of BTS source, in source order,
# rather than reconstructions from observed behaviour. The install ships
# CvGameCoreDLL.dll as a compiled binary and no source; the two mods that
# bundle their own SDK copy (RFC, The Road to War) hold `canHaveImprovement`
# BYTE-IDENTICALLY, which is what licenses treating it as unmodified base
# code. `calculateNatureYield` differs between them in one place - RFC adds
# an Inca branch on the isImpassable early-out - so the impassable case
# follows the common remainder rather than either copy. See REFERENCES.md.
# ---------------------------------------------------------------------------

# Entries in CIV4ImprovementInfos.xml that are not improvements in any sense
# a player would recognise: engine-internal markers for a worked plot, the
# rubble left by a razed city, and a goody hut. A MODELLING fact, not a
# scope choice - a tile carrying one of these is bare ground as far as
# yields go, and running a hut through improvement_yield "clears" the forest
# under it and loses its hammer.
NOT_REAL_IMPROVEMENTS = frozenset((
    "IMPROVEMENT_LAND_WORKED",
    "IMPROVEMENT_WATER_WORKED",
    "IMPROVEMENT_CITY_RUINS",
    "IMPROVEMENT_GOODY_HUT",
))

# Real improvements the tile view does not offer, because they are outside
# turns 0-50. Purely a SCOPE choice and the one likely future edit here:
# widening the window means deleting from this list, which must stay safe to
# do. Keeping it separate from NOT_REAL_IMPROVEMENTS is what makes it safe -
# the two sets happen to be disjoint today, and fusing them would mean a
# scope edit in the candidate list silently changed how an existing
# improvement on a tile is valued. Watermill would in any case need cardinal
# river geometry the export does not carry.
OUT_OF_SCOPE_IMPROVEMENTS = frozenset((
    "IMPROVEMENT_LUMBERMILL",
    "IMPROVEMENT_WINDMILL",
    "IMPROVEMENT_WATERMILL",
    "IMPROVEMENT_FORT",
    "IMPROVEMENT_WELL",
    "IMPROVEMENT_OFFSHORE_PLATFORM",
    "IMPROVEMENT_FOREST_PRESERVE",
))


def workable_improvements(rules):
    """Improvements the tile view will consider, in a stable order.

    Only those a worker action actually builds: an ImprovementInfo with no
    BuildInfo pointing at it cannot be ordered, whatever its flags say.

    Excludes rather than includes, so a mod's new improvement shows up by
    default: a tool that silently omits something buildable is the failure
    mode this whole subcommand exists to fix, and one extra row is a far
    cheaper mistake than one missing.
    """
    buildable = set(build.get("improvement")
                    for build in rules.builds.values()
                    if build.get("improvement"))
    return tuple(sorted(key for key in rules.improvements
                        if key in buildable
                        and key not in NOT_REAL_IMPROVEMENTS
                        and key not in OUT_OF_SCOPE_IMPROVEMENTS))

# How each yield column is NAMED to a reader. Not an XML order - the game
# calls the middle column "production" and every player calls it hammers -
# so this has no source to be read from. It is positionally locked to
# `Rules.yield_order`, which IS read from CIV4YieldInfos.xml; index into
# both with the same integer and never hardcode the type keys beside it
# (an earlier version did, duplicating a list the Rules object already
# holds - see parse_ordered_types on why guessing a positional order is a
# silent mistranslation rather than an error).
YIELD_LABELS = ("food", "hammers", "commerce")


def _triplet(values=None):
    """A mutable [food, production, commerce], defaulting to zeroes."""
    if not values:
        return [0, 0, 0]
    return [values[0], values[1], values[2]]


def _add(into, values):
    if values:
        for index in range(3):
            into[index] += values[index]
    return into


def _yield_change_for(rules, yield_key, field):
    """One column of the per-yield table: hills, lake or the city floor."""
    entry = rules.yield_info.get(yield_key)
    return entry.get(field, 0) if entry else 0


def _city_floor(rules, tile, state, values):
    """Raise a city-centre tile to iMinCity, as calculateYield's `bCity` clause.

    The city centre is worked for free and never yields less than 2/1/1
    whatever sits under it, which is why a city on plains reads [2,1,1] and
    not the [1,1,0] the terrain alone gives. Found by sweeping the sample
    against the engine rather than from the XML: 69 tiles disagreed and
    every one of them was a city centre. That sweep is now a committed test
    (test_tile_yields_match_the_engine_on_every_sample_tile), so removing
    this floor fails a check rather than merely contradicting a comment.

    Only the floor is modelled. iCityChange and the population terms are all
    zero in the stock files, so they would be untestable code.
    """
    if not _is_city_tile(tile, state):
        return values
    floored = list(values)
    for index, yield_key in enumerate(rules.yield_order):
        floored[index] = max(floored[index],
                             _yield_change_for(rules, yield_key, "min_city"))
    return floored


def _is_city_tile(tile, state):
    """Is one of our cities standing on this tile?

    Only our own: `cities` is the section carrying coordinates. A rival city
    sits in `foreignCities`, which carries x/y too, so both are checked -
    the floor is a property of the tile, not of who owns it.
    """
    x, y = tile.get("x"), tile.get("y")
    for section in ("cities", "foreignCities"):
        for city in state.get(section) or []:
            if city.get("x") == x and city.get("y") == y:
                return True
    return False


def nature_yield(rules, tile, state=None):
    """The tile's yield BEFORE any improvement, as CvPlot::calculateNatureYield.

    Delegates to improvement_yield with no improvement rather than repeating
    the accumulation. That is not tidiness: the two used to add up the same
    terrain/hills/bonus/feature/river terms independently, and a peak fix
    applied to this one left the view - which goes through the other - still
    printing 2 food for a plot the engine reports as [0,0,0]. One
    accumulator means one place for such a clause to be missing from.

    Kept as a named function because the question it answers is distinct and
    has one production caller: `PrereqNatureYields` is tested against the
    BARE tile, which is what stops Farms on desert.

    The C++ signature also carries a bIgnoreFeature flag. It is not
    reproduced here - nothing in scope passes it, and an unused parameter
    that mirrors a source signature reads as supported when it is untested.
    """
    return nature_terms(rules, tile, state)[0]


def _potential_city_work(tile):
    """Could any city ever work this tile? (`CvPlot::updatePotentialCityWork`)

    False only for deep ocean: a plot with no land anywhere in its 21-tile
    city cross yields [0,0,0] whatever its terrain says, because no city can
    ever be founded in range to work it. `calculateYield` returns 0 outright
    for such a plot, which is why the map shows open sea as barren.

    **Read from the export, not re-derived, because it is NOT derivable.**
    Two attempts failed in opposite directions and the reason is fundamental:
    the engine tests every plot in the cross, including ones the player has
    never revealed, while `map.tiles` holds only revealed tiles. Measured on
    the baseline sample, (82,37) with 11 unrevealed / 10 water / 0 land
    yields [0,0,0] and (72,40) with 13 unrevealed / 8 water / 0 land yields
    [1,0,1] - identical in every fact the export carries. Treating unrevealed
    as water was wrong on 24 tiles, as land on 609.

    So the tile's own exported `yields` settles it, which is the engine's
    answer rather than a reconstruction of it. That costs nothing here: this
    function exists to explain a zero the export already states, and water
    tiles carry no improvement decision in scope beyond the two boat builds,
    which need a resource that deep ocean does not have.
    """
    if tile.get("plotType") != "PLOT_OCEAN":
        return True
    exported = tile.get("yields")
    if exported is not None and not any(exported):
        return False
    return True


def _impassable(tile):
    """Peaks and ice - nothing can be built on them.

    The engine asks CvPlot::isImpassable, which is terrain-or-feature
    impassability. Only these two matter in scope and both are checkable
    from the export.
    """
    if tile.get("plotType") == "PLOT_PEAK":
        return True
    return (tile.get("feature") or "") == "FEATURE_ICE"


def can_have_improvement(rules, tile, improvement_type, known):
    """Why this improvement cannot go on this tile, or None if it can.

    A transcription of CvPlot::canHaveImprovement in SOURCE ORDER, which is
    load-bearing rather than stylistic: the bonus check is an early
    `return true` sitting ABOVE the flatlands, irrigation and nature-yield
    gates. That single ordering fact is why a Farm is legal on dry Corn and
    on hill Corn, and reordering these clauses to read more naturally would
    silently produce the wrong answer on exactly the tiles worth asking about.

    Returns a reason string (the caller renders it) or None for "legal".
    The tech gate is checked by the caller, not here - the engine keeps it in
    canBuild rather than canHaveImprovement, and the two answer different
    questions: "could this ever sit here" versus "may I order it now".
    """
    improvement = rules.improvements.get(improvement_type)
    if improvement is None:
        raise RulesError("no such improvement: %s" % improvement_type)

    if _impassable(tile):
        return "impassable terrain"

    is_water = tile.get("plotType") == "PLOT_OCEAN"
    if improvement.get("water") != is_water:
        return "water improvement on land" if improvement.get("water") \
            else "land improvement on water"

    feature_key = tile.get("feature") or ""
    feature = rules.features.get(feature_key)
    if feature and feature.get("no_improvement"):
        return "%s allows no improvements" % _plain(feature_key)

    # THE EARLY RETURN. Everything below is bypassed when the tile's resource
    # validates the improvement, which is the Farm-on-dry-Corn case.
    bonus_key = tile.get("bonus") or ""
    if bonus_key:
        struct = improvement.get("bonus_structs", {}).get(bonus_key)
        if struct and struct.get("makes_valid"):
            return None

    if improvement.get("no_fresh_water") and tile.get("freshWater"):
        return "not on fresh water"
    if improvement.get("requires_flatlands") and tile.get("plotType") == "PLOT_HILLS":
        return "needs flatland, this is hills"
    if improvement.get("requires_feature") and not feature_key:
        return "needs a feature on the tile"

    valid = False
    if improvement.get("hills_makes_valid") and tile.get("plotType") == "PLOT_HILLS":
        valid = True
    if improvement.get("fresh_water_makes_valid") and tile.get("freshWater"):
        valid = True
    # bRiverSideMakesValid is a river-CROSSING test on cardinal neighbours;
    # the export carries `river` as a plain boolean by design, so this is the
    # looser "on a river" reading. It can only ever admit a tile the engine
    # would also admit for some other reason in scope, and the one improvement
    # that REQUIRES riverside (Watermill) is excluded - see OMITS.
    if improvement.get("river_side_makes_valid") and tile.get("river"):
        valid = True
    if improvement.get("terrain_valid", {}).get(tile.get("terrain") or ""):
        valid = True
    if feature_key and improvement.get("feature_valid", {}).get(feature_key):
        valid = True
    if not valid:
        # Deliberately does NOT blame the feature, even when one is present.
        # A feature never causes this branch: canHaveImprovement consults it
        # only through FeatureMakesValid, which can add validity and never
        # remove it. An earlier version reported "blocked by Forest" here and
        # was wrong twice over - the forest is not what invalidated the tile,
        # and a Mine on a forested hill is legal anyway (it needs the
        # chopping tech, which clearing_requirement reports separately).
        return "not valid on %s" % _plain(tile.get("terrain") or "this terrain")

    if improvement.get("requires_river_side") and not tile.get("river"):
        return "needs to be beside a river"

    nature = nature_yield(rules, tile)
    prereq = improvement.get("prereq_nature")
    if prereq:
        for index in range(3):
            if nature[index] < prereq[index]:
                return "needs %d %s from the bare tile, it makes %d" % (
                    prereq[index], YIELD_LABELS[index], nature[index])

    # No irrigation CHAINING: the engine's isIrrigationAvailable also follows
    # a carried chain from an adjacent irrigated tile, which is a midgame
    # concern and deliberately out of scope. Fresh water on the tile itself is
    # the early-game answer. Named in OMITS so the narrowing is visible.
    if improvement.get("requires_irrigation") and not tile.get("freshWater"):
        return "needs irrigation - no fresh water on this tile"

    return None


def build_blocker(rules, tile, improvement_type, state):
    """Why this cannot be ORDERED here, beyond the tile being able to hold it.

    canHaveImprovement answers "could this ever sit here"; CvPlot::canBuild
    wraps it with gates that have nothing to do with terrain, and two of them
    bite in ordinary play:

      * the tile already carries this improvement, or one that upgrades into
        the same thing (a Cottage where a Hamlet stands);
      * the tile is inside another team's borders, where you may build
        nothing at all bar the few bOutsideBorders improvements.

    Both were missing at first, and both produced a confident "you can build
    this" on a tile where the game will not let you - the worse failure of the
    two available, since the reader has no way to doubt it.
    """
    if improvement_type is None:
        return None
    existing = tile.get("improvement")
    if existing:
        if existing == improvement_type:
            return "already built here"
        if _upgrades_to_same(rules, existing, improvement_type):
            return "%s here already becomes this" % existing

    owner = tile.get("owner")
    player_id = (state.get("player") or {}).get("id")
    if owner is not None and player_id is not None and owner != player_id:
        improvement = rules.improvements.get(improvement_type) or {}
        if not improvement.get("outside_borders"):
            return "inside %s's borders" % _owner_label(state, owner)
    return None


def _upgrades_to_same(rules, existing, wanted):
    """Do these two improvements share a final upgrade target?

    The Cottage line is the case in scope: a Cottage cannot be built where a
    Hamlet stands, because both end at Town. Mirrors canBuild's
    finalImprovementUpgrade comparison.
    """
    final = _final_upgrade(rules, existing)
    return final is not None and final == _final_upgrade(rules, wanted)


def _final_upgrade(rules, improvement_type):
    """Follow <ImprovementUpgrade> to the end of the chain.

    Cottage -> Hamlet -> Village -> Town. `seen` guards a cycle the stock
    files do not contain but a mod could; the loop is iterative, so it takes
    no accumulator parameter.
    """
    seen = set()
    current = improvement_type
    while current and current not in seen:
        seen.add(current)
        nxt = (rules.improvements.get(current) or {}).get("upgrade")
        if not nxt:
            return current
        current = nxt
    return current


def connecting_improvement(rules, bonus_type, tile=None):
    """The improvement that puts this resource into your trade network.

    `bBonusTrade` on the improvement's own BonusTypeStruct, which is the
    engine's gate in `CvPlot::updatePlotGroupBonus`: a resource joins the
    plot group's bonus count only if the tile is a city OR carries an
    improvement whose `isImprovementBonusTrade` names it. So this is not a
    "which is best" judgement - it is the one improvement that connects the
    resource at all, and every other option on a resource tile leaves it
    unconnected.

    Exactly one per bonus across all 32 in the stock files, with one pair -
    Oil takes WELL on land and OFFSHORE_PLATFORM at sea - which `tile`
    disambiguates when supplied. `bBonusMakesValid` and `bBonusTrade` are
    identical on every struct in both trees (checked), so the connecting
    improvement is always also a legal one.
    """
    if not bonus_type:
        return None
    matches = []
    for key in sorted(rules.improvements):
        struct = (rules.improvements[key].get("bonus_structs")
                  or {}).get(bonus_type)
        if struct and struct.get("trade"):
            matches.append(key)
    if len(matches) > 1 and tile is not None:
        water = tile.get("plotType") == "PLOT_OCEAN"
        matches = [key for key in matches
                   if bool(rules.improvements[key].get("water")) == water]
    return matches[0] if len(matches) == 1 else None


def bonus_trade_tech(rules, bonus_type):
    """The tech that lets a CITY work this resource, if it is not yet known.

    A second, separate gate from the build's own tech and easy to miss
    because nothing else in the view mentions it: `updatePlotGroupBonus`
    checks `TechCityTrade` before it checks the improvement. Copper needs
    Bronze Working to be revealed at all and Mining to be mined; Horse needs
    Animal Husbandry for both. Returns the type key or None.
    """
    entry = rules.bonuses.get(bonus_type or "")
    tech = entry.get("city_trade") if entry else None
    return tech if tech and tech != "NONE" else None


def build_for(rules, improvement_type):
    """The worker action that produces this improvement, and its tech.

    The tech gate is NOT on the improvement - every ImprovementInfo in the
    stock files has an empty <PrereqTech>, and Agriculture/Mining/Pottery are
    attached to BUILD_FARM/BUILD_MINE/BUILD_COTTAGE instead. Reading the
    improvement's own field yields None, which reads as "no tech needed" and
    is wrong for almost every improvement in the game.

    Returns (build_key, tech) or (None, None).
    """
    for build_key, build in sorted(rules.builds.items()):
        if build.get("improvement") == improvement_type:
            return build_key, build.get("tech")
    return None, None


def clearing_requirement(rules, tile, improvement_type):
    """The build that removes a feature standing on this tile, and its tech.

    A feature is NOT an obstacle to legality - verified against the source,
    against an expectation that said otherwise. `canHaveImprovement` never
    consults the feature except via FeatureMakesValid and bRequiresFeature,
    so a Mine on a forested hill is perfectly legal; what the forest costs is
    a separate per-feature TECH inside the build, because clearing it is part
    of performing the build. That is why this returns a REQUIREMENT rather
    than a refusal, and why it is reported alongside a legal verdict.

    This is the join the trial missed: the agent had already run
    `rules.py tech TECH_BRONZE_WORKING`, seen `remove FEATURE_FOREST`, and
    still recommended a mine on a forested hill. Both facts were on screen in
    different places and nothing put them together.

    Returns (build_type, tech, feature) or None. Walks the nested
    FeatureStructs parse_builds already reads rather than the top-level
    PrereqTech - the per-feature tech is the one that gates this tile.
    """
    feature_key = tile.get("feature") or ""
    if not feature_key:
        return None
    improvement = rules.improvements.get(improvement_type) or {}
    # An improvement that REQUIRES the feature obviously does not clear it.
    if improvement.get("requires_feature"):
        return None
    for build_key, build in sorted(rules.builds.items()):
        if build.get("improvement") != improvement_type:
            continue
        for entry in build.get("features") or []:
            if entry.get("feature") == feature_key and entry.get("remove"):
                return (build_key, entry.get("tech"), feature_key)
    return None


def nature_terms(rules, tile, state=None, traits=()):
    """The unimproved tile's yield, decomposed the same way as an improved one.

    Passes improvement_type=None rather than naming some harmless
    improvement and filtering its terms back out - that earlier trick broke
    the moment a test fixture had no IMPROVEMENT_FARM in it. The bare tile
    is a case the accumulator handles, not a special one.
    """
    return improvement_yield(rules, tile, None, known=set(), traits=traits,
                             state=state)


def improvement_yield(rules, tile, improvement_type, known, traits=(),
                      state=None):
    """The tile's yield WITH this improvement, and the terms that make it up.

    Returns (total, terms) where terms is a list of (label, triplet) in the
    order the game applies them, so the caller can print the decomposition
    that would have exposed the invented Despotism penalty in the trial.

    Every term is data-driven. In particular the resource contributes TWICE
    and through different files - once bare (BonusInfo.YieldChange, Corn's
    +1 food) and once as a reward for this specific improvement
    (ImprovementInfo.BonusTypeStructs, Corn's +2 on a Farm). Reporting only
    one of the two is precisely the 4-instead-of-5 error.
    """
    # None means "the bare tile" - see nature_terms. An empty dict rather
    # than a guard at every use: none of the improvement fields below are
    # present, so each term falls away on its own.
    if improvement_type is None:
        improvement = {}
    else:
        improvement = rules.improvements.get(improvement_type)
        if improvement is None:
            raise RulesError("no such improvement: %s" % improvement_type)

    terms = []
    total = _triplet()

    # INVARIANT: this is the ONLY tile-yield accumulator, and every
    # whole-tile early-out belongs at the top of it. `nature_yield` and
    # `nature_terms` are projections of this function, not parallel
    # implementations - so a clause added here is inherited by all three.
    #
    # Keep it that way. There were once two accumulators, and a peak fix
    # applied to one left the view - which reached the other - printing
    # 2 food for a plot the engine reports as [0,0,0]. If a future
    # calculateYield clause seems to need adding "in both places", that is
    # the signal a second accumulator has crept back in, not a reason to
    # write the clause twice.
    if _impassable(tile):
        return [0, 0, 0], [("impassable", [0, 0, 0])]
    # Not a computed term but an ORACLE READ: deep ocean is underivable from
    # `map.tiles` (see _potential_city_work), so this one clause trusts the
    # export where every other term here is calculated.
    if state is not None and not _potential_city_work(tile):
        return [0, 0, 0], [("open sea - no city can reach it", [0, 0, 0])]

    terrain_key = tile.get("terrain") or ""
    terrain = rules.terrains.get(terrain_key)
    base = _triplet(terrain.get("yields") if terrain else None)
    terms.append((_plain(terrain_key), list(base)))
    _add(total, base)

    plot_type = tile.get("plotType")
    for index, yield_key in enumerate(rules.yield_order):
        step = _triplet()
        if plot_type == "PLOT_HILLS":
            step[index] += _yield_change_for(rules, yield_key, "hills")
        if tile.get("lake"):
            step[index] += _yield_change_for(rules, yield_key, "lake")
        if any(step):
            label = "hills" if plot_type == "PLOT_HILLS" else "lake"
            terms.append((label, step))
            _add(total, step)

    bonus_key = tile.get("bonus") or ""
    bonus = rules.bonuses.get(bonus_key)
    if bonus and bonus.get("yields") and any(bonus["yields"]):
        terms.append((_plain(bonus_key), list(bonus["yields"])))
        _add(total, bonus["yields"])

    feature_key = tile.get("feature") or ""
    feature = rules.features.get(feature_key)
    # An improvement that does not REQUIRE the feature clears it first, so its
    # yield change is gone by the time the improvement stands. Only the
    # feature-requiring improvements (all excluded from scope) keep it - as
    # does the bare tile, which clears nothing.
    keeps_feature = (improvement_type is None
                     or improvement.get("requires_feature"))
    if feature and keeps_feature and feature.get("yields") and any(feature["yields"]):
        terms.append((_plain(feature_key), list(feature["yields"])))
        _add(total, feature["yields"])

    if tile.get("river"):
        source = feature if (feature and keeps_feature) else terrain
        river = source.get("river") if source else None
        if river and any(river):
            terms.append(("river", list(river)))
            _add(total, river)

    own = improvement.get("yields")
    if own and any(own):
        terms.append((_plain(improvement_type), list(own)))
        _add(total, own)

    struct = improvement.get("bonus_structs", {}).get(bonus_key)
    if struct and struct.get("yields") and any(struct["yields"]):
        terms.append(("%s on %s" % (_plain(improvement_type), _plain(bonus_key)),
                      list(struct["yields"])))
        _add(total, struct["yields"])

    if improvement.get("irrigated") and tile.get("freshWater") \
            and any(improvement["irrigated"]):
        terms.append(("fresh water", list(improvement["irrigated"])))
        _add(total, improvement["irrigated"])

    for entry in improvement.get("tech_yields") or []:
        if entry.get("tech") in known and entry.get("yields") \
                and any(entry["yields"]):
            terms.append((_plain(entry["tech"]), list(entry["yields"])))
            _add(total, entry["yields"])

    total = [max(0, value) for value in total]

    # Order matters and follows calculateYield: the city floor is applied
    # BEFORE the trait threshold, so a Financial leader's city centre can be
    # lifted to 1 commerce by the floor and then cleared by the threshold.
    if state is not None:
        floored = _city_floor(rules, tile, state, total)
        if floored != total:
            step = [floored[i] - total[i] for i in range(3)]
            terms.append(("city centre minimum", step))
            total = floored

    # Financial last, and tested against the running total: the threshold is
    # "this tile already makes 2+ commerce", which is only decidable once
    # every other term has landed.
    for trait_key in traits:
        trait = rules.traits.get(trait_key)
        thresholds = trait.get("yield_thresholds") if trait else None
        if not thresholds:
            continue
        step = _triplet()
        for index in range(3):
            if thresholds[index] and total[index] >= thresholds[index]:
                step[index] += 1
        if any(step):
            terms.append((_plain(trait_key), step))
            total = [total[i] + step[i] for i in range(3)]

    return total, terms


def player_traits(rules, state):
    """The active player's traits, via the leader the state file exports.

    `player.traits` does not exist in the schema - only `player.leader` - so
    this join through CIV4LeaderHeadInfos is the only route. Returns () when
    the leader is unknown rather than guessing, which makes a missing trait
    file show up as "no Financial bonus" rather than a crash.
    """
    leader_key = ((state.get("player") or {}).get("leader")) or ""
    leader = rules.leaders.get(leader_key)
    return tuple(leader.get("traits") or ()) if leader else ()


def owner_traits(rules, state, owner_id):
    """Traits for whoever owns a tile - ours or a rival's.

    A rival's leader is only knowable if we have MET them: `contacts` carries
    the leader for each met civ. An unmet owner returns () with a False
    second element, so the caller can say "traits unknown" rather than
    quietly computing the tile as though the owner were traitless.
    """
    player = state.get("player") or {}
    if owner_id is None or owner_id == player.get("id"):
        return player_traits(rules, state), True
    for contact in state.get("contacts") or []:
        if contact.get("playerId") == owner_id:
            leader = rules.leaders.get(contact.get("leader") or "")
            return (tuple(leader.get("traits") or ()) if leader else ()), True
    return (), False


def find_tile(state, x, y):
    """The exported tile at (x, y), or None if it was never revealed.

    None is the honest answer for a never-scouted tile rather than an error
    case to paper over: `map.tiles` contains every tile the player has EVER
    revealed, so absence means the player has genuinely never seen it. A
    fogged tile is present (with visibleNow false) and is answerable.
    """
    for tile in (state.get("map") or {}).get("tiles") or []:
        if tile.get("x") == x and tile.get("y") == y:
            return tile
    return None


# ---------------------------------------------------------------------------
# Per-city buildability
# ---------------------------------------------------------------------------


def find_city(state, name):
    """Match a city by name, case-insensitively. Exact match wins."""
    cities = state.get("cities") or []
    for city in cities:
        if (city.get("name") or "") == name:
            return city
    lowered = name.lower()
    for city in cities:
        if (city.get("name") or "").lower() == lowered:
            return city
    return None


def city_connected_bonuses(city):
    """The resources this city's trade network delivers, as a set.

    Per city rather than per empire because they genuinely differ: Oporto is
    founded on t36 with nothing connected and picks up both of Lisbon's
    resources on t37, when the road at (77,15) closes the chain. Membership
    only - quantity is an empire fact the engine does not model per city.
    """
    grouped = city.get("bonuses") or {}
    found = set()
    for group in ("strategic", "happiness", "health"):
        found.update(grouped.get(group) or [])
    return found


def food_build_rate(city, unit):
    """Hammers per turn for this unit, folding in food if it is a bFood build.

    Settlers and workers are built with food AND hammers: while one is in the
    queue the city's entire food surplus is added to production, so the city
    stops growing and the unit arrives much sooner. Ignoring it made the tool
    quote roughly double the real time on the two builds that dominate turns
    0-50.

    Returns (rate, folded) so the caller can label an estimate that assumes
    growth stops - the trade is real and belongs to the reader.

    PRIMARY PATH: schema increment 6 exports `productionFromHammers` and
    `productionFromFood` directly - the engine's own split, taken the way
    CvCity::getProductionBarPercentages sizes the city screen's two-tone bar.
    An ordinary build's rate is simply the hammer half, no inference from
    what happens to be queued, and no "optimistic" flag, because the case
    that flag existed for is exactly the one the split resolves. If the food
    build itself is already queued, its surplus is inside `food`; if not,
    the surplus is still growing the city and sits in `foodPerTurn` instead -
    either way it is this hypothetical build's to have.

    FALLBACK: older captures carry only `productionPerTurn`/`foodPerTurn`, and
    the split has to be inferred. Lisbon on consecutive turns showed why it's
    fragile both ways:

        t42  UNIT_WARRIOR   foodPerTurn 6   productionPerTurn 7
        t43  UNIT_SETTLER   foodPerTurn 0   productionPerTurn 13   (= 6 + 7)

    `productionPerTurn` ALREADY includes the food while a food build is in
    progress, and `foodPerTurn` reads 0 then - so a food build's own rate is
    the total as-is, while every OTHER build sharing that city inherits food
    it will never get and must be flagged "optimistic" rather than corrected,
    since the split is not recoverable from one file (Lisbon's hammers move
    8 -> 2 across t37 -> t38 as worked tiles change).
    """
    hammers = city.get("productionFromHammers")
    if hammers is not None:
        food = city.get("productionFromFood") or 0
        if unit.get("food_production"):
            surplus = food or (city.get("foodPerTurn") or 0)
            if surplus > 0:
                return hammers + surplus, True
            return hammers, False
        # An ordinary build never receives the food half, whatever the city is
        # currently training. This is the whole point of the split.
        return hammers, False

    rate = city.get("productionPerTurn") or 0
    surplus = city.get("foodPerTurn") or 0
    producing = city.get("producing") or ""
    # foodPerTurn reads 0 exactly while a food build is in the queue, so a
    # unit under production with no surplus is the "already folded in" case.
    # (Disorder also zeroes food, and then rate is 0 too, so nothing moves.)
    already_folded = producing.startswith("UNIT_") and surplus == 0 and rate > 0

    if unit.get("food_production"):
        if already_folded:
            return rate, True
        if surplus > 0:
            return rate + surplus, True
        return rate, False

    if already_folded:
        # Ordinary build while a food build is running: part of `rate` is food
        # this build would not get, so the estimate is optimistic. Flagged
        # rather than silently overstated.
        return rate, "optimistic"
    return rate, False


def _resource_gate(bonus_type, connected, rules, state, known):
    """One resource prerequisite, as a short blocker phrase or None if met.

    Deliberately terser than `_resource_status`: that block is the whole answer
    for a single lookup, whereas here it is one cell in a list of twenty, and
    the per-tile detail belongs in the drill-down the row points at.
    """
    if bonus_type in connected:
        return None
    entry = rules.bonuses.get(bonus_type) or {}
    reveal = entry.get("reveal")
    if reveal and reveal != "NONE" and reveal not in known:
        # The honest answer is not "you lack it" - you cannot yet tell either
        # way, which is a different fact and the one that decides whether to
        # research the revealing tech at all.
        return "%s not revealed yet (needs %s)" % (bonus_type, reveal)
    tiles = [t for t in (state.get("map") or {}).get("tiles") or []
             if t.get("bonus") == bonus_type]
    if not tiles:
        return "%s: none on your map yet" % bonus_type
    # Visible but not connected: name the nearest thing to act on. Borders
    # first, since an unowned tile needs a city or culture before anything
    # else can be done to it.
    for tile in tiles:
        gaps = []
        if tile.get("owner") is None:
            gaps.append("outside your borders")
        if not tile.get("improvement"):
            gaps.append("unimproved")
        if not tile.get("route"):
            gaps.append("no road")
        if gaps:
            return "%s at (%d,%d): %s" % (bonus_type, tile["x"], tile["y"],
                                          ", ".join(gaps))
    return "%s visible but not connected" % bonus_type


def _tech_blocker(tech, state, in_progress=None):
    """`needs TECH_X`, saying so when TECH_X is the one being researched.

    "needs TECH_MASONRY" and "needs TECH_MASONRY - researching now, 7 turns
    left" are different decisions: the first is a plan, the second is a wait.
    """
    if in_progress and tech == in_progress:
        research = (state.get("player") or {}).get("research") or {}
        left = research.get("turnsLeft")
        if left is not None:
            return ("needs %s - RESEARCHING NOW, ~%d turns left"
                    % (tech, left))
        return "needs %s - RESEARCHING NOW" % tech
    return "needs %s" % tech


def unit_availability(rules, unit_type, unit, city, state, known, connected,
                      other_uniques, in_progress=None):
    """Why this unit can or cannot be trained here, as a list of blockers.

    An empty list means buildable now. The list is every reason, not the first
    one: "needs Bronze Working AND copper" is a different plan from either
    alone, and stopping at the first gate would hide the second until the
    first is paid.
    """
    blockers = []
    if unit_type in other_uniques:
        return ["another civilization's unique unit"]
    if unit.get("domain") == "DOMAIN_SEA" and not city.get("coastal"):
        blockers.append("city is not coastal (sea unit)")
    # Religion and corporation state is not in the export at all, so these are
    # reported as unknown rather than as met or unmet. Calling a missionary
    # available when no religion has spread here would be a confident wrong
    # answer of exactly the kind this tool exists to prevent.
    if unit.get("religion"):
        blockers.append(OUT_OF_SCOPE + "needs %s present here - not in the "
                        "export, check the city screen" % unit["religion"])
    if unit.get("corporation"):
        blockers.append(OUT_OF_SCOPE + "needs %s - corporations are out of "
                        "scope" % unit["corporation"])
    tech = unit.get("prereq_tech")
    if tech and tech != "NONE" and tech not in known:
        blockers.append(_tech_blocker(tech, state, in_progress))
    # BonusType is required outright; PrereqBonuses is an AND-list beside it.
    if unit.get("bonus_type"):
        gate = _resource_gate(unit["bonus_type"], connected, rules,
                              state, known)
        if gate:
            blockers.append(gate)
    for bonus in unit.get("prereq_bonuses") or []:
        gate = _resource_gate(bonus, connected, rules, state, known)
        if gate:
            blockers.append(gate)
    return blockers


def building_availability(rules, building_type, building, city, state, known,
                          connected, other_uniques, wonders, in_progress=None):
    """Why this building can or cannot be constructed here.

    Carries the three gates that made the empire-wide list impossible: bWater
    against cities[].coastal, bRiver against the city tile's river flag, and
    PrereqBuildingClasses against cities[].buildings - all per city, none
    derivable from anywhere else in the export.
    """
    blockers = []
    if building_type in other_uniques:
        return ["another civilization's unique building"]

    class_key = rules.class_of_building.get(building_type)
    class_entry = rules.building_classes.get(class_key) if class_key else None
    if class_entry:
        built = set((wonders or {}).get("built") or [])
        national = set((wonders or {}).get("national") or [])
        if class_entry["max_global"] == 1 and class_key in built:
            # Gone globally. The tool used to say only that rival production is
            # invisible, which is still true of a wonder nobody has finished.
            return ["ALREADY BUILT somewhere in the world - no longer available"]
        if class_entry["max_player"] == 1 and class_key in national:
            return ["you already have one (national wonder, one per player)"]

    if building_type in (city.get("buildings") or []):
        return ["already built here"]

    if building.get("holy_city"):
        # A shrine is buildable only in the city that founded the religion, and
        # only by a Great Prophet. Neither fact is in the export.
        return [OUT_OF_SCOPE + "holy city of %s only, and built by a Great "
                "Prophet" % building["holy_city"]]
    if building.get("religion"):
        blockers.append(OUT_OF_SCOPE + "needs %s present here - not in the "
                        "export, check the city screen" % building["religion"])
    if building.get("corporation"):
        blockers.append(OUT_OF_SCOPE + "needs %s - corporations are out of "
                        "scope" % building["corporation"])

    tech = building.get("tech")
    if tech and tech != "NONE" and tech not in known:
        blockers.append(_tech_blocker(tech, state, in_progress))

    if building.get("water") and not city.get("coastal"):
        blockers.append("city is not coastal")
    if building.get("river") and not _city_on_river(city, state):
        blockers.append("city is not on a river")

    have_classes = set()
    for existing in city.get("buildings") or []:
        existing_class = rules.class_of_building.get(existing)
        if existing_class:
            have_classes.add(existing_class)
    for required in building.get("prereq_buildings") or []:
        if required not in have_classes:
            blockers.append("needs %s here" % required)

    resources = list(building.get("prereq_bonuses") or [])
    if building.get("bonus"):
        resources.append(building["bonus"])
    for bonus in resources:
        gate = _resource_gate(bonus, connected, rules, state, known)
        if gate:
            blockers.append(gate)
    return blockers


def _city_on_river(city, state):
    """Whether the city's own tile is on a river.

    Not exported as a city field, but the city stands on a map tile and `river`
    is exported there, so this is a join rather than a derivation. A city tile
    missing from map.tiles would be a broken export; treated as not-a-river
    rather than raising, since this gates one line of one row.
    """
    for tile in (state.get("map") or {}).get("tiles") or []:
        if tile.get("x") == city.get("x") and tile.get("y") == city.get("y"):
            return bool(tile.get("river"))
    return False


def _unique_sets(rules, state):
    """(units you may build, buildings you may build) as exclusion sets.

    Returns the types belonging to OTHER civs. Your own uniques are not in it,
    so they list normally; the class default you replace is, so it drops out.
    """
    mine = (state.get("player") or {}).get("civilization")
    ours = (rules.civilizations or {}).get(mine) or {"units": {}, "buildings": {}}
    our_units = set(ours["units"].values())
    our_buildings = set(ours["buildings"].values())

    other_units, other_buildings = set(), set()
    for key, civ in (rules.civilizations or {}).items():
        if key == mine:
            continue
        other_units.update(civ["units"].values())
        other_buildings.update(civ["buildings"].values())

    # A class we override loses its other members: our unique REPLACES them.
    for unit_type, unit in (rules.units or {}).items():
        if unit.get("unit_class") in ours["units"]:
            other_units.add(unit_type)
    for building_type in (rules.buildings or {}):
        if rules.class_of_building.get(building_type) in ours["buildings"]:
            other_buildings.add(building_type)

    # ...but never our own uniques, which the sweep above just swept up.
    return other_units - our_units, other_buildings - our_buildings


def _closure_block(rules, tech_type, known, show_known, max_depth, out, state):
    """Shared by `unit` and `tech`: the tree, then the totals."""
    needed = closure(rules, tech_type, known)
    tree, hidden = render_tree(rules, tech_type, known, show_known, max_depth,
                               state=state)

    out.append("")
    out.append("TECH CLOSURE - full walk, %d prerequisite%s still needed"
               % (len(needed), "" if len(needed) == 1 else "s"))
    out.extend("  " + line for line in tree)
    out.append("")
    out.append("  Indentation is prerequisite depth. Unlabelled children are ALL")
    out.append("  required; ANY ONE OF marks a choice. A tech appearing twice is")
    out.append("  one tech, counted once.")
    if hidden[0]:
        out.append("  %d prerequisite%s you already have %s hidden (--show-known)."
                   % (hidden[0], "" if hidden[0] == 1 else "s",
                      "is" if hidden[0] == 1 else "are"))

    entry = rules.techs.get(tech_type)
    # No route comparison when the or-list is already satisfied: there is no
    # choice left to make, and listing the roads not taken - priced, with turn
    # estimates - reads as work still to do.
    if entry and or_satisfied(entry["or"], known):
        pass  # the tree already says which branch met it
    elif entry and len(entry["or"]) > 1:
        out.append("")
        out.append("ROUTE COST - all-in, each route including %s itself"
                   % tech_type)
        own_cost = rules.cost(tech_type) if tech_type not in known else 0
        rate = _rate_of(state)
        for route in entry["or"]:
            route_set = closure(rules, route, known) | (
                set() if route in known else {route}
            )
            # The all-in figure, matching the single-route TOTAL TO UNLOCK line
            # above: a reader comparing routes is choosing how to reach this
            # tech, not how to reach the intermediate one.
            total = sum(rules.cost(item) for item in route_set) + own_cost
            turns = turns_estimate(total, rate)
            suffix = "  ~%d turns" % turns if turns is not None else ""
            # `route_set` is never empty here: it is empty only when the route
            # itself is known, which satisfies the or-list, which means this
            # block does not run. The earlier "OPEN NOW" case was dead once the
            # satisfied-or rule landed.
            out.append("  via %-24s %2d tech%s %6d all-in%s"
                       % (route, len(route_set),
                          "  " if len(route_set) == 1 else "s ",
                          total, suffix))
        out.append("")
        out.append("  Totals include %s's own %d. Routes are listed in XML order"
                   % (tech_type, own_cost))
        out.append("  and NOT ranked - cost is one factor, what else each route")
        out.append("  unlocks is the other. Turns extrapolate your current rate.")

    total = sum(rules.cost(item) for item in needed)
    own = rules.cost(tech_type) if tech_type not in known else 0
    out.append("")
    # `or_satisfied` must be tested here too, and with the same sense as above:
    # once the choice is made there is exactly one number to pay, so this takes
    # the single-total branch. Gating the two blocks on different conditions is
    # what left the Pyramids printing a multi-route caveat directly beneath
    # "prerequisites are already met", pointing at route figures no longer shown.
    if entry and len(entry["or"]) > 1 and not or_satisfied(entry["or"], known):
        # A union total across or-branches is a number nobody ever pays: you
        # walk one route, so summing both overstates the real cost by the whole
        # of the route you do not take (762 vs ~451 for TECH_MONARCHY). Printing
        # it beside per-route totals would invite reading it as "the cost", so
        # the union is described as coverage and the routes carry the cost.
        # No "add its own cost" instruction here: the route lines above are
        # already all-in, and telling the reader to add it again double-counts.
        out.append("  %d beakers would cover ALL %d routes - you pay one of"
                   % (total + own, len(entry["or"])))
        out.append("  them, so use the all-in route figures above, not this.")
    else:
        # The actionable number leads. It used to print prerequisites first and
        # the real total second; a trial read "62 beakers" as the cost of
        # TECH_ARCHERY when the answer was 155. Same lesson as run_history's
        # walk-before-straight-line ordering: when a caveat does not stick,
        # change the layout rather than adding words.
        out.append("  TOTAL TO UNLOCK %-18s %5d beakers"
                   % (tech_type, total + own))
        turns = _turns_line(total + own, state, indent="    ")
        if turns:
            out.append(turns)
        if total:
            out.append("    of which prerequisites: %d" % total)
        out.append("")
        out.append("  Turns are an extrapolation at your CURRENT rate, which moves")
        out.append("  as cities grow and the science slider changes. Not a schedule.")
    return needed


def view_unit(rules, unit_type, state, show_known, max_depth):
    unit = rules.units.get(unit_type)
    if unit is None:
        raise _not_found("unit", unit_type, rules.units,
                         _relative(rules.unit_path, rules.xml_root),
                         "UNIT_AXEMAN",
                         annotate=lambda u: u["unit_class"] or "")

    known = effective_known(state)
    out = []
    out.append("%s - Beyond the Sword XML, against %s"
               % (unit_type, state_summary(state)))
    out.append("")
    out.append("  %s:%d" % (_relative(rules.unit_path, rules.xml_root), unit["line"]))

    out.append("")
    out.append("COMBAT")
    out.append("  class      %s" % (unit["combat_class"] or "(none)"))
    out.append("  strength   %d" % unit["strength"])
    out.append("  moves      %d" % unit["moves"])
    # Hammers scale with game speed only. CIV4GameSpeedInfo has iTrainPercent
    # and iConstructPercent, but CIV4HandicapInfo has only iAITrainPercent /
    # iAIConstructPercent - AI-side, not the player's. So unlike research,
    # difficulty does NOT change what a unit costs you. An agent trial quoted a
    # raw iCost and said outright it was not confident the number was the one
    # the city screen shows; it was right to doubt, and this is the answer.
    train_pct = rules.train_pct
    scaled = unit["cost"] * train_pct // 100
    if train_pct == 100:
        out.append("  cost       %d hammers" % scaled)
    else:
        out.append("  cost       %d hammers (base %d x game speed %d%%)"
                   % (scaled, unit["cost"], train_pct))

    abilities = []
    for combat_type, value in unit["combat_mods"]:
        abilities.append("%+d%% vs %s" % (value, combat_type))
    # Attack-only and defence-only modifiers keep their own wording: "+100%
    # attacking UNITCLASS_AXEMAN" is a reason to move, "+100% defending vs
    # UNITCLASS_CHARIOT" is a reason to sit still, and a shared phrasing would
    # make the two indistinguishable.
    for label in ("attacking", "defending vs", "vs"):
        for unit_class, value in unit["class_mods"].get(label, []):
            abilities.append("%+d%% %s %s" % (value, label, unit_class))
    # Printed beside the <UnitCombatMods> entries because it is the same kind
    # of fact, despite living in its own XML field. The animals are named
    # rather than left as a bare "vs animals" - four is a short enough list to
    # state, and "which ones" is the immediate next question - but they are
    # looked up from the data for the same reason the holders below are: which
    # units are animals is a fact about the file, not a rule. Lowercased
    # without the prefix because this sits mid-clause; the keys are one lookup
    # away for anyone who wants to grep them.
    if unit["animal_combat"]:
        animals = sorted(key[len("UNIT_"):].lower() if key.startswith("UNIT_")
                         else key
                         for key, other in rules.units.items()
                         if other["is_animal"])
        abilities.append("%+d%% vs animals%s"
                         % (unit["animal_combat"],
                            " (%s)" % ", ".join(animals) if animals else ""))
    if unit["is_animal"]:
        # The holders are looked up rather than named, because "the Scout" is a
        # fact about the current data, not a rule: iAnimalCombat is an ordinary
        # field any unit could carry, and a hardcoded name would go quietly
        # wrong under a mod while reading as though the engine special-cases it.
        holders = sorted(key for key, other in rules.units.items()
                         if other["animal_combat"])
        if holders:
            abilities.append("counts as an animal - %s %s an animal combat "
                             "bonus against this"
                             % (", ".join(holders),
                                "has" if len(holders) == 1 else "have"))
        else:
            abilities.append("counts as an animal - units with an animal "
                             "combat bonus get it against this")
    if unit["city_attack"]:
        abilities.append("%+d%% attacking cities" % unit["city_attack"])
    if unit["city_defense"]:
        abilities.append("%+d%% city defence" % unit["city_defense"])
    if unit["bombard_rate"]:
        abilities.append(
            "bombards a city's defence bonus down by %d points per turn"
            % unit["bombard_rate"])
    if unit["ignore_building_defense"]:
        abilities.append("ignores a city's building defence bonus "
                         "(walls and the like)")
    # Gated on iCollateralDamage, never on the limit: 25 units carry a non-zero
    # limit and max-units while dealing no collateral at all, because flanking
    # reuses those two fields. The limit and cap are folded into this one line
    # rather than printed separately - alone they say nothing, and the engine
    # needs all three to be non-zero for any of it to happen.
    if (unit["collateral_damage"] and unit["collateral_damage_limit"]
            and unit["collateral_damage_max_units"]):
        abilities.append(
            "collateral damage to up to %d other units in the stack, "
            "each down to %d%% health"
            % (unit["collateral_damage_max_units"],
               unit["collateral_damage_limit"]))
    if unit["hills_defense"]:
        abilities.append("%+d%% defence on hills" % unit["hills_defense"])
    if unit["hills_attack"]:
        abilities.append("%+d%% attacking hills" % unit["hills_attack"])
    if unit["first_strikes"]:
        abilities.append("%d first strike%s" % (unit["first_strikes"],
                                                "" if unit["first_strikes"] == 1 else "s"))
    if unit["withdrawal"]:
        abilities.append("%d%% withdrawal" % unit["withdrawal"])
    for unit_class, value in unit["flanking"]:
        abilities.append("flanking strike vs %s (%d%%)" % (unit_class, value))
    # Printed only for a genuine cap. 100 is the default and 0 is a non-combat
    # unit, whose strength 0 already says so - printing either would put a
    # line on 117 of the 123 units that means nothing.
    if 0 < unit["combat_limit"] < 100:
        abilities.append(
            "damages only to %d%% health - cannot make the kill"
            % unit["combat_limit"])
    for combat_type in unit["collateral_immune"]:
        abilities.append("immune to collateral damage from %s" % combat_type)
    if unit["first_strike_immune"]:
        abilities.append("immune to first strikes")
    if unit["no_defensive_bonus"]:
        abilities.append("no terrain defensive bonus")
    if unit["ignore_terrain_cost"]:
        abilities.append("ignores terrain movement cost (every tile costs 1)")
    # Stated as the concrete consequence rather than as the field name: the
    # question this answers is "is it safe to send THIS unit into that hut",
    # and "no bad goodies" does not obviously mean "cannot trigger the hostile
    # barbarian result".
    if unit["no_bad_goodies"]:
        abilities.append("never triggers a hostile result from a goody hut")
    for terrain in unit["terrain_impassable"]:
        abilities.append("cannot enter %s" % terrain)
    for feature in unit["feature_impassable"]:
        abilities.append("cannot enter %s" % feature)
    if abilities:
        out.append("  abilities  " + ("\n             ".join(abilities)))

    # Its own line rather than an `abilities` entry: these are promotions, so
    # the answer to "what does that actually do" is another subcommand, and a
    # bare name inside a list of prose effects reads as if it were one.
    if unit["free_promotions"]:
        out.append("  starts with %s" % ", ".join(unit["free_promotions"]))
        out.append("             built with these already taken - "
                   "`rules.py promotion` for what each does")

    out.append("")
    out.append("REQUIRES")
    prereq = unit["prereq_tech"]
    if prereq and prereq != "NONE":
        mark = _tech_status(prereq, known, state)
        out.append("  tech       %-26s %s" % (prereq, mark))
    else:
        out.append("  tech       (none)")
    resources = list(unit["prereq_bonuses"])
    outright = unit["bonus_type"]
    if outright:
        resources.append(outright)
    if resources:
        label = "resource" if outright and not unit["prereq_bonuses"] else "resource"
        if unit["prereq_bonuses"]:
            out.append("  %-10s %s" % (label, " or ".join(unit["prereq_bonuses"])))
        if outright:
            out.append("  %-10s %s (required outright)" % (label, outright))
        for name in resources:
            out.extend("             " + line
                       for line in _resource_status(rules, name, state, known))
        out.append("             CONNECTED is checked against your trade network.")
        out.append("             A resource merely visible on the map is not enough:")
        out.append("             it needs your borders, the right improvement and a")
        out.append("             road. Where that is missing the gap is named above.")

    if prereq and prereq != "NONE":
        _closure_block(rules, prereq, known, show_known, max_depth, out, state)

        # Reverse lookup: everything else gated on the same tech. This exists
        # for `intel` - spotting a UNIT_GREEK_PHALANX and spotting a
        # UNIT_AXEMAN are the same tech conclusion, and an agent that only
        # knows the generic unit will not make the join.
        #
        # Unit class is printed rather than asserting these are replacements:
        # a shared class means one replaces the other, a different class means
        # the tech simply unlocks both. Writing this, a hand-grep put
        # UNIT_MAYA_HOLKAN in this list; it is a SPEARMAN replacement needing
        # TECH_HUNTING, and the 95-line grep window had crossed into the next
        # block. The parser was right and the grep was wrong.
        siblings = sorted(
            (key, other["unit_class"])
            for key, other in rules.units.items()
            if other["prereq_tech"] == prereq and key != unit_type
        )
        if siblings:
            own_class = unit["unit_class"]
            out.append("")
            out.append("SAME TECH ALSO UNLOCKS")
            for name, unit_class in siblings:
                same = " (replaces this one)" if unit_class == own_class else ""
                out.append("  %-34s %s%s" % (name, unit_class or "?", same))
            out.append("")
            out.append("  Seeing any of these implies the same tech. Same unit class")
            out.append("  means one replaces the other; a different class means the")
            out.append("  tech unlocks both.")

    out.append("")
    out.append("OMITS")
    out.append("  Buildings, civics and improvements on this tech - `rules.py tech`.")
    out.append("  Obsolescence, upgrade paths and AI weighting.")
    out.append("  What a specific promotion does - `rules.py promotion`.")
    out.append("  Air-combat fields (interception), and the AI weighting, XP and")
    out.append("  unit-AI values. These are real fields in the same block, NOT")
    out.append("  printed: silence here is not a claim the unit lacks them.")
    out.append("  Abilities defined outside CIV4UnitInfos.xml. Some movement and")
    out.append("  terrain rules live in the SDK and are NOT reported here.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


# Flat numeric fields on a parsed promotion, each an accumulator the engine
# adds straight into a running total per unit (CvUnit::setHasPromotion,
# verified in CvUnit.cpp: changeExtraCombatPercent, changeExtraCityAttackPercent,
# etc. - one change*() call per field, no interaction or cap between them).
# Shared between _promotion_effects (single promotion) and _promotion_totals
# (several at once) so the wording can never drift between the two.
_FLAT_EFFECT_FIELDS = (
    ("combat_percent", "%+d%% combat"),
    ("city_attack", "%+d%% city attack"),
    ("city_defense", "%+d%% city defence"),
    ("hills_attack", "%+d%% hills attack"),
    ("hills_defense", "%+d%% hills defence"),
    ("withdrawal", "%+d%% withdrawal"),
    ("chance_first_strikes", "%+d%% chance of a first strike"),
    ("visibility", "%+d visibility"),
    ("intercept_change", "%+d%% interception"),
    ("collateral_protection", "%+d%% collateral damage protection"),
    ("collateral_damage_change", "%+d%% collateral damage dealt"),
    ("pillage", "%+d%% pillage"),
    ("experience_percent", "%+d%% experience from combat"),
    ("same_tile_heal", "%+d%% same-tile healing"),
    ("adjacent_tile_heal", "%+d%% adjacent-tile healing"),
    ("neutral_heal", "%+d%% neutral-territory healing"),
    ("enemy_heal", "%+d%% enemy-territory healing"),
)

# Boolean flags: the engine ORs these across held promotions (CvUnit tracks a
# COUNT per flag, e.g. changeAmphibCount, so it is true if ANY held promotion
# sets it) - never summed, unlike _FLAT_EFFECT_FIELDS.
_FLAG_EFFECT_FIELDS = (
    ("always_heal", "always heals, even after moving or attacking"),
    ("hills_double_move", "double movement on hills"),
    ("amphib", "no attack penalty from the sea"),
    ("river", "no attack penalty across a river"),
    ("blitz", "can attack more than once per turn"),
    ("immune_to_first_strikes", "immune to first strikes"),
)


def _promotion_effects(promotion):
    """Human-readable EFFECTS lines for one parsed promotion."""
    effects = []
    for key, template in _FLAT_EFFECT_FIELDS:
        if promotion[key]:
            effects.append(template % promotion[key])
    if promotion["first_strikes"]:
        n = promotion["first_strikes"]
        effects.append("%+d first strike%s" % (n, "" if abs(n) == 1 else "s"))
    if promotion["moves"]:
        n = promotion["moves"]
        effects.append("%+d move%s" % (n, "" if abs(n) == 1 else "s"))
    for key, label in _FLAG_EFFECT_FIELDS:
        if promotion[key]:
            effects.append(label)
    for label, key in (("attack", "terrain_attack"), ("defence", "terrain_defense")):
        for terrain, value in promotion[key]:
            effects.append("%+d%% %s on %s" % (value, label, terrain))
    for label, key in (("attack", "feature_attack"), ("defence", "feature_defense")):
        for feature, value in promotion[key]:
            effects.append("%+d%% %s in %s" % (value, label, feature))
    for terrain in promotion["terrain_double_move"]:
        effects.append("double movement on %s" % terrain)
    for feature in promotion["feature_double_move"]:
        effects.append("double movement in %s" % feature)
    for combat_type, value in promotion["unit_combat_mods"]:
        effects.append("%+d%% vs %s" % (value, combat_type))
    for domain, value in promotion["domain_mods"]:
        effects.append("%+d%% vs %s units" % (value, domain))
    return effects


def _view_one_promotion(rules, promotion_type, state, show_known, max_depth,
                        brief=False):
    """One PROMOTION_'s own block: EFFECTS always, AVAILABLE TO/REQUIRES too
    unless `brief` - which view_promotable sets for a unit's ALREADY HAS
    section, where both are moot (the unit already has it: what it is
    offered to and what it needed no longer matter, only what it does).
    view_promotion's own standalone lookup keeps brief=False, since there
    the promotion is hypothetical and both questions are exactly the point.
    """
    promotion = rules.promotions.get(promotion_type)
    if promotion is None:
        if not rules.promotions:
            raise RulesError(
                "CIV4PromotionInfos.xml did not load - cannot answer "
                "promotion questions on this install.")
        raise _not_found("promotion", promotion_type, rules.promotions,
                         _relative(rules.promotion_path, rules.xml_root),
                         "PROMOTION_COMBAT1")

    known = effective_known(state)
    out = []
    if brief:
        out.append(promotion_type)
    else:
        out.append("%s - Beyond the Sword XML, against %s"
                   % (promotion_type, state_summary(state)))
    out.append("")
    out.append("  %s:%d" % (_relative(rules.promotion_path, rules.xml_root),
                            promotion["line"]))

    out.append("")
    out.append("EFFECTS")
    effects = _promotion_effects(promotion)
    if effects:
        out.append("  " + ("\n  ".join(effects)))
    else:
        out.append("  (no numeric effects parsed - see OMITS)")

    if brief:
        return out

    out.append("")
    out.append("AVAILABLE TO")
    if promotion["restricted_to_unit_combats"]:
        out.append("  " + ", ".join(promotion["restricted_to_unit_combats"]))
    else:
        # Not observed in the stock file - every real promotion's UnitCombats
        # lists at least one class - but if it ever were empty, the
        # eligibility path (_promotion_valid_for_unit) treats that as
        # "offered to nobody", matching CvGameCoreUtils::isPromotionValid's
        # getUnitCombat() membership test. This wording must agree with that,
        # not claim the opposite.
        out.append("  no unit combat class (not observed in the stock file)")

    out.append("")
    out.append("REQUIRES")
    prereqs = []
    if promotion["prereq"]:
        prereqs.append(promotion["prereq"])
    if promotion["prereq_or"]:
        prereqs.append(" or ".join(promotion["prereq_or"]))
    if prereqs:
        for line in prereqs:
            out.append("  promotion   %s" % line)
    else:
        out.append("  promotion   (none)")
    if promotion["tech"]:
        mark = _tech_status(promotion["tech"], known, state)
        out.append("  tech        %-26s %s" % (promotion["tech"], mark))
        _closure_block(rules, promotion["tech"], known, show_known, max_depth,
                       out, state)
    else:
        out.append("  tech        (none)")
    return out


def _promotion_totals(promotions):
    """Combined EFFECTS lines for several promotions held AT ONCE on one unit.

    Verified safe to sum in CvUnit::setHasPromotion (CvUnit.cpp): every flat
    numeric field is added into the unit's running total via its own
    change*() call - iCombatPercent into m_iExtraCombatPercent,
    iCityAttack into m_iExtraCityAttackPercent, and so on for every field in
    _FLAT_EFFECT_FIELDS plus firstStrikes/moves, terrain/feature attack and
    defence per-index, terrain/feature double-move counts, unit-combat mods
    and domain mods - one accumulator per field, no cap and no interaction
    term found between any two promotions' contributions. Flags in
    _FLAG_EFFECT_FIELDS are OR'd (a per-flag COUNT > 0), never summed.

    Callers currently only reach this behind a "more than one held" guard,
    but an empty `promotions` returns [] rather than raising - a total of
    nothing is a valid, if odd, question, and there is no reason to prefer a
    KeyError over an empty answer if that guard is ever relaxed.
    """
    if not promotions:
        return []
    totals = {}
    for promotion in promotions:
        for key, _template in _FLAT_EFFECT_FIELDS:
            totals[key] = totals.get(key, 0) + promotion[key]
        totals["first_strikes"] = totals.get("first_strikes", 0) + promotion["first_strikes"]
        totals["moves"] = totals.get("moves", 0) + promotion["moves"]
        for list_key in ("terrain_attack", "terrain_defense", "feature_attack",
                         "feature_defense", "unit_combat_mods", "domain_mods"):
            bucket = totals.setdefault(list_key, {})
            for name, value in promotion[list_key]:
                bucket[name] = bucket.get(name, 0) + value
        for list_key in ("terrain_double_move", "feature_double_move"):
            bucket = totals.setdefault(list_key, set())
            bucket.update(promotion[list_key])
        for key, _label in _FLAG_EFFECT_FIELDS:
            totals[key] = totals.get(key, False) or promotion[key]

    effects = []
    for key, template in _FLAT_EFFECT_FIELDS:
        if totals[key]:
            effects.append(template % totals[key])
    if totals["first_strikes"]:
        n = totals["first_strikes"]
        effects.append("%+d first strike%s" % (n, "" if abs(n) == 1 else "s"))
    if totals["moves"]:
        n = totals["moves"]
        effects.append("%+d move%s" % (n, "" if abs(n) == 1 else "s"))
    for key, label in _FLAG_EFFECT_FIELDS:
        if totals[key]:
            effects.append(label)
    for label, key in (("attack", "terrain_attack"), ("defence", "terrain_defense")):
        for terrain, value in sorted(totals[key].items()):
            if value:
                effects.append("%+d%% %s on %s" % (value, label, terrain))
    for label, key in (("attack", "feature_attack"), ("defence", "feature_defense")):
        for feature, value in sorted(totals[key].items()):
            if value:
                effects.append("%+d%% %s in %s" % (value, label, feature))
    for terrain in sorted(totals["terrain_double_move"]):
        effects.append("double movement on %s" % terrain)
    for feature in sorted(totals["feature_double_move"]):
        effects.append("double movement in %s" % feature)
    for combat_type, value in sorted(totals["unit_combat_mods"].items()):
        if value:
            effects.append("%+d%% vs %s" % (value, combat_type))
    for domain, value in sorted(totals["domain_mods"].items()):
        if value:
            effects.append("%+d%% vs %s units" % (value, domain))
    return effects


def find_unit(state, unit_id):
    """Match one of the player's own units by its engine id (an int)."""
    for unit in state.get("units") or []:
        if unit.get("id") == unit_id:
            return unit
    return None


# The isOnlyDefensive exclusion set from CvGameCoreUtils::isPromotionValid
# (:241-252) - VERBATIM, not a subset: a unit that can only defend is refused
# any promotion setting ANY of these seven fields, independent of whether it
# would otherwise pass the collateral/blitz/amphib/river checks elsewhere in
# the cascade. An earlier draft of this tuple wrongly assumed three of the
# seven were "covered by the checks below rather than duplicated" - they are
# not; isOnlyDefensive is its own OR-condition over all seven, checked before
# and independent of the later per-field checks.
_ONLY_DEFENSIVE_BLOCKED_FIELDS = (
    "city_attack", "withdrawal", "collateral_damage_change",
    "blitz", "amphib", "river", "hills_attack",
)


def _promotion_valid_for_unit(rules, unit, promotion_type, _seen=None):
    """CvGameCoreUtils::isPromotionValid, reproduced - whether `unit` could
    EVER take `promotion_type`, given only its own fixed properties (combat
    class, only-defensive, moves, collateral/intercept capability). This is
    NOT eligibility (no prereq/tech/held checks - see _promotable_promotions
    for those); it answers "is this promotion even shaped for this unit."

    Recurses into the promotion's own PromotionPrereq/PrereqOr chain, because
    the engine does: isPromotionValid re-validates a prerequisite promotion
    against the SAME checks, not just "do you hold it" (canAcquirePromotion
    checks holding; isPromotionValid separately re-derives validity for the
    prereq itself, CvGameCoreUtils.cpp:287-293 for PromotionPrereq and a
    parallel block for the OR pair). This matters for FREE promotions: a
    UNIT_JAPAN_SAMURAI holds PROMOTION_DRILL1 for free despite being MELEE
    and DRILL1 being ARCHER/SIEGE-only - isPromotionValid(DRILL1) is false
    for a Samurai, so isPromotionValid(DRILL2) is false too, even though the
    Samurai visibly HAS DRILL1. A version of this function that only checked
    "is DRILL1 held" (an earlier draft did exactly this) would wrongly call
    DRILL2 available. `_seen` guards the walk against a prereq cycle, which
    the stock file has never been observed to contain (mirroring the same
    guard pattern render_tree/_closure_block use for the tech DAG).
    """
    if _seen is None:
        _seen = set()
    if promotion_type in _seen:
        return False
    _seen.add(promotion_type)

    promotion = rules.promotions[promotion_type]
    if unit["combat_class"] is None:
        return False
    if unit["combat_class"] not in promotion["restricted_to_unit_combats"]:
        return False
    if unit["only_defensive"] and any(
        promotion[field] for field in _ONLY_DEFENSIVE_BLOCKED_FIELDS
    ):
        return False
    if unit["moves"] == 1 and promotion["blitz"]:
        return False
    cannot_deal_collateral = (
        not unit["collateral_damage"] or not unit["collateral_damage_limit"]
        or not unit["collateral_damage_max_units"])
    if cannot_deal_collateral and promotion["collateral_damage_change"]:
        return False
    if not unit["interception"] and promotion["intercept_change"]:
        return False

    prereq = promotion["prereq"]
    if prereq and not _promotion_valid_for_unit(rules, unit, prereq, _seen):
        return False
    prereq_or = promotion["prereq_or"]
    if prereq_or and not any(
        _promotion_valid_for_unit(rules, unit, p, _seen) for p in prereq_or
    ):
        return False
    return True


def _promotable_promotions(rules, unit_type, held, known):
    """PROMOTION_ keys this specific unit could take next, and why not for
    the rest - CyUnit.canAcquirePromotion(), reproduced field by field.

    `unit_type` is the UNIT_ type (rules.units' key); `held` is the set of
    PROMOTION_ keys already on the unit (units[].promotions - empty list
    still means level 1, nothing taken). Verified against
    CvGameCoreDLL/CvUnit.cpp:canAcquirePromotion and
    CvGameCoreUtils.cpp:isPromotionValid, both cited in REFERENCES.md:

      - Already held -> refused outright (isHasPromotion check).
      - PromotionPrereq / PromotionPrereqOr1+2 -> must already hold the
        required one, or at least one of the OR-alternatives.
      - TechPrereq -> must be known.
      - isLeader() promotions (Great General field promotions) are excluded
        outright - this function never models bLeader=true.
      - The candidate itself, AND every promotion in its prereq chain, must
        pass _promotion_valid_for_unit (combat class, only-defensive,
        blitz/collateral/intercept capability) - see that function for why
        the chain is re-checked rather than just "is it held".
      - bIgnoreTerrainCost blocks anything with iMoveDiscountChange, but that
        field is not parsed on the promotion side yet (out of scope: nothing
        in _FLAT_EFFECT_FIELDS covers it), so this ONE check is a documented
        no-op rather than silently wrong - flagged in view_promotable's OMITS.

    NOT modelled, and said explicitly rather than silently: StateReligionPrereq
    (state religion is not in schema/state.schema.json at all).
    getFreePromotions itself IS modelled, indirectly: a free promotion is
    already in `held` (granted at unit creation) so the "already holds it"
    refusal excludes it same as any held promotion, but its CHILDREN are not
    exempt from validity just because their parent was free - see
    _promotion_valid_for_unit's Samurai/DRILL1/DRILL2 example.

    Returns (available, blocked) - available a sorted list of PROMOTION_ keys,
    blocked a sorted list of (PROMOTION_ key, reason) for everything else in
    the file, so a caller can show why a promotion is absent rather than just
    that it is.
    """
    unit = rules.units.get(unit_type)

    available = []
    blocked = []
    for key, promotion in sorted(rules.promotions.items()):
        if key in held:
            blocked.append((key, "already held"))
            continue

        if promotion["is_leader"]:
            blocked.append((key, "Great General field promotion - not "
                                 "acquired through XP"))
            continue

        prereq = promotion["prereq"]
        if prereq and prereq not in held:
            blocked.append((key, "needs %s first" % prereq))
            continue
        prereq_or = promotion["prereq_or"]
        if prereq_or and not any(p in held for p in prereq_or):
            blocked.append((key, "needs one of %s first"
                           % " or ".join(prereq_or)))
            continue

        tech = promotion["tech"]
        if tech and tech not in known:
            blocked.append((key, "needs %s" % tech))
            continue

        if unit is None or unit["combat_class"] is None:
            blocked.append((key, "this unit has no combat class"))
            continue
        if unit["combat_class"] not in promotion["restricted_to_unit_combats"]:
            blocked.append((key, "not offered to %s" % unit["combat_class"]))
            continue

        if unit["only_defensive"] and any(
            promotion[field] for field in _ONLY_DEFENSIVE_BLOCKED_FIELDS
        ):
            blocked.append((key, "this unit can only defend"))
            continue

        if unit["moves"] == 1 and promotion["blitz"]:
            blocked.append((key, "this unit has only 1 move"))
            continue

        cannot_deal_collateral = (
            not unit["collateral_damage"] or not unit["collateral_damage_limit"]
            or not unit["collateral_damage_max_units"])
        if cannot_deal_collateral and promotion["collateral_damage_change"]:
            blocked.append((key, "this unit cannot deal collateral damage"))
            continue

        if not unit["interception"] and promotion["intercept_change"]:
            blocked.append((key, "this unit cannot intercept"))
            continue

        # Everything above is the candidate's OWN checks (kept inline so the
        # per-case reasons above stay specific: "not offered to X" reads
        # better than "prereq chain invalid"). What's left is the part those
        # inline checks cannot see - whether a HELD prerequisite this
        # promotion depends on would itself still be valid for this unit.
        # Only reachable via a free promotion (a normally-acquired prereq
        # already passed these same checks when it was taken), but the
        # engine does not special-case that, so neither does this.
        chain_ok = True
        if prereq and not _promotion_valid_for_unit(rules, unit, prereq):
            chain_ok = False
        elif prereq_or and not any(
            _promotion_valid_for_unit(rules, unit, p) for p in prereq_or
        ):
            chain_ok = False
        if not chain_ok:
            blocked.append((key, "held via a free promotion this unit "
                                 "would not otherwise qualify for"))
            continue

        available.append(key)
    return available, blocked


def view_promotable(rules, unit_id, state, show_known, max_depth, eligible=False):
    """One of your units' promotions, by engine id: the combined effect of
    everything it already holds, each one's own detail, and - with
    eligible=True - what it could take next.

    Takes an id rather than a UNIT_ type because eligibility depends on which
    promotions THIS unit already holds (units[].promotions), not on the type
    alone - two Scouts can be eligible for different things. `intel`'s
    garrison/field listing prints each unit's id next to it for exactly this.

    Held promotions render brief (_view_one_promotion(brief=True)): AVAILABLE
    TO and REQUIRES are both moot for something the unit already has - what it
    is offered to and what it needed no longer matter, only what it does.
    COMBINED EFFECTS leads rather than trails, because the usual question is
    "what does this unit fight like right now", which the total answers
    directly; the per-promotion breakdown underneath is for when that total
    needs explaining, not the first thing read.

    CAN TAKE NEXT / BLOCKED is opt-in (eligible=True) rather than always
    printed: "what does this unit have" is the common question and "what
    could it take next" a less frequent one, and BLOCKED alone lists every
    promotion in the file - real information (the loud majority-blocked case
    IS itself the answer to "why can't I give it a specific one") but not
    something to print by default when it usually will not be read.
    """
    unit = find_unit(state, unit_id)
    if unit is None:
        raise RulesError(
            "no unit with id %d in this state file. IDs are printed by "
            "run_history.py intel next to each unit, e.g. 'id 16385'."
            % unit_id)

    known = effective_known(state)
    held = sorted(unit.get("promotions") or [])

    out = []
    out.append("%s id %d" % (unit["type"], unit_id))

    if held:
        if len(held) > 1:
            out.append("")
            out.append("COMBINED EFFECTS - " + ", ".join(held))
            totals = _promotion_totals([rules.promotions[p] for p in held])
            if totals:
                out.append("  " + ("\n  ".join(totals)))
            else:
                out.append("  (no numeric effects parsed - see OMITS)")

        out.append("")
        out.append("ALREADY HAS")
        for i, promotion_type in enumerate(held):
            if i:
                out.append("")
            out.extend(_view_one_promotion(rules, promotion_type, state,
                                           show_known, max_depth, brief=True))
    else:
        out.append("")
        out.append("ALREADY HAS: (none)")

    if eligible:
        available, blocked = _promotable_promotions(
            rules, unit["type"], set(held), known)

        out.append("")
        out.append("=" * 60)
        out.append("")
        out.append("CAN TAKE NEXT")
        if available:
            for key in available:
                out.append("  %s" % key)
        else:
            out.append("  nothing right now")

        out.append("")
        out.append("BLOCKED")
        if blocked:
            for key, reason in blocked:
                out.append("  %-28s %s" % (key, reason))
        else:
            out.append("  nothing - every promotion in the file is available")

    out.append("")
    out.append("OMITS")
    if not eligible:
        out.append("  What this unit could take next - pass --eligible.")
    out.append("  Whether this unit's XP already funds a pick - `intel`'s garrison")
    out.append("  listing and units[].promotionsAvailable answer that; this only")
    out.append("  answers WHICH promotions the rules allow. Great General field")
    out.append("  promotions (isLeader promotions) and anything gated on state")
    out.append("  religion (not in the schema) are excluded outright rather than")
    out.append("  guessed at. iMoveDiscountChange is not a parsed promotion field,")
    out.append("  so a bIgnoreTerrainCost unit's gate against it is not enforced -")
    out.append("  flagged, not silently wrong.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


def view_promotion(rules, promotion_type, state, show_known, max_depth):
    """What a single PROMOTION_ key actually does, and what it takes.

    Mirrors view_unit's shape (effects, then prerequisites) because a
    promotion IS a unit-modifier bundle - the same reason parse_promotions
    reuses parse_units' parsing patterns. `units[].promotions` and
    `units[].promotionsAvailable` (schema increment 7) name WHICH promotions a
    unit has or could take; this answers what the name actually means, the
    join `intel`'s garrison listing deliberately does not make (see
    run_history._combat_note) - same division of labour as `unit`/`tech`
    already have with `intel`.

    Checking several promotions held together on one real unit, and what
    they add up to, is `promotion <state> --for-unit ID` (view_promotable) -
    it reads units[].promotions itself rather than asking the caller to
    type each name. An earlier draft of this function also took a list of
    TYPEs directly for that case; dropped once --for-unit existed, since a
    hypothetical combination not actually held by any unit was not a real
    question anyone asked, and it let COMBINED EFFECTS (_promotion_totals)
    live in exactly one place instead of two.
    """
    out = _view_one_promotion(rules, promotion_type, state, show_known, max_depth)
    out.append("")
    out.append("OMITS")
    out.append("  Which units currently have this (`intel`'s garrison listing names")
    out.append("  them) and combat odds against a specific enemy - the agent's call,")
    out.append("  not this tool's. State-religion prerequisites and leader-only")
    out.append("  promotions (Great General field promotions) are not resolved here.")
    out.append("  What several promotions add up to on one unit - `promotion <state>")
    out.append("  --for-unit ID` totals what that unit actually holds.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


def view_tech(rules, tech_type, state, show_known, max_depth):
    entry = rules.techs.get(tech_type)
    if entry is None:
        raise _not_found("tech", tech_type, rules.techs,
                         _relative(rules.tech_path, rules.xml_root),
                         "TECH_BRONZE_WORKING",
                         annotate=lambda t: t["era"] or "")

    known = effective_known(state)
    out = []
    status = _tech_status(tech_type, known, state)
    out.append("%s - %d beakers%s"
               % (tech_type, rules.cost(tech_type),
                  "" if status == "[NEED]" else "  " + status))
    out.append("  against %s" % state_summary(state))
    out.append("")
    out.append("  %s:%d" % (_relative(rules.tech_path, rules.xml_root), entry["line"]))
    out.append("  cost = base %d x speed %d%% x world %d%% x handicap %d%%"
               % (entry["cost"], rules.speed_pct, rules.world_pct, rules.handicap_pct))

    out.append("")
    if entry["and"]:
        out.append("NEEDS  (and-list - ALL required)")
        for parent in entry["and"]:
            out.append("  %-26s %s" % (parent, _tech_status(parent, known, state)))
    if entry["or"]:
        met = [b for b in entry["or"] if b in known]
        if met:
            # Satisfied: state which branch met it and stop. Listing the
            # alternatives with [NEED] beside them is how an unneeded tech gets
            # read as required.
            pending = any(b == researching(state) for b in met)
            out.append("NEEDS  (or-list - %s via %s)"
                       % ("SATISFIED ONCE RESEARCH COMPLETES" if pending
                          else "ALREADY MET", ", ".join(met)))
            for parent in met:
                out.append("  %-26s %s"
                           % (parent, _tech_status(parent, known, state)))
            others = [b for b in entry["or"] if b not in known]
            if others:
                out.append("  (alternative%s, not needed: %s)"
                           % ("" if len(others) == 1 else "s", ", ".join(others)))
        else:
            label = ("NEEDS  (or-list - ANY ONE suffices, not both)"
                     if len(entry["or"]) > 1 else "NEEDS")
            out.append(label)
            for parent in entry["or"]:
                out.append("  %-26s %s"
                           % (parent, _tech_status(parent, known, state)))
    if not entry["and"] and not entry["or"]:
        out.append("NEEDS  nothing - this is a tech-tree root")

    _closure_block(rules, tech_type, known, show_known, max_depth, out, state)

    found = rules.unlocked_by(tech_type)
    out.append("")
    out.append("UNLOCKS")
    if found:
        for category in ("units", "buildings", "civics", "projects",
                         "improvements", "worker actions", "feature work",
                         "resources revealed", "resources usable"):
            if category in found:
                items = found[category]
                out.append("  %-18s %s" % (category, items[0]))
                for item in items[1:]:
                    out.append("  %-18s %s" % ("", item))
    if entry["abilities"]:
        for ability in entry["abilities"]:
            out.append("  %-18s %s" % ("ability", ability))
    if entry["free_techs"]:
        out.append("  %-18s %d free tech%s on first discovery"
                   % ("bonus", entry["free_techs"],
                      "" if entry["free_techs"] == 1 else "s"))
    if entry["free_units"] and entry["free_units"] != "NONE":
        out.append("  %-18s free %s on first discovery"
                   % ("bonus", entry["free_units"]))
    if not found and not entry["abilities"]:
        out.append("  (nothing this tool resolves - see OMITS below)")

    # Founding a religion is a RACE, not a grant: the first team to the tech
    # founds it and everyone later gets nothing. Folding this into UNLOCKS
    # would state a guarantee the game does not make.
    religions = sorted(k for k, v in rules.religions.items()
                       if v.get("tech") == tech_type)
    if religions:
        out.append("")
        out.append("FOUNDS A RELIGION - IF YOU ARE FIRST")
        for religion in religions:
            out.append("  %s" % religion)
        out.append("  The first team to this tech founds it; later arrivals get")
        out.append("  nothing. Whether anyone has beaten you to it is not in the")
        out.append("  export - this is a race, not a reward.")

    out.append("")
    out.append("OMITS")
    missing = [name for name in
               ("buildings", "civics", "projects", "improvements", "builds",
                "bonuses", "religions")
               if name not in rules.sources]
    if missing:
        out.append("  NOT LOADED (file absent from this install): %s"
                   % ", ".join(missing))
        out.append("  Those categories are missing from UNLOCKS above, not empty.")
    out.append("  Corporations, espionage, promotions, great-person effects, and")
    out.append("  anything the SDK implements without an XML row.")
    out.append("  Unit and building hammer costs are base XML values scaled by game")
    out.append("  speed only - unlike research, no handicap multiplier applies.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


def _building_effects(building):
    """Field-derived effects as English sentences, in a fixed order.

    Extracted from view_building so the translation of fields to prose can be
    tested on its own - it is the part most likely to be wrong (a draft read a
    culture value as gold) and the part a new field extends.
    """
    effects = []
    if building["health"]:
        effects.append("%+d health" % building["health"])
    if building["happiness"]:
        effects.append("%+d happiness" % building["happiness"])
    if building["great_people"]:
        effects.append("%+d great people points per turn" % building["great_people"])
    if building["great_person"] and building["great_person"] != "NONE":
        effects.append("great person born here is more likely to be %s"
                       % building["great_person"])
    for domain, amount in building["free_experience"]:
        where = "" if not domain or domain == "NONE" else " (%s)" % domain
        effects.append("+%d experience to new units built here%s" % (amount, where))
    for name, value in building["commerce_changes"]:
        effects.append("%+d %s per turn" % (value, _plain(name)))
    for name, value in building["commerce_modifiers"]:
        effects.append("%+d%% %s in this city" % (value, _plain(name)))
    for name, value in building["yield_changes"]:
        effects.append("%+d %s per turn" % (value, _plain(name)))
    for name, value in building["yield_modifiers"]:
        effects.append("%+d%% %s in this city" % (value, _plain(name)))
    if building["team_share"]:
        effects.append("shared with your whole team")
    return effects


def _city_build_turns(cost, state, building=None):
    """`~5 turns in Lisbon (12 hpt), ~25 in Oporto (2 hpt)`.

    Per-city because production is wildly uneven early: in the baseline run at
    t40 the same 50-hammer building is 5 turns in Lisbon and 25 in Oporto, and
    that gap decides the answer. Same extrapolation caveat as research turns -
    productionPerTurn carries one-off overflow the turn after a build finishes,
    so it is not a steady-state rate.

    `building` excludes cities the site gates rule out. Without it the
    Lighthouse printed `~5 turns in Lisbon` directly above `city must be
    coastal`, with Lisbon not coastal - two lines of one block contradicting
    each other, and nothing in the output able to catch it. Excluded cities are
    NAMED rather than silently dropped: a city missing from the list with no
    explanation reads as a data problem, and the reason is the actionable part.
    """
    parts = []
    excluded = []
    for city in sorted(state.get("cities") or [],
                       key=lambda c: -(c.get("productionPerTurn") or 0)):
        name = city.get("name", "?")
        if building is not None:
            if building.get("water") and not city.get("coastal"):
                excluded.append("%s is not coastal" % name)
                continue
            if building.get("river") and not _city_on_river(city, state):
                excluded.append("%s is not on a river" % name)
                continue
        rate = city.get("productionPerTurn") or 0
        turns = turns_estimate(cost, rate)
        if turns is None:
            parts.append("%s cannot build (0 hpt)" % name)
        else:
            parts.append("~%d turns in %s (%d hpt)" % (turns, name, rate))
    if not parts and excluded:
        parts.append("no city of yours can build this")
    for reason in excluded:
        parts.append("excluded: %s" % reason)
    return parts


def _gate_summary(state, passes):
    """` - yes: Oporto; no: Lisbon` for a per-city site gate."""
    yes, no = [], []
    for city in state.get("cities") or []:
        (yes if passes(city) else no).append(city.get("name", "?"))
    if not yes and not no:
        return ""
    parts = []
    if yes:
        parts.append("yes: %s" % ", ".join(sorted(yes)))
    if no:
        parts.append("no: %s" % ", ".join(sorted(no)))
    return " - " + "; ".join(parts)


def view_building(rules, building_type, state, show_known, max_depth):
    building = rules.buildings.get(building_type)
    if building is None:
        if not rules.buildings:
            raise RulesError(
                "CIV4BuildingInfos.xml did not load - cannot answer building "
                "questions on this install.")
        raise _not_found("building", building_type, rules.buildings,
                         _relative(rules.building_path, rules.xml_root),
                         "BUILDING_BARRACKS",
                         annotate=lambda b: "%d hammers" % b["cost"])

    known = effective_known(state)
    out = []
    out.append("%s - Beyond the Sword XML, against %s"
               % (building_type, state_summary(state)))
    out.append("")
    out.append("  %s:%d" % (_relative(rules.building_path, rules.xml_root),
                            building["line"]))

    # What kind of thing this is leads, because it changes the decision more
    # than any effect: "50 hammers, build everywhere" and "500 hammers, one per
    # world, possibly already lost" are different kinds of object.
    class_key = rules.class_of_building.get(building_type)
    class_entry = rules.building_classes.get(class_key) if class_key else None
    is_world_wonder = bool(class_entry and class_entry["max_global"] == 1)
    is_national = bool(class_entry and class_entry["max_player"] == 1
                       and not is_world_wonder)
    out.append("")
    if class_entry:
        out.append("  %s: iMaxGlobalInstances %d, iMaxPlayerInstances %d"
                   % (class_key, class_entry["max_global"],
                      class_entry["max_player"]))
    else:
        out.append("  building class not resolved - likely a unique replacement;")
        out.append("  wonder status below may be wrong, check the XML.")
    out.append("")
    if is_world_wonder:
        out.append("  WORLD WONDER - one in the entire world")
    elif is_national:
        out.append("  NATIONAL WONDER - one per player")
    else:
        out.append("  ordinary building - one per city")

    cost = building["cost"] * rules.train_pct // 100
    if rules.train_pct == 100:
        out.append("  cost       %d hammers" % cost)
    else:
        out.append("  cost       %d hammers (base %d x game speed %d%%)"
                   % (cost, building["cost"], rules.train_pct))
    for line in _city_build_turns(cost, state, building):
        out.append("             %s" % line)

    # `wonders` answers half of what this block used to disclaim entirely. The
    # old text - "a rival may already be building this, the export cannot see
    # rival production" - was written before increment 5 and stayed true only
    # for a wonder nobody has finished. Once it is in wonders.built it is not a
    # race, it is over, and quoting a build time above is actively misleading.
    wonders = state.get("wonders") or {}
    if is_world_wonder and class_key in set(wonders.get("built") or []):
        out.append("")
        out.append("  ALREADY BUILT somewhere in the world - this is no longer")
        out.append("  available to you, and the turn estimates above are moot.")
        out.append("  The export does not say who built it or where.")
    elif is_national and class_key in set(wonders.get("national") or []):
        out.append("")
        out.append("  YOU ALREADY HAVE ONE - a national wonder is one per player,")
        out.append("  so the turn estimates above are moot.")
    elif is_world_wonder:
        out.append("")
        out.append("  Not built anywhere yet, but a rival may be building it now.")
        out.append("  The export cannot see rival production, so this is a race")
        out.append("  you cannot check. Losing it converts your hammers to gold.")

    out.append("")
    out.append("REQUIRES")
    tech = building["tech"]
    if tech and tech != "NONE":
        out.append("  tech       %-26s %s"
                   % (tech, _tech_status(tech, known, state)))
    else:
        out.append("  tech       (none - available from the start)")
    if building["prereq_buildings"]:
        out.append("  building   %s (in this city)"
                   % ", ".join(building["prereq_buildings"]))
    resources = list(building["prereq_bonuses"])
    if building["bonus"]:
        resources.append(building["bonus"])
    if resources:
        out.append("  resource   %s" % " or ".join(resources))
        for name in resources:
            out.extend("             " + line
                       for line in _resource_status(rules, name, state, known))
    # The gates that vary per city report which of yours pass, since "must be
    # coastal" is a rule and "Lisbon is not" is the answer.
    if building["water"]:
        out.append("  city       must be coastal%s"
                   % _gate_summary(state, lambda c: bool(c.get("coastal"))))
    if building["river"]:
        out.append("  city       must be on a river%s"
                   % _gate_summary(state, lambda c: _city_on_river(c, state)))

    if tech and tech != "NONE" and tech not in known:
        _closure_block(rules, tech, known, show_known, max_depth, out, state)

    effects = _building_effects(building)

    out.append("")
    out.append("EFFECTS")
    if effects:
        for effect in effects:
            out.append("  %s" % effect)
    else:
        out.append("  none in the data fields - see the game's own summary below")

    # The game's own one-liner. It is the only place an SDK-implemented effect
    # is written down at all: the Pyramids' "access all Government civics" has
    # no data field anywhere, and this text is how the game itself states it.
    # Kept separate from EFFECTS because it is ADVICE COPY, not a spec - it
    # emphasises what the designers thought mattered and silently omits real
    # numbers (the Pyramids' +6 culture and team-sharing appear only above).
    strategy = rules.strategy.get(building["strategy_key"] or "")
    if strategy:
        out.append("")
        out.append("THE GAME'S OWN SUMMARY")
        for line in _wrap(strategy, 68):
            out.append("  %s" % line)

    if building["obsolete"] and building["obsolete"] != "NONE":
        out.append("")
        out.append("OBSOLETE WITH  %s" % building["obsolete"])

    # The honesty block. Without it a complete-looking EFFECTS list invites the
    # conclusion that a wonder does nothing else - the same authoritative-with-
    # a-hole failure that made the units-only UNLOCKS block actively harmful.
    # BUILDING_PYRAMID is the clearest case: its best-known effect (any civic
    # regardless of tech) has no XML field at all and lives in the SDK.
    out.append("")
    out.append("CAVEAT - THE EFFECTS LIST IS NOT EXHAUSTIVE")
    out.append("  Many building effects - especially wonders' signature abilities -")
    out.append("  are implemented in the SDK with no data field at all. EFFECTS reads")
    if strategy:
        out.append("  fields only, which is why the summary above is printed beside it:")
        out.append("  it is the game's own wording and catches what no field carries.")
        out.append("  But it is advice copy, not a spec - it can omit real numbers too.")
    else:
        out.append("  fields only, and this building has no strategy text to fall back")
        out.append("  on, so the list above may be the smaller half of the story.")
    out.append("  An effect missing from EFFECTS is NOT evidence the building lacks")
    out.append("  it. The in-game Civilopedia has the authoritative text.")

    out.append("")
    out.append("OMITS")
    out.append("  Espionage, culture-level gating, defence and bombard values, AI")
    out.append("  weighting, art and sound.")
    out.append("  Whether any of your cities can actually build it right now -")
    out.append("  that is per-city and depends on what each already has.")
    out.append("  Hammer costs scale with game speed only, not difficulty. Turn")
    out.append("  figures extrapolate current output and are not a schedule.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


def _availability_rows(entries, blockers_of, cost_of, rate_of, distance_of=None,
                       horizon=NEAR_TECH_HORIZON):
    """Rows as (type, cost, turns, blockers, folded), alphabetical, plus a far
    count.

    `rate_of(key)` returns (hammers_per_turn, folded) so a row can be priced at
    its own rate: a bFood unit is built partly from the city's food surplus, so
    a Settler and a Barracks in the same city do not progress at the same
    speed.

    Alphabetical is deliberate and is the no-ranking guarantee in code: cost
    order or available-first would both be an opinion about what to build, and
    this tool's line is that the list is derived, not selected.

    Blocked rows are kept only while they are near enough to act on. Listing
    every blocked entry was the first implementation and it was unusable: 453
    lines at t43, in which UNIT_CHARIOT sat between an Airship and an Artillery
    piece. The cut is on tech distance rather than on a count, because "one
    tech away" is a fact about the game rather than a page size - and it is
    exactly the set that answers "what am I about to unlock", which is the
    question behind switching production. The far ones are counted, never
    silently dropped.
    """
    rows = []
    far = 0
    for key in sorted(entries):
        blockers = blockers_of(key)
        if blockers and any(b.startswith(OUT_OF_SCOPE) for b in blockers):
            # Corporation and religion gates are tech-open, so the tech horizon
            # never reaches them: at t43 they were 14 of 24 surviving rows, all
            # of them eras away. Counted with the far ones rather than given a
            # third category, since the reader's question is the same - "not
            # now, and not something I am about to unlock".
            far += 1
            continue
        if blockers and distance_of is not None:
            distance = distance_of(key)
            if distance is not None and distance > horizon:
                far += 1
                continue
        cost = cost_of(key)
        row_rate, folded = rate_of(key)
        turns = turns_estimate(cost, row_rate) if not blockers else None
        rows.append((key, cost, turns, blockers, folded))
    return rows, far


def _render_rows(out, rows):
    if not rows:
        out.append("  (none)")
        return
    for key, cost, turns, blockers, folded in rows:
        # `+food` marks an estimate that assumes the city stops growing: a
        # bFood build eats the whole surplus. The trade is the reader's, so it
        # is labelled rather than footnoted away. "optimistic" is the reverse
        # case - the rate currently carries food this build would not get.
        # The "optimistic" case applies to every ordinary row at once, so it is
        # stated once in the section header rather than repeated on 30 lines.
        suffix = " (+food, growth stops)" if folded is True else ""
        if blockers:
            out.append("  %-32s %4d  BLOCKED" % (key, cost))
            for blocker in blockers:
                out.append("  %-32s       %s" % ("", blocker))
        elif turns is None:
            out.append("  %-32s %4d  available (0 hpt - cannot progress)" % (key, cost))
        else:
            out.append("  %-32s %4d  available, ~%d turns%s"
                       % (key, cost, turns, suffix))


def view_city(rules, city_name, state):
    """What this city can build now, and what is blocking the rest.

    The list is derived, not selected: given tech, connected resources,
    coastal, buildings and the wonder state there is exactly one correct
    answer, and no parameter to tune. That is what separates it from the query
    language this folder refuses - there is nothing to filter toward. Blocked
    entries stay in the list with the blocker named, because a buildable-only
    list reads as a shortlist and cannot answer "what am I about to unlock",
    which is the question behind switching production.
    """
    if not city_name:
        raise RulesError("`city` needs a city name, e.g. Lisbon")
    city = find_city(state, city_name)
    if city is None:
        names = [c.get("name") or "?" for c in (state.get("cities") or [])]
        if not names:
            raise RulesError(
                "you have no cities in this state file - `city` needs one.")
        raise RulesError(
            "no city called %r in this state file.\nYour cities: %s"
            % (city_name, ", ".join(sorted(names))))

    # `city` is the one view that must NOT use effective_known. That set folds
    # in the tech being researched, which is right when costing a route - you
    # will have it before anything downstream matters - and wrong here, where
    # the question is what the city can start building THIS turn. At t43
    # Masonry sits at 4/124 with 7 turns left, and folding it in reported the
    # Pyramids, the Great Wall and Walls as available now.
    known = set((state.get("player") or {}).get("knownTechs") or [])
    in_progress = researching(state)
    # Horizon distance still uses the softer set: a tech already being paid for
    # is not "one tech away" on top of what is in the bank.
    horizon_known = effective_known(state)
    connected = city_connected_bonuses(city)
    other_units, other_buildings = _unique_sets(rules, state)
    wonders = state.get("wonders") or {}
    rate = city.get("productionPerTurn") or 0

    out = []
    out.append("%s (%d,%d) - what it can build, against %s"
               % (city.get("name"), city.get("x", -1), city.get("y", -1),
                  state_summary(state)))
    out.append("")
    out.append("CITY")
    out.append("  population %s" % city.get("population", "?"))
    out.append("  production %d hammers/turn" % rate)
    out.append("  coastal    %s" % ("yes" if city.get("coastal") else "no"))
    out.append("  on river   %s" % ("yes" if _city_on_river(city, state) else "no"))
    built_here = city.get("buildings") or []
    out.append("  buildings  %s" % (", ".join(sorted(built_here))
                                    if built_here else "(none)"))
    out.append("  resources  %s" % (", ".join(sorted(connected))
                                    if connected else "(none connected)"))
    producing = city.get("producing")
    if producing:
        out.append("  building   %s now" % producing)

    # How many techs away a thing is, for the horizon cut. Cached because the
    # closure walk runs once per blocked row and the same techs recur.
    distance_cache = {}

    def tech_distance(tech):
        if not tech or tech == "NONE" or tech in horizon_known:
            return 0
        if tech not in distance_cache:
            distance_cache[tech] = len(
                closure(rules, tech, horizon_known)) + 1
        return distance_cache[tech]

    # Trainable-shaped only: iCost <= 0 is animals and great people, which are
    # in the same file and are not things a city trains.
    unit_keys = [k for k, v in (rules.units or {}).items()
                 if v.get("cost", 0) > 0 and k not in other_units]
    unit_rows, far_units = _availability_rows(
        unit_keys,
        lambda k: unit_availability(rules, k, rules.units[k], city, state,
                                    known, connected, other_units,
                                    in_progress),
        lambda k: rules.units[k]["cost"] * rules.train_pct // 100,
        lambda k: food_build_rate(city, rules.units[k]),
        lambda k: tech_distance(rules.units[k].get("prereq_tech")),
    )
    # iCost -1 means a city never produces it: Academies, shrines and the like
    # are placed by a great person. Listing them as "available, ~0 turns" was
    # the first version and it invited building something uncommandable.
    building_keys = [k for k, v in (rules.buildings or {}).items()
                     if v.get("cost", 0) > 0 and k not in other_buildings]
    building_rows, far_buildings = _availability_rows(
        building_keys,
        lambda k: building_availability(rules, k, rules.buildings[k], city,
                                        state, known, connected,
                                        other_buildings, wonders,
                                        in_progress),
        lambda k: rules.buildings[k]["cost"] * rules.train_pct // 100,
        # A building is never a food build, but it hits the same trap in
        # reverse when the city is currently making a settler or worker.
        lambda k: food_build_rate(city, {}),
        lambda k: tech_distance(rules.buildings[k].get("tech")),
    )

    open_units = [r for r in unit_rows if not r[3]]
    open_buildings = [r for r in building_rows if not r[3]]

    # One line, not a suffix on every ordinary row: while a settler or worker is
    # in the queue the city's food is inside productionPerTurn, so every non-food
    # estimate below is a little fast.
    #
    # This only ever fires on a capture predating schema increment 6. With
    # `productionFromHammers` exported the split is exact, food_build_rate never
    # returns "optimistic", and the caveat correctly vanishes rather than being
    # printed beside numbers that no longer need it.
    optimistic = any(row[4] == "optimistic"
                     for row in unit_rows + building_rows)

    out.append("")
    out.append("UNITS - %d available now, %d one tech away"
               % (len(open_units), len(unit_rows) - len(open_units)))
    if optimistic:
        out.append("  %s is a food build, so this city's %d hpt currently"
                   % (city.get("producing"), rate))
        out.append("  includes its food surplus. Estimates for anything else")
        out.append("  below are therefore a little optimistic.")
    _render_rows(out, unit_rows)
    if far_units:
        out.append("  ... and %d further off, not listed (more than %d tech away)"
                   % (far_units, NEAR_TECH_HORIZON))

    out.append("")
    out.append("BUILDINGS - %d available now, %d one tech away"
               % (len(open_buildings), len(building_rows) - len(open_buildings)))
    _render_rows(out, building_rows)
    if far_buildings:
        out.append("  ... and %d further off, not listed (more than %d tech away)"
                   % (far_buildings, NEAR_TECH_HORIZON))

    out.append("")
    out.append("HOW TO READ THIS")
    out.append("  Cost is hammers, scaled for game speed. Turns extrapolate this")
    out.append("  city's CURRENT %d hpt, which moves as it grows - not a schedule." % rate)
    out.append("  Rows are alphabetical and NOT ranked: which of these to build is")
    out.append("  the judgement this tool does not make.")
    out.append("  Blocked rows stay listed with the reason, so a blocker you are")
    out.append("  about to clear is visible before you clear it. Only things")
    out.append("  within %d tech are listed; the rest are counted, not shown."
               % NEAR_TECH_HORIZON)
    out.append("  For the full picture on any row - effects, prerequisites, the")
    out.append("  game's own summary - run `rules.py unit|building TYPE <state>`.")

    out.append("")
    out.append("THIS OMITS")
    out.append("  Whether a rival is already building a world wonder - the export")
    out.append("  cannot see rival production, so an unbuilt wonder is still a race.")
    out.append("  Corporations and espionage, out of scope for now. What a specific")
    out.append("  unit's promotions do - `rules.py promotion`.")
    out.append("  Anything the engine gates in C++ with no data field behind it.")
    if not rules.civilizations:
        out.append("  CIV4CivilizationInfos.xml did not load, so other civs' unique")
        out.append("  units and buildings are NOT filtered out of these lists.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


GOODY_IMPROVEMENT = "IMPROVEMENT_GOODY_HUT"


def plot_distance(state, a, b):
    """The engine's `plotDistance`, wrap-aware. NOT Chebyshev.

    `CvGameCoreUtils.h:144`: `max(dX, dY) + (min(dX, dY) / 2)`, over
    `xDistance`/`yDistance`, which fold the coordinate difference around the
    map when that axis wraps. The `+ min/2` term is the whole point and is
    easy to miss: at (3,3) the engine says 4 and Chebyshev says 3, and they
    diverge on every diagonal. Getting it wrong misjudges the one-city
    hostile radius exactly at its boundary, which is where it is asked.

    Deliberately implemented here rather than imported from `render_map`,
    whose `distance()` is a different metric on purpose - the city-founding
    rule it serves really is a square box scan (`CvPlayer.cpp:5005-5008`),
    so that is `stepDistance` and correct for its own use. Two metrics both
    called "distance" is the trap; each is named for what it actually is.
    """
    game = state.get("game") or {}
    width = game.get("mapWidth") or 0
    height = game.get("mapHeight") or 0
    dx = abs(a[0] - b[0])
    if game.get("wrapX") and width:
        dx = min(dx, width - dx)
    dy = abs(a[1] - b[1])
    if game.get("wrapY") and height:
        dy = min(dy, height - dy)
    return max(dx, dy) + min(dx, dy) // 2


def find_goody_huts(state):
    """Every revealed goody hut on the map, as (x, y).

    The engine's own `isRevealedGoody()` is `improvementInfo(revealed
    improvement).isGoody()`, and `IMPROVEMENT_GOODY_HUT` is the only
    `bGoody` improvement in either tree. `map.tiles.improvement` is already
    the REVEALED getter, so this inherits the export's fog honesty: a hut in
    unexplored territory is simply absent, exactly as for the player.
    """
    hits = []
    for tile in (state.get("map") or {}).get("tiles") or []:
        if tile.get("improvement") == GOODY_IMPROVEMENT:
            hits.append((tile.get("x"), tile.get("y")))
    return sorted(hits)


def _unit_label(own):
    """How to name one of our own units in prose: type plus id."""
    return "%s (id %s)" % (own.get("type", "?"), own.get("id", "?"))


def _goody_eligibility(rules, goody, state, unit, own=None, hut=None):
    """Why this outcome cannot be drawn right now, or None if it can.

    A direct transcription of `CvPlayer::canReceiveGoody`, in source order, and
    deliberately only the clauses this tool can actually evaluate from a state
    file. Every clause that IS evaluated returns prose naming the gate; the
    ones that cannot be are listed in the view's OMITS rather than guessed.

    `unit` is the unit dict from the XML (not the state), or None for "no
    particular unit". None is NOT the same as an arbitrary unit: several
    clauses key off the unit that pops the hut, and the engine treats a NULL
    unit as failing them - but a hut is always popped BY something, so None
    here means "unit-dependent, not yet decided" and those clauses are reported
    as conditional rather than as hard exclusions.

    `own` is the same unit as the STATE exports it (id, damage, promotions), or
    None. It is what turns three of those conditionals into decided answers,
    because a unit TYPE cannot answer them: a healthy Warrior and a half-dead
    one are the same string. `hut` is the hut's own (x, y), which is never the
    unit's tile - a unit standing on a hut has already popped it.
    """
    game = state.get("game") or {}
    turn = game.get("gameTurn") or 0
    cities = state.get("cities") or []

    # iExperience: needs a promotable unit AND 10 elapsed turns. Only the turn
    # half is decidable - `promotionsAvailable` cannot stand in for
    # canAcquirePromotionAny(), so the rest is named in OMITS (see README).
    if goody["experience"] > 0 and turn < GOODY_EXPERIENCE_MIN_TURNS:
        return "not before turn %d" % GOODY_EXPERIENCE_MIN_TURNS

    # iDamagePrereq: the unit must ALREADY be hurt to at least this share of
    # its max HP. `damage` is exported as a percentage of health lost, which is
    # the same scale the engine compares against (maxHitPoints * prereq / 100),
    # so this is a direct comparison rather than a conversion.
    if goody["damage_prereq"] > 0:
        if own is not None:
            hurt = own.get("damage") or 0
            if hurt < goody["damage_prereq"]:
                return ("%s is at %d%% damage, needs %d%%"
                        % (_unit_label(own), hurt, goody["damage_prereq"]))
        else:
            # Without one of our units this is genuinely undecidable: a unit
            # TYPE says nothing about that unit's damage. Asserting an
            # exclusion the tool cannot see is the failure it exists to fix.
            return ("conditional: only if the popping unit is already at %d%% "
                    "damage" % goody["damage_prereq"])

    # bBad: THE clause this subcommand exists for. Note the engine's own
    # ordering - `pUnit == NULL || isNoBadGoodies()` - so immunity is a
    # property of the popping unit, nothing else.
    if goody["bad"] and unit is not None and unit.get("no_bad_goodies"):
        return "%s can never draw a hostile result" % unit["type"]

    # UnitClass: a free unit. If that unit is a combat unit and not
    # only-defensive, it is withheld for the first 20 turns (and in every
    # multiplayer game, which the export cannot see - see OMITS).
    if goody["unit_class"]:
        granted = _unit_of_class(rules, goody["unit_class"])
        if granted is None:
            return "no unit of %s for this civ" % goody["unit_class"]
        if (granted["strength"] > 0 and not granted["only_defensive"]
                and turn < GOODY_COMBAT_UNIT_MIN_TURNS):
            return "combat unit, not before turn %d" % GOODY_COMBAT_UNIT_MIN_TURNS

    # BarbarianClass: the hostile outcomes.
    if goody["barb_class"]:
        if "GAMEOPTION_NO_BARBARIANS" in (game.get("options") or []):
            return "GAMEOPTION_NO_BARBARIANS is on"
        # Both of these are genuine engine protections and both are temporary.
        # The second one ENDS when you found your second city, which is the
        # opposite of what a player would assume.
        if not cities:
            return "you have no cities yet"
        if len(cities) == 1:
            radius = GOODY_BARB_SAFE_RADIUS_AT_ONE_CITY - len(cities)
            if hut is None:
                return ("conditional: blocked within %d tiles of your only city"
                        % radius)
            # Decided, given the hut's own position. The engine measures from
            # the HUT, not from the popping unit (`canReceiveGoody` takes the
            # plot), so this needs the target tile rather than where the unit
            # is standing - and `findCity` is nearest-own-city, hence min().
            city = min(cities, key=lambda c: plot_distance(
                state, hut, (c.get("x"), c.get("y"))))
            gap = plot_distance(state, hut, (city.get("x"), city.get("y")))
            if gap <= radius:
                return ("hut is %d tile%s from %s, your only city (blocked "
                        "within %d)" % (gap, "" if gap == 1 else "s",
                                        city.get("name", "?"), radius))
    return None


def _unit_of_class(rules, unit_class):
    """The unit this civ actually gets for a unit class, unique or default.

    The engine reads `CivilizationInfo.getCivilizationUnits(class)`, which is
    the civ's unique when it has one and the class default otherwise. Without
    the civilization file loaded this falls back to any unit of the class,
    which is right for every civ that has no unique in it.
    """
    candidates = [u for u in rules.units.values()
                  if u.get("unit_class") == unit_class]
    if not candidates:
        return None
    for unit in candidates:
        if not _is_unique_unit(rules, unit["type"]):
            return unit
    return candidates[0]


def _is_unique_unit(rules, unit_type):
    """True if some civ names this unit as its replacement for a class.

    `units` maps class -> unit type, so this tests the VALUES. Reading the keys
    instead silently answers "is this a class", which is never true of a unit
    type and would make every unit look like the class default.
    """
    for entry in rules.civilizations.values():
        if unit_type in (entry.get("units") or {}).values():
            return True
    return False


def goody_distribution(rules, handicap_entry, state, unit, own=None, hut=None):
    """The draw table, split into what can and cannot be drawn right now.

    Returns (rows, eligible_total, table_size). Each row is a dict carrying the
    goody type, its multiplicity in the 20-entry table, its share of the draw,
    and either None or the reason it cannot come up.

    The share is over the WHOLE table, not over the eligible subset, because
    that is what the engine actually rolls; the eligible entries' shares
    therefore sum to less than 100% and the shortfall is the re-roll. See
    NUM_DO_GOODY_ATTEMPTS for why that shortfall is a real outcome.
    """
    table = handicap_entry.get("goodies") or []
    counts = {}
    for key in table:
        counts[key] = counts.get(key, 0) + 1

    rows = []
    eligible = 0
    for key in sorted(counts):
        goody = rules.goodies.get(key)
        # An outcome named by the handicap but missing from GoodyInfo.xml can
        # only mean the file did not load or a mod diverged. Reported, never
        # silently dropped - a missing row understates the hostile share.
        blocked = ("not in %s" % os.path.basename(GOODY_FILE) if goody is None
                   else _goody_eligibility(rules, goody, state, unit, own, hut))
        conditional = bool(blocked) and blocked.startswith("conditional:")
        if not blocked or conditional:
            eligible += counts[key]
        rows.append({
            "type": key,
            "count": counts[key],
            "goody": goody,
            "blocked": None if conditional else blocked,
            "conditional": blocked[len("conditional: "):] if conditional else None,
        })
    return rows, eligible, len(table)


def _goody_effect(goody):
    """One line saying what the outcome actually gives you."""
    if goody is None:
        return "?"
    parts = []
    if goody["gold"] or goody["gold_rand1"] or goody["gold_rand2"]:
        low = goody["gold"]
        high = goody["gold"] + max(goody["gold_rand1"] - 1, 0) \
            + max(goody["gold_rand2"] - 1, 0)
        parts.append("%d-%d gold" % (low, high))
    if goody["tech"]:
        parts.append("a free tech (any you could research now)")
    if goody["experience"]:
        parts.append("%d experience to the popping unit" % goody["experience"])
    if goody["healing"]:
        parts.append("heals %d%% damage" % goody["healing"])
    if goody["map_range"]:
        parts.append("reveals map within %d tiles (%d%% per tile)"
                     % (goody["map_range"], goody["map_prob"]))
    if goody["unit_class"]:
        parts.append("a free %s" % goody["unit_class"])
    if goody["barb_class"]:
        # The FLOOR, not the probability. iBarbarianUnitProb reads as "chance
        # of trouble" and is not - the engine spawns iMinBarbarians regardless
        # and rolls only for further ones. Stating the guaranteed count is the
        # part a decision turns on; the per-extra-tile roll is left to the
        # OMITS note about where they land.
        parts.append("HOSTILE: %d+ %s adjacent, guaranteed"
                     % (goody["min_barbarians"], goody["barb_class"]))
    return "; ".join(parts) if parts else "nothing"


def view_goody(rules, handicap_type, state, unit_type=None, unit_id=None,
               at=None):
    """What a goody hut can produce for this game, and what it cannot.

    THE FAILURE THIS EXISTS TO PREVENT, from a live trial: the agent ran
    `rules.py handicap`, read `iBarbarianCreationTurnsElapsed = 25`, and told
    the player a hut was safe to pop for another 16 turns. That field governs
    MAP SPAWNS and gates nothing in the hut path - `CvPlayer::doGoody` never
    consults it. The hut produced a hostile warband that killed the player's
    only unit.

    The answer sharpens with what the caller supplies: nothing gives the
    difficulty's table with the unit- and position-dependent gates named as
    conditions; `unit_type` resolves hostile immunity; `unit_id` plus `at`
    resolve damage and the one-city radius too, deciding the rest.

    Presentation, not a verdict, at every level - it prints a percentage and
    never the words "safe" or "unsafe". Whether that percentage is worth the
    unit is the player's trade, not the tool's.
    """
    if handicap_type is None:
        handicap_type = state.get("game", {}).get("handicap")
    if handicap_type is None:
        raise RulesError("no handicap in the state file and none given")

    entry = rules.handicaps.get(handicap_type)
    if entry is None:
        raise _not_found("handicap", handicap_type, rules.handicaps,
                         _relative(rules.handicap_path, rules.xml_root),
                         "HANDICAP_NOBLE")

    # One of OUR units, by engine id, as `intel` prints it - the same shape as
    # `promotion --for-unit`. It resolves its own TYPE, so passing both is a
    # contradiction waiting to happen rather than a convenience.
    own = None
    if unit_id is not None:
        own = find_unit(state, unit_id)
        if own is None:
            ids = ", ".join(str(u.get("id")) for u in (state.get("units") or []))
            raise RulesError(
                "no unit with id %s in this state file.%s"
                % (unit_id, ("\nYour units: " + ids) if ids else
                   " You have no units in it."))
        unit_type = own.get("type")

    unit = None
    if unit_type:
        unit = rules.units.get(unit_type)
        if unit is None:
            raise _not_found("unit", unit_type, rules.units,
                             _relative(rules.unit_path, rules.xml_root),
                             "UNIT_SCOUT")

    huts = find_goody_huts(state)
    hut = None
    if at is not None:
        hut = at
        # A hut is a TARGET tile, never the unit's own: a unit standing on one
        # has already popped it. So this is validated against the map rather
        # than trusted - a coordinate typo would otherwise silently produce a
        # confident distance to the wrong tile.
        if hut not in huts:
            known = (", ".join("(%d,%d)" % h for h in huts) if huts
                     else "none are revealed in this state file")
            raise RulesError(
                "no revealed goody hut at (%d,%d).\nRevealed huts: %s"
                % (hut[0], hut[1], known))
        if own is not None and (own.get("x"), own.get("y")) == hut:
            raise RulesError(
                "%s is standing on the hut at (%d,%d) - a unit on a hut has "
                "already popped it.\nPass the hut the unit is moving TO."
                % (_unit_label(own), hut[0], hut[1]))

    if not rules.goodies:
        raise RulesError(
            "%s did not load, so goody outcomes cannot be reported.\n"
            "It is VANILLA-ONLY - there is no Beyond the Sword copy - so a "
            "BTS-only search finds nothing." % GOODY_FILE)

    rows, eligible, size = goody_distribution(rules, entry, state, unit,
                                              own, hut)

    out = []
    out.append("%s - what a goody hut can produce" % handicap_type)
    out.append("  against %s" % state_summary(state))
    if own is not None:
        line = "  popped by %s at (%s,%s)" % (_unit_label(own), own.get("x"),
                                              own.get("y"))
        if hut is not None:
            steps = plot_distance(state, (own.get("x"), own.get("y")), hut)
            line += ", hut at (%d,%d), %d tile%s away" % (
                hut[0], hut[1], steps, "" if steps == 1 else "s")
        out.append(line)
        if hut is not None:
            # The one assumption a decided answer rests on, stated rather than
            # left implicit: the gates are evaluated for the board as it stands
            # now. Moving there is free, but founding a city on the way removes
            # the one-city protection this may just have applied.
            out.append("  assumes it pops from there, board as it stands.")
    else:
        if unit is not None:
            out.append("  popped by %s" % unit_type)
        if hut is not None:
            out.append("  hut at (%d,%d)" % hut)

    own_handicap = state.get("game", {}).get("handicap")
    if own_handicap and own_handicap != handicap_type:
        out.append("")
        out.append("  NOTE: this game is %s. The rules below are %s and are NOT"
                   % (own_handicap, handicap_type))
        out.append("  in effect - run without a TYPE for this game's own.")

    # The handicap block only - one line, matching every other view.
    #
    # CIV4GoodyInfo.xml is deliberately NOT cited, though it is the other half
    # of this view's data. A citation exists so the agent can go and read what
    # the tool did not print (AGENT_GUIDE rule 5's "grep the install directly"
    # escape hatch), and there is nothing left in that file to read: a
    # GoodyInfo block carries 19 tags and the OUTCOMES rows already render
    # every one that bears on a decision. The handicap block is the opposite -
    # 67 tags, of which this view touches one table - so a reader landing there
    # has somewhere to go.
    out.append("")
    out.append("  %s:%d"
               % (_relative(rules.handicap_path, rules.xml_root), entry["line"]))

    # The one piece of mechanism worth printing, above the table rather than in
    # a footnote: a trial read this field off `handicap`, called a hut safe for
    # 16 more turns, and lost its only unit. Everything else about how the roll
    # works was cut as derivation an agent does not act on.
    out.append("")
    out.append("  iBarbarianCreationTurnsElapsed does NOT gate huts - it governs")
    out.append("  map spawns only. A hut can turn hostile on turn 1.")

    hostile = [r for r in rows
               if r["goody"] and r["goody"]["bad"] and not r["blocked"]]
    out.append("")
    out.append("OUTCOMES")
    # Share only, no raw multiplicity: the share IS the count over the table
    # size, and the count is the half an agent cannot act on.
    for row in rows:
        share = 100.0 * row["count"] / size if size else 0.0
        marker = "!" if row["goody"] and row["goody"]["bad"] else " "
        detail = ("CANNOT: %s" % row["blocked"] if row["blocked"]
                  else _goody_effect(row["goody"]))
        out.append("%s %-26s %5.1f%%  %s"
                   % (marker, row["type"], share, detail))
        if row["conditional"]:
            out.append("  %-26s         %s" % ("", row["conditional"]))

    # Hostile alone: the only figure here that changes a decision. Every row's
    # renormalised share was measured and nine of ten moved under 1.5 points,
    # so printing them buried this number under arithmetic nobody acts on.
    hostile_count = sum(r["count"] for r in hostile)
    raw_share = 100.0 * hostile_count / size if size else 0.0
    real_share = 100.0 * hostile_count / eligible if eligible else 0.0
    # The `above N%` note only when the two genuinely differ - it explains why
    # the rows do not sum to this figure, which otherwise reads as a bug.
    out.append("")
    out.append("HOSTILE CHANCE  %.1f%%" % real_share)
    if eligible < size and real_share > raw_share:
        out.append("  above the %.1f%% the table shows: blocked rows are"
                   " re-drawn onto the rest." % raw_share)

    # The interaction the ROADMAP asked for by name: the distribution alone
    # never states it, and joining two subcommands by hand is what failed.
    # Stated once, phrased for the case in hand - an earlier version printed
    # the roster AND a branch about the named unit AND a re-run hint, which is
    # three sentences carrying one fact.
    immune = sorted(u["type"] for u in rules.units.values()
                    if u.get("no_bad_goodies"))
    out.append("")
    if not immune:
        out.append("NOTE: no unit in the loaded XML carries bNoBadGoodies,")
        out.append("  which is unexpected for vanilla BTS - check the install.")
    elif unit is not None and unit.get("no_bad_goodies"):
        out.append("%s carries bNoBadGoodies: the hostile rows are excluded"
                   % unit_type)
        out.append("  for it entirely, not merely unlikely.")
    else:
        # Named only when we know what the player actually has: suggesting a
        # Scout to someone with none is advice, not a lookup.
        available = sorted(set(
            u.get("type") for u in (state.get("units") or [])
            if (rules.units.get(u.get("type")) or {}).get("no_bad_goodies")))
        out.append("%s cannot draw a hostile result, on any difficulty or turn."
                   % " and ".join(immune))
        if available:
            out.append("  You have %s this turn - popping with one is zero risk."
                       % ", ".join(available))
        elif unit is None:
            out.append("  Pass --for-unit ID (or --popped-by TYPE) to price"
                       " a specific unit.")

    # Revealed huts are listed whenever the caller did not name one, because
    # this is the argument that decides the most and the coordinate is sitting
    # in the state file the caller already passed. An unlisted flag is a flag
    # nobody uses - the same reason the immunity above is printed unprompted.
    if hut is None and huts:
        out.append("")
        out.append("REVEALED HUTS  (--at X,Y decides the rows above)")
        for spot in huts:
            note = ""
            if own is not None:
                note = ("  %d tiles away"
                        % plot_distance(state, (own.get("x"), own.get("y")),
                                        spot))
            out.append("  (%d,%d)%s" % (spot[0], spot[1], note))

    out.append("")
    out.append("OMITS")
    # What is genuinely unavailable shrinks as the caller supplies more, and
    # the list has to shrink with it: an OMITS line naming something the view
    # just decided is the same authoritative-looking wrongness this subcommand
    # was built to remove, only inverted.
    if hut is None:
        out.append("  Whether a specific hut is inside the one-city radius"
                   " (--at X,Y).")
    if own is None:
        out.append("  How damaged the popping unit is, which gates healing"
                   " (--for-unit ID).")
    # canAcquirePromotionAny is never fully decidable even with a unit:
    # promotionsAvailable counts what banked XP funds, and zero does not mean
    # "cannot promote" - a fresh unit promotes fine once this goody grants XP.
    out.append("  Whether the unit can still promote, which gates"
               " GOODY_EXPERIENCE.")
    out.append("  Whether any goody tech is still researchable for you.")
    out.append("  Multiplayer, which withholds free combat units at any turn.")
    out.append("  Exactly where barbarians land - terrain around the hut can")
    out.append("  leave them fewer plots than the counts above suggest.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


def view_handicap(rules, handicap_type, state):
    if handicap_type is None:
        handicap_type = state.get("game", {}).get("handicap")
    if handicap_type is None:
        raise RulesError("no handicap in the state file and none given")

    entry = rules.handicaps.get(handicap_type)
    if entry is None:
        raise _not_found("handicap", handicap_type, rules.handicaps,
                         _relative(rules.handicap_path, rules.xml_root),
                         "HANDICAP_NOBLE")

    out = []
    out.append("%s - barbarian and animal rules" % handicap_type)
    out.append("  against %s" % state_summary(state))

    # An explicit type that is not this game's own is legitimate (comparing
    # difficulties) but the header then shows two handicaps, and the one being
    # reported is not the one in play. Say so rather than let the reader pick.
    own = state.get("game", {}).get("handicap")
    if own and own != handicap_type:
        out.append("")
        out.append("  NOTE: this game is %s. The rules below are %s and are NOT"
                   % (own, handicap_type))
        out.append("  in effect - run without a TYPE for this game's own.")
    out.append("")
    out.append("  %s:%d" % (_relative(rules.handicap_path, rules.xml_root), entry["line"]))

    out.append("")
    out.append("ANIMALS")
    for name, description in ANIMAL_FIELDS:
        out.append("  %-34s %5d   %s" % (name, entry[name], description))

    out.append("")
    out.append("BARBARIANS")
    for name, description in BARBARIAN_FIELDS:
        out.append("  %-34s %5d   %s" % (name, entry[name], description))

    out.append("")
    out.append("RESEARCH")
    out.append("  %-34s %5d   applied to every tech cost"
               % ("iResearchPercent", entry["iResearchPercent"]))

    out.append("")
    out.append("OMITS")
    out.append("  AI-only bonuses (iAI*) and the non-barbarian handicap fields -")
    out.append("  production, growth, maintenance, war weariness.")
    out.append("  Spawn counts are per-map-area rules, not schedules: this says what")
    out.append("  the rules are, not where or when anything will appear.")
    # The cross-reference is the fix for a specific live failure: a trial read
    # iBarbarianCreationTurnsElapsed off THIS block, concluded a goody hut was
    # safe for 16 more turns, and lost the player's only unit to it. That field
    # gates map spawns and nothing in the hut path, so the block above cannot
    # answer a hut question and must say so rather than look like it can.
    out.append("  Goody huts: the turn fields above DO NOT gate them - a hut can")
    out.append("  produce hostiles on turn 1. Run `rules.py goody` for that table.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


def _format_terms(terms):
    """The decomposition, as `2 grass +1 corn +2 farm-on-corn` per column.

    Printed alongside the total rather than instead of it. The trial this
    item exists to fix reported a bare wrong number with no working shown,
    and a bare RIGHT number is not much better - the reader cannot tell a
    correct answer from a plausible one. The terms are what make the
    invented Despotism penalty visible as an extra line that is not there.
    """
    lines = []
    for index, label in enumerate(YIELD_LABELS):
        parts = [(name, values[index]) for name, values in terms if values[index]]
        if not parts:
            continue
        rendered = []
        for position, (name, value) in enumerate(parts):
            if position == 0:
                rendered.append("%d %s" % (value, name))
            else:
                rendered.append("%s%d %s" % ("+" if value > 0 else "-",
                                             abs(value), name))
        lines.append((label, " ".join(rendered)))
    return lines


def _yield_total(values):
    """`3 food, 2 hammers` - zero columns dropped, all-zero rendered once."""
    parts = ["%d %s" % (value, YIELD_LABELS[index])
             for index, value in enumerate(values) if value]
    return ", ".join(parts) if parts else "nothing"


def view_improvement(rules, improvement_type, state, at=None):
    """What an improvement yields - in the abstract, or on one named tile.

    Two modes through one path deliberately. The static mode answers "what
    does a Farm do", which is the lookup `rules.py` never had; `--at X,Y`
    answers "what would it do HERE, and may I build it", which is the
    question the trial actually asked. Sharing the arithmetic is the point:
    a static table that disagreed with the tile answer would be worse than
    having neither.
    """
    known = effective_known(state)
    if at is not None:
        return _view_tile(rules, at, state, known, improvement_type)
    if not improvement_type:
        raise RulesError(
            "`improvement` needs a type (e.g. IMPROVEMENT_FARM) or --at X,Y")

    improvement = rules.improvements.get(improvement_type)
    if improvement is None:
        raise _not_found("improvement", improvement_type, rules.improvements,
                         _relative(rules.sources.get("improvements",
                                                     (None, None))[0],
                                   rules.xml_root),
                         "IMPROVEMENT_FARM")

    out = []
    out.append("%s" % improvement_type)
    out.append("  against %s" % state_summary(state))
    out.append("")

    build_key, tech = build_for(rules, improvement_type)
    if tech:
        out.append("TECH  %s %s   (via %s)"
                   % (tech, _tech_status(tech, known, state), build_key))
    elif build_key:
        out.append("TECH  none - %s is available from the start" % build_key)
    else:
        out.append("TECH  no worker action builds this")
    out.append("")

    out.append("YIELDS")
    own = improvement.get("yields")
    if own and any(own):
        out.append("  flat        %s" % _yield_total(own))
    else:
        # Worth stating rather than omitting: a Farm's food does NOT come
        # from a flat yield, and assuming it does is how the +2 Corn term
        # gets dropped.
        out.append("  flat        none - this improvement has no yield of its own")
    if improvement.get("irrigated") and any(improvement["irrigated"]):
        out.append("  irrigated   %s (fresh water)"
                   % _yield_total(improvement["irrigated"]))
    for entry in improvement.get("tech_yields") or []:
        if entry.get("yields") and any(entry["yields"]):
            out.append("  %s   %s %s" % (entry["tech"],
                                         _yield_total(entry["yields"]),
                                         _tech_status(entry["tech"], known, state)))

    structs = improvement.get("bonus_structs") or {}
    if structs:
        out.append("")
        out.append("ON A RESOURCE")
        out.append("  Each line is IN ADDITION to the resource's own yield and the")
        out.append("  terrain's. `makes valid` bypasses every terrain restriction below.")
        for bonus_key in sorted(structs):
            struct = structs[bonus_key]
            bonus_own = (rules.bonuses.get(bonus_key) or {}).get("yields")
            bits = []
            if struct.get("yields") and any(struct["yields"]):
                # _delta_text rather than a "+" prefix on _yield_total: a
                # mine on Gems is -1 hammers and +5 commerce, which the
                # prefix rendered as "+-1 hammers, 5 commerce" - wrong sign
                # on one term and a missing sign on the other.
                bits.append(_delta_text(struct["yields"]))
            else:
                bits.append("no extra yield")
            if bonus_own and any(bonus_own):
                bits.append("(resource itself: %s)" % _yield_total(bonus_own))
            if struct.get("makes_valid"):
                bits.append("[makes valid]")
            out.append("  %-24s %s" % (bonus_key, " ".join(bits)))

    out.append("")
    out.append("WHERE IT CAN GO")
    for line in _legality_prose(rules, improvement):
        out.append("  %s" % line)

    out.append("")
    out.append("OMITS")
    out.append("  What a tile ACTUALLY yields - run with --at X,Y for that, which")
    out.append("  joins terrain, resource, feature, river and your traits, and")
    out.append("  says whether you can build here at all.")
    out.append("  Worker-turns to build. A build that clears a feature costs the")
    out.append("  improvement's time PLUS the clearing time, charged as one job.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


def _legality_prose(rules, improvement):
    """The legality flags as sentences, in canHaveImprovement's own order."""
    lines = []
    if improvement.get("water"):
        lines.append("water tiles only")
    else:
        lines.append("land tiles only")
    terrains = sorted(k for k, v in (improvement.get("terrain_valid") or {}).items() if v)
    if terrains:
        lines.append("terrain: %s" % ", ".join(terrains))
    features = sorted(k for k, v in (improvement.get("feature_valid") or {}).items() if v)
    if features:
        lines.append("feature: %s" % ", ".join(features))
    if improvement.get("hills_makes_valid"):
        lines.append("hills make it valid")
    if improvement.get("fresh_water_makes_valid"):
        lines.append("fresh water makes it valid")
    if improvement.get("river_side_makes_valid"):
        lines.append("being beside a river makes it valid")
    if improvement.get("requires_flatlands"):
        lines.append("REQUIRES flatland (no hills)")
    if improvement.get("requires_feature"):
        lines.append("REQUIRES a feature on the tile")
    if improvement.get("requires_river_side"):
        lines.append("REQUIRES a river side")
    if improvement.get("requires_irrigation"):
        lines.append("REQUIRES irrigation - fresh water, or a chain from it")
    if improvement.get("no_fresh_water"):
        lines.append("NOT on fresh water")
    prereq = improvement.get("prereq_nature")
    if prereq and any(prereq):
        lines.append("bare tile must already make %s" % _yield_total(prereq))
    if not terrains and not features:
        lines.append("(no terrain list - validity comes from the flags above,")
        lines.append(" or from a resource that makes it valid)")
    return lines


def _view_tile(rules, at, state, known, only=None):
    """Every in-scope improvement for one tile, with the yield each would give.

    Iterates rather than taking an improvement argument: the question in play
    is "what should the worker do here", and answering it one improvement at
    a time puts the enumeration back on the caller. `only` narrows it when a
    specific improvement WAS named alongside --at.
    """
    x, y = at
    tile = find_tile(state, x, y)
    if tile is None:
        raise RulesError(
            "no tile at %d,%d in this state file.\n"
            "`map.tiles` holds every tile you have EVER revealed, so an absent "
            "one has never been scouted - there is nothing to report, not even "
            "its terrain. Check the coordinates against `render_map.py`, and "
            "remember y increases SOUTH." % (x, y))

    # The header carries only what bears on the decision. Route, and the
    # trait list on a leader with no yield trait, were both dropped after
    # reading real output: neither changes an improvement choice, and every
    # line here is one the reader pays for on every call.
    descriptors = [tile.get("terrain") or "?"]
    plot_type = tile.get("plotType")
    if plot_type:
        descriptors.append(plot_type[len("PLOT_"):].lower())
    for flag in ("feature", "bonus"):
        if tile.get(flag):
            descriptors.append(tile[flag])
    for flag, label in (("river", "river"), ("freshWater", "fresh water"),
                        ("lake", "lake")):
        if tile.get(flag):
            descriptors.append(label)

    owner = tile.get("owner")
    traits, owner_known = owner_traits(rules, state, owner)
    player = state.get("player") or {}
    foreign = owner is not None and owner != player.get("id")
    if foreign:
        who = _owner_label(state, owner)
        descriptors.append("owned by %s" % who
                           if owner_known else "owned by %s (unmet)" % who)

    out = []
    out.append("tile %d,%d - %s" % (x, y, ", ".join(descriptors)))
    if tile.get("improvement"):
        out.append("  has %s" % tile["improvement"])

    # The single most decision-relevant fact on a resource tile, and the one
    # the yield columns actively obscure: only ONE improvement connects the
    # resource to your trade network, and a rival option that scores better
    # on raw yield still leaves the resource unconnected.
    bonus_key = tile.get("bonus") or ""
    connector = connecting_improvement(rules, bonus_key, tile)
    if connector:
        note = "  %s is CONNECTED by %s" % (bonus_key, connector)
        if tile.get("improvement") == connector:
            note += " - already built"
        out.append(note)
        trade_tech = bonus_trade_tech(rules, bonus_key)
        if trade_tech and trade_tech not in known:
            # Distinct from the build's own tech and checked FIRST by the
            # engine, so it can block the connection even once the
            # improvement stands.
            out.append("  and needs %s %s before any city can work it"
                       % (trade_tech, _tech_status(trade_tech, known, state)))
    if not tile.get("visibleNow"):
        out.append("  NOT VISIBLE NOW - remembered terrain. Terrain and "
                   "resources do not change;")
        out.append("  a unit or a newly built improvement here would not show.")

    # "NOW" must mean what the tile yields TODAY, which on an already-improved
    # tile is not the bare-terrain figure. Getting this wrong understates the
    # status quo and makes every alternative look better than it is - the
    # precise shape of bad advice on a tile that is already working.
    #
    # A goody hut is an IMPROVEMENT in the data and emphatically not one
    # here: running it through improvement_yield clears the tile's feature
    # (huts do not set bRequiresFeature) and loses the forest's hammer.
    #
    # NOT_REAL_IMPROVEMENTS only - deliberately NOT the out-of-scope list.
    # A Windmill is a real improvement that this view merely declines to
    # OFFER; if one is standing on the tile it still produces yields, and
    # treating it as bare ground here would understate the tile.
    existing = tile.get("improvement")
    if existing in NOT_REAL_IMPROVEMENTS:
        existing = None
    if existing and existing in rules.improvements:
        current, current_terms = improvement_yield(
            rules, tile, existing, known, traits, state)
    else:
        current, current_terms = nature_terms(rules, tile, state, traits)
    out.append("")
    out.append("NOW           %s" % _yield_total(current))
    for label, rendered in _format_terms(current_terms):
        out.append("  %-9s %s" % (label, rendered))

    out.append("")
    candidates = [only] if only else list(workable_improvements(rules))
    rows = []
    for improvement_type in candidates:
        if rules.improvements.get(improvement_type) is None:
            continue
        why = (can_have_improvement(rules, tile, improvement_type, known)
               or build_blocker(rules, tile, improvement_type, state))
        if why is not None and only is None:
            continue
        total, terms = improvement_yield(rules, tile, improvement_type, known,
                                         traits, state)
        rows.append((improvement_type, why, total, terms))

    # The connecting improvement first. This is ordering, not ranking: it is
    # not a claim that it yields most (a Mine on Gems does not), but that it
    # is the only option that connects the resource at all - a different
    # kind of fact, and the one a reader scanning the list needs first.
    # Everything else stays alphabetical.
    if connector:
        rows.sort(key=lambda row: (row[0] != connector, row[0]))

    if not rows:
        # Say WHY nothing is listed. "Nothing can be built here" reads as a
        # property of the terrain, and on a foreign tile that is the wrong
        # conclusion entirely - the tile may be excellent and simply not
        # yours.
        if _impassable(tile):
            # Named specifically: a peak yields nothing and can never be
            # improved OR worked, which is a different fact from "no
            # improvement happens to fit this terrain".
            out.append("NOTHING BUILDABLE - impassable. This tile yields "
                       "nothing and cannot be worked.")
        elif foreign:
            out.append("NOTHING BUILDABLE - this tile is inside %s's borders."
                       % _owner_label(state, owner))
        elif tile.get("improvement"):
            out.append("NOTHING TO ADD - %s is already here and nothing else "
                       "in scope is legal." % tile["improvement"])
        else:
            out.append("NOTHING BUILDABLE - no improvement in scope is legal "
                       "on this terrain.")
    else:
        out.append("IF YOU BUILD")
        for improvement_type, why, total, terms in rows:
            out.append("")
            if why is not None:
                out.append("  %s - CANNOT: %s" % (improvement_type, why))
                continue
            # Against what the tile yields TODAY, so on an improved tile the
            # figure is the real trade of replacing what stands there.
            delta = [total[i] - current[i] for i in range(3)]
            out.append("  %-24s %s   (%s)%s"
                       % (improvement_type, _yield_total(total),
                          _delta_text(delta),
                          "   <- CONNECTS %s" % bonus_key
                          if improvement_type == connector else ""))
            # Only the columns the improvement actually moved. The unchanged
            # ones are already on the NOW line above and repeating them was
            # the single largest source of noise in the first output.
            for label, rendered in _format_terms(terms):
                if delta[YIELD_LABELS.index(label)]:
                    out.append("      %-9s %s" % (label, rendered))
            for line in _build_gates(rules, tile, improvement_type, known,
                                     state):
                out.append("      %s" % line)
            # The cost that no yield column shows. Losing a strategic
            # resource is not a yield trade at all - it can remove a whole
            # unit line from what the empire can build - so it is stated on
            # the row rather than left to be inferred from its absence.
            if connector and improvement_type != connector:
                if tile.get("improvement") == connector:
                    out.append("      LOSES    %s - replaces the %s that "
                               "connects it" % (bonus_key, connector))
                else:
                    out.append("      leaves   %s unconnected" % bonus_key)

    out.append("")
    out.append("OMITS")
    out.append("  Worker-turns to build. A build that clears a feature costs the")
    out.append("  improvement's time PLUS the clearing time, charged as one job.")
    out.append("  Irrigation chaining, so a dry tile fed by a chain of farms reads")
    out.append("  as illegal here. Cottage growth (the yield is a fresh Cottage).")
    out.append("  Out of scope: Lumbermill, Windmill, Watermill, Fort, Well,")
    out.append("  Offshore Platform, Forest Preserve.")
    out.append("  " + MOD_WARNING)
    return "\n".join(out)


def _delta_text(delta):
    """`+2 food, -1 hammers` against the unimproved tile."""
    parts = ["%s%d %s" % ("+" if value > 0 else "-", abs(value),
                          YIELD_LABELS[index])
             for index, value in enumerate(delta) if value]
    return ", ".join(parts) if parts else "no change"


def _owner_label(state, owner_id):
    for contact in state.get("contacts") or []:
        if contact.get("playerId") == owner_id:
            return "%s (player %s)" % (contact.get("leader") or "?", owner_id)
    return "player %s" % owner_id


def _build_gates(rules, tile, improvement_type, known, state):
    """Tech gates between "legal here" and "orderable now".

    Two separate gates and they come from different places, which is exactly
    what the trial failed to join: the improvement's own PrereqTech, and the
    per-feature tech inside the BUILD that clears whatever is standing here.
    A forested hill is a legal Mine site that still needs Bronze Working.
    """
    lines = []
    _build_key, tech = build_for(rules, improvement_type)
    if tech and tech not in known:
        lines.append("needs    %s %s" % (tech, _tech_status(tech, known, state)))
    clearing = clearing_requirement(rules, tile, improvement_type)
    if clearing:
        build_key, clear_tech, feature = clearing
        if clear_tech and clear_tech not in known:
            lines.append("needs    %s %s to clear %s first"
                         % (clear_tech, _tech_status(clear_tech, known, state),
                            feature))
        else:
            lines.append("clears   %s as part of the build" % feature)
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="Reverse and transitive rules lookups against the Civ IV XML.",
    )
    parser.add_argument(
        "subject",
        choices=("unit", "tech", "building", "promotion", "city", "handicap",
                 "goody", "improvement"),
        help="what to look up",
    )
    # `state` is the only required positional and always comes last, so
    # `handicap` can default its type from the state file without an optional
    # positional. An earlier version made TYPE optional: argparse then filled
    # right-to-left, so `rules.py unit UNIT_AXEMAN` bound the unit name to
    # `state` and reported "state file not found: UNIT_AXEMAN" - an error
    # naming the wrong argument entirely.
    parser.add_argument(
        "type_key", metavar="TYPE", nargs="?", default=None,
        help="e.g. UNIT_AXEMAN, TECH_MONARCHY, PROMOTION_COMBAT1, or a city "
             "name for `city`. Required for `unit`, `tech`, `building`, "
             "`promotion` and `city`; `handicap` and `goody` default to the "
             "state file's own. `promotion` also accepts --for-unit ID instead.",
    )
    parser.add_argument(
        "state",
        help="a turn's state JSON. Required: tech costs depend on game speed, "
             "world size and handicap, so a lookup without it is 1.0-4.5x wrong.",
    )
    parser.add_argument(
        "--show-known", action="store_true",
        help="include prerequisites you already have (hidden by default)",
    )
    parser.add_argument(
        "--depth", type=int, default=None,
        help="truncate the printed tree at this depth. Totals always cover the "
             "full walk - a partial total is a wrong number.",
    )
    parser.add_argument(
        "--for-unit", type=int, default=None, metavar="ID",
        help="one of your units, by engine id (as `intel` prints it). For "
             "`promotion`, in place of TYPE: prints their combined effect and "
             "each one's own detail. For `goody`, the unit popping the hut: "
             "resolves its damage and hostile immunity from the state file "
             "rather than from a type. Put this AFTER the state file, since "
             "argparse cannot always resolve a value-taking option sitting "
             "between TYPE and a required positional.",
    )
    parser.add_argument(
        "--eligible", action="store_true",
        help="with --for-unit: also list every promotion this unit could "
             "take next, and why not for the rest. Off by default - most "
             "questions about a unit are answered by what it already has.",
    )
    parser.add_argument(
        "--popped-by", default=None, metavar="UNIT",
        help="`goody` only: compute the table for this unit popping the hut, "
             "e.g. UNIT_SCOUT. The Scout and the Explorer cannot draw a "
             "hostile result at all, so the distribution genuinely differs "
             "rather than merely being annotated. Put this AFTER the state "
             "file, for the same argparse reason as --for-unit.",
    )
    parser.add_argument(
        "--at", default=None, metavar="X,Y",
        help="a tile, as `intel` and `render_map` print coordinates - remember "
             "y increases SOUTH. For `improvement`, the tile to report on: "
             "what it yields now and what each improvement would make it. For "
             "`goody`, the hut's own tile, never the unit's (a unit standing "
             "on a hut has already popped it), which decides the one-city "
             "hostile radius. Put this AFTER the state file.",
    )
    parser.add_argument("--config", default=None, help=argparse.SUPPRESS)
    return parser


def _parse_coordinate(raw):
    """Parse an `X,Y` argument into a tuple, or raise a RulesError.

    Its own function because the failure has to name the format: argparse's
    own type= error prints the raw value and the callable's name, which tells
    a caller who wrote `--at 62 28` nothing about the missing comma.
    """
    parts = raw.replace(" ", "").split(",")
    if len(parts) != 2:
        raise RulesError(
            "--at takes a hut's coordinates as X,Y (e.g. --at 62,28), not %r"
            % raw)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        raise RulesError(
            "--at takes two whole numbers as X,Y (e.g. --at 62,28), not %r"
            % raw)


def main(argv=None):
    # `--at 62 28` is the natural way to mistype `--at 62,28`, and argparse
    # reports it as "unrecognized arguments: 28" - which names neither the flag
    # nor the missing comma. Caught here because parse_args exits the process
    # before any of our own validation runs.
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra:
        if args.at is not None and len(extra) == 1 and extra[0].lstrip("-").isdigit():
            sys.stderr.write(
                "--at takes X,Y as ONE argument with a comma and no space: "
                "--at %s,%s\n" % (args.at, extra[0])
            )
            return 2
        parser.error("unrecognized arguments: %s" % " ".join(extra))

    type_key = args.type_key
    state_path = args.state

    if args.for_unit is not None and args.subject not in ("promotion", "goody"):
        sys.stderr.write("--for-unit only applies to `promotion` and `goody`\n")
        return 2
    # For `promotion` the id REPLACES the type; for `goody` the type is the
    # handicap, which the id says nothing about, so the pair is legitimate
    # there and only the unit-naming flags conflict.
    if (args.for_unit is not None and type_key is not None
            and args.subject == "promotion"):
        sys.stderr.write(
            "--for-unit already looks up a unit's promotions - it does not "
            "take a TYPE as well: %s\n" % type_key
        )
        return 2
    if args.eligible and args.for_unit is None:
        sys.stderr.write("--eligible only applies alongside --for-unit\n")
        return 2
    if args.popped_by is not None and args.subject != "goody":
        sys.stderr.write("--popped-by only applies to `goody`\n")
        return 2
    if args.at is not None and args.subject not in ("goody", "improvement"):
        sys.stderr.write("--at only applies to `goody` and `improvement`\n")
        return 2
    # Both name the popping unit, and --for-unit is strictly the better one.
    # Silently letting one win would answer about a different unit than the
    # caller named in the other.
    if args.popped_by is not None and args.for_unit is not None:
        sys.stderr.write(
            "--popped-by and --for-unit both name the popping unit - pass "
            "one. --for-unit ID is the stronger: it resolves the type too.\n"
        )
        return 2

    # With TYPE optional, argparse fills right-to-left when it is omitted:
    # `state` alone gets no TYPE. For `unit`/`tech`/`building`/`promotion`/
    # `city` that means a forgotten state file shows up as a type-shaped
    # value in `state`, so catch it here and name the real problem rather
    # than reporting "state file not found: UNIT_AXEMAN". `promotion
    # --for-unit ID` is the one case where a missing TYPE is correct on
    # purpose, so it skips this.
    if (args.subject in ("unit", "tech", "building", "promotion", "city",
                         "improvement")
            and type_key is None
            and not (args.subject == "promotion" and args.for_unit is not None)
            # `improvement --at X,Y` reports on the tile rather than one named
            # improvement, so a missing TYPE is correct there - same shape as
            # `promotion --for-unit`.
            and not (args.subject == "improvement" and args.at is not None)):
        # `city` takes a plain name rather than a TYPE key, so the "did they
        # forget the state file" test cannot key off a prefix - a bare word is
        # exactly what a city argument looks like. Anything not ending .json is
        # taken as the missing-state case.
        if args.subject == "city":
            looks_like_a_type = not state_path.lower().endswith(".json")
            example = state_path if looks_like_a_type else "Lisbon"
        else:
            looks_like_a_type = state_path.upper().startswith(
                ("UNIT_", "TECH_", "BUILDING_", "PROMOTION_", "IMPROVEMENT_"))
            example = (state_path if looks_like_a_type
                       else args.subject.upper() + "_...")
        sys.stderr.write(
            "`%s` needs both a %s and a state file:\n"
            "    python harness/rules.py %s %s <state.json>\n"
            % (args.subject, "city name" if args.subject == "city" else "TYPE",
               args.subject, example)
        )
        # The tile mode is the one worth reaching for, and a caller who typed
        # a bare `improvement` has probably not read far enough to know it
        # exists.
        if args.subject == "improvement":
            sys.stderr.write(
                "or ask about one tile, which is usually what you want:\n"
                "    python harness/rules.py improvement <state.json> --at X,Y\n"
            )
        return 2

    try:
        state = load_state(state_path)
        rules = Rules(resolve_xml_root(args.config), state.get("game", {}))

        if args.subject == "unit":
            if not type_key:
                raise RulesError("`unit` needs a type, e.g. UNIT_AXEMAN")
            text = view_unit(rules, type_key, state, args.show_known, args.depth)
        elif args.subject == "tech":
            if not type_key:
                raise RulesError("`tech` needs a type, e.g. TECH_MONARCHY")
            text = view_tech(rules, type_key, state, args.show_known, args.depth)
        elif args.subject == "building":
            if not type_key:
                raise RulesError("`building` needs a type, e.g. BUILDING_BARRACKS")
            text = view_building(rules, type_key, state, args.show_known,
                                 args.depth)
        elif args.subject == "promotion":
            if args.for_unit is not None:
                text = view_promotable(rules, args.for_unit, state,
                                       args.show_known, args.depth,
                                       eligible=args.eligible)
            else:
                if not type_key:
                    raise RulesError(
                        "`promotion` needs a type or --for-unit ID, "
                        "e.g. PROMOTION_COMBAT1")
                text = view_promotion(rules, type_key, state, args.show_known,
                                      args.depth)
        elif args.subject == "city":
            # No --show-known/--depth: `city` prints no tech tree, so neither
            # flag has anything to act on. Same shape as view_handicap.
            text = view_city(rules, type_key, state)
        elif args.subject == "goody":
            at = _parse_coordinate(args.at) if args.at is not None else None
            text = view_goody(rules, type_key, state, args.popped_by,
                              args.for_unit, at)
        elif args.subject == "improvement":
            at = _parse_coordinate(args.at) if args.at is not None else None
            text = view_improvement(rules, type_key, state, at)
        else:
            text = view_handicap(rules, type_key, state)
    except RulesError as exc:
        sys.stderr.write("%s\n" % exc)
        return 2

    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
