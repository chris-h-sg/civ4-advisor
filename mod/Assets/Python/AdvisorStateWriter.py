## AdvisorStateWriter
## State extraction, hand-rolled JSON serialization, and atomic file writes for the
## civ4-advisor mod. Python 2.4 has no `json` module, so this is a minimal serializer,
## scoped to the value types this mod deals in: dict, list, str/unicode, int, long,
## float, bool, None.
##
## All schema/extraction logic lives here rather than in CvCustomEventManager because
## this module is re-read from disk on every export - edits take effect next turn
## without restarting the game, which the event manager can't do at any price. Note
## that is NOT plain reload(), which silently does nothing in this interpreter; see
## CvCustomEventManager._refreshStateWriter.

import os
import time

from CvPythonExtensions import *

## Bumped only on breaking changes to the state format - see schema/state.schema.json.
SCHEMA_VERSION = 2

## Spaces per indent level in the output file. Pretty-printed rather than compact so
## a turn's export can be eyeballed against what the game UI actually shows.
INDENT = 2

## Milliseconds after which the map scan is loud about itself in PythonDbg.log. It
## warns and nothing more - a silently truncated map is indistinguishable from
## genuine fog of war, which is far worse than a slow export.
SLOW_MAP_MS = 250

## time.clock is the high-resolution wall clock on Windows/Python 2.4. It was removed
## in Python 3.8, so fall back for the sake of mod/tests, which runs this same source
## under Python 3.
try:
	_clock = time.clock
except AttributeError:
	_clock = time.time


def _localConfig(name, default):
	'''A setting from LocalConfig.py (gitignored, machine-specific - see
	LocalConfig.py.example), or default if the module or the setting is absent.

	A missing LocalConfig is a normal state, not an error: a machine without one
	should simply not export rather than crash.

	Two things not to "fix" here. The paths cannot be derived instead: the embedded
	interpreter reports module paths relative to its own Assets/Python search root
	regardless of which physical folder (base game vs. mod, even through the
	junction) supplied the file. And although THIS module is re-read from disk on
	every export, LocalConfig is not - it comes back from the import cache, so
	editing LocalConfig.py needs a game restart. reload() would not help; it
	silently does nothing in this interpreter (see
	CvCustomEventManager._refreshStateWriter).'''
	try:
		import LocalConfig
	except ImportError:
		return default
	return getattr(LocalConfig, name, default)


def getStateRootDir():
	'''Absolute path to write per-game state folders under, or None when this
	machine has no LocalConfig.'''
	return _localConfig('STATE_DIR', None)


def _gameFolderName(ctx):
	'''Folder name identifying one played game: leader + a synthetic game ID.

	The engine exposes no persistent per-game ID to Python, and there is no way
	to even READ one for free. Confirmed against the BTS SDK source: CyGame has
	no getMapRandSeed, and the CyRandom object CyGame.getMapRand() returns binds
	only get() (consumes the RNG stream - a mutation disguised as a query) and
	init() (SETS the seed rather than reading it). So _gameId() WRITES an ID
	instead, into CvGame.scriptData - a free-form string field the engine
	already serializes with the save (CvGame::read/write calls
	ReadString/WriteString on it), the standard modding mechanism for
	"remember something across turns and saves". See CLAUDE.md "Design
	decisions" for the full reasoning and the read-only alternative rejected in
	favor of this.'''
	leader = ctx.gc.getLeaderHeadInfo(ctx.player.getLeaderType()).getType()
	gameId = _gameId(ctx)
	return '%s_%s' % (leader, gameId)


def _gameId(ctx):
	'''CvGame.scriptData, generating and persisting one the first time it's empty.

	Once written, every later load of this save - including a full game
	restart - returns the same value, which is what makes the folder
	assignment stable for the life of the game rather than just the session.'''
	gameId = ctx.game.getScriptData()
	if not gameId:
		gameId = '%d' % int(time.time() * 1000)
		ctx.game.setScriptData(gameId)
	return gameId


def getTurnFilePath(gameTurn, playerId):
	'''Absolute path for one turn's export, or None when this machine has no
	LocalConfig.

	One file per turn, inside a per-game folder, so a full game's history is kept
	rather than overwritten every turn. Building a fresh _Context here (rather
	than reusing buildState's) is deliberate: the folder name only needs the
	leader and game ID, neither of which is fog-sensitive, so it is fine to
	resolve independently of _requireActivePlayer's guard.'''
	rootDir = getStateRootDir()
	if rootDir is None:
		return None
	ctx = _Context(playerId)
	folder = _gameFolderName(ctx)
	return os.path.join(rootDir, folder, 'turn_%04d.json' % gameTurn)


def _isTimingEnabled():
	'Whether to log per-section export timings. Off unless LocalConfig says otherwise.'
	return _localConfig('LOG_TIMINGS', False)


def _log(message):
	'''Write a line to Logs\\PythonDbg.log (needs LoggingEnabled=1 - see mod/README.md).

	Guarded end to end: logging is a diagnostic, and must never be the thing that
	breaks an export.'''
	try:
		import CvUtil
		CvUtil.pyPrint('civ4-advisor: %s' % message)
	except:
		pass


class _Context(object):
	'''The handful of Cy* objects every section builder needs, resolved once.

	Exists so that adding a section doesn't mean re-threading a different set of
	parameters through buildState and each builder - they all just take a ctx.'''

	def __init__(self, playerId):
		self.gc = CyGlobalContext()
		self.game = self.gc.getGame()
		self.cyMap = self.gc.getMap()
		self.playerId = playerId
		self.player = self.gc.getPlayer(playerId)
		# Some state (techs, plot visibility) is per-TEAM rather than per-player.
		# The plot getters want the raw team ID, not the CyTeam object.
		self.teamId = self.player.getTeam()
		self.team = self.gc.getTeam(self.teamId)
		# Memo slot for _strategicBonuses, filled on first use. Not resolved in
		# __init__ because getTurnFilePath builds a _Context purely to read the
		# leader and game ID, and would otherwise pay for a sweep of every unit
		# and building it never looks at.
		self._strategicBonuses = None

	def strategicBonuses(self):
		'''The memoized strategic-bonus set, or None if not yet computed.

		An accessor pair rather than callers touching ctx._strategicBonuses
		directly: the underscore says "not yours", and every other piece of
		state on _Context is read through a plain attribute, so a lone private
		one being poked from a module-level function is exactly the kind of
		thing that gets copied into the next builder that needs a cache.'''
		return self._strategicBonuses

	def setStrategicBonuses(self, strategic):
		self._strategicBonuses = strategic


def _requireActivePlayer(ctx):
	'''Refuse to export for anyone but the player the game considers active.

	Two getters this module needs silently answer for the ACTIVE team rather than
	for any team we can pass, with no API to ask about a specific player:
	CyPlot.calculateYield(bDisplay=True), and CyUnit.getVisualOwner(), which takes
	no team argument at all. Exporting for anyone else would quietly produce
	someone else's view of the map. The assumption holds in single player but
	nothing enforces it, so fail loudly; _exportState logs the traceback and
	writes no file.

	Checked here rather than in each affected builder: it is a property of the
	whole export, and a guard living in one section is one the next section
	silently does without - which is what nearly happened when the second
	active-team dependency arrived.'''
	activePlayerId = ctx.game.getActivePlayer()
	if ctx.playerId != activePlayerId:
		raise AssertionError(
			'refusing to export for player %d while player %d is active: tile yields'
			' and unit ownership would be the active player\'s, not this one\'s'
			% (ctx.playerId, activePlayerId))


def buildState(gameTurn, playerId, trigger):
	'''Build the state dict described by schema/state.schema.json.

	Every section is implemented, so output validates against the whole schema.
	An empty list here is honest and means what it says - a player who has met
	nobody writes `"contacts": []` - which is only true because no section is
	missing any more. During the incremental build, unimplemented sections were
	omitted precisely so that an empty list could not be mistaken for one.

	Omission still means something at the FIELD level: inside a tile, a unit or a
	foreign city, a missing field means "this field holds its documented default"
	(see _buildTile, _buildUnit, _buildForeignCity).'''
	ctx = _Context(playerId)
	_requireActivePlayer(ctx)
	started = _clock()
	state = {
		'meta': {
			'schemaVersion': SCHEMA_VERSION,
			'trigger': trigger,
		},
		'game': _buildGame(ctx, gameTurn),
		'player': _buildPlayer(ctx),
		'units': _buildUnits(ctx),
		'cities': _buildCities(ctx),
		'wonders': _buildWonders(ctx),
		'contacts': _buildContacts(ctx),
		'foreignUnits': _buildForeignUnits(ctx),
		'foreignCities': _buildForeignCities(ctx),
	}
	# Timed separately from everything else: this is the only section whose cost
	# scales with how much of the map the player has uncovered.
	mapStarted = _clock()
	state['map'] = _buildMap(ctx)
	_reportTimings(mapStarted - started, _clock() - mapStarted, len(state['map']['tiles']))
	_invertY(state, state['game']['mapHeight'])
	return state


def _invertY(state, mapHeight):
	'''Flip every exported y so 0 is the NORTH edge and y increases southward.

	The engine's own coordinate space is y-up (0,0 southwest), and every prior
	attempt to correct for that in the harness - documented convention, printed
	compass bearings - reduced but did not eliminate agents narrating north and
	south backwards while reading x correctly every time. That asymmetry (x
	never wrong, y always wrong) is the tell: y-up is not the convention a model
	brings from screen/image/matrix coordinates, and the mismatch gets silently
	normalised away below the level where the agent notices. This fixes the data
	to match the universal prior instead of asking every future reader to hold
	the correction in mind. See CLAUDE.md for the full reasoning, including why
	the field is still named `y` (not renamed to avoid re-teaching "standard x,y
	coordinates") and why SCHEMA_VERSION bumped to 2 as the substitute signal - a
	stale v1 file must fail loudly rather than render mirrored.

	Applied once, here, after every section is built, rather than inverting each
	`getY()` call at its many source call sites - every _build* function keeps
	reading and writing raw engine coordinates exactly as before; only the
	assembled document changes.'''
	def flip(y):
		return mapHeight - 1 - y

	for unit in state['units']:
		unit['y'] = flip(unit['y'])
		# A mission destination is a plot coordinate and must flip with every other
		# one. Missed here it would be the single worst place for the bug: a
		# mirrored destination reads as a plausible tile the unit is NOT walking
		# to, with the unit's own (correctly flipped) position beside it to make
		# the pair look internally consistent.
		mission = unit.get('mission')
		if mission and 'destination' in mission:
			mission['destination']['y'] = flip(mission['destination']['y'])
	for city in state['cities']:
		city['y'] = flip(city['y'])
		for tile in city['workedTiles']:
			tile[1] = flip(tile[1])
	for tile in state['map']['tiles']:
		tile['y'] = flip(tile['y'])
	for unit in state['foreignUnits']:
		unit['y'] = flip(unit['y'])
	for city in state['foreignCities']:
		city['y'] = flip(city['y'])


