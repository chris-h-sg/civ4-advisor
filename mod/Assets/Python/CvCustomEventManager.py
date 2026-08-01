## CvCustomEventManager
## civ4-advisor mod. Contains only our added logic - subclasses the base game's
## CvEventManager rather than copying/modifying it directly, per community convention
## (see CLAUDE.md "Design decisions" and REFERENCES.md). Base game behavior is
## preserved by calling the superclass method first in every override.
##
## Wired in via Assets/Python/EntryPoints/CvEventInterface.py, which points
## normalEventManager at this class instead of the base CvEventManager.

from CvPythonExtensions import *
import os
import sys
import traceback
import CvUtil
import CvEventManager
import AdvisorStateWriter

gc = CyGlobalContext()


def _findSource(moduleName):
	'''Absolute path of moduleName's .py, or None if it can't be located.

	Neither of the two ways you would normally find this works in the embedded
	interpreter, both verified in-game rather than assumed:
	  - __file__ is reported relative to the engine's own Assets/Python search
	    root, not the real physical location (see AdvisorStateWriter).
	  - sys.path holds nothing os.path can resolve either - measured 2026-08-01,
	    every entry failed os.path.isfile.
	So the real answer comes from LocalConfig.MOD_PYTHON_DIR. sys.path is still
	tried afterwards on the chance it resolves on someone else's install.'''
	fileName = moduleName + '.py'
	roots = []
	try:
		import LocalConfig
		roots.append(getattr(LocalConfig, 'MOD_PYTHON_DIR', None))
	except ImportError:
		# No LocalConfig on this machine: not an error, just no hot-reload.
		pass
	roots.extend(sys.path)
	for root in roots:
		if not root:
			continue
		try:
			candidate = os.path.join(root, fileName)
			if os.path.isfile(candidate):
				return os.path.abspath(candidate)
		except:
			# A malformed path entry must not stop the search.
			continue
	return None


def _refreshStateWriter():
	'''Re-read AdvisorStateWriter.py from disk. Returns a short note on how, for the log.

	reload() alone does NOT reliably work in this interpreter. Measured 2026-08-01:
	the source was edited at 23:10:27, an export ran at 23:12:56, reload() raised
	nothing, and the output was still the pre-edit format - stale code, silently.
	python24.dll is stock CPython, so reload() itself is the standard one; the
	suspect is the engine's own import hook serving cached module source.

	So try to sidestep the import system entirely: locate the real file and
	execfile() it straight into the existing module's namespace. Same module
	object, so AdvisorStateWriter.<anything> elsewhere keeps working; the
	functions inside it are simply rebound from current source text.

	Falls back to reload() when the file can't be located (no LocalConfig, or no
	MOD_PYTHON_DIR in it), which is no worse than what we had.'''
	path = _findSource('AdvisorStateWriter')
	if path is None:
		reload(AdvisorStateWriter)
		return 'reload() fallback - source not locatable, set MOD_PYTHON_DIR in LocalConfig.py'
	execfile(path, AdvisorStateWriter.__dict__)
	return 'execfile %s' % path


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
		self._exportState(gc.getGame().getGameTurn(), gc.getGame().getActivePlayer(), 'onGameStart')

	def onLoadGame(self, argsList):
		result = CvEventManager.CvEventManager.onLoadGame(self, argsList)
		# onGameStart only fires for a brand new game, not a loaded save - a common
		# gotcha per community docs (see REFERENCES.md). Without this, resuming a save
		# would silently miss its first state export until the player's next full
		# turn-processing cycle (see onEndGameTurn below).
		CvUtil.pyPrint('civ4-advisor: exporting state at onLoadGame')
		self._exportState(gc.getGame().getGameTurn(), gc.getGame().getActivePlayer(), 'onLoadGame')
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
		self._exportState(iGameTurn + 1, gc.getGame().getActivePlayer(), 'onEndGameTurn')

	def _exportState(self, gameTurn, playerId, trigger):
		'''State export must never crash or hang the game - any failure here is swallowed
		so a turn can always proceed.

		Deliberately thin: it only passes through the few facts the hooks know
		(which turn, which player, which hook fired) and leaves ALL schema and
		extraction logic to AdvisorStateWriter, which _refreshStateWriter re-reads
		just below, so it can be edited without restarting the game. Growing this
		method would move logic into the one file that can't be refreshed: the
		engine already holds a CvCustomEventManager instance built from the old
		class, and nothing can retroactively re-class it, so edits HERE always
		need a full game restart.'''
		try:
			# Dev convenience: pick up edits to AdvisorStateWriter.py without
			# restarting the game. NOT to LocalConfig.py, which it imports -
			# that still comes from the import cache. See _refreshStateWriter
			# on why this isn't just reload().
			how = _refreshStateWriter()
			CvUtil.pyPrint('civ4-advisor: refreshed state writer via %s' % how)
			state = AdvisorStateWriter.buildState(gameTurn, playerId, trigger)
			AdvisorStateWriter.writeStateFile(AdvisorStateWriter.getStateFilePath(), state)
		except:
			# Swallowed so a failed export can never block a turn - but logged, because
			# a silent failure is otherwise indistinguishable from the mod not running
			# at all. Lands in Logs\PythonDbg.log (needs LoggingEnabled=1, see mod/README.md).
			# The logging itself is guarded too: it must not turn a failed export into
			# a crash, which is the one thing this handler exists to prevent.
			try:
				CvUtil.pyPrint('civ4-advisor: state export FAILED at %s\n%s' % (trigger, traceback.format_exc()))
			except:
				pass
