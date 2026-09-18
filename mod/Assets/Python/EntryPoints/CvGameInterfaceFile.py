# Sid Meier's Civilization 4
# Copyright Firaxis Games 2005
#
# This file allows you to reference a mod version of the GameInterface
#
# civ4-advisor: only change from the base file is instantiating
# CvAdvisorGameUtils instead of CvGameUtils - the base game ships this file
# specifically so a mod can do that without touching CvGameInterface.py itself
# (see its own "MODDERS" comment, and AI_OPPONENT_PLAN.md "The two entry points
# don't collide"). CvAdvisorGameUtils subclasses the base CvGameUtils and calls
# through to it for every AI_* callback we don't override, so stock behavior is
# unchanged unless LocalConfig.MODE == 'opponent'.
import CvAdvisorGameUtils
from CvPythonExtensions import *

GameUtils = CvAdvisorGameUtils.CvAdvisorGameUtils()