def _reportTimings(otherSeconds, mapSeconds, tileCount):
	'''Log how long the export took. Measuring is unconditional (two clock reads);
	only the reporting is conditional, so the slow-map warning can't be switched off
	by forgetting to set a config flag.'''
	mapMs = mapSeconds * 1000.0
	if mapMs >= SLOW_MAP_MS:
		_log('WARNING: map section took %d ms for %d tiles - the export blocks the game'
			% (int(mapMs), tileCount))
	if _isTimingEnabled():
		_log('timings: sections %d ms, map %d ms (%d tiles)'
			% (int(otherSeconds * 1000.0), int(mapMs), tileCount))


def _buildGame(ctx, gameTurn):
	'''Game-level context: the turn, plus the setup the player chose at creation.

	The rule for this section: export the setup PARAMETERS, never the generated
	map's statistics. Both are available, side by side on the same objects, and the
	difference is the whole point - a parameter is on the setup screen, a statistic
	answers a question the player has to explore to answer. REFERENCES.md "Game
	setup vs. generated-map statistics" lists which getters fall on which side; the
	forbidden ones raise in the test mocks so this stays enforced, not remembered.'''
	return {
		'gameTurn': gameTurn,
		# getTurnYear(n) rather than getGameTurnYear() so the year matches the turn
		# we're labelling this export with - at onEndGameTurn those differ by one
		# (see CvCustomEventManager.onEndGameTurn on the +1).
		'year': ctx.game.getTurnYear(gameTurn),
		# Era is the player's own current era, not the game's start era.
		'era': ctx.gc.getEraInfo(ctx.player.getCurrentEra()).getType(),
		'gameSpeed': ctx.gc.getGameSpeedInfo(ctx.game.getGameSpeedType()).getType(),
		# A map script filename ("Fractal", "Continents"), not an XML Type key -
		# there is nothing to join it against. Free-form by nature.
		'mapScript': ctx.cyMap.getMapScriptName(),
		'worldSize': ctx.gc.getWorldInfo(ctx.cyMap.getWorldSize()).getType(),
		'climate': ctx.gc.getClimateInfo(ctx.cyMap.getClimate()).getType(),
		'seaLevel': ctx.gc.getSeaLevelInfo(ctx.cyMap.getSeaLevel()).getType(),
		# The game's difficulty. Per-player handicaps can differ in multiplayer;
		# this is the setting chosen at setup, which is what the field means.
		'handicap': ctx.gc.getHandicapInfo(ctx.game.getHandicapType()).getType(),
		# How crowded the map is. countCivPlayersEverAlive, NOT countCivPlayersAlive:
		# "ever alive" is the number the game started with, so it stays constant and
		# cannot reveal that a civ has been destroyed before the player could know.
		# (It also excludes barbarians and colonial vassals - see REFERENCES.md.)
		'totalCivs': ctx.game.countCivPlayersEverAlive(),
		'options': _buildGameOptions(ctx),
		'victories': _buildVictories(ctx),
		'mapWidth': ctx.cyMap.getGridWidth(),
		'mapHeight': ctx.cyMap.getGridHeight(),
		# bool() because these come back from the C++ bindings as ints, and the
		# serializer would emit those as 0/1 rather than JSON true/false.
		'wrapX': bool(ctx.cyMap.isWrapX()),
		'wrapY': bool(ctx.cyMap.isWrapY()),
	}


def _enabledTypes(count, isEnabled, getInfo):
	'''XML Type keys of the first `count` infos for which isEnabled(i) is true.

	The game exposes several of these "ask per index, collect the ones that are on"
	lists - techs known, game options set, victories enabled - all with the same
	shape of loop over a getNumXInfos() count.'''
	types = []
	for i in range(count):
		if isEnabled(i):
			types.append(getInfo(i).getType())
	return types


def _buildGameOptions(ctx):
	'''Game options that are switched ON, in XML order; usually a short list or empty.

	Small field, outsized effect on our actual scope: GAMEOPTION_RAGING_BARBARIANS
	and GAMEOPTION_NO_BARBARIANS change turn 1-20 advice more than almost anything
	else in this file, and GAMEOPTION_AGGRESSIVE_AI changes how risky early scouting
	and thin defence are.'''
	return _enabledTypes(ctx.gc.getNumGameOptionInfos(), ctx.game.isOption,
		ctx.gc.getGameOptionInfo)


def _buildVictories(ctx):
	'Victory conditions enabled for this game, in XML order.'
	return _enabledTypes(ctx.gc.getNumVictoryInfos(), ctx.game.isVictoryValid,
		ctx.gc.getVictoryInfo)


def _buildPlayer(ctx):
	return {
		'id': ctx.playerId,
		'leader': ctx.gc.getLeaderHeadInfo(ctx.player.getLeaderType()).getType(),
		'civilization': ctx.gc.getCivilizationInfo(ctx.player.getCivilizationType()).getType(),
		'gold': ctx.player.getGold(),
		# Net treasury delta per turn, NOT total commerce - the research half of the
		# commerce split is beakersPerTurn below. See REFERENCES.md
		# "Research-rate mechanics" for why that isn't just raw slider commerce.
		'goldPerTurn': ctx.player.calculateGoldRate(),
		'beakersPerTurn': ctx.player.calculateResearchRate(TechTypes.NO_TECH),
		'score': ctx.game.getPlayerScore(ctx.playerId),
		'research': _buildResearch(ctx),
		'knownTechs': _buildKnownTechs(ctx),
		'civics': _buildCivics(ctx),
		'bonuses': _buildPlayerBonuses(ctx),
	}


## The three buckets bonuses are grouped into, in the order a player thinks about
## them. Keys of the `bonuses` objects on both player and city.
_BONUS_GROUPS = ('strategic', 'happiness', 'health')


def _bonusGroup(iBonus, info, strategic):
	'''Which of _BONUS_GROUPS a bonus belongs to, or None to leave it out entirely.

	`strategic` is the precomputed set of bonus indices something can be built
	with - see _strategicBonuses, which has to sweep every unit and building to
	work it out, so it is built once per export rather than per bonus.

	Health and happiness come straight off the XML: CIV4BonusInfos carries iHealth
	and iHappiness per bonus, and they are exactly what the city's health and
	happiness bars credit when the resource is connected (the base game's own
	advisor tests getBonusInfo(i).getHealth()/getHappiness() > 0 to decide which
	"resource connected" popup to show).

	STRATEGIC HAS NO XML FLAG - there is no bStrategic, and inventing one from a
	hardcoded name list would silently go wrong under any mod that adds resources.
	It is derived instead, from the only thing that actually makes a resource
	strategic: something needs it in order to be built. A bonus that unlocks no
	unit and no building is a trade good, however valuable.

	Precedence matters and is deliberate: a bonus that both unlocks units AND
	gives happiness (Ivory, Horses in some rulesets) is filed under strategic,
	because that is the fact that changes what you build. Each bonus appears in at
	most one group, so the three lists partition rather than overlap - a bonus in
	two places reads as two separate resources at a glance.

	Bonuses in none of the three (pure trade goods with no yield effect) return
	None and are omitted. They are still visible per-tile in map.tiles; what is
	being grouped here is the connected-resource summary, not the map.'''
	if iBonus in strategic:
		return 'strategic'
	# > 0 rather than != 0: a NEGATIVE iHealth exists (the engine allows it) and
	# listing such a bonus under "health" would read as a benefit.
	if info.getHappiness() > 0:
		return 'happiness'
	if info.getHealth() > 0:
		return 'health'
	return None


def _strategicBonuses(ctx):
	'''The set of bonus indices that some unit or building requires to be built.

	There is no bStrategic flag in the XML and no isStrategic() on CvBonusInfo -
	checked against the BUG Python API reference, which is also where the tempting
	shortcut dies: CvBonusInfo does NOT expose a reverse index (no
	getNumUnitsWithBonus / getNumBuildingsWithBonus), so a bonus cannot be asked
	what it unlocks. The relation only exists in the other direction, on each unit
	and building, hence this sweep.

	Deriving it beats a hardcoded name list, which would be wrong under any mod
	that adds resources and silently wrong under any that retunes them.

	Both prerequisite forms count, and they mean different things: getPrereqAndBonus
	is a single REQUIRED bonus, while getPrereqOrBonuses(i) is an array of
	alternatives, any one of which suffices (the Spearman's Bronze/Iron/Horse). For
	deciding "is this resource strategic" either form qualifies it. The array is
	fixed-length, sized by the global defines rather than a hardcoded 4, and its
	unused slots hold NO_BONUS.

	Cost is numUnits + numBuildings times a handful of calls, once per export -
	independent of map size, and dwarfed by the map scan. Memoized on the context
	because _buildBonusGroups runs once per city as well as once for the player,
	and the answer is the same every time (it depends only on the XML rules).'''
	cached = ctx.strategicBonuses()
	if cached is not None:
		return cached
	strategic = {}
	unitOrs = ctx.gc.getDefineINT('NUM_UNIT_PREREQ_OR_BONUSES')
	for i in range(ctx.gc.getNumUnitInfos()):
		_collectPrereqBonuses(ctx.gc.getUnitInfo(i), unitOrs, strategic)
	buildingOrs = ctx.gc.getDefineINT('NUM_BUILDING_PREREQ_OR_BONUSES')
	for i in range(ctx.gc.getNumBuildingInfos()):
		_collectPrereqBonuses(ctx.gc.getBuildingInfo(i), buildingOrs, strategic)
	ctx.setStrategicBonuses(strategic)
	return strategic


