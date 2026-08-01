# Sid Meier's Civilization 4
# Copyright Firaxis Games 2005
#
# CvEventInterface.py
#
# These functions are App Entry Points from C++
# WARNING: These function names should not be changed
# WARNING: These functions can not be placed into a class
#
# No other modules should import this
#
# civ4-advisor: only change from the base file is importing CvCustomEventManager
# instead of CvEventManager, and instantiating that instead - per community
# convention (see CLAUDE.md "Design decisions" and REFERENCES.md), the four
# functions below are otherwise untouched.
import CvUtil
import CvCustomEventManager
from CvPythonExtensions import *

normalEventManager = CvCustomEventManager.CvCustomEventManager()

def getEventManager():
	return normalEventManager

def onEvent(argsList):
	'Called when a game event happens - return 1 if the event was consumed'
	return getEventManager().handleEvent(argsList)

def applyEvent(argsList):
	context, playerID, netUserData, popupReturn = argsList
	return getEventManager().applyEvent(argsList)

def beginEvent(context, argsList=-1):
	return getEventManager().beginEvent(context, argsList)
