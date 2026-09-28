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

TWO-STEP FLOW, SCRIPT-SIDE FIRST: before ever calling Claude, this asks
harness/rules.py for the same list `rules.py tech --available` prints (no LLM
involved - its XML-prerequisite walk, imported and run in-process on a
techs-only Rules, see _tech_rules) to get the actual legal candidate set for
this exact game state, then hands Claude that menu to choose from
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
every tech in the game's XML (see _tech_choice_schema for why not the
candidate list). This replaces asking nicely in the prompt text
("no explanation, no punctuation, just the bare key"), which a live run
measured failing 5 of 12 times: Claude would notice its first instinct was
already known and reason out loud to a corrected answer ("TECH_AGRICULTURE...
wait, that's already known... TECH_WRITING"), breaking the bare-key contract
even though the FINAL answer was often fine. The schema makes that shape of
response impossible to produce - the model can still think as much as it
wants internally, but what comes back on stdout is `structured_output`, a
literal enum member, never prose. The enum also rules out an invented key;
an off-list but real tech is caught by the "not in candidates" check in
main() and falls through to stock AI, same as any other failure.

Uses `claude -p`, run from a cwd OUTSIDE this repo (AI_OPPONENT_PLAN.md
"Lessons that constrain what comes next": running from inside civ4-advisor
auto-loads CLAUDE.md + auto-memory, ~66k cache-creation tokens and ~$0.27
before the prompt is even read).

Calls the claude.cmd shim DIRECTLY via subprocess, not through `powershell
-Command claude -p ...`: PowerShell's own command-line parser treats `{`/`}`
in an unquoted argument as a script block, so passing a JSON schema through
`-Command` fails with "Unexpected token ':'" before claude ever runs -
confirmed live. Calling the .cmd path directly sidesteps a shell parser
entirely (Python's subprocess spawns it without invoking cmd.exe or
powershell.exe to interpret the argument list), which also sidesteps Git
Bash's shell-snapshot tax measured there without needing to name
PowerShell as the shell explicitly - there is no shell in the loop at all.

PRE-STARTED WHEN POSSIBLE: the call goes to claude_worker.py (this
directory), which keeps a claude process already started and waiting, so the
game's freeze doesn't include the CLI's ~3s of startup. With no worker running
this script starts one for next time and calls claude directly - see
_call_claude and claude_worker.py's docstring.

Every call is logged to decide_tech_log.jsonl (this directory) - the request
(state excerpt, turn, candidate list), response (raw answer, resolved
validity, wall clock, timestamp) - so decisions can be tracked and compared
across a game rather than trusted blind. See _log_decision.

Each entry also carries a per-call time breakdown - `timing` (seconds per
phase of this script, from process creation onward) and `claude` (the CLI's
own duration, API time, turn count and token figures from its JSON result) -
kept permanently, since they are how we know where a call's time goes. See
docs/AI_OPPONENT_PLAN.md "Timing and performance".
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time

AI_OPPONENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(AI_OPPONENT_DIR)
STATE_DIR = os.environ.get('CIV4_ADVISOR_STATE_DIR', os.path.join(REPO_ROOT, 'state'))
LOG_PATH = os.environ.get('CIV4_ADVISOR_TECH_LOG', os.path.join(AI_OPPONENT_DIR, 'decide_tech_log.jsonl'))
HARNESS_DIR = os.path.join(REPO_ROOT, 'harness')
WORKER_SCRIPT = os.path.join(AI_OPPONENT_DIR, 'claude_worker.py')
WORKER_FILE = os.path.join(AI_OPPONENT_DIR, 'claude_worker.json')

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

# Pinned rather than inherited from the user's own Claude Code settings, which
# would otherwise choose them (and change them silently whenever those
# settings change) - timings and decisions are only comparable across runs at
# a fixed model and effort. Sonnet 5.5 rather than Opus 5.5: on the same
# inputs it answered ~0.8s faster at ~40% lower cost, with the same pick 9
# times in 10 (docs/AI_OPPONENT_PLAN.md "Timing and performance").
# CIV4_ADVISOR_CLAUDE_MODEL overrides the model for a comparison run (see
# devtools/bench_decide_tech.py --models); the game never sets it.
CLAUDE_MODEL = os.environ.get('CIV4_ADVISOR_CLAUDE_MODEL') or 'claude-sonnet-5-5'
CLAUDE_EFFORT = 'medium'

# What claude -p would otherwise load from the user's own Claude Code setup,
# none of which this call uses (docs/AI_OPPONENT_PLAN.md "Timing and
# performance"):
# - hooks: a Stop hook playing a notification sound through PowerShell
#   measured ~4s of an ~11s call, and changed nothing the model saw;
# - MCP servers, including claude.ai connectors (--strict-mcp-config with no
#   --mcp-config loads none): ~1.4s of startup, and a race - whether their
#   tools reached the prompt depended on connection timing;
# - skills (--disable-slash-commands): a listing of every skill the user has,
#   none of them about Civ IV.
CLAUDE_SETTINGS = json.dumps({'disableAllHooks': True})
CLAUDE_ISOLATION_FLAGS = ['--settings', CLAUDE_SETTINGS, '--strict-mcp-config', '--disable-slash-commands']


def _process_start_time():
    """Epoch seconds at which this process was created, or None if it can't
    be read. Windows-only (GetProcessTimes), the only platform the mod calls
    this from; it covers the interpreter's own startup, which time.time() at
    the top of main() cannot see."""
    try:
        import ctypes
        from ctypes import wintypes
        creation, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        if not kernel32.GetProcessTimes(kernel32.GetCurrentProcess(), ctypes.byref(creation),
                                        ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return ticks / 1e7 - 11644473600  # FILETIME: 100ns ticks since 1601
    except Exception:
        return None


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


def _tech_rules(state):
    """A techs-only rules.Rules for this game's setup - the techs and the
    research-cost multipliers, which is all the candidate list and the schema
    enum need - or None on any failure. Imported and run in-process: spawning
    `rules.py tech --available` cost ~0.6s per call, ~0.3s of it parsing ~20
    XML files this never reads (docs/AI_OPPONENT_PLAN.md "Timing and
    performance"). Refuses a state whose schemaVersion rules.py would refuse,
    exactly as the command line's load_state does."""
    try:
        if HARNESS_DIR not in sys.path:
            sys.path.insert(0, HARNESS_DIR)
        import rules
        if (state.get('meta') or {}).get('schemaVersion') != rules.STATE_SCHEMA_VERSION:
            return None
        return rules.Rules(rules.resolve_xml_root(), state.get('game', {}), techs_only=True)
    except Exception:
        return None


def _available_techs(techRules, state):
    """Every tech immediately legal to start - the rows `rules.py tech
    --available` prints, from the same function - as a sorted list, or []
    without rules. The caller treats [] as "give up", same as any other
    decide_tech.py failure mode, rather than falling back to the old
    free-form prompt."""
    if techRules is None:
        return []
    import rules
    try:
        return rules.available_techs(techRules, state)
    except Exception:
        return []


def _build_prompt(state, candidates):
    player = state.get('player', {})
    research = player.get('research', {})
    return PROMPT_TEMPLATE.format(
        known_techs=', '.join(player.get('knownTechs', [])) or '(none)',
        current_tech=research.get('current') or '(none selected)',
        civics=json.dumps(player.get('civics', {})),
        candidates='\n'.join(candidates),
    )


def _tech_choice_schema(enum):
    """JSON Schema constraining the response to one key from `enum`.

    `enum` is every tech in the game (the techs_only Rules' `techs`), NOT
    the candidate list,
    for the prompt cache: claude -p turns the schema into a tool definition
    that sits ahead of our prompt, so a per-call enum changed that prefix on
    every call and re-created thousands of cached tokens each time
    (docs/AI_OPPONENT_PLAN.md "Timing and performance"). A constant enum keeps
    the prefix identical across calls; the legal candidates are in the prompt,
    which comes last. The cost: the schema no longer makes an off-list pick
    impossible, only an invented key - main()'s "not in candidates" check
    catches the rest, and the mod falls through to stock AI."""
    return json.dumps({
        'type': 'object',
        'properties': {
            'tech': {'type': 'string', 'enum': list(enum)},
        },
        'required': ['tech'],
        'additionalProperties': False,
    })


def _claude_argv(enum, streaming):
    """The claude command line. `streaming` is the form claude_worker.py
    pre-starts (stream-json in and out); the other is a one-shot call. Both
    send the same prompt and get the same `result` fields back.

    CLAUDE_CMD is the resolved claude.cmd path, run directly rather than
    through a shell - see module docstring for why routing this through
    `powershell -Command` breaks on the JSON schema's braces."""
    io = (['--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose']
          if streaming else ['--output-format', 'json'])
    return ([CLAUDE_CMD, '-p'] + io + ['--model', CLAUDE_MODEL, '--effort', CLAUDE_EFFORT]
            + CLAUDE_ISOLATION_FLAGS + ['--json-schema', _tech_choice_schema(enum)])


def _start_worker(argv):
    """Starts claude_worker.py detached, for the NEXT call to use, pre-starting
    a claude process for `argv` straight away. It must
    not inherit this process's stdout: that is the game's os.popen pipe, and
    the game blocks until every holder of it has closed it - a worker holding
    it would freeze the game for the worker's whole life."""
    try:
        subprocess.Popen(
            [sys.executable, WORKER_SCRIPT, json.dumps({'argv': argv, 'cwd': CLAUDE_CWD})],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                           | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)))
    except OSError:
        pass