def _collectPrereqBonuses(info, numOrs, strategic):
	'''Add every bonus one unit/building requires into the `strategic` set.

	A dict used as a set - Python 2.4 has no set literal and the built-in set is
	only just available; a dict with dummy values is the idiom that works either
	way and is what the rest of this module would need anyway.'''
	iBonus = info.getPrereqAndBonus()
	if iBonus != BonusTypes.NO_BONUS:
		strategic[iBonus] = True
	for i in range(numOrs):
		iBonus = info.getPrereqOrBonuses(i)
		if iBonus != BonusTypes.NO_BONUS:
			strategic[iBonus] = True


def _emptyBonusGroups():
	'''A fresh {group: []} for every group, so absent groups never mean anything.

	Written even when empty, unlike the field-level omission used in map.tiles: the
	groups are a fixed set of three, not open-ended defaults, and "no strategic
	resources connected" is a fact worth stating rather than an absence to infer.'''
	groups = {}
	for group in _BONUS_GROUPS:
		groups[group] = []
	return groups


def _buildBonusGroups(ctx, include):
	'''XML Type keys of every bonus include(i) accepts, grouped and sorted.

	`include` is the per-bonus test that differs between the two callers - the
	player's trade network (getNumAvailableBonuses) and one city's connection
	(hasBonus) - so the grouping and ordering live here once rather than twice.'''
	strategic = _strategicBonuses(ctx)
	groups = _emptyBonusGroups()
	for i in range(ctx.gc.getNumBonusInfos()):
		if not include(i):
			continue
		info = ctx.gc.getBonusInfo(i)
		group = _bonusGroup(i, info, strategic)
		if group is not None:
			groups[group].append(info.getType())
	for group in _BONUS_GROUPS:
		groups[group].sort()
	return groups


def _buildPlayerBonuses(ctx):
	'''Resources connected to the player's trade network anywhere, with counts.

	Quantity is a PLAYER-level fact and deliberately not repeated per city: the
	engine tracks how many of a resource you have empire-wide, while a city merely
	has the connection or does not. The count is what matters for trading a spare
	away, and is meaningless inside a city.

	Counted, not boolean, so `counts` sits beside the grouped lists rather than
	replacing them: the lists answer "what do I have", the counts answer "what can
	I spare". Only connected resources appear at all - one sitting unimproved in
	the ground is not here, it is in map.tiles.

	The counts are collected in one pass and the grouping reads that same dict,
	so getNumAvailableBonuses is asked once per bonus rather than twice. The two
	must agree: a resource in `counts` but missing from every group (or the
	reverse) would be a contradiction within one section.'''
	counts = {}
	for i in range(ctx.gc.getNumBonusInfos()):
		count = ctx.player.getNumAvailableBonuses(i)
		if count > 0:
			counts[i] = count
	# `in` rather than counts.has_key: has_key is the 2.4 idiom but was removed in
	# Python 3, which mod/tests runs this same source under.
	bonuses = _buildBonusGroups(ctx, lambda i: i in counts)
	bonuses['counts'] = _keyedByType(ctx, counts)
	return bonuses


def _keyedByType(ctx, byIndex):
	'''Re-key a {bonusIndex: value} dict by XML Type key.

	Indices are the engine's currency and Type keys are the export's; converting
	at the boundary keeps the lookup loops above working in indices without
	leaking them into the file.'''
	out = {}
	for i in byIndex.keys():
		out[ctx.gc.getBonusInfo(i).getType()] = byIndex[i]
	return out


def _buildCityBonuses(ctx, city):
	'''Resources connected TO THIS CITY, grouped the same way as the player's.

	hasBonus is the engine's own "is this resource connected here" test, the one
	the base game's advisor uses. It already folds in everything: revealed by tech,
	improved correctly, linked by road/river/coast to this city, not severed by war
	and not traded away. That makes it the right question for "can this city build
	an Axeman", and deliberately not a diagnosis - it cannot say WHY a resource is
	missing. Joining map.tiles (bonus, improvement, route) against this is what
	distinguishes "no copper anywhere" from "copper in the fat cross, unroaded".

	No fog concern: our own cities, our own trade network.'''
	return _buildBonusGroups(ctx, city.hasBonus)


def _buildResearch(ctx):
	'Current research is NO_TECH before the player has picked one (e.g. turn 0).'
	iTech = ctx.player.getCurrentResearch()
	research = {
		'current': None,
		'progress': None,
		'cost': None,
		'turnsLeft': None,
		'sciencePercent': ctx.player.getCommercePercent(CommerceTypes.COMMERCE_RESEARCH),
	}
	if iTech != TechTypes.NO_TECH:
		research['current'] = ctx.gc.getTechInfo(iTech).getType()
		research['progress'] = _researchProgress(ctx, iTech)
		# The TEAM's cost, not getTechInfo(iTech).getResearchCost() - the latter is
		# the raw XML number, before the handicap/game-speed/world-size scaling that
		# produces the figure actually shown in game.
		research['cost'] = ctx.team.getResearchCost(iTech)
		# bOverflow=True to match the turn count the game's own UI displays, which
		# credits leftover beakers from the previously completed tech.
		research['turnsLeft'] = ctx.player.getResearchTurnsLeft(iTech, True)
	return research


def _researchProgress(ctx, iTech):
	'''Beakers banked toward iTech, as the in-game research bar fills it.

	Progress is stored per TEAM, but the game adds the player's leftover research
	from the previously completed tech on top - scaled by the same modifier that
	inflates the research rate (see REFERENCES.md "Research-rate mechanics"),
	because overflow is spent against the new tech at the new tech's rate. Formula
	lifted from Screens/CvMainInterface.py, which computes exactly this to size the
	bar; without the overflow term, progress would understate what the player sees
	on the turn after a tech completes, and would be inconsistent with turnsLeft,
	which already credits it.

	// rather than / so this stays integer division on Python 3 too (the mod runs
	on 2.4, but mod/tests exercises this same source under 3); both operands are
	non-negative here, so floor and truncation agree with the engine's C++ int math.'''
	progress = ctx.team.getResearchProgress(iTech)
	overflow = ctx.player.getOverflowResearch() * ctx.player.calculateResearchModifier(iTech) // 100
	return progress + overflow


def _buildKnownTechs(ctx):
	'Techs are known per-team, not per-player.'
	return _enabledTypes(ctx.gc.getNumTechInfos(), ctx.team.isHasTech, ctx.gc.getTechInfo)


def _buildCivics(ctx):
	'Maps each civic option (government, legal, ...) to the civic currently run in it.'
	civics = {}
	for i in range(ctx.gc.getNumCivicOptionInfos()):
		iCivic = ctx.player.getCivics(i)
		if iCivic != CivicTypes.NO_CIVIC:
			civics[ctx.gc.getCivicOptionInfo(i).getType()] = ctx.gc.getCivicInfo(iCivic).getType()
	return civics


def _buildWonders(ctx):
	'''Which wonders are gone and which the player has already built.

	The one fact in this file that CANNOT be derived from anything else exported,
	and the reason this section exists: whether the Pyramids are still available
	depends on whether some rival built them, which is nothing to do with our
	techs, resources or cities. Without it, advice will confidently recommend a
	wonder that was completed elsewhere ten turns ago.

	NOT a fog-of-war leak, and this was checked rather than assumed. The game's own
	Info screen (CvInfoScreen's wonder tab) lists every world wonder built anywhere
	in the world, and gates only the BUILDER'S IDENTITY on isHasMet - showing
	"Unknown" for the civ and city when the player has not met them, while showing
	the wonder itself unconditionally. So "this wonder is taken" is public
	knowledge; "Hammurabi built it in Babylon" is not. This section therefore
	exports the former and never the latter: no owner, no city, no date. The
	player also gets a global popup message the moment any world wonder completes.

	built/national split by scope, since the two answer different questions:
	  - `built` is world wonders (getMaxGlobalInstances 1) completed ANYWHERE, i.e.
	    the ones no longer available to anyone. Read via
	    CyGame.getBuildingClassCreatedCount, a game-level counter - deliberately
	    not by sweeping rivals' cities, which would need their city lists and would
	    miss wonders in cities we have never seen.
	  - `national` is national wonders (getMaxPlayerInstances 1) THIS PLAYER has
	    built, from CyPlayer.getBuildingClassCount. Rivals' national wonders are
	    absent because they are neither public nor relevant - they do not use
	    anything up for us.

	Both are lists of BUILDINGCLASS_ Type keys, not BUILDING_ ones: the limit is a
	property of the class, and the class is what joins against a rival civ's unique
	replacement (a Ziggurat and a Courthouse are one class). Sorted for diffability
	like every other list here.'''
	built = []
	national = []
	for i in range(ctx.gc.getNumBuildingClassInfos()):
		info = ctx.gc.getBuildingClassInfo(i)
		if info.getMaxGlobalInstances() == 1:
			if ctx.game.getBuildingClassCreatedCount(i) > 0:
				built.append(info.getType())
		# elif, not a second if: the two limits are mutually exclusive in practice
		# and a class carrying both would otherwise be listed twice, in sections
		# that mean different things.
		elif info.getMaxPlayerInstances() == 1:
			if ctx.player.getBuildingClassCount(i) > 0:
				national.append(info.getType())
	built.sort()
	national.sort()
	return {'built': built, 'national': national}


def _sortedRows(rows):
	'''Take (sortKey..., tieBreak, dict) tuples and return just the dicts, in order.

	Entities are sorted because the engine's own iteration order isn't documented as
	stable, and unsorted output would produce spurious turn-to-turn diffs - the same
	reason the serializer sorts dict keys. Callers put the tie-break (an ever-
	increasing counter) immediately before the dict so that two rows with equal sort
	keys never make the sort compare the dicts themselves.'''
	rows.sort()
	out = []
	for row in rows:
		out.append(row[-1])
	return out


