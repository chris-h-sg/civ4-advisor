## CvCustomEventManager
## civ4-advisor mod. Contains only our added logic - subclasses the base game's
## CvEventManager rather than copying/modifying it directly, per community convention
## (see CLAUDE.md "Design decisions" and REFERENCES.md). Base game behavior is
## preserved by calling the superclass method first in every override.
##
## Wired in via Assets/Python/EntryPoints/CvEventInterface.py, which points
## normalEventManager at this class instead of the base CvEventManager.

from CvPythonExtensions import *
import CvUtil
import CvEventManager
import AdvisorStateWriter

gc = CyGlobalContext()


class CvCustomEventManager(CvEventManager.CvEventManager):

	def onGameStart(self, argsList):
		CvEventManager.CvEventManager.onGameStart(self, argsList)
		# onBeginPlayerTurn/onEndGameTurn (see below) do not bound the player's actual
		# interactive turn and never fire for the game's true first turn - there's no
		# "control returned to human" transition at game start. This is the only hook
		# that fires before the player has acted on turn 0, so it's the right place to
		# export that turn's state. Confirmed via in-game instrumentation and community
		# docs (TGA's Python Tutorial - see REFERENCES.md) - not documented turn-number
		# semantics assumed from the API reference.
		CvUtil.pyPrint('civ4-advisor: exporting state at onGameStart')
		self._exportState(gc.getGame().getGameTurn(), gc.getGame().getActivePlayer())

	def onLoadGame(self, argsList):
		result = CvEventManager.CvEventManager.onLoadGame(self, argsList)
		# onGameStart only fires for a brand new game, not a loaded save - a common
		# gotcha per community docs (see REFERENCES.md). Without this, resuming a save
		# would silently miss its first state export until the player's next full
		# turn-processing cycle (see onEndGameTurn below).
		CvUtil.pyPrint('civ4-advisor: exporting state at onLoadGame')
		self._exportState(gc.getGame().getGameTurn(), gc.getGame().getActivePlayer())
		return result

	def onEndGameTurn(self, argsList):
		CvEventManager.CvEventManager.onEndGameTurn(self, argsList)
		# onEndGameTurn fires LAST in a round's processing - after the human player AND
		# every AI civ have each had their own onBeginPlayerTurn/onEndPlayerTurn pair
		# fire (confirmed via in-game file-based instrumentation; also matches community
		# docs stating onBeginGameTurn/onEndGameTurn both fire at turn end, not
		# beginning - see REFERENCES.md). That makes this the freshest available
		# snapshot of "what the player is about to see" when they regain control -
		# no hook fires at that exact moment, since control returns silently. iGameTurn
		# here is the round that just finished, hence +1 to label state for the round
		# about to start (matching onGameStart/onLoadGame's numbering, which need no
		# adjustment since they fire before any turn has been processed).
		iGameTurn = argsList[0]
		CvUtil.pyPrint('civ4-advisor: exporting state at onEndGameTurn (turn %d finished)' % iGameTurn)
		self._exportState(iGameTurn + 1, gc.getGame().getActivePlayer())

	def _exportState(self, gameTurn, playerId):
		'State export must never crash or hang the game - any failure here is swallowed so a turn can always proceed.'
		try:
			reload(AdvisorStateWriter)  # dev convenience - edits to AdvisorStateWriter.py (and LocalConfig.py, which it imports) take effect next turn without restarting the game. Does NOT help for this file - the engine already holds a reference to an instantiated CvCustomEventManager built from the old class, which reload() can't retroactively update.
			state = {
				'gameTurn': gameTurn,
				'playerId': playerId,
			}
			AdvisorStateWriter.writeStateFile(AdvisorStateWriter.getStateFilePath(), state)
		except:
			pass
