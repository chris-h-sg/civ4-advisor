"""Spike stand-in for the real decision process (docs/AI_OPPONENT_PLAN.md, item C).

Called synchronously by the mod's AI_chooseProduction override, once per build
decision. Reads decision_config.txt (same directory) for a single unit type key
and prints it to stdout - nothing else on stdout, since the mod reads the whole
thing as the answer. No LLM, no JSON schema, no validation: that's deliberately
out of scope for this spike, which only proves the process round-trip works.

Hand-edit decision_config.txt mid-game to change what gets built without
restarting Civ 4.

Can sleep DECISION_DELAY_SECONDS before answering, as a stand-in for real LLM
latency (docs/AI_OPPONENT_PLAN.md item D measured 71-142s wall clock per
call) - useful for checking whether anything in the round-trip (os.popen, the
callback, the game itself) has a timeout shorter than that. 0 by default so
routine testing (e.g. the ai-opponent-mode export spike) isn't paying for it.
"""

import os
import sys
import time

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'decision_config.txt')
DECISION_DELAY_SECONDS = 0


def main():
    if DECISION_DELAY_SECONDS:
        time.sleep(DECISION_DELAY_SECONDS)
    try:
        configFile = open(CONFIG_PATH, 'r')
        try:
            unitKey = configFile.read().strip()
        finally:
            configFile.close()
    except IOError:
        sys.stderr.write('decide_production.py: could not read %s\n' % CONFIG_PATH)
        sys.exit(1)

    if not unitKey:
        sys.stderr.write('decide_production.py: %s is empty\n' % CONFIG_PATH)
        sys.exit(1)

    sys.stdout.write(unitKey)


if __name__ == '__main__':
    main()