def _buildUnits(ctx):
	'''The player's own units.

	Iteration uses the firstUnit/nextUnit cursor pair and the isDead() filter, the
	same way the base game's PyHelpers.getUnitList does.'''
	rows = []
	unit, cursor = ctx.player.firstUnit(False)
	while unit:
		if not unit.isDead():
			# len(rows) breaks ID ties so the sort never has to compare two dicts.
			rows.append((unit.getID(), len(rows), _buildUnit(ctx, unit)))
		unit, cursor = ctx.player.nextUnit(cursor, False)
	return _sortedRows(rows)


def _buildUnit(ctx, unit):
	row = {
		'id': unit.getID(),
		'type': ctx.gc.getUnitInfo(unit.getUnitType()).getType(),
		'x': unit.getX(),
		'y': unit.getY(),
		# Total moves for a turn, NOT moves remaining. movesLeft() would be the
		# obvious field but is unusable at our export timing: it is
		# maxMoves() - moves already spent, and the per-turn reset happens in
		# CvUnit::doTurn(), which runs when the player's next turn activates -
		# after onEndGameTurn has fired and we have already written the file. So
		# movesLeft() here always reports the turn that just ENDED, not the one
		# this export is labelled for. Confirmed in a live capture: a warrior that
		# had moved reported 0.
		#
		# baseMoves() is already in whole displayed moves (the game's own movement
		# line prints movesLeft()/MOVE_DENOMINATOR against baseMoves(), so they
		# share units) and includes promotions and team domain bonuses, not just
		# the unit's XML base.
		'moves': unit.baseMoves(),
	}
	# Percentage of health lost, not hit points; 100 would be dead. Omitted when
	# unhurt, which is the documented default and the overwhelmingly common case -
	# the same field-level omission map.tiles uses, and the same rule foreign units
	# follow, so "damage" reads identically wherever it appears in the file.
	_setIfDamaged(ctx, row, unit)
	# Level, XP and promotion keys are inputs to a combat-odds judgement, not the
	# verdict itself - the agent still weighs push-versus-retreat, but only if it
	# can see what a unit has already earned. All five fields are omitted at their
	# default (level 1, 0 XP, no promotions, nothing available, nothing owed),
	# same rule as damage - a fresh unit is the common case.
	level = unit.getLevel()
	if level > 1:
		row['level'] = level
	experience = unit.getExperience()
	if experience:
		row['experience'] = experience
	available, toNext = _promotionProgress(ctx, unit)
	if toNext:
		row['experienceToNextLevel'] = toNext
	promotions = _buildPromotions(ctx, unit)
	if promotions:
		row['promotions'] = promotions
	if available:
		row['promotionsAvailable'] = available
	# What this unit has been ORDERED to do, which no other field implies - a Worker
	# mid-Farm and an idle Worker standing on the same tile export identically
	# without it. Omitted entirely when the queue is empty, the common case for a
	# unit awaiting orders.
	mission = _buildMission(ctx, unit)
	if mission:
		row['mission'] = mission
	# The unit's standing ORDER, which is a separate mechanism from the mission
	# queue above and not covered by it: fortify/sleep/heal/sentry set an activity
	# and then DELETE their mission (CvSelectionGroup.cpp:1014-1056, every one
	# `bDelete = true`), so by export time a fortified unit's queue is empty.
	# Without these two fields a dug-in unit and an idle one are identical here.
	_setActivity(ctx, row, unit)
	return row


## ActivityTypes (CvEnums.h:1334-1348) as exported keys. ACTIVITY_AWAKE is the
## default and omitted; the numeric values are the enum's own ordering, which is
## stable and marked "Exposed to Python" in the header. NO_ACTIVITY (-1) and the
## air/naval/plunder activities are all out of scope for turns 0-50 and simply
## fall through to omission rather than being invented into names.
_ACTIVITY_TYPES = {
	1: 'ACTIVITY_HOLD',
	2: 'ACTIVITY_SLEEP',
	3: 'ACTIVITY_HEAL',
	4: 'ACTIVITY_SENTRY',
}


def _setActivity(ctx, row, unit):
	'''Record the unit's standing order and accrued fortification.

	Two fields rather than one, because the engine needs both to answer "is this
	unit dug in": FORTIFY and SLEEP BOTH set ACTIVITY_SLEEP
	(CvSelectionGroup.cpp:1018-1029), so activity alone cannot tell a fortified
	unit from a sleeping one - only fortifyTurns > 0 separates them.

	fortifyTurns is also a combat input in its own right, not just a flag: the
	engine's defence bonus is getFortifyTurns() * FORTIFY_MODIFIER_PER_TURN
	(CvUnit.cpp:8584), i.e. +5% per turn to a cap of 5 turns / +25% in this
	install's GlobalDefines.xml. Exported as the raw turn count rather than the
	percentage, keeping the "export inputs, not verdicts" line - the harness joins
	it against the XML constant the same way it does everything else.

	Both fields are omitted at their default (awake, unfortified), the same
	field-omission rule the rest of units[] follows.'''
	group = unit.getGroup()
	if group is not None and not group.isNone():
		activity = _ACTIVITY_TYPES.get(group.getActivityType())
		if activity:
			row['activity'] = activity
	fortifyTurns = unit.getFortifyTurns()
	if fortifyTurns:
		row['fortifyTurns'] = fortifyTurns


def _buildMission(ctx, unit):
	'''The head of this unit's mission queue, or None when it has no orders.

	HEAD ONLY, not the whole queue. The engine's queue can hold several missions
	(shift-clicked orders), and the game's own interface renders the rest as "..."
	with no detail - see CvMainInterface.py:2713-2737. Exporting the head matches
	both that display and the shape cities already use for `producing`, and a
	backlog is vanishingly rare in turns 0-50. Purely additive to widen later.

	The payload fields depend on the mission, because iData1/iData2 mean different
	things per mission type and there is no generic reading of them. Verified in
	the BTS SDK source (CvSelectionGroup.cpp) rather than assumed - a uniform
	"export data1 and data2" would be silently wrong for MISSION_MOVE_TO_UNIT,
	whose pair is a player/unit ID, not a coordinate.'''
	group = unit.getGroup()
	if group is None or group.isNone():
		return None
	if group.getLengthMissionQueue() <= 0:
		return None
	missionType = group.getMissionType(0)
	if missionType < 0:
		return None
	info = ctx.gc.getMissionInfo(missionType)
	mission = {'type': info.getType()}
	data1 = group.getMissionData1(0)
	data2 = group.getMissionData2(0)
	if info.isBuild():
		_setBuildMission(ctx, mission, unit, data1)
	elif info.getType() in _DESTINATION_MISSIONS:
		# iData1/iData2 are the destination plot (CvSelectionGroup.cpp:1577-1582,
		# groupPathTo(iData1, iData2, ...), and the done-check at :1431 is
		# at(iData1, iData2)). Deliberately no turns-to-arrive companion to
		# turnsLeft below: the engine repaths every turn and caches no ETA, so
		# there is no getMoveTurnsLeft to read, and deriving one would mean
		# reimplementing pathfinding - explicitly out of scope.
		mission['destination'] = {'x': data1, 'y': data2}
	elif info.getType() == 'MISSION_MOVE_TO_UNIT':
		# NOT a coordinate: iData1 is a player ID and iData2 a unit ID
		# (CvSelectionGroup.cpp:1473, GET_PLAYER(iData1).getUnit(iData2)).
		# Exported only when the target is OUR unit, where it joins against
		# units[].id. A rival's target is dropped rather than exported: foreign
		# units carry no id at all (they are visibility-gated and forgotten by
		# design), so there would be nothing to join it against, and a stable
		# rival unit ID is precisely the memory the engine does not keep.
		if data1 == ctx.playerId:
			mission['targetUnitId'] = data2
	return mission


def _setBuildMission(ctx, mission, unit, buildType):
	'''Fill in the BUILD_ key and turns remaining for a build mission.

	turnsLeft starts as the game's own figure, read the way the interface reads it
	(CvMainInterface.py:2725): plot().getBuildTurnsLeft(build, 0, 0). It then gets
	a -1 correction for a worker that has already worked this turn - see
	_buildTurnsLeftOvercount for the whole derivation, which is an export-timing
	artifact of the engine's own arithmetic rather than a staleness bug of the
	kind `moves` and `damage` had.

	The corrected number is PROSPECTIVE: turnsLeft == 1 means "completes during
	the turn this file is labelled for, unless the player cancels or re-orders the
	unit first" - the player retains the whole turn to intervene.'''
	mission['build'] = ctx.gc.getBuildInfo(buildType).getType()
	plot = unit.plot()
	if plot is None or plot.isNone():
		return
	turnsLeft = plot.getBuildTurnsLeft(buildType, 0, 0)
	mission['turnsLeft'] = turnsLeft - _buildTurnsLeftOvercount(unit, turnsLeft)


def _buildTurnsLeftOvercount(unit, turnsLeft):
	'''1 when getBuildTurnsLeft has counted the turn in progress twice, else 0.

	CvPlot::getBuildTurnsLeft (CvPlot.cpp:2441-2492, verified against the SDK
	source and then confirmed in live play) ends with an unconditional
	`iTurnsLeft++`, because the interface reads it MID-TURN, while the player is
	deciding and before this turn's work has landed. To stay consistent it first
	subtracts a "now" build rate from the work remaining - but only from workers
	that can still move:

		if (pLoopUnit->canMove()) iNowBuildRate += pLoopUnit->workRate(false);

	(workRate(false) states the same gate a second time, returning 0 when
	!canMove() - CvUnit.cpp:7409-7415.)

	Mid-turn both halves fire and cancel out. At OUR export timing they do not: we
	run from onEndGameTurn, by which point a worker that spent its turn building
	can no longer move, so iNowBuildRate stays 0, this turn's work is never
	subtracted, and the trailing ++ adds a turn on top of a figure that already
	included it. The result is exactly one too high. Confirmed live in both
	directions: a 5-turn Farm one turn in reported 5 (true answer 4), and a build
	about to finish reported 2 (true answer 1).

	Gated on canMove() rather than applied unconditionally, because it is the
	engine's own discriminator and there is a real case on the other side of it: a
	worker ORDERED to build but not yet acted this turn (just arrived, or idle
	when the order was given) still can move, so its "now" rate IS subtracted and
	its figure is already correct - subtracting there would make it one too low.

	The turnsLeft > 1 guard is not defensive padding. getBuildTurnsLeft returns
	std::max(1, iTurnsLeft), so a raw 1 has been through a floor and cannot be
	told apart from a genuine 1; subtracting there could yield 0, claiming a build
	already finished.'''
	if turnsLeft > 1 and not unit.canMove():
		return 1
	return 0


