## CvAdvisorGameUtils
## civ4-advisor mod, ai-opponent spike. Contains only our added logic - subclasses
## the base game's CvGameUtils rather than copying/modifying it, same convention
## CvCustomEventManager already follows for CvEventManager (see CLAUDE.md "Design
## decisions"). Every override calls the superclass method for any player/city we
## are not driving, so stock AI behavior is unchanged.
##
## Wired in via Assets/Python/EntryPoints/CvGameInterfaceFile.py, which points
## GameUtils at this class instead of the base CvGameUtils. This is a different
## indirection point from CvEventInterface.py (which the advisor mod already
## modifies) - see docs/AI_OPPONENT_PLAN.md "The two entry points don't collide".
##
## SPIKE SCOPE (docs/AI_OPPONENT_PLAN.md, item C): AI_chooseTech is a real Claude
## call - the first callback in this mod backed by an actual LLM decision rather
## than a human-edited stand-in. AI_chooseProduction, by contrast, is back to
## stock (returns 0 unconditionally) - the earlier hardcoded-Warrior/external-
## process spike proved the round-trip mechanism and is retired now that
## AI_chooseTech carries it for real; re-introducing production would double the
## callback surface this task needs to reason about for no new proof.
##
## AI_chooseTech calls out to ai-opponent/decide_tech.py (Python 3) synchronously
## via os.popen - same mechanism decide_production.py proved live, same
## "blocking call inside the callback" tradeoff accepted for this spike (see
## docs/AI_OPPONENT_PLAN.md item C and "Spike: external-process round-trip").
## decide_tech.py reads the latest exported turn_NNNN.json for the current game,
## calls `claude -p`, and prints a single TECH_ key to stdout.
##
## RETURN-CONTRACT TRAP (AI_OPPONENT_PLAN.md "B2"): AI_chooseTech returns a
## TechTypes int, not a 1/0 boolean - CvPlayerAI does
## `eBestTech = (TechTypes)lResult` and only falls back to stock AI_bestTech() on
## NO_TECH (-1). Returning True/False here would silently order tech 0.

from CvPythonExtensions import *
import CvUtil
import CvGameUtils
import os
import time

gc = CyGlobalContext()

## ai-opponent/ lives at the repo root, i.e. two levels up from mod/Assets/Python
## (this file's deployed location, via the mod/ -> Mods junction - see CLAUDE.md
## "Paths can't be derived at runtime" for why LocalConfig.MOD_PYTHON_DIR, not
## __file__, is the source of truth for repo-relative paths in this interpreter).
DECIDE_TECH_SCRIPT_NAME = 'decide_tech.py'

## Wall-clock budget for the external process, documented rather than
## code-enforced (see _decideTech). Real Claude calls measured 71-142s wall
## clock (AI_OPPONENT_PLAN.md item D); this is a margin above that, not a
## timeout os.popen can actually enforce in Python 2.4 (see _decideTech).
DECIDE_TIMEOUT_SECONDS = 180

NO_TECH = -1


def opponentModeActive():
	'''True when LocalConfig.MODE drives an AI opponent - either 'opponent' alone
	or 'both' alongside the advisor. Shared by CvCustomEventManager (gates the
	human-facing export) and this module's own AI_chooseTech gating, so the
	two modules agree on what "opponent mode is on" means without duplicating the
	LocalConfig lookup.'''
	try:
		import LocalConfig
	except ImportError:
		return False
	return getattr(LocalConfig, 'MODE', 'advisor') in ('opponent', 'both')


def advisorModeActive():
	'''True when LocalConfig.MODE keeps the advisor's own (human-player) export
	running - either 'advisor' (the default) or 'both'.'''
	try:
		import LocalConfig
	except ImportError:
		return True
	return getattr(LocalConfig, 'MODE', 'advisor') in ('advisor', 'both')


