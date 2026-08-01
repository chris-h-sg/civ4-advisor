## AdvisorStateWriter
## State extraction, hand-rolled JSON serialization, and atomic file writes for the
## civ4-advisor mod. Python 2.4 has no `json` module, so this is a minimal serializer
## covering only the value types we actually pass in: dict, list, str, int, float,
## bool, None.
##
## All schema/extraction logic lives here rather than in CvCustomEventManager because
## this module is re-read from disk on every export - edits take effect next turn
## without restarting the game, which the event manager can't do at any price. Note
## that is NOT plain reload(), which silently does nothing in this interpreter; see
## CvCustomEventManager._refreshStateWriter.

import os

from CvPythonExtensions import *

## Bumped only on breaking changes to the state format - see schema/state.schema.json.
SCHEMA_VERSION = 1

## Spaces per indent level in the output file. Pretty-printed rather than compact so
## a turn's export can be eyeballed against what the game UI actually shows.
INDENT = 2


def getStateFilePath():
	'''State output path comes from LocalConfig.py (gitignored, machine-specific - see
	LocalConfig.py.example). __file__-relative path derivation was tried and does not
	work here: the embedded interpreter reports module paths relative to its own
	Assets/Python search root regardless of which physical folder (base game vs. mod,
	even through the junction) actually supplied the file.

	Note this module is re-read from disk on every export, but LocalConfig is NOT -
	it comes back from the import cache, so editing LocalConfig.py needs a game
	restart. Don't add reload(LocalConfig) to "fix" that; reload() silently does
	nothing here (see CvCustomEventManager._refreshStateWriter).'''
	try:
		import LocalConfig
	except ImportError:
		return None
	return LocalConfig.STATE_FILE_PATH


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
		self.team = self.gc.getTeam(self.player.getTeam())


def buildState(gameTurn, playerId, trigger):
	'''Build the state dict described by schema/state.schema.json.

	Only meta/game/player are implemented so far (build order is recorded in
	CLAUDE.md). The not-yet-implemented sections are deliberately OMITTED rather
	than written as empty lists: an empty `units` array would be indistinguishable
	from "this player genuinely has no units". Consequence: output does not validate
	against the full schema until every section is implemented. That's expected
	during the incremental build, not a bug.'''
	ctx = _Context(playerId)
	return {
		'meta': {
			'schemaVersion': SCHEMA_VERSION,
			'trigger': trigger,
		},
		'game': _buildGame(ctx, gameTurn),
		'player': _buildPlayer(ctx),
	}


def _buildGame(ctx, gameTurn):
	return {
		'gameTurn': gameTurn,
		# getTurnYear(n) rather than getGameTurnYear() so the year matches the turn
		# we're labelling this export with - at onEndGameTurn those differ by one
		# (see CvCustomEventManager.onEndGameTurn on the +1).
		'year': ctx.game.getTurnYear(gameTurn),
		# Era is the player's own current era, not the game's start era.
		'era': ctx.gc.getEraInfo(ctx.player.getCurrentEra()).getType(),
		'gameSpeed': ctx.gc.getGameSpeedInfo(ctx.game.getGameSpeedType()).getType(),
		'mapWidth': ctx.cyMap.getGridWidth(),
		'mapHeight': ctx.cyMap.getGridHeight(),
		# bool() because these come back from the C++ bindings as ints, and the
		# serializer would emit those as 0/1 rather than JSON true/false.
		'wrapX': bool(ctx.cyMap.isWrapX()),
		'wrapY': bool(ctx.cyMap.isWrapY()),
	}


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
		'turnsLeft': None,
		'sciencePercent': ctx.player.getCommercePercent(CommerceTypes.COMMERCE_RESEARCH),
	}
	if iTech != TechTypes.NO_TECH:
		research['current'] = ctx.gc.getTechInfo(iTech).getType()
		# bOverflow=True to match the turn count the game's own UI displays, which
		# credits leftover beakers from the previously completed tech.
		research['turnsLeft'] = ctx.player.getResearchTurnsLeft(iTech, True)
	return research


def _buildKnownTechs(ctx):
	'Techs are known per-team, not per-player.'
	techs = []
	for i in range(ctx.gc.getNumTechInfos()):
		if ctx.team.isHasTech(i):
			techs.append(ctx.gc.getTechInfo(i).getType())
	return techs


def _buildCivics(ctx):
	'Maps each civic option (government, legal, ...) to the civic currently run in it.'
	civics = {}
	for i in range(ctx.gc.getNumCivicOptionInfos()):
		iCivic = ctx.player.getCivics(i)
		if iCivic != CivicTypes.NO_CIVIC:
			civics[ctx.gc.getCivicOptionInfo(i).getType()] = ctx.gc.getCivicInfo(iCivic).getType()
	return civics


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


def toJson(value, indent=0):
	'''Serialize to JSON. indent=0 gives one compact line; indent>0 pretty-prints
	with that many spaces per level. Dict keys are sorted so that repeated exports
	of the same state produce byte-identical output (Python 2.4 dicts have no
	insertion order), which makes turn-to-turn diffs meaningful.'''
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
		# list() around keys() is redundant in 2.4 but keeps this serializer runnable
		# under Python 3 too, so it can be unit-tested outside the game (see mod/README.md).
		keys = list(value.keys())
		keys.sort()
		items = []
		for key in keys:
			# str() only for rendering - `key` itself must stay untouched, or the
			# value lookup below misses for any non-string key.
			renderedKey = key
			if not isinstance(renderedKey, basestring):
				renderedKey = str(renderedKey)
			items.append('"%s": %s' % (_escape(renderedKey), _toJson(value[key], indent, level + 1)))
		return _joinItems(items, '{', '}', indent, level)
	if isinstance(value, (list, tuple)):
		if not value:
			return '[]'
		items = [_toJson(item, indent, level + 1) for item in value]
		return _joinItems(items, '[', ']', indent, level)
	raise TypeError('AdvisorStateWriter.toJson: unsupported type %s' % type(value))


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