## Missions whose iData1/iData2 pair is a destination PLOT rather than anything
## else. Kept as an explicit whitelist, not a prefix match on the type name:
## MISSION_MOVE_TO_UNIT reads as a move by name while storing a player/unit ID
## pair, so a name-based test would export an ID pair as a coordinate.
_DESTINATION_MISSIONS = ('MISSION_MOVE_TO', 'MISSION_ROUTE_TO')


def _promotionProgress(ctx, unit):
	'''(promotionsAvailable, experienceToNextLevel) for one unit.

	Computed together because both walk the same level ladder, and the two are
	mutually exclusive by construction: experienceToNextLevel only answers "how
	far until the FIRST pick is funded" and reads 0 the moment promotionsAvailable
	is at least 1 - it never reports the distance to some further-out pick once
	one is already banked, which would force the agent to hold two numbers with
	context-dependent meaning in its head at once.

	CyUnit.experienceNeeded() only answers for the unit's OWN current level - it is
	a C++->Python callback that reads getLevel() internally, with no way to ask
	about a hypothetical one - so there is no single engine call for either of
	these. Walk the same formula it uses instead (CvGameUtils.py's
	getExperienceNeeded, verified in the local install and cited in
	REFERENCES.md): level*level + 1, then bumped by the player's flat
	getLevelExperienceModifier percentage, rounded up.

	promotionsAvailable is an upper bound on picks available, not a guarantee: it
	answers whether the XP exists, but not whether an eligible promotion actually
	exists at each hypothetical level - CyUnit.canAcquirePromotionAny() depends on
	the unit's specific promotion tree and unit-combat class, which this does not
	evaluate. See the schema field description for the full caveat.'''
	modifier = ctx.player.getLevelExperienceModifier()
	level = unit.getLevel()
	experience = unit.getExperience()
	available = 0
	while True:
		needed = level * level + 1
		if modifier:
			needed += (needed * modifier + 99) // 100
		if experience < needed:
			if available:
				return available, 0
			return available, needed - experience
		level += 1
		available += 1


def _setIfDamaged(ctx, row, unit):
	'''Record a unit's damage AFTER this turn's heal, or leave the field out entirely
	when the result is unhurt.

	getDamage() alone is the same kind of stale as movesLeft(): CvUnit::doTurn() heals
	a hurt unit in the same pass that resets moves, and that pass runs after our
	export hook fires and before the player regains control - so the raw value here
	always describes the turn that just ended, not the one this export is labelled
	for. Confirmed live: a scout at 76 damage was already healed further in-game by
	the time the file caught up (see REFERENCES.md "doTurn() mutation-order audit").

	Unlike moves, there is no live equivalent to fall back to - CyUnit exposes no
	healRate() at all (confirmed live: AttributeError). So instead of exporting the
	stale value, the post-heal one is predicted from _healRate, whose components ARE
	individually exposed even though the aggregate isn't. See _healRate for the one
	acknowledged gap this prediction carries (a city's building-derived heal bonus).'''
	damage = unit.getDamage()
	if damage and _willHealThisTurn(unit):
		damage -= _healRate(ctx, unit, unit.plot())
		if damage < 0:
			damage = 0
	if damage:
		row['damage'] = damage


def _willHealThisTurn(unit):
	'''Whether CvUnit::doTurn() will run this unit through its heal branch.

	Exact match of the engine's own gate (CvUnit.cpp:713-725, verified against the BTS
	SDK source): a unit that has moved this turn only heals if it carries the Always
	Heal promotion (e.g. Medic III via its own tree); a unit that has not moved heals
	whenever it is hurt. One separate, out-of-scope damage source sits just above this
	gate in doTurn() and is NOT reconstructed here: terrain-feature turn damage (e.g.
	Fallout), applied unconditionally before the heal check regardless of hasMoved.
	That is a damage SOURCE, not a heal-timing question, and would need its own
	feature-damage sweep to predict - left as a known residual staleness alongside the
	city-heal-rate gap in _healRate.'''
	if unit.hasMoved():
		return unit.isAlwaysHeal()
	return unit.isHurt()


## dx,dy offsets for the 8 plots adjacent to a unit's own tile. There is no
## plotDirection binding exposed to Python, so the neighbour walk is hand-rolled.
_ADJACENT_OFFSETS = (
	(-1, -1), (0, -1), (1, -1),
	(-1, 0), (1, 0),
	(-1, 1), (0, 1), (1, 1),
)


def _unitPromotionHealBonuses(ctx, unit):
	'''(enemy, neutral, friendly) heal-rate percentage bonuses from this unit's own
	promotions, summed across every promotion it carries.

	Same enum-sweep shape as _buildPromotions, just accumulating three XML fields
	(CIV4PromotionInfos.xml's HealRateChange trio) instead of collecting Type keys.
	getSameTileHealChange/getAdjacentTileHealChange (the Medic line) are handled
	separately in _bestNearbyHeal - those affect OTHER units nearby, not this one's
	own base rate, and the engine takes the best nearby value rather than summing it.'''
	enemy = 0
	neutral = 0
	friendly = 0
	for i in range(ctx.gc.getNumPromotionInfos()):
		if not unit.isHasPromotion(i):
			continue
		info = ctx.gc.getPromotionInfo(i)
		enemy += info.getEnemyHealChange()
		neutral += info.getNeutralHealChange()
		friendly += info.getFriendlyHealChange()
	return enemy, neutral, friendly


def _territoryHealRate(ctx, unit, plot):
	'''The base heal-rate percentage for the territory a unit currently stands in.

	Reconstructs CvUnit::healRate()'s base-rate branch (CvUnit.cpp:3499-3524, verified
	against the BTS SDK source): a city tile (CvPlot.isCity, true/our-team form) heals
	at the city rate, PLUS a building-derived CvCity.getHealRate() bonus this
	reconstruction cannot see - see _healRate for why that term is an acknowledged,
	permanent gap. The engine's own promotion adjustment on a city tile is a
	friendly-or-neutral choice, NEVER enemy - the source picks between
	getExtraFriendlyHeal and getExtraNeutralHeal there even though the city might not
	be ours, and does not consult getExtraEnemyHeal at all on a city tile.

	Off a city tile, the engine picks friendly/enemy/neutral by TEAM, not by player:
	isFriendlyTerritory(plotTeam) is friendly only for our own team or a vassal
	relation (structurally unreachable in turns 0-50, since vassalage needs a
	capitulation war), otherwise the tile is enemy if the plot's owning team is at war
	with ours and neutral otherwise - which also covers an unowned plot, whose team is
	NO_TEAM and is never "at war" with anyone. Each branch is further adjusted by this
	unit's own promotion bonuses from _unitPromotionHealBonuses, matching the engine's
	getExtraFriendlyHeal/getExtraEnemyHeal/getExtraNeutralHeal accumulators, which are
	themselves built from the same per-promotion XML fields swept there.'''
	enemyBonus, neutralBonus, friendlyBonus = _unitPromotionHealBonuses(ctx, unit)
	if plot.isCity():
		owner = plot.getOwner()
		if owner == ctx.playerId:
			return ctx.gc.getDefineINT('CITY_HEAL_RATE') + friendlyBonus
		return ctx.gc.getDefineINT('CITY_HEAL_RATE') + neutralBonus
	owner = plot.getOwner()
	if owner == ctx.playerId:
		return ctx.gc.getDefineINT('FRIENDLY_HEAL_RATE') + friendlyBonus
	if owner != PlayerTypes.NO_PLAYER:
		ownerTeam = ctx.gc.getPlayer(owner).getTeam()
		if ctx.team.isAtWar(ownerTeam):
			return ctx.gc.getDefineINT('ENEMY_HEAL_RATE') + enemyBonus
	return ctx.gc.getDefineINT('NEUTRAL_HEAL_RATE') + neutralBonus


def _bestNearbyHeal(ctx, unit, plot):
	'''The largest same-tile or adjacent-tile heal bonus any friendly unit nearby
	grants this one (the Medic line), matching the engine's iBestHeal reduction
	(CvUnit.cpp:3526-3573, verified against the BTS SDK source) - the best available
	bonus applies, not the sum of all of them.

	Only our own team's units are asked: a rival's Medic promotions are not ours to
	read, and the engine's own check is teammate-scoped besides. No plotDirection
	binding exists in the Python layer, so the 8 neighbours are walked by hand via
	_ADJACENT_OFFSETS rather than an engine-provided iterator.'''
	best = 0
	best = _bestHealOnPlot(ctx, plot, best, ctx.gc.getPromotionInfo, 'getSameTileHealChange')
	x = plot.getX()
	y = plot.getY()
	for dx, dy in _ADJACENT_OFFSETS:
		neighbor = ctx.cyMap.plot(x + dx, y + dy)
		if neighbor is None or neighbor.isNone():
			continue
		best = _bestHealOnPlot(ctx, neighbor, best, ctx.gc.getPromotionInfo, 'getAdjacentTileHealChange')
	return best


def _bestHealOnPlot(ctx, plot, best, getPromotionInfo, changeMethodName):
	'''Fold every TEAMMATE unit standing on one plot into the running best-heal value.

	Teammate, not owner - the engine's own check is getTeam() == getTeam()
	(CvUnit.cpp:3536, 3562), which a player-equality check would get wrong for a
	teamed civ. getOwner() (not getVisualOwner()) is correct and safe here: unlike
	foreignUnits, this never leaves the export, and a hidden-nationality unit's true
	team is exactly what determines whether it actually contributes this bonus.'''
	for i in range(plot.getNumUnits()):
		other = plot.getUnit(i)
		if ctx.gc.getPlayer(other.getOwner()).getTeam() != ctx.teamId:
			continue
		for p in range(ctx.gc.getNumPromotionInfos()):
			if not other.isHasPromotion(p):
				continue
			change = getattr(getPromotionInfo(p), changeMethodName)()
			if change > best:
				best = change
	return best


