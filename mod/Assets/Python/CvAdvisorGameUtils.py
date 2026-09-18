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
## SPIKE SCOPE (docs/AI_OPPONENT_PLAN.md, item C, external-process step): prove a
## synchronous, blocking round-trip to a separate Python 3 process from inside
## AI_chooseProduction. The "decision" is still hand-set by a human editing a
## plain text config file - ai-opponent/decision_config.txt - read by
## ai-opponent/decide_production.py, which prints the unit type key to stdout.
## No LLM, no JSON schema, no watcher/plan-file polling pattern. Deliberately a
## blocking call inside the callback rather than the poll-a-plan-file pattern
## item C otherwise describes - accepting "the game waits" over "the game might
## miss a turn" for this test only.

from CvPythonExtensions import *
import CvUtil
import CvGameUtils
import os

gc = CyGlobalContext()

## ai-opponent/ lives at the repo root, i.e. two levels up from mod/Assets/Python
## (this file's deployed location, via the mod/ -> Mods junction - see CLAUDE.md
## "Paths can't be derived at runtime" for why LocalConfig.MOD_PYTHON_DIR, not
## __file__, is the source of truth for repo-relative paths in this interpreter).
DECIDE_SCRIPT_NAME = 'decide_production.py'

## Wall-clock budget for the external process, documented rather than
## code-enforced (see _decideProduction). decide_production.py currently
## sleeps 5s before answering as a stand-in for real LLM latency, hence the
## margin above near-zero.
DECIDE_TIMEOUT_SECONDS = 10


def opponentModeActive():
	'''True when LocalConfig.MODE drives an AI opponent - either 'opponent' alone
	or 'both' alongside the advisor. Shared by CvCustomEventManager (gates the
	human-facing export) and this module's own AI_chooseProduction gating, so the
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


def _decideProduction():
	'''Blocking round-trip to the external decide_production.py - see module
	docstring for why that's acceptable here and not in the real loop. Returns
	a unit type key string, or None on any failure (missing repo root, spawn
	failure, non-zero exit, empty output). Uses os.popen, confirmed working
	in this interpreter; see docs/AI_OPPONENT_PLAN.md item C for the
	os.spawnv alternative this was checked against.'''
	repoRoot = _repoRoot()
	if not repoRoot:
		return None
	scriptPath = os.path.join(repoRoot, 'ai-opponent', DECIDE_SCRIPT_NAME)
	if not os.path.isfile(scriptPath):
		return None
	# DECIDE_TIMEOUT_SECONDS above is not enforced here - os.popen has no
	# timeout in Python 2.4 without threading. A hang is this spike's finding
	# to report, not something to route around silently.
	pipe = os.popen('python "%s"' % scriptPath, 'r')
	try:
		output = pipe.read()
	finally:
		pipe.close()
	unitKey = output.strip()
	if not unitKey:
		return None
	return unitKey


class CvAdvisorGameUtils(CvGameUtils.CvGameUtils):

	def AI_chooseProduction(self, argsList):
		pCity = argsList[0]
		try:
			advisorPlayerId = _advisorPlayerId()
			if advisorPlayerId is not None and pCity.getOwner() == advisorPlayerId:
				unitKey = _decideProduction()
				if unitKey:
					unitType = gc.getInfoTypeForString(unitKey)
					if unitType != -1:
						# Signature is (eOrder, iData1, iData2, bSave, bPop, bAppend,
						# bForce) - verified against CvCity::pushOrder in the bundled
						# SDK source (CvCity.cpp), not assumed from position. iData2=-1
						# (no specific unit AI - the engine fills in the unit's default).
						# CvCityAI::AI_chooseProduction (CvCityAI.cpp) already calls
						# clearOrderQueue() before invoking this callback, so the queue
						# is empty here regardless; bPop=True is defensive, not load-
						# bearing. bForce=False: an externally-chosen unit should be
						# legitimately trainable, so there's no reason to bypass
						# canTrain.
						pCity.pushOrder(OrderTypes.ORDER_TRAIN, unitType, -1, False, True, False, False)
						CvUtil.pyPrint('civ4-advisor (opponent spike): forced %s in city %s (player %d), via external process'
							% (unitKey, pCity.getName(), advisorPlayerId))
						return 1
				CvUtil.pyPrint('civ4-advisor (opponent spike): external process gave no usable unit key, falling through')
		except:
			# Never crash or hang the game - fall through to stock AI on any failure.
			try:
				CvUtil.pyPrint('civ4-advisor (opponent spike): AI_chooseProduction FAILED, falling through')
			except:
				pass
		return CvGameUtils.CvGameUtils.AI_chooseProduction(self, argsList)