def _ask_worker(prompt, enum):
    """(result event, path) from claude_worker.py, or (None, why) when there
    is no usable worker - the caller then calls claude directly. Starts a
    worker when none is listening. path is 'warm' (a pre-started process
    answered) or 'cold' (the worker had to start one, e.g. after a code
    change)."""
    try:
        with open(WORKER_FILE, encoding='utf-8') as f:
            info = json.load(f)
        conn = socket.create_connection(('127.0.0.1', info['port']), timeout=1)
    except (OSError, ValueError, KeyError, TypeError):
        _start_worker(_claude_argv(enum, True))
        return None, 'direct (no worker)'
    with conn:
        conn.settimeout(180)
        request = {'token': info.get('token'), 'argv': _claude_argv(enum, True),
                   'cwd': CLAUDE_CWD, 'prompt': prompt}
        conn.sendall((json.dumps(request) + '\n').encode('utf-8'))
        reply = json.loads(conn.makefile('r', encoding='utf-8').readline())
    if not reply.get('ok'):
        return None, 'direct (worker error: %s)' % reply.get('error')
    return reply['result'], 'warm' if reply.get('warm') else 'cold'


def _ask_direct(prompt, enum):
    result = subprocess.run(
        _claude_argv(enum, False),
        input=prompt,
        cwd=CLAUDE_CWD,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        # With --output-format json the error is reported on stdout, not
        # stderr - an API error left stderr empty and the log said nothing.
        raise RuntimeError('claude -p exited %d: %s %s' % (
            result.returncode, result.stderr.strip(), result.stdout.strip()[:2000]))
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError('claude -p did not return valid JSON: %s' % exc)


def _call_claude(prompt, enum):
    """Asks Claude, with a JSON schema constraining the reply to
    {"tech": "<one of enum>"}, cwd outside this repo - through the
    pre-started claude_worker.py when one is running, else directly. Returns
    (tech_key, wall_clock_seconds, claude_stats, path); path says which route
    answered. Raises on a failed call or a missing structured_output - the
    caller decides what to print on failure."""
    if not CLAUDE_CMD:
        raise RuntimeError('claude not found on PATH')
    start = time.time()
    try:
        payload, path = _ask_worker(prompt, enum)
    except (OSError, ValueError, KeyError):
        # A worker that took the request may have spent a call on it; asking
        # again directly costs a second one, which beats no decision.
        payload, path = None, 'direct (worker connection failed)'
    if payload is None:
        payload = _ask_direct(prompt, enum)
    elapsed = time.time() - start
    if payload.get('is_error'):
        raise RuntimeError('claude reported an error: %s' % str(payload.get('result'))[:2000])
    structured = payload.get('structured_output')
    if not isinstance(structured, dict) or 'tech' not in structured:
        raise RuntimeError('claude -p response had no structured_output.tech: %r' % payload)
    return structured['tech'], elapsed, _claude_stats(payload), path


def _claude_stats(payload):
    """The parts of claude -p's JSON result that say where the call's time
    and tokens went: the CLI's own wall clock (duration_ms), time spent
    waiting on the API (duration_api_ms), model round trips (num_turns),
    token usage including prompt-cache reads/writes, and which models ran."""
    usage = payload.get('usage') or {}
    modelUsage = payload.get('modelUsage') or {}
    return {
        'durationMs': payload.get('duration_ms'),
        'durationApiMs': payload.get('duration_api_ms'),
        'numTurns': payload.get('num_turns'),
        'costUsd': payload.get('total_cost_usd'),
        'inputTokens': usage.get('input_tokens'),
        'outputTokens': usage.get('output_tokens'),
        'cacheReadTokens': usage.get('cache_read_input_tokens'),
        'cacheCreationTokens': usage.get('cache_creation_input_tokens'),
        'thinkingTokens': sum(m.get('thinkingTokens') or 0 for m in modelUsage.values()),
        'models': sorted(modelUsage.keys()),
    }


class _Timer(object):
    """The per-call `timing` block: seconds from the previous mark (or from
    process creation, for the first) to each named mark, plus the total."""

    def __init__(self):
        now = time.time()
        processStart = _process_start_time()
        self.timing = {}
        if processStart is not None:
            self.timing['startupToMain'] = round(now - processStart, 3)
        self._start = processStart if processStart is not None else now
        self._last = now

    def mark(self, name):
        now = time.time()
        self.timing[name] = round(now - self._last, 3)
        self._last = now

    def finish(self):
        self.timing['total'] = round(time.time() - self._start, 3)
        return self.timing


def _log_decision(entry, timer):
    entry['timing'] = timer.finish()
    entry['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as logFile:
            logFile.write(json.dumps(entry) + '\n')
    except OSError:
        pass


def main():
    timer = _Timer()
    playerId = sys.argv[1] if len(sys.argv) > 1 else None

    stateFilePath = _find_latest_state_file()
    if stateFilePath is None:
        sys.stderr.write('decide_tech.py: no state file found under %s\n' % STATE_DIR)
        sys.exit(1)

    with open(stateFilePath, 'r', encoding='utf-8') as stateFile:
        state = json.load(stateFile)
    timer.mark('stateLoad')

    techRules = _tech_rules(state)
    candidates = _available_techs(techRules, state)
    timer.mark('rules')

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
        logEntry['error'] = 'no available techs (rules.available_techs returned none)'
        _log_decision(logEntry, timer)
        sys.stderr.write('decide_tech.py: no available techs found via rules.available_techs\n')
        sys.exit(1)

    prompt = _build_prompt(state, candidates)
    timer.mark('promptBuild')

    enum = sorted(techRules.techs) if techRules is not None else None
    logEntry['schemaEnum'] = 'allTechs' if enum else 'candidates'

    try:
        rawAnswer, elapsed, claudeStats, claudePath = _call_claude(prompt, enum or candidates)
    except Exception as exc:
        timer.mark('claudeCli')
        logEntry['error'] = str(exc)
        _log_decision(logEntry, timer)
        sys.stderr.write('decide_tech.py: claude call failed: %s\n' % exc)
        sys.exit(1)

    timer.mark('claudeCli')
    logEntry['rawAnswer'] = rawAnswer
    logEntry['wallClockSeconds'] = elapsed
    logEntry['claude'] = claudeStats
    logEntry['claudePath'] = claudePath

    # The JSON schema in _call_claude constrains structured_output.tech to a
    # real tech key, so the shape check below cannot fail in practice; it is
    # defense-in-depth against a schema the model quietly ignored or a claude
    # CLI version that stops enforcing --json-schema as strictly. The
    # candidate check CAN fail - the enum is every tech, not just the legal
    # ones (see _tech_choice_schema) - and is logged when it does.
    # is_error: false is not a validity check (AI_OPPONENT_PLAN.md "Lessons
    # that constrain what comes next"), so nothing here is trusted on faith
    # alone. The mod re-validates resolution and isHasTech independently
    # regardless - this is a tighter, earlier gate, not a replacement for
    # that one.
    if not rawAnswer.startswith('TECH_') or ' ' in rawAnswer or '\n' in rawAnswer:
        logEntry['shapeValid'] = False
        _log_decision(logEntry, timer)
        sys.stderr.write('decide_tech.py: answer does not look like a bare TECH_ key: %r\n' % rawAnswer)
        sys.exit(1)

    logEntry['shapeValid'] = True

    if rawAnswer not in candidates:
        logEntry['inCandidateList'] = False
        _log_decision(logEntry, timer)
        sys.stderr.write('decide_tech.py: answer %r is not one of the offered candidates\n' % rawAnswer)
        sys.exit(1)

    logEntry['inCandidateList'] = True
    _log_decision(logEntry, timer)
    sys.stdout.write(rawAnswer)


if __name__ == '__main__':
    main()