def _healRate(ctx, unit, plot):
	'''Predicted heal-rate percentage this unit will receive at the end of the
	current turn, the sum of its territory-based base rate and the best nearby
	Medic-line bonus - CvUnit::healRate()'s own two terms (CvUnit.cpp:3482-3576,
	verified against the BTS SDK source).

	ONE ACKNOWLEDGED GAP: a city's building-derived bonus (CvCity.getHealRate(), e.g.
	from an Aqueduct) reads a raw C++ member with no Python binding and no XML
	fallback, so it cannot be reconstructed here. A unit garrisoned in a city with a
	heal-boosting building will heal faster than this predicts - a permanent, bounded
	undercount of damage-after-heal for that one case, not a general staleness.'''
	return _territoryHealRate(ctx, unit, plot) + _bestNearbyHeal(ctx, unit, plot)


def _buildPromotions(ctx, unit):
	'''PROMOTION_ Type keys this unit has, sorted.

	isHasPromotion swept over every promotion in CIV4PromotionInfos.xml - the same
	enum-sweep shape as _buildKnownTechs, just per-unit instead of per-team. No fog
	concern: a unit whose position we already export is one we can see, and this is
	our own unit besides.'''
	promotions = []
	for i in range(ctx.gc.getNumPromotionInfos()):
		if unit.isHasPromotion(i):
			promotions.append(ctx.gc.getPromotionInfo(i).getType())
	promotions.sort()
	return promotions


def _buildCities(ctx):
	'''The player's own cities.

	The isNone()/getOwner() filter mirrors the base game's PyHelpers.getCityList.'''
	rows = []
	city, cursor = ctx.player.firstCity(False)
	while city:
		if not city.isNone() and city.getOwner() == ctx.playerId:
			rows.append((city.getID(), len(rows), _buildCity(ctx, city)))
		city, cursor = ctx.player.nextCity(cursor, False)
	return _sortedRows(rows)


def _buildCity(ctx, city):
	producing = _buildProducing(ctx, city)
	total, hammers, food = _productionRates(city)
	return {
		'id': city.getID(),
		# A wstring: unicode, and the first game-supplied text in the export.
		'name': city.getName(),
		'x': city.getX(),
		'y': city.getY(),
		'population': city.getPopulation(),
		'food': city.getFood(),
		# foodDifference(bBottom=True) is the figure the city screen's growth
		# indicator uses; it reads 0 rather than negative during disorder.
		'foodPerTurn': city.foodDifference(True),
		'growthThreshold': city.growthThreshold(),
		'producing': producing,
		'production': city.getProduction(),
		'productionNeeded': _buildProductionNeeded(city, producing),
		# The figure the city screen shows, and the two halves it is made of - see
		# _productionRates for why both halves are exported rather than derived.
		'productionPerTurn': total,
		'productionFromHammers': hammers,
		'productionFromFood': food,
		# Culture is per-player within a city; the owner's share is the one that
		# counts against cultureThreshold for the next border pop.
		'culture': city.getCulture(ctx.playerId),
		'cultureThreshold': city.getCultureThreshold(),
		'happy': city.happyLevel(),
		'unhappy': city.unhappyLevel(0),
		'healthy': city.goodHealth(),
		'unhealthy': city.badHealth(False),
		'workedTiles': _buildWorkedTiles(ctx, city),
		'buildings': _buildCityBuildings(ctx, city),
		'bonuses': _buildCityBonuses(ctx, city),
		# Whether a Harbour, Lighthouse or any naval unit is possible here at all -
		# a hard gate on a whole branch of what the city can build, and one the
		# harness would otherwise have to rebuild from map.tiles by testing all
		# eight neighbours for water and then excluding lakes. isCoastal is the
		# engine's own test, and takes the minimum water-body size the XML requires
		# (MIN_WATER_SIZE_FOR_OCEAN), which is exactly the part a hand-rolled
		# adjacency check gets wrong: a city on a two-tile pond is not coastal.
		'coastal': bool(city.isCoastal(ctx.gc.getMIN_WATER_SIZE_FOR_OCEAN())),
	}


def _buildCityBuildings(ctx, city):
	'''What this city has already built, as BUILDING_ Type keys, sorted.

	The prerequisite half of "what can this city build now": the two things that
	gate a building are its tech and its prerequisite BUILDING, and the second is
	only answerable from here. It also stops the obvious mistake in the other
	direction - recommending something the city already has.

	BUILDING_ keys, not BUILDINGCLASS_ ones, and this is the opposite choice from
	the `wonders` section on purpose. There the limit is a property of the class,
	so the class is the right key. Here what matters is the actual thing standing
	in the city, with its real effects: Portugal's Feitoria and a generic Trading
	Post are one class but not the same building. The mapping is NOT a rename
	either - 28 stock buildings have a class whose name differs from their own,
	several of them many-to-one (BUILDING_COAL_PLANT, BUILDING_HYDRO_PLANT and
	BUILDING_NUCLEAR_PLANT are all BUILDINGCLASS_FACTORY), so the harness cannot
	recover one from the other by string surgery. If a class key is ever needed
	alongside this, export it as its own field rather than swapping this one.

	Iterating buildings rather than classes for the same reason: hasBuilding takes
	a building, and going via classes would need the civ's class->building
	resolution, which would hand back the generic building for any class where
	this civ has a unique - the exact confusion this field is meant to avoid.

	getNumBuilding, NOT hasBuilding - which does not exist on CyCity and cost a
	live export to discover. The base game's own Python calls pCity.hasBuilding()
	in eight places, so it looks unimpeachable, but those call sites run against
	WorldBuilder screens and getPlotCity() results; the real binding is
	isHasBuilding, and the BUG reference flags even that as a compatibility shim
	that "no longer exists in C++" and merely forwards to getNumBuilding. So the
	underlying method is used directly: one fewer layer, and nothing to be
	deprecated out from under us.

	getNumBuilding rather than getNumRealBuilding because it counts FREE buildings
	too, and the Palace in the capital is exactly that - a free building. The
	"real" variant would silently omit the one building this field is most obviously
	expected to show.

	No fog concern: our own cities. Rivals' buildings are deliberately absent from
	foreignCities, which exports only what the nameplate shows.'''
	buildings = []
	for i in range(ctx.gc.getNumBuildingInfos()):
		if city.getNumBuilding(i) > 0:
			buildings.append(ctx.gc.getBuildingInfo(i).getType())
	buildings.sort()
	return buildings


def _buildWorkedTiles(ctx, city):
	'''[x, y] of every tile this city has a citizen on, city centre included.

	Lives on the city rather than on each map tile for three reasons. It is honest
	by construction: we only ever iterate our OWN cities, so a rival's worked tiles
	cannot leak - whereas CyPlot.isBeingWorked() is live truth with no fog check,
	and the engine's fog-aware wrapper (CvPlot::isVisibleWorked) is one of the few
	CvPlot methods NOT exposed to Python, so map-side we would have to re-implement
	it by hand. It is ~10x cheaper: 2 calls per city plot (42 per city) instead of 2
	per revealed map tile. And it keeps map.tiles purely geographic.

	The city centre is included because it is worked for free and does produce
	yield; leaving it out would stop the list accounting for the city's output.

	The set of tiles a city COULD work is not exported - it is derivable, being the
	5x5 square around the city minus the four corners (CITY_PLOTS_RADIUS is 2, hence
	NUM_CITY_PLOTS == 21). Neither are specialists, which are the citizens left over:
	population + 1 - len(workedTiles).'''
	tiles = []
	for i in range(ctx.gc.getNUM_CITY_PLOTS()):
		if not city.isWorkingPlotByIndex(i):
			continue
		plot = city.getCityIndexPlot(i)
		# Plots off the edge of the map (a city near the poles) come back invalid.
		if plot is None or plot.isNone():
			continue
		tiles.append([plot.getX(), plot.getY()])
	tiles.sort()
	return tiles


def _buildProducing(ctx, city):
	'''The XML Type key of whatever the city is building, or None if nothing is.

	The order-kind cascade is the one CvWBDesc.py uses to serialize a city.'''
	if city.isProductionUnit():
		return ctx.gc.getUnitInfo(city.getProductionUnit()).getType()
	if city.isProductionBuilding():
		return ctx.gc.getBuildingInfo(city.getProductionBuilding()).getType()
	if city.isProductionProject():
		return ctx.gc.getProjectInfo(city.getProductionProject()).getType()
	if city.isProductionProcess():
		return ctx.gc.getProcessInfo(city.getProductionProcess()).getType()
	return None


def _productionRates(city):
	'''(total, hammers, food) hammers per turn, as the city screen's bar splits them.

	(bIgnoreFood=False, bOverflow=True) is the total the city screen prints: food
	converted to hammers counts, and so does carried-over overflow from the previous
	completed build - which makes it a one-turn figure rather than a steady rate on
	the turn right after something finished. Both halves inherit that.

	The split is the ENGINE'S OWN, not one invented here: CvCity::getProductionBarPercentages
	sizes its two-tone bar with exactly this subtraction, calling
	getCurrentProductionDifference(True, True) for the hammer part and taking the food
	part as the difference from the (False, True) total. The two calls subtract cleanly
	in every state because bFoodProduction gates one additive term inside
	getProductionDifference and changes nothing else - the hammer expression is
	identical between them. Under disorder that function returns 0 outright, so all
	three come back 0 together rather than disagreeing.

	Exported rather than left to the harness because the split is NOT recoverable from
	a single turn's file: while a food build is queued the food is already inside the
	total and foodDifference reads 0, so nothing else in the export separates them, and
	the previous turn's figure does not decompose this one because worked tiles change
	between turns. It is not recoverable from the XML either - the engine's test is the
	unit's bFood flag OR a civic with isMilitaryFoodProduction (Police State) making
	every military unit food-fed, so the qualifying set is wider than CIV4UnitInfos.xml
	shows. Only a unit order can qualify at all; buildings, projects and processes never
	consume food.

	Cost is one extra C++ call per city, against a map sweep of thousands of plots.'''
	total = city.getCurrentProductionDifference(False, True)
	hammers = city.getCurrentProductionDifference(True, True)
	return total, hammers, total - hammers


