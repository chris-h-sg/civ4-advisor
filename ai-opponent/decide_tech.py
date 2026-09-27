"""Real Claude call for AI_chooseTech (docs/AI_OPPONENT_PLAN.md, item C).

Called synchronously by the mod's AI_chooseTech override, once per research
choice - far less often than AI_chooseProduction, so the blocking-freeze
tradeoff documented in the mod (see CvAdvisorGameUtils module docstring) is
accepted here. Same contract shape as decide_production.py: reads state,
prints exactly one bare answer to stdout, nothing else - here a single
TECH_ key instead of a unit key.

Usage: decide_tech.py <playerId>

playerId picks which player's own exported state to read (state files are
per-game, not per-player, but the game folder name embeds the leader, and the
mod always calls this for its own configured AI - the argument exists so this
script never has to guess which of possibly-several state/ subfolders is the
right game; see _find_latest_state_file). Not currently used to disambiguate
beyond "read the most recently modified game folder", since this spike's test
setup only ever has one game running at a time - see the mtime caveat below.

TWO-STEP FLOW, SCRIPT-SIDE FIRST: before ever calling Claude, this shells out
to `harness/rules.py tech --available` (no LLM involved - it's the mod's own
XML-prerequisite walk, run as a subprocess) to get the actual legal candidate
set for this exact game state, then hands Claude that menu to choose from
rather than asking it to invent a TECH_ key from scratch. This replaces an
earlier version that prompted from knownTechs alone: a live 120-turn run
found it twice proposed a tech missing a prerequisite (TECH_POTTERY without
TECH_THE_WHEEL, TECH_BRONZE_WORKING without TECH_MINING) and once a tech
already known - all silently swallowed by the mod's fall-through, so 3 of 12
research turns played on stock AI instead of the LLM's intended pick, with no
visible failure anywhere. Picking a name from a short printed list is also a
narrower task than free-form generation, which is expected to help with the
OTHER failure mode this run found: 5 of 12 calls broke the bare-key contract
by reasoning out loud ("TECH_AGRICULTURE... wait, that's already known...
TECH_WRITING") after noticing their first instinct was invalid - a list with
the invalid options already removed gives that reasoning nothing to trip on.

STRUCTURED OUTPUT, NOT A PROMPT REQUEST: `claude -p --output-format json
--json-schema ...` forces the response into a JSON object matching the given
schema - here {"tech": "TECH_..."}, with `tech` constrained to an `enum` of
exactly the candidate list. This replaces asking nicely in the prompt text
("no explanation, no punctuation, just the bare key"), which a live run
measured failing 5 of 12 times: Claude would notice its first instinct was
already known and reason out loud to a corrected answer ("TECH_AGRICULTURE...
wait, that's already known... TECH_WRITING"), breaking the bare-key contract
even though the FINAL answer was often fine. The schema makes that shape of
response impossible to produce - the model can still think as much as it
wants internally, but what comes back on stdout is `structured_output`, a
literal enum member, never prose. The `enum` constraint also means the model
cannot even in principle return a well-formed TECH_ key outside the offered
list - a second, redundant backstop against the illegal-pick failure mode
_available_techs already closes structurally.

Uses `claude -p`, run from a cwd OUTSIDE this repo (AI_OPPONENT_PLAN.md item D:
running from inside civ4-advisor auto-loads CLAUDE.md + auto-memory, ~66k
cache-creation tokens and ~$0.27 before the prompt is even read).

Calls the claude.cmd shim DIRECTLY via subprocess, not through `powershell
-Command claude -p ...`: PowerShell's own command-line parser treats `{`/`}`
in an unquoted argument as a script block, so passing a JSON schema through
`-Command` fails with "Unexpected token ':'" before claude ever runs -
confirmed live. Calling the .cmd path directly sidesteps a shell parser
entirely (Python's subprocess spawns it without invoking cmd.exe or
powershell.exe to interpret the argument list), which also sidesteps Git
Bash's shell-snapshot tax from item D's measurement without needing to name
PowerShell as the shell explicitly - there is no shell in the loop at all.

Every call is logged to decide_tech_log.jsonl (this directory) - the request
(state excerpt, turn, candidate list), response (raw answer, resolved
validity, wall clock, timestamp) - so decisions can be tracked and compared
across a game rather than trusted blind. See _log_decision.
"""

import json
import os
import shutil
import subprocess
import sys
import time

AI_OPPONENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(AI_OPPONENT_DIR)
STATE_DIR = os.environ.get('CIV4_ADVISOR_STATE_DIR', os.path.join(REPO_ROOT, 'state'))
LOG_PATH = os.path.join(AI_OPPONENT_DIR, 'decide_tech_log.jsonl')
RULES_SCRIPT = os.path.join(REPO_ROOT, 'harness', 'rules.py')

