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
SCHEMA_VERSION = 1

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


def getStateFilePath():
	'Absolute path to write state to, or None when this machine has no LocalConfig.'
	return _localConfig('STATE_FILE_PATH', None)


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


def buildState(gameTurn, playerId, trigger):
	'''Build the state dict described by schema/state.schema.json.

	Only meta/game/player/units/cities/map are implemented so far (build order is
	recorded in CLAUDE.md). The not-yet-implemented sections are deliberately
	OMITTED rather than written as empty lists: an empty `contacts` array would be
	indistinguishable from a player who has met nobody. Consequence: output does
	not validate against the full schema until every section is implemented.
	That's expected during the incremental build, not a bug.

	Note that omission means two different things at two different levels: a
	missing SECTION means "not implemented yet", while a missing FIELD inside an
	implemented tile means "this field has its documented default" (see _buildTile).'''
	ctx = _Context(playerId)
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
	}
	# Timed separately from everything else: this is the only section whose cost
	# scales with how much of the map the player has uncovered.
	mapStarted = _clock()
	state['map'] = _buildMap(ctx)
	_reportTimings(mapStarted - started, _clock() - mapStarted, len(state['map']['tiles']))
	return state


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
	}


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


def _sortById(rows):
	'''Take (engineId, tieBreak, dict) tuples and return just the dicts, ID-ordered.

	Entities are sorted because the engine's own iteration order isn't documented as
	stable, and unsorted output would produce spurious turn-to-turn diffs - the same
	reason the serializer sorts dict keys.'''
	rows.sort()
	out = []
	for row in rows:
		out.append(row[2])
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
	return _sortById(rows)


def _buildUnit(ctx, unit):
	return {
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
		# Percentage of health lost, not hit points: 0 is unhurt, 100 is dead.
		'damage': unit.getDamage(),
	}


def _buildCities(ctx):
	'''The player's own cities.

	The isNone()/getOwner() filter mirrors the base game's PyHelpers.getCityList.'''
	rows = []
	city, cursor = ctx.player.firstCity(False)
	while city:
		if not city.isNone() and city.getOwner() == ctx.playerId:
			rows.append((city.getID(), len(rows), _buildCity(ctx, city)))
		city, cursor = ctx.player.nextCity(cursor, False)
	return _sortById(rows)


def _buildCity(ctx, city):
	producing = _buildProducing(ctx, city)
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
		# (bIgnoreFood=False, bOverflow=True) matches what the city screen shows:
		# food converted to hammers counts, and so does carried-over overflow from
		# the previous completed build (which makes this a one-turn figure, not a
		# steady rate, on the turn right after something finished).
		'productionPerTurn': city.getCurrentProductionDifference(False, True),
		# Culture is per-player within a city; the owner's share is the one that
		# counts against cultureThreshold for the next border pop.
		'culture': city.getCulture(ctx.playerId),
		'cultureThreshold': city.getCultureThreshold(),
		'happy': city.happyLevel(),
		'unhappy': city.unhappyLevel(0),
		'healthy': city.goodHealth(),
		'unhealthy': city.badHealth(False),
		'workedTiles': _buildWorkedTiles(ctx, city),
	}


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
	them. See _reportTimings.'''
	# calculateYield(bDisplay=True) below reads the ACTIVE team's revealed state
	# internally (verified in CvPlot::calculateYield - it calls getRevealedOwner /
	# getRevealedImprovementType / getRevealedRouteType against
	# GC.getGame().getActiveTeam(), not against any team we could pass). There is no
	# API to ask for another player's displayed yields. In single player that is
	# always the human - CvGame::setActivePlayer is called only from CvGame::read,
	# gated on !isGameMultiPlayer(), and never rotates while the AI civs take their
	# turns - so the assumption holds. But if it were ever violated we would silently
	# export someone else's view of the map, so fail loudly instead. _exportState
	# turns this into a logged traceback and no state file.
	activePlayerId = ctx.game.getActivePlayer()
	if ctx.playerId != activePlayerId:
		raise AssertionError(
			'refusing to export map for player %d while player %d is active: tile yields'
			' would be the active player\'s, not this one\'s' % (ctx.playerId, activePlayerId))
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

	No-ops when path is None, which is what getStateFilePath() returns if LocalConfig
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