def _buildProductionNeeded(city, producing):
	'''Hammer cost of the current build, or None where there isn't one.

	getProductionNeeded() returns MAX_INT (2147483647) both when the order queue is
	empty and when the city is running a process - a process converts hammers to
	gold/beakers/culture forever and never completes. Verified in the BTS game-core
	source (CvCity::getProductionNeeded falls through to MAX_INT for ORDER_MAINTAIN
	and for a NULL head node). Exporting that sentinel as a number would read as a
	real, absurdly expensive build, so both cases become null.'''
	if producing is None or city.isProductionProcess():
		return None
	return city.getProductionNeeded()


def _buildMap(ctx):
	'''Every tile the player's team has ever revealed, in row-major (y, then x) order.

	Row-major matches the engine's own plot indexing (CvMap::plotX is index % width,
	plotY is index / width) and reads like the map; the ordering matters because
	unsorted output would produce spurious turn-to-turn diffs, same as for
	units/cities. Iterating with plot(x, y) rather than plotByIndex(i) costs the same
	one call per plot but gets the coordinates for free instead of via two more.

	Cost note: this touches every plot on the map (4368 on a standard map), so the
	isRevealed gate comes first and is the only call made for the great majority of
	them. See _reportTimings.

	calculateYield(bDisplay=True) below answers for the ACTIVE team rather than for
	ctx's - buildState refuses to run at all when those differ, see
	_requireActivePlayer.'''
	tiles = []
	# Both ranges hoisted out of the loops: range() builds a real list in Python 2.4,
	# so an inline range(width) would allocate one per row.
	xs = range(ctx.cyMap.getGridWidth())
	for y in range(ctx.cyMap.getGridHeight()):
		for x in xs:
			plot = ctx.cyMap.plot(x, y)
			if not plot.isRevealed(ctx.teamId, False):
				continue
			tiles.append(_buildTile(ctx, plot))
	return {'tiles': tiles}


def _buildTile(ctx, plot):
	'''One revealed tile.

	Only x/y/terrain/yields are unconditional; everything else is omitted when it
	holds the default recorded for it in schema/state.schema.json.

	Fog of war, the substance of this function: improvement, route and owner are the
	only three things the engine keeps a per-team remembered copy of, so those MUST
	use the revealed getters. Everything else has no revealed variant to use - the
	engine has no memory of it, and reads it live in its own tile mouseover too, so
	a live value here is the same call the game makes to draw that tooltip rather
	than an approximation of it. Details in REFERENCES.md "Plot/map API semantics".

	bDebug is False on every revealed getter, never True: True bypasses to live truth
	whenever isDebugMode() is on, which would silently turn the whole export into
	full-map truth if WorldBuilder or the Chipotle cheat were ever toggled.'''
	# Coordinates lead the line: they identify the row, and alphabetical order would
	# otherwise bury them at the end, after every field they apply to.
	tile = _Record(('x', 'y'))
	tile['x'] = plot.getX()
	tile['y'] = plot.getY()
	tile['terrain'] = ctx.gc.getTerrainInfo(plot.getTerrainType()).getType()
	tile['yields'] = _tileYields(plot)
	plotType = _tilePlotType(plot)
	if plotType is not None:
		tile['plotType'] = plotType
	if plot.isLake():
		tile['lake'] = True
	if plot.isFreshWater():
		tile['freshWater'] = True
	if plot.isRiver():
		tile['river'] = True
	iFeature = plot.getFeatureType()
	if iFeature != FeatureTypes.NO_FEATURE:
		tile['feature'] = ctx.gc.getFeatureInfo(iFeature).getType()
	# Team-aware but NOT fog-aware: this hides resources the team lacks the tech to
	# see (CvPlot::getBonusType checks isHasTech(getTechReveal())), which is the
	# distinction that matters - a bonus stays visible through fog once revealed.
	iBonus = plot.getBonusType(ctx.teamId)
	if iBonus != BonusTypes.NO_BONUS:
		tile['bonus'] = ctx.gc.getBonusInfo(iBonus).getType()
	# Also how goody huts arrive: they are an improvement, and the engine's own
	# isRevealedGoody() is just improvementInfo(revealed improvement).isGoody().
	iImprovement = plot.getRevealedImprovementType(ctx.teamId, False)
	if iImprovement != ImprovementTypes.NO_IMPROVEMENT:
		tile['improvement'] = ctx.gc.getImprovementInfo(iImprovement).getType()
	iRoute = plot.getRevealedRouteType(ctx.teamId, False)
	if iRoute != RouteTypes.NO_ROUTE:
		tile['route'] = ctx.gc.getRouteInfo(iRoute).getType()
	iOwner = plot.getRevealedOwner(ctx.teamId, False)
	if iOwner != PlayerTypes.NO_PLAYER:
		tile['owner'] = iOwner
	if plot.isVisible(ctx.teamId, False):
		tile['visibleNow'] = True
	return tile


def _tilePlotType(plot):
	'''The tile's plot type as a string, or None for plain flat land (the default).

	Peak/hills/water/flatland are one engine enum (m_ePlotType), not independent
	flags, so this is one field rather than three booleans that could contradict
	each other. The names are the game's own, from the PlotTypes enum in CvEnums.h.

	Read via the isPeak/isHills/isWater predicates rather than getPlotType() for two
	reasons: those three are confirmed present in the Python layer (the base game
	uses them), whereas the individual PlotTypes.PLOT_* constants are not referenced
	anywhere in it, so relying on them would be an assumption; and plot type is the
	one enum-like value in the schema with no XML info object behind it - there is no
	gc.getPlotTypeInfo(i).getType() to ask for the string, unlike terrain, feature,
	bonus and the rest. That makes this the schema's single documented exception to
	"every enum-like value is an XML Type key", and it is why the mapping is spelled
	out here instead of being read from the game.'''
	if plot.isPeak():
		return 'PLOT_PEAK'
	if plot.isHills():
		return 'PLOT_HILLS'
	if plot.isWater():
		return 'PLOT_OCEAN'
	return None


def _tileYields(plot):
	'''[food, production, commerce] as the game itself displays them.

	bDisplay=True is what both of the engine's display paths pass - the yield icons
	on the map (CvPlot::updateSymbols) and the tile mouseover
	(CvGameTextMgr::setPlotHelp) - and it is also the fog-honest choice, since it
	makes calculateYield use the revealed improvement/route/owner internally.

	Two surprises inherited from the engine, both deliberate:
	  - A plot with no land anywhere in its 21-tile city cross reports [0, 0, 0] no
	    matter what it is, because calculateYield returns 0 when !isPotentialCityWork.
	    Deep ocean therefore looks barren - which is exactly what the map shows.
	  - On an unowned tile, bDisplay substitutes the active player as owner, so
	    player-specific effects (the Financial trait's extra commerce, golden-age
	    yields) are applied to land nobody owns. Again, what the map shows.'''
	return [
		plot.calculateYield(YieldTypes.YIELD_FOOD, True),
		plot.calculateYield(YieldTypes.YIELD_PRODUCTION, True),
		plot.calculateYield(YieldTypes.YIELD_COMMERCE, True),
	]


def _otherPlayers(ctx):
	'''(playerId, CyPlayer) for every live player except the one being exported.

	getMAX_PLAYERS(), not getMAX_CIV_PLAYERS(): the barbarians occupy the final slot
	and the foreign sections want them. Only contacts filters them back out.

	Walking each player's own list (as the base game's military advisor does) rather
	than sweeping plots is both cheaper and, for cities, the only correct option -
	see _buildForeignCities.'''
	out = []
	for i in range(ctx.gc.getMAX_PLAYERS()):
		if i == ctx.playerId:
			continue
		player = ctx.gc.getPlayer(i)
		if not player.isAlive():
			continue
		out.append((i, player))
	return out


def _buildContacts(ctx):
	'''Rival civs we have met, in player-ID order (which the loop already gives us).

	DO NOT simplify the filter to isHasMet alone. Barbarian and minor teams declare
	war on every civ team in CvGame::initDiplomacy, and CvTeam::declareWar calls
	meet(), so isHasMet and isAtWar are both true for the barbarians from turn 0 -
	the naive loop reports a barbarian contact, at war, in every export. The four
	conditions here are the ones the base game's own Foreign Advisor applies.

	isHasMet is asked of OUR team about theirs (it is symmetric - CvTeam::meet calls
	makeHasMet on both sides), so the mod never fetches a rival CyTeam, which is the
	object that would expose their techs and research.'''
	contacts = []
	for playerId, player in _otherPlayers(ctx):
		if player.isBarbarian() or player.isMinorCiv():
			continue
		teamId = player.getTeam()
		# Teammates are not people you have diplomacy with; their units and cities
		# still show up in the foreign sections below.
		if teamId == ctx.teamId:
			continue
		if not ctx.team.isHasMet(teamId):
			continue
		contact = _Record(('playerId',))
		contact['playerId'] = playerId
		contact['leader'] = ctx.gc.getLeaderHeadInfo(player.getLeaderType()).getType()
		contact['civilization'] = ctx.gc.getCivilizationInfo(player.getCivilizationType()).getType()
		# The five-bucket value the UI shows, and the most this could leak even by
		# accident: the numeric AI_getAttitudeVal is not in the Python API.
		contact['attitude'] = ctx.gc.getAttitudeInfo(player.AI_getAttitude(ctx.playerId)).getType()
		# bool() because the C++ bindings hand back 1/0 and the serializer would
		# otherwise emit those rather than JSON true/false.
		contact['atWar'] = bool(ctx.team.isAtWar(teamId))
		contacts.append(contact)
	return contacts


def _buildForeignUnits(ctx):
	'''Other players' units, but only those standing on a tile we can see right now.

	Sorted by owner then position, so the section groups by civ - "what does this
	one have near me" is how it gets read. The key comes off the built row rather
	than the unit because `owner` is the VISUAL owner: a disguised unit then sorts
	with the barbarians it is pretending to belong to, as the game presents it.
	Type is part of the key because units stack and the engine's iteration order
	is not documented as stable.'''
	rows = []
	for playerId, player in _otherPlayers(ctx):
		unit, cursor = player.firstUnit(False)
		while unit:
			row = _buildForeignUnit(ctx, unit)
			if row is not None:
				# len(rows) breaks ties so the sort never compares two dicts.
				rows.append((row['owner'], row['y'], row['x'], row['type'], len(rows), row))
			unit, cursor = player.nextUnit(cursor, False)
	return _sortedRows(rows)