# claude -p must not run with cwd inside this repo - see module docstring.
# Any directory outside civ4-advisor works; the user's home directory is
# always present and never itself CLAUDE.md-bearing for this project.
CLAUDE_CWD = os.path.expanduser('~')

# Resolved once at import time via shutil.which, which - unlike a bare
# ['claude', ...] passed to subprocess.run without shell=True - actually
# finds the .cmd shim on PATH the way a real shell's command lookup would.
# Not hardcoded to one machine's npm global path; see module docstring for
# why this must be the literal .cmd rather than routed through a shell.
CLAUDE_CMD = shutil.which('claude')


# No "answer with ONLY the bare key" instruction needed here - the JSON
# schema passed to `claude -p --json-schema` (see _call_claude and
# _tech_choice_schema) enforces that structurally, so the prompt is free to
# just ask the question. Reasoning happens wherever the model wants it to;
# only structured_output is read.
PROMPT_TEMPLATE = """You are choosing the next technology to research for an AI-controlled civilization in Civilization IV.

Known technologies: {known_techs}
Currently researching: {current_tech}
Civics: {civics}

Candidates (every tech immediately legal to start researching right now - already filtered for known prerequisites, unranked, alphabetical):
{candidates}

Pick exactly ONE tech key from the candidate list above. Prioritize early-game fundamentals (expansion, growth, basic infrastructure, and unlocking key resources/improvements) unless known techs suggest a different priority."""