def _advisorPlayerId():
	'''Engine player id of the AI civ we're driving this spike for, or None.

	None whenever opponent mode isn't active or AI_OPPONENT_PLAYER_KEY isn't set,
	which folds the mode check into the identity check per AI_OPPONENT_PLAN.md
	"Mode gating" - no separate "is opponent mode on" branch needed on the hot
	path. Matched by leader type per AI_OPPONENT_PLAN.md "Targeting one AI only"
	(the scriptData tagging trick is for the real loop, not this spike).'''
	if not opponentModeActive():
		return None
	try:
		import LocalConfig
	except ImportError:
		return None
	leaderKey = getattr(LocalConfig, 'AI_OPPONENT_PLAYER_KEY', None)
	if not leaderKey:
		return None
	try:
		leaderType = gc.getInfoTypeForString(leaderKey)
	except:
		return None
	if leaderType == -1:
		return None
	# getMAX_PLAYERS(), not getMAX_CIV_PLAYERS() - see AdvisorStateWriter._otherPlayers
	# for why that bound is the one already verified correct in this codebase. The
	# barbarian slot never matches here since it has no leader type to compare.
	for i in range(gc.getMAX_PLAYERS()):
		player = gc.getPlayer(i)
		if player.isAlive() and not player.isHuman() and player.getLeaderType() == leaderType:
			return i
	return None


def _repoRoot():
	'''Repo root, derived from LocalConfig.MOD_PYTHON_DIR (mod/Assets/Python), or
	None if that setting is missing. See the module docstring above for why this
	is read from LocalConfig rather than __file__ - the same dead end CLAUDE.md
	already documents for MOD_PYTHON_DIR itself.'''
	try:
		import LocalConfig
	except ImportError:
		return None
	modPythonDir = getattr(LocalConfig, 'MOD_PYTHON_DIR', None)
	if not modPythonDir:
		return None
	# mod/Assets/Python -> repo root is three levels up.
	return os.path.dirname(os.path.dirname(os.path.dirname(modPythonDir)))


def _decideTech(playerId):
	'''Blocking round-trip to the external decide_tech.py - see module
	docstring for why that's acceptable here and not in the real loop. Returns
	a tech type key string, or None on any failure (missing repo root, missing
	script, spawn failure, empty output). Uses os.popen, same mechanism
	decide_production.py proved live; see docs/AI_OPPONENT_PLAN.md item C for
	the os.spawnv alternative this was checked against.

	playerId is passed as a command-line argument so decide_tech.py can find
	the right game's latest state file without guessing - see that script for
	how it locates state/<leader>_<gameId>/.'''
	repoRoot = _repoRoot()
	if not repoRoot:
		return None
	scriptPath = os.path.join(repoRoot, 'ai-opponent', DECIDE_TECH_SCRIPT_NAME)
	if not os.path.isfile(scriptPath):
		return None
	# DECIDE_TIMEOUT_SECONDS above is not enforced here - os.popen has no
	# timeout in Python 2.4 without threading. A hang is a finding to report,
	# not something to route around silently (same as the production spike).
	# Timed from just before the spawn to after the pipe closes, so the logged
	# figure is the whole freeze the game sees; decide_tech_log.jsonl's
	# `timing.total` covers the same call from inside the child, and the
	# difference is the spawn itself (docs/AI_OPPONENT_PLAN.md "Timing and
	# performance").
	start = time.time()
	pipe = os.popen('python "%s" %d' % (scriptPath, playerId), 'r')
	try:
		output = pipe.read()
	finally:
		pipe.close()
		CvUtil.pyPrint('civ4-advisor (opponent spike): decide_tech round trip %.3fs' % (time.time() - start))
	techKey = output.strip()
	if not techKey:
		return None
	return techKey


class CvAdvisorGameUtils(CvGameUtils.CvGameUtils):

	def AI_chooseTech(self, argsList):
		ePlayer, bFree = argsList
		try:
			advisorPlayerId = _advisorPlayerId()
			if advisorPlayerId is not None and ePlayer == advisorPlayerId:
				techKey = _decideTech(ePlayer)
				if techKey:
					techType = gc.getInfoTypeForString(techKey)
					# Validate before trusting: must resolve, and must not already
					# be known - is_error: false from the external process is not a
					# validity check (AI_OPPONENT_PLAN.md item D), and a fluent,
					# well-formed, already-known tech is a real failure mode, not a
					# hypothetical one.
					if techType != NO_TECH and not gc.getTeam(gc.getPlayer(ePlayer).getTeam()).isHasTech(techType):
						CvUtil.pyPrint('civ4-advisor (opponent spike): AI_chooseTech ordering %s for player %d, via external process'
							% (techKey, advisorPlayerId))
						return techType
					CvUtil.pyPrint('civ4-advisor (opponent spike): external process gave unusable tech key %s, falling through' % techKey)
		except:
			# Never crash or hang the game - fall through to stock AI on any failure.
			try:
				CvUtil.pyPrint('civ4-advisor (opponent spike): AI_chooseTech FAILED, falling through')
			except:
				pass
		return CvGameUtils.CvGameUtils.AI_chooseTech(self, argsList)