def _buildForeignUnit(ctx, unit):
	'''One rival unit, or None if the player cannot currently see it.

	"Visible", not "revealed" - the engine keeps no memory of where enemy units
	were, so neither do we, and a unit disappearing between two exports means it
	went out of sight rather than that it died. The pairing with isInvisible is the
	base game's own, from CvMilitaryAdvisor.

	isInvisible is nearly a no-op this early (only the Spy and Great Spy are
	permanently invisible) but is honoured because it also covers cargo, which the
	map does not draw either.'''
	if unit.isDead():
		return None
	plot = unit.plot()
	if plot is None or plot.isNone():
		return None
	if not plot.isVisible(ctx.teamId, False):
		return None
	if unit.isInvisible(ctx.teamId, False):
		return None
	row = _Record(('x', 'y'))
	row['x'] = unit.getX()
	row['y'] = unit.getY()
	# getVisualOwner, not getOwner: hidden-nationality units show as barbarian
	# outside their owner's cities, and the export must not be what unmasks one.
	# Answers for the ACTIVE team - see _requireActivePlayer.
	row['owner'] = unit.getVisualOwner()
	row['type'] = ctx.gc.getUnitInfo(unit.getUnitType()).getType()
	# Legitimately visible: the engine folds every unit's damage into the stack
	# strength printed in the tile mouseover, gated only on the plot being visible.
	# Live-read, deliberately NOT run through _setIfDamaged's heal prediction: that
	# reconstruction leans on promotions and territory this unit's true owner
	# controls, none of which the export has any standing to predict for a rival.
	damage = unit.getDamage()
	if damage:
		row['damage'] = damage
	return row


def _buildForeignCities(ctx):
	'''Other players' cities that our team has actually laid eyes on.

	Unlike units, cities are remembered - the nameplate stays on the map under fog.
	The gate is the engine's own per-city isRevealed flag, which is STRICTER than
	the tile being revealed: CvCity::init only reveals a new city to teams that can
	currently SEE the plot, so a city founded on a tile we revealed long ago but
	cannot see now is correctly absent until we next look.

	DO NOT re-implement this as a sweep of revealed plots calling getPlotCity():
	that reads live truth and would surface exactly those fog-founded cities.

	Sorted by owner then position, like foreign units. No type in the key here -
	two cities cannot share a tile.'''
	rows = []
	for playerId, player in _otherPlayers(ctx):
		# isNone()/getOwner() mirrors PyHelpers.getCityList, the same as _buildCities.
		city, cursor = player.firstCity(False)
		while city:
			if (not city.isNone() and city.getOwner() == playerId
					and city.isRevealed(ctx.teamId, False)):
				row = _buildForeignCity(city, playerId)
				rows.append((row['owner'], row['y'], row['x'], len(rows), row))
			city, cursor = player.nextCity(cursor, False)
	return _sortedRows(rows)


def _buildForeignCity(city, ownerId):
	'''One rival city, as the game draws its nameplate.

	Every field is read LIVE rather than remembered, which matches the UI rather
	than overstating it: the engine builds the plate from getName(), getPopulation()
	and isStarCity() with no visibility check, while deliberately gating the food
	and production bars beside them on canBeSelected(). Nothing about a city's
	insides is exported because nothing about it is shown.

	ownerId comes from the loop rather than a second getOwner() call, and is the
	real owner: cities have no visual-owner equivalent to disguise them.'''
	row = _Record(('x', 'y'))
	row['x'] = city.getX()
	row['y'] = city.getY()
	row['owner'] = ownerId
	# A wstring, like our own cities' names.
	row['name'] = city.getName()
	row['population'] = city.getPopulation()
	# The star on the nameplate: CvCity::isStarCity is literally "return
	# isCapital()", exported for the renderer and gated on neither team nor
	# visibility. Omitted when false, like the tile booleans.
	if city.isCapital():
		row['capital'] = True
	return row


def _escape(s):
	out = []
	for ch in s:
		if ch == '\\':
			out.append('\\\\')
		elif ch == '"':
			out.append('\\"')
		elif ch == '\n':
			out.append('\\n')
		elif ch == '\r':
			out.append('\\r')
		elif ch == '\t':
			out.append('\\t')
		elif ch < ' ':
			# JSON forbids raw control characters inside strings.
			out.append('\\u%04x' % ord(ch))
		else:
			out.append(ch)
	return ''.join(out)


## A container is kept on one line if its rendered form fits within this width;
## otherwise it's broken across lines. Keeps short dicts and flat lists (knownTechs)
## readable instead of exploding every value onto its own line.
_MAX_INLINE_WIDTH = 88


class _Record(dict):
	'''A dict the serializer renders on one line, with `leading` keys written first.

	For rows in a long homogeneous table - map tiles - where the point is to scan
	down a column of alike lines and diff them turn to turn. Measured against a
	realistic turn-20 reveal, about three quarters of tiles exceed _MAX_INLINE_WIDTH,
	so without the always-inline behaviour the section would come out as a ragged mix
	of one-liners and exploded objects: the worst of both.

	A marker rather than a bigger _MAX_INLINE_WIDTH because the width is doing real
	work elsewhere - raising it far enough to fit a tile would also collapse
	`research` and change how every existing section renders. Subclasses dict, so
	isinstance checks and the rest of the serializer treat it as one.

	`leading` is a fixed tuple of key names to put at the front, in that order, with
	everything else sorted after them as usual. It exists so a tile can lead with its
	coordinates: plain alphabetical order buries x and y at the end of the line, past
	the fields they identify. This does NOT weaken the determinism that makes exports
	diffable turn to turn - that needs a FIXED key order, not an alphabetical one,
	and a constant tuple followed by a sort is just as fixed.'''

	def __init__(self, leading=()):
		dict.__init__(self)
		self.leading = leading


def toJson(value, indent=0):
	'''Serialize to JSON. indent=0 gives one compact line; indent>0 pretty-prints
	with that many spaces per level. Dict keys are sorted so that repeated exports
	of the same state produce byte-identical output (Python 2.4 dicts have no
	insertion order), which makes turn-to-turn diffs meaningful. A _Record may pin
	a few keys ahead of the sorted rest - still a fixed order, see _orderedKeys.'''
	return _toJson(value, indent, 0)


def _toJson(value, indent, level):
	if value is None:
		return 'null'
	if value is True:
		return 'true'
	if value is False:
		return 'false'
	if isinstance(value, (int, long, float)):
		return str(value)
	if isinstance(value, basestring):
		return '"%s"' % _escape(value)
	if isinstance(value, dict):
		if not value:
			return '{}'
		keys = _orderedKeys(value)
		items = []
		for key in keys:
			# str() only for rendering - `key` itself must stay untouched, or the
			# value lookup below misses for any non-string key.
			renderedKey = key
			if not isinstance(renderedKey, basestring):
				renderedKey = str(renderedKey)
			items.append('"%s": %s' % (_escape(renderedKey), _toJson(value[key], indent, level + 1)))
		if isinstance(value, _Record):
			return '{' + ', '.join(items) + '}'
		return _joinItems(items, '{', '}', indent, level)
	if isinstance(value, (list, tuple)):
		if not value:
			return '[]'
		items = [_toJson(item, indent, level + 1) for item in value]
		return _joinItems(items, '[', ']', indent, level)
	raise TypeError('AdvisorStateWriter.toJson: unsupported type %s' % type(value))


def _orderedKeys(value):
	'''Key order for one dict: a _Record's `leading` keys first, then the rest sorted.

	Sorting is what makes two exports of the same state byte-identical, since Python
	2.4 dicts have no insertion order - see toJson. A _Record's fixed leading tuple
	is equally deterministic, just not alphabetical.'''
	# list() around keys() is redundant in 2.4 but keeps this serializer runnable
	# under Python 3 too, so it can be unit-tested outside the game (see mod/README.md).
	keys = list(value.keys())
	keys.sort()
	leading = getattr(value, 'leading', ())
	if not leading:
		return keys
	ordered = []
	for key in leading:
		# Absent keys are normal: tile fields are omitted at their defaults.
		if key in value:
			ordered.append(key)
			keys.remove(key)
	return ordered + keys


def _joinItems(items, opener, closer, indent, level):
	oneLine = opener + ', '.join(items) + closer
	if indent <= 0:
		return oneLine
	# An item containing a newline was itself broken across lines, so this
	# container has to be too, however short it looks.
	if len(oneLine) <= _MAX_INLINE_WIDTH and oneLine.find('\n') == -1:
		return oneLine
	pad = ' ' * (indent * (level + 1))
	return opener + '\n' + pad + (',\n' + pad).join(items) + '\n' + ' ' * (indent * level) + closer


def writeStateFile(path, state):
	'''Write state (a dict) to path as JSON via a temp file, then rename over the target.

	No-ops when path is None, which is what getTurnFilePath() returns if LocalConfig
	is missing - a machine without it should not crash, just not export.

	On the "atomic" claim: os.rename() fails on Windows when the target exists, and
	Python 2.4 has no atomic replace (os.replace is Python 3 only, and ctypes only
	arrived in 2.5), so the old file is removed first. That leaves a brief window
	where the state file is ABSENT - but never one where it is half-written, which
	is the case the harness actually has to be protected from. A missing file is
	trivially detectable and retryable; a truncated one silently parses as garbage.'''
	if path is None:
		return
	stateDir = os.path.dirname(path)
	if not os.path.exists(stateDir):
		os.makedirs(stateDir)
	text = toJson(state, INDENT) + '\n'
	if isinstance(text, unicode):
		# Game strings (city names, etc.) come back as wstrings, so any state
		# containing one makes the whole rendered document unicode. JSON's default
		# encoding is UTF-8. Written in binary mode so the bytes on disk are exactly
		# these and Windows doesn't silently rewrite the line endings.
		text = text.encode('utf-8')
	tempPath = path + '.tmp'
	f = open(tempPath, 'wb')
	try:
		f.write(text)
	finally:
		f.close()
	if os.path.exists(path):
		os.remove(path)
	os.rename(tempPath, path)