def _find_latest_state_file():
    """Most recently modified turn_NNNN.json under any state/<leader>_<gameId>/
    folder. mtime, not filename, since state/ can in principle hold more than
    one game folder (old test runs) and only the current game's latest file
    is relevant - the mod always calls this script for a game already in
    progress. Returns None if state/ doesn't exist or has no turn files yet."""
    if not os.path.isdir(STATE_DIR):
        return None
    candidates = []
    for gameFolder in os.listdir(STATE_DIR):
        gameFolderPath = os.path.join(STATE_DIR, gameFolder)
        if not os.path.isdir(gameFolderPath):
            continue
        for name in os.listdir(gameFolderPath):
            if name.startswith('turn_') and name.endswith('.json'):
                fullPath = os.path.join(gameFolderPath, name)
                candidates.append((os.path.getmtime(fullPath), fullPath))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def _available_techs(stateFilePath):
    """Shells out to `rules.py tech --available` (no LLM - a subprocess call
    to the same prerequisite-walk logic the mod itself will validate against)
    and parses the TECH_ keys out of its output. Returns a sorted list, or []
    on any failure (missing script, non-zero exit, nothing parseable) - the
    caller treats an empty list as "give up", same as any other decide_tech.py
    failure mode, rather than falling back to the old free-form prompt."""
    if not os.path.isfile(RULES_SCRIPT):
        return []
    try:
        result = subprocess.run(
            [sys.executable, RULES_SCRIPT, 'tech', stateFilePath, '--available'],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    # Each candidate row is "  TECH_FOO   123 beakers  ERA_ANCIENT" - the
    # leading two-space indent (view_available_techs) distinguishes a row
    # from the tech names that can also appear in prose lines elsewhere in
    # the output (e.g. "researching TECH_LEFT now").
    candidates = []
    for line in result.stdout.splitlines():
        if line.startswith('  TECH_'):
            candidates.append(line.split()[0])
    return sorted(candidates)


def _build_prompt(state, candidates):
    player = state.get('player', {})
    research = player.get('research', {})
    return PROMPT_TEMPLATE.format(
        known_techs=', '.join(player.get('knownTechs', [])) or '(none)',
        current_tech=research.get('current') or '(none selected)',
        civics=json.dumps(player.get('civics', {})),
        candidates='\n'.join(candidates),
    )


def _tech_choice_schema(candidates):
    """JSON Schema constraining the response to exactly one candidate key.

    The `enum` is the real teeth here, not just `pattern: ^TECH_[A-Z0-9_]+$`:
    a pattern alone would still let the model return a syntactically valid
    but off-menu tech (or a hallucinated one), which is exactly the failure
    _available_techs's post-hoc "not in candidates" check exists to catch.
    Building the enum from the SAME list handed to the model in the prompt
    means the schema and the prompt can never quietly drift apart into
    offering different candidate sets."""
    return json.dumps({
        'type': 'object',
        'properties': {
            'tech': {'type': 'string', 'enum': list(candidates)},
        },
        'required': ['tech'],
        'additionalProperties': False,
    })


def _call_claude(prompt, candidates):
    """Runs claude -p with the prompt and a JSON schema constraining the
    reply to {"tech": "<one of candidates>"}, cwd outside this repo. Returns
    (tech_key, wall_clock_seconds). Raises on a non-zero exit, unparseable
    JSON, or a missing structured_output - the caller decides what to print
    on failure.

    Invokes CLAUDE_CMD (the resolved claude.cmd path) directly rather than
    through a shell - see module docstring for why routing this through
    `powershell -Command` breaks on the JSON schema's braces."""
    if not CLAUDE_CMD:
        raise RuntimeError('claude not found on PATH')
    start = time.time()
    result = subprocess.run(
        [CLAUDE_CMD, '-p', '--output-format', 'json',
         '--json-schema', _tech_choice_schema(candidates)],
        input=prompt,
        cwd=CLAUDE_CWD,
        capture_output=True,
        text=True,
        timeout=180,
    )
    elapsed = time.time() - start
    if result.returncode != 0:
        raise RuntimeError('claude -p exited %d: %s' % (result.returncode, result.stderr.strip()))
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError('claude -p did not return valid JSON: %s' % exc)
    structured = payload.get('structured_output')
    if not isinstance(structured, dict) or 'tech' not in structured:
        raise RuntimeError('claude -p response had no structured_output.tech: %r' % payload)
    return structured['tech'], elapsed


def _log_decision(entry):
    entry['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as logFile:
            logFile.write(json.dumps(entry) + '\n')
    except OSError:
        pass


def main():
    playerId = sys.argv[1] if len(sys.argv) > 1 else None

    stateFilePath = _find_latest_state_file()
    if stateFilePath is None:
        sys.stderr.write('decide_tech.py: no state file found under %s\n' % STATE_DIR)
        sys.exit(1)

    with open(stateFilePath, 'r', encoding='utf-8') as stateFile:
        state = json.load(stateFile)

    candidates = _available_techs(stateFilePath)

    logEntry = {
        'playerId': playerId,
        'stateFile': stateFilePath,
        'gameTurn': state.get('game', {}).get('gameTurn'),
        'knownTechs': state.get('player', {}).get('knownTechs', []),
        'currentTech': state.get('player', {}).get('research', {}).get('current'),
        'candidates': candidates,
    }

    if not candidates:
        # No legal candidate (rules.py failed, or genuinely nothing
        # researchable) - nothing for Claude to choose between, so don't
        # spend a call on it. Same "give up cleanly" contract as every other
        # failure mode here: empty stdout, the mod falls through to stock.
        logEntry['error'] = 'no available techs (rules.py --available returned none)'
        _log_decision(logEntry)
        sys.stderr.write('decide_tech.py: no available techs found via rules.py --available\n')
        sys.exit(1)

    prompt = _build_prompt(state, candidates)

    try:
        rawAnswer, elapsed = _call_claude(prompt, candidates)
    except Exception as exc:
        logEntry['error'] = str(exc)
        _log_decision(logEntry)
        sys.stderr.write('decide_tech.py: claude call failed: %s\n' % exc)
        sys.exit(1)

    logEntry['rawAnswer'] = rawAnswer
    logEntry['wallClockSeconds'] = elapsed

    # The JSON schema in _call_claude already constrains structured_output.tech
    # to an enum of `candidates`, so a well-formed response cannot fail either
    # check below in practice. Kept anyway as defense-in-depth against a
    # schema the model quietly ignored or a claude CLI version that stops
    # enforcing --json-schema as strictly - is_error: false is not a validity
    # check (AI_OPPONENT_PLAN.md item D), so nothing here is trusted on faith
    # alone. The mod re-validates resolution and isHasTech independently
    # regardless - this is a tighter, earlier gate, not a replacement for that
    # one.
    if not rawAnswer.startswith('TECH_') or ' ' in rawAnswer or '\n' in rawAnswer:
        logEntry['shapeValid'] = False
        _log_decision(logEntry)
        sys.stderr.write('decide_tech.py: answer does not look like a bare TECH_ key: %r\n' % rawAnswer)
        sys.exit(1)

    logEntry['shapeValid'] = True

    if rawAnswer not in candidates:
        logEntry['inCandidateList'] = False
        _log_decision(logEntry)
        sys.stderr.write('decide_tech.py: answer %r is not one of the offered candidates\n' % rawAnswer)
        sys.exit(1)

    logEntry['inCandidateList'] = True
    _log_decision(logEntry)
    sys.stdout.write(rawAnswer)


if __name__ == '__main__':
    main()
