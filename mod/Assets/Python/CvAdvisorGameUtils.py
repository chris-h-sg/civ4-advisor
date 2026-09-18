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
## SPIKE SCOPE (docs/AI_OPPONENT_PLAN.md, "Spike: AI_chooseTech only", adapted to
## AI_chooseProduction): prove that overriding one AI callback for one AI player
## sticks, by always choosing the same unit. No LLM, no watcher, no plan files -
## the "decision" is a hardcoded constant. Every other AI_* callback falls through
## to stock (return 0) untouched.

from CvPythonExtensions import *
import CvUtil
import CvGameUtils

gc = CyGlobalContext()

## Cheap and available turn 1 in every ruleset checked - good enough for "does the
## callback fire and stick", which is all this spike needs to prove.
SPIKE_UNIT_KEY = 'UNIT_WARRIOR'


def _advisorPlayerId():
	'''Engine player id of the AI civ we're driving this spike for, or None.

	None whenever MODE isn't 'opponent' or AI_OPPONENT_PLAYER_KEY isn't set, which
	folds the mode check into the identity check per AI_OPPONENT_PLAN.md "Mode
	gating" - no separate "is opponent mode on" branch needed on the hot path.
	Matched by leader type per AI_OPPONENT_PLAN.md "Targeting one AI only" (the
	scriptData tagging trick is for the real loop, not this spike).'''
	try:
		import LocalConfig
	except ImportError:
		return None
	if getattr(LocalConfig, 'MODE', 'advisor') != 'opponent':
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


class CvAdvisorGameUtils(CvGameUtils.CvGameUtils):

	def AI_chooseProduction(self, argsList):
		pCity = argsList[0]
		try:
			advisorPlayerId = _advisorPlayerId()
			if advisorPlayerId is not None and pCity.getOwner() == advisorPlayerId:
				unitType = gc.getInfoTypeForString(SPIKE_UNIT_KEY)
				if unitType != -1:
					# Signature is (eOrder, iData1, iData2, bSave, bPop, bAppend,
					# bForce) - verified against CvCity::pushOrder in the bundled
					# SDK source (CvCity.cpp), not assumed from position. iData2=-1
					# (no specific unit AI - the engine fills in the unit's default).
					# CvCityAI::AI_chooseProduction (CvCityAI.cpp) already calls
					# clearOrderQueue() before invoking this callback, so the queue
					# is empty here regardless; bPop=True is defensive, not load-
					# bearing. bForce=False: UNIT_WARRIOR should be legitimately
					# trainable, so there's no reason to bypass canTrain.
					pCity.pushOrder(OrderTypes.ORDER_TRAIN, unitType, -1, False, True, False, False)
					CvUtil.pyPrint('civ4-advisor (opponent spike): forced %s in city %s (player %d)'
						% (SPIKE_UNIT_KEY, pCity.getName(), advisorPlayerId))
					return 1
		except:
			# Never crash or hang the game - fall through to stock AI on any failure.
			try:
				CvUtil.pyPrint('civ4-advisor (opponent spike): AI_chooseProduction FAILED, falling through')
			except:
				pass
		return CvGameUtils.CvGameUtils.AI_chooseProduction(self, argsList)
