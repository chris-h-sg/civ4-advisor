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
##   SCORES_FILE = r'...\scores.csv'   append every AI civ's score at the end
##                                    of each round (onEndGameTurn)
##   DEFINES = {'NAME': value, ...}   override GlobalDefines integers with
##                                    setDefineINT before anything else runs.
##                                    Not saved with the game, and held for
##                                    the life of the game process, which the
##                                    trial runner closes at the end of a run.
##
## Dev-only, so the scores deliberately ignore fog of war: they are for judging
## a run, never for feeding a decision.

import os
import sys
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


def _applyDefines(gc, defines):
	for name in sorted(defines):
		before = gc.getDefineINT(name)
		gc.setDefineINT(name, defines[name])
		CvUtil.pyPrint('civ4-advisor devtools: define %s %d -> %d' % (name, before, gc.getDefineINT(name)))


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


# Per-process run state. This file is re-read on every call, so it can't hold
# state itself; an attribute on sys lives exactly as long as the game process,
# so a crashed or killed run can never leave it behind for a later game.
_RUN_STATE = '_civ4AdvisorDevRun'


def _writeScores(gc, path, turn):
	'''One row per living AI civ. The human slot is skipped: it is never a
	trial subject, and after autoplay ends it is only the placeholder Lion.
	So is a civ with nothing left: one removed by KILL_LEADERS still reads
	isAlive() until the engine's end-of-turn check.'''
	f = open(path, 'a')
	try:
		for i in range(gc.getMAX_CIV_PLAYERS()):
			p = gc.getPlayer(i)
			if p.isAlive() and not p.isHuman() and (p.getNumUnits() or p.getNumCities()):
				f.write('%d,%d,%s,%d\n' % (turn, i, _leaderKey(gc, p), gc.getGame().getPlayerScore(i)))
	finally:
		f.close()


def onEndGameTurn(iGameTurn):
	state = getattr(sys, _RUN_STATE, None)
	if not state or not state.get('scores'):
		return
	# +1: labelled like the turn files - the round that just ended produces
	# the state of the turn about to be played.
	_writeScores(CyGlobalContext(), state['scores'], iGameTurn + 1)


def onLoadGame():
	path = _controlPath()
	if not os.path.isfile(path):
		return
	settings = _consume(path)
	gc = CyGlobalContext()
	scores = settings.get('SCORES_FILE')
	setattr(sys, _RUN_STATE, {'scores': scores})
	if scores:
		f = open(scores, 'w')
		f.write('turn,player,leader,score\n')
		f.close()
	_applyDefines(gc, settings.get('DEFINES', {}))
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
	if scores:
		_writeScores(gc, scores, gc.getGame().getGameTurn())
