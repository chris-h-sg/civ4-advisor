## DevHooks - development automation that runs INSIDE the game. Not part of the
## shipped mod: the mod only calls into this file when LocalConfig.DEV_HOOKS
## names it (see _runDevHook in CvCustomEventManager.py).
##
## Python 2.4, like the rest of the in-game code. Re-read from disk on every
## call, so edits apply without restarting the game. DEV_HOOKS_DIR is injected
## by the mod's loader - __file__ can't be trusted in the embedded interpreter.
##
## Everything is driven by a one-shot control file, devtools/runs/control.py,
## which the trial runner writes before launching the game. It is consumed
## (renamed to control.consumed.py) the moment a save loads, so it applies to
## exactly one load: loading one of your own saves later never autoplays.
##
## Recognised settings in control.py:
##   AUTOPLAY_TURNS = N               start N turns of AI autoplay
##   KILL_LEADERS = ['LEADER_X', ...] remove these civs first (e.g. the fourth
##                                    civ of a mirrored-map setup)

import os
from CvPythonExtensions import *
import CvUtil


def _controlPath():
	return os.path.join(os.path.dirname(DEV_HOOKS_DIR), 'runs', 'control.py')


def _consume(path):
	'''Read the control file and rename it out of the way. Windows os.rename
	fails when the target exists and Python 2.4 has no os.replace.'''
	settings = {}
	execfile(path, settings)
	consumed = path[:-len('.py')] + '.consumed.py'
	if os.path.exists(consumed):
		os.remove(consumed)
	os.rename(path, consumed)
	return settings


def _leaderKey(gc, player):
	return gc.getLeaderHeadInfo(player.getLeaderType()).getType()


def _logRoster(gc, label):
	'''One line per living civ: id, leader, team, human flag, and unit
	positions - enough to check a mirrored start from the log alone.'''
	lines = ['civ4-advisor devtools: roster %s' % label]
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if not p.isAlive():
			continue
		units = []
		unit, it = p.firstUnit(False)
		while unit:
			units.append('%s@%d,%d' % (gc.getUnitInfo(unit.getUnitType()).getType(), unit.getX(), unit.getY()))
			unit, it = p.nextUnit(it, False)
		units.sort()
		lines.append('  %d %s team=%d human=%d cities=%d units=%s' % (
			i, _leaderKey(gc, p), p.getTeam(), p.isHuman(), p.getNumCities(), ' '.join(units)))
	CvUtil.pyPrint('\n'.join(lines))


def _killLeaders(gc, leaderKeys):
	'''Remove every civ led by one of leaderKeys - the Python-console step the
	mirrored test setup used to need by hand. Both calls are required: a
	leftover Settler alone keeps a civ alive.'''
	for i in range(gc.getMAX_CIV_PLAYERS()):
		p = gc.getPlayer(i)
		if p.isAlive() and _leaderKey(gc, p) in leaderKeys:
			p.killCities()
			p.killUnits()
			CvUtil.pyPrint('civ4-advisor devtools: removed player %d (%s)' % (i, _leaderKey(gc, p)))


def onLoadGame():
	path = _controlPath()
	if not os.path.isfile(path):
		return
	settings = _consume(path)
	gc = CyGlobalContext()
	_logRoster(gc, 'at load')
	killLeaders = settings.get('KILL_LEADERS', [])
	if killLeaders:
		_killLeaders(gc, killLeaders)
	turns = settings.get('AUTOPLAY_TURNS', 0)
	if turns > 0:
		# Same as the cheat console's Game.AIPlay N: removes the human civ and
		# lets every AI play; when the count runs out the human is revived as a
		# single placeholder Lion.
		game = gc.getGame()
		game.setAIAutoPlay(turns)
		CvUtil.pyPrint('civ4-advisor devtools: setAIAutoPlay(%d) -> %d' % (turns, game.getAIAutoPlay()))
	_logRoster(gc, 'after setup')
