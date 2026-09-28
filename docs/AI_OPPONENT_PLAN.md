# Plan — an LLM-controlled AI opponent

A *sibling project* to the advisor, on branch `ai-opponent`: one AI civ's strategic decisions are made by Claude, and everything else stays stock procedural AI. Different runtime, prompts and output contract from the advisor. The advisor's era cutoff doesn't apply, and its fog-honesty rules are inverted. Keep it out of `ROADMAP.md`, which is the advisor's queue.

Prompted by [CivBench](https://arxiv.org/html/2604.07733v1) / [Vox Deorum](https://arxiv.org/abs/2512.18564), which did this for Civ V's strategic layer but needed a modified DLL. Civ 4 exposes the same seam in Python.

Markers: ✅ confirmed (live, unless marked "source") · ⚠️ needs confirmation · ❓ open.

## Where we stand

| Piece | State |
| --- | --- |
| Mode switch (`LocalConfig.MODE`: `advisor` / `opponent` / `both`) and targeting one AI by leader | ✅ live. The advisor path is unchanged when the mode is `advisor`, which `mod/tests/` asserts. |
| Per-turn export of the AI civ's own fog-honest state | ✅ live, `state/<leader>_<gameId>/turn_NNNN.json` |
| **Tech choice by Claude** (`AI_chooseTech`) | ✅ live — 100 turns, 13/13 decisions applied; ~4.5s game freeze per call on Opus 5.5 (see "Timing and performance") |
| Production, city sites, war, diplomacy, unit orders, civics/sliders | stock AI |
| Unattended test platform (mirrored map, autoplay) | ✅ live, unattended: `devtools/run_trial.py` |
| Plan-file decision loop (**C**), evaluation (**E**) | not started |

## Next increments

Not yet scheduled, in no fixed order:

- **Harness tools for the tech call.** It has none today: the prompt doesn't name them, `cwd` is outside the repo, and `-p` auto-denies anything that needs a permission prompt. Giving it `rules.py` means naming it in the prompt and allowing it narrowly (`--allowedTools "Bash(python <repo>/harness/rules.py:*)"`). That changes results by design and risks the 71–142s tool-using call times measured earlier, all of it a game freeze. Measure with `devtools/bench_decide_tech.py` before and after.
- **Production.** Fires once per city per completed build, so it needs the plan-file loop (**C**), not a synchronous call.
- **City sites.** There is no callback for this. Where a Settler goes is decided in the engine's unit AI, so it most likely means taking over Settler orders via `AI_unitUpdate`, which needs **B** measured first, or by pushing missions to the Settler directly.
- **Richer context for the tech call.** It currently sees only known techs, current research, civics and the candidate list. Whether more context (connected resources, cities, what each candidate unlocks) improves the choices is an evaluation question (**E**).

## How tech choice works

```
AI_chooseTech(ePlayer, bFree)                 ← gated: opponent mode + matching leader
  └── os.popen: python ai-opponent/decide_tech.py <playerId>          (blocking)
        ├── latest state/<leader>_<gameId>/turn_NNNN.json
        ├── rules.available_techs on a techs-only rules.Rules (in-process)  ← legal candidates
        ├── Claude: a pre-started claude from ai-opponent/claude_worker.py,
        │     or claude -p directly  --json-schema {enum: every tech}      ← candidates in the prompt
        └── stdout: one TECH_ key            (+ a line in decide_tech_log.jsonl)
  └── resolves, not already known → return the TechTypes int
      anything else → base class → stock AI
```

The mod falls through to stock AI on any failure, so a broken call means ordinary play rather than a stuck game. **That also makes failures invisible in-game — the log is the only way to see them.**

## Lessons that constrain what comes next

**Getting a usable answer out of the LLM**
- **Constrain the output structurally; asking in the prompt isn't enough.** A first run asked for "only the bare key" and applied only 4 of 12 decisions. Five times Claude corrected itself in prose (`"TECH_AGRICULTURE... wait, that's already known... TECH_WRITING"`). Three times it picked a tech that was illegal (missing prerequisite) or already known. Two fixes brought it to 13/13: offer a pre-filtered candidate list (`rules.py tech --available`), and constrain the reply with `--json-schema`. Apply the same pattern to every future decision: enumerate the legal options in code, then have the model choose one.
- **Keep the schema constant and put the per-call options in the prompt.** The enum was first built from the candidate list, which re-created the whole prompt cache on every call (see "Timing and performance"). It is now every tech in the XML, so it still blocks invented keys; an off-list pick is caught by `decide_tech.py`'s candidate check and falls through to stock AI. 26/26 on-list since the change (11 benchmark calls, 15 in trials).
- **`is_error: false` is not a validity check.** Haiku on low effort returned fluent, well-formatted, entirely fabricated plans and reported success. The mod still re-validates every answer independently.
- **Don't economise on model or effort; shrink the context instead.** Haiku was unusable, and Sonnet on low effort broke the output contract. Cost is dominated by reading the input, not generating the answer.

**Calling `claude -p` from a script**
- **Call `claude.cmd` directly**, resolved with `shutil.which` and given an argument list via `subprocess.run`. Routing through `powershell -Command` breaks on a JSON schema: PowerShell reads `{`/`}` as a script block. It also avoids Git Bash's first-call shell-snapshot cost (measured at 12–38s).
- **Run with `cwd` outside this repo.** From inside, `claude -p` auto-loads CLAUDE.md and memory: ~67k tokens and ~$0.27 before the prompt is read.
- **Pin the model and effort** (`--model claude-opus-5-5 --effort medium`). Unpinned, the user's own settings choose, and they had silently been choosing Sonnet. Opus 5.5 needs CLI **2.1.280 or newer**; older versions fail with an API 400.
- **Isolate the call from the user's own Claude Code setup:** `--settings '{"disableAllHooks": true}' --strict-mcp-config --disable-slash-commands`. Hooks, MCP servers and skills all load in `-p` mode even with `cwd` outside the repo, and none are used here. What each cost is in "Timing and performance".
- **With `--output-format json` an error arrives on stdout, not stderr.** An API 400 left stderr empty, so `decide_tech.py` logs stdout too.
- **A process started from a Claude Code session passes its `CLAUDE_*`/`MCP_*` variables down.** A game launched from a session hands them to `claude -p`, changing its effort, entrypoint and auth path. `devtools/` launches the game and the benchmark without them.
- **Pre-start the CLI rather than paying its startup inside the freeze** (`claude_worker.py`, "Timing and performance"). A tool-free call now takes ~3.5s offline and ~4.5s in-game. A tool-using advisor-style call took 71–142s.

**Blocking calls inside callbacks**
- A blocking call freezes the whole game for its duration (confirmed with an artificial 5s delay). The limit is how often the callback fires, not whether a freeze happens at all:

| Callback | Receives → returns | Fires | Synchronous LLM call? |
| --- | --- | --- | --- |
| `AI_chooseTech(ePlayer, bFree)` | player id → **`TechTypes` int**, `-1` falls through | per research choice | ✅ tolerable, confirmed |
| `AI_doWar(eTeam)` | **team** id → `1`/`0` | per team per turn | ⚠️ ~4.5s every turn |
| `AI_doDiplo(ePlayer)` | player id → `1`/`0` | per player per turn | ⚠️ ~4.5s every turn |
| `AI_chooseProduction(pCity)` | `CyCity` → `1`/`0` | per city, **only when its queue empties** | ❌ scales with cities |
| `AI_unitUpdate(pUnit)` | `CyUnit` → `1` = wait for next slice / `0` | per unit, per update slice | ❌ |

**The mod side**
- **`AI_chooseTech` returns a tech index, not a boolean.** `CvPlayerAI` casts the return value straight to `TechTypes`, so `return True` silently orders tech 0 (source ✅, tested). The other four callbacks return `1`/`0`.
- **Returning `0` from a callback hands the decision back to stock AI**, which makes taking over one decision at a time viable. The callbacks are global dispatch points, so gate on identity inside each: `pCity.getOwner()` / `pUnit.getOwner()`, the player id, or the team id for `AI_doWar`.
- **Exporting a non-active player's state:** flip `CyGame.setActivePlayer(id, False)` around the export and restore it in a `finally`. Two getters (`calculateYield(bDisplay=True)`, `getVisualOwner()`) answer only for the active player. Safe for a non-human target: the password/net-ID branch is gated on `isHuman()` (source ✅), and no UI side effects were seen over 20+ turns. Verified fog-honest: two civs' turn-0 revealed tiles don't overlap.
- **`onBeginPlayerTurn(N)` fires at the end of turn N**, so exports use `N + 1`, same as the advisor's `onEndGameTurn`. Turn 0 has to come from `onGameStart`/`onLoadGame`, since no player-turn hook fires before turn 1.
- **`pushOrder(eOrder, iData1, iData2, bSave, bPop, bAppend, bForce)`** is the real signature (source ✅, live).
- The `AI_*` callbacks enter through `EntryPoints/CvGameInterfaceFile.py`, a hook the base game ships for this purpose, so they never touch the advisor's `CvEventInterface.py` (✅ live).
- Python 2.4 in the game has `os.popen`/`os.spawnv` but no `subprocess`.

## Timing and performance

Measured 2026-09-28 on Opus 5.5 at medium effort, CLI 2.1.283. `decide_tech.py` logs every call's breakdown (`timing`, `claude`, `claudePath`) to `decide_tech_log.jsonl`; the mod logs the whole `os.popen` round trip to `PythonDbg.log`; `devtools/bench_decide_tech.py` replays saved turns offline. Identical inputs vary up to 2×, so every figure is a median of 5 or more calls, never a single one.

| Component (median seconds) | Baseline, offline | Isolated + constant enum, offline | + pre-started CLI, offline | + pre-started CLI, in-game | + in-process `rules`, in-game |
| --- | --- | --- | --- | --- | --- |
| Python startup to `main` | 0.28 | 0.26 | 0.27 | 0.41 | 0.35 |
| state load | 0.04 | 0.05 | 0.04 | 0.13 | 0.12 |
| candidates (`rules.py tech --available`: subprocess, then in-process techs-only) | 0.67 | 0.63 | 0.61 | 0.78 | 0.05 |
| CLI startup and teardown (CLI total − `duration_ms`) | 3.74 | 2.55 | 0.04 | 0.07 | 0.07 |
| CLI's own time outside the API (`duration_ms` − API) | 4.30 | 0.21 | 0.18 | 0.20 | 0.20 |
| API (`duration_api_ms`) | 3.70 | 2.95 | 2.25 | 2.33 | 3.53 |
| **`decide_tech.py` total** | **12.76** | **6.79** | **3.52** | **4.25** | **4.32** |
| spawn from the game (round trip − total) | | | | 0.23 | 0.29 |
| **game freeze (`os.popen` round trip)** | | | | **4.51** | **4.62** |
| **freeze minus API: everything but the model** | | | | **1.83** | **1.09** |

Warm calls only: 5 from two trials, then 2 after the `rules` change; a game's first call is cold (7.8–9.6s). Compare the last row: the final column's API time ran long (2.33s, 4.73s). Offline, candidates went 0.61s → 0.04s. The pre-worker 9.4s freeze included ~1.1s of extra CLI startup in-game, which went with the startup.

**Cost per call, at list price:**

| | Prompt tokens re-created | Cost |
| --- | --- | --- |
| Baseline: candidate enum, MCP connectors | all ~28.8k, every call | ~$0.23 |
| Constant enum, no MCP or skills | ~1.9k (the prompt itself); ~24.2k read from cache | ~$0.02 |
| The same, first call after the cache expires | ~26k | ~$0.21 |

The cache is written with a 1-hour TTL, so a game whose tech choices are under an hour apart pays the full price once. The 100-turn run's 13 decisions would cost about $3 at baseline and about $0.46 now.

Every call is `num_turns` 2: one API request, then the local `StructuredOutput` tool call (~1ms).

**What changed and what each bought:**
- **Hooks off: −5.1s.** The user's global `Stop` hook plays a notification sound through PowerShell's `PlaySync` and took ~4s per call (visible in a `--debug-file` trace). It also played that sound in-game on every research choice. The prompt token count per input was identical with and without.
- **MCP off: −1.0 to −1.4s of startup** (with skills off in the same run; −1.4s tested alone, n=3). The claude.ai connectors (7 fetched, 5 connected) cost a server-list fetch of ~0.9s before the first turn. Worse, **whether their tools reached the prompt was a race**: most calls read ~28.8k tokens, and one whose turn started before three connectors finished read 25.3k. That also kept the prompt prefix from ever repeating.
- **Constant schema enum: the cache now holds.** `--json-schema` becomes a tool definition that sits ahead of the prompt. A per-call candidate enum therefore changed the prefix every call, and every real-game call re-created ~28.8k tokens. With the enum fixed, calls read ~24.2k from cache and create only ~1.9k, the tail holding the prompt itself. Worth ~0.3s of API time; the big win is cost.
- Skills off: the skill listing is gone from the prompt; its time saving was not measured separately.
- **Pre-started CLI: −3.3s offline, −4.9s in-game.** `ai-opponent/claude_worker.py` keeps one `claude` process started and waiting, so a call pays neither the CLI's startup nor its ~0.6s of exit.
  - **How:** `--input-format stream-json` finishes startup before waiting for its prompt; plain `-p` doesn't (evidence in `REFERENCES.md` "Calling `claude -p` from a script").
  - **Still one fresh session per answer:** each spare gets exactly one message and its stdin is closed, so no conversation carries between calls. The prompt is token-for-token the same (24,151 read + ~1,850 created in both modes).
  - **Startup:** `decide_tech.py` starts the worker detached the first time it finds none, and uses it from the next call on. With no handles inherited — the game's `os.popen` waits until every holder of its pipe has closed it.
  - **Fallback:** anything unusable — no worker, a changed command line, a dead spare — falls back to calling `claude` directly or starting a fresh process: slower, never wrong.
  - **Lifetime:** the worker exits after 30 idle minutes, so it outlives a game by up to that long, holding one idle `claude` process.
- **Candidates in-process on a techs-only `Rules`: −0.57s offline, −0.73s in-game.** Spawning `rules.py tech --available` paid Python's startup plus ~0.3s parsing all 25 XML files, when the list needs only the techs and three cost multipliers. `Rules(roots, game, techs_only=True)` parses just those, leaving the other attributes absent so a view handed one fails loudly. `decide_tech.py` calls `rules.available_techs()` on it directly, and takes the schema enum from the same parse. The command line is unchanged: `tech --available` uses the techs-only form internally. A harness test checks both forms print the same list on every sample turn, and the old and new candidate lists were identical on all 1,035 saved states.

**Where a warm in-game call goes now:** the API, ~2.3–4.7s and irreducible at this model and effort, plus ~1.1s of everything else: Python startup ~0.35s, state load ~0.12s, candidates ~0.05s, the CLI's own time around the API ~0.2s, the worker hand-off ~0.07s, and ~0.3s spawning from the game through `cmd.exe`. Each of those is under the ~0.5s worth chasing.

**Tried, not worth it (under ~0.5s each):**
- Calling `claude.exe` directly instead of the npm `.cmd` shim saves 0.04s. Moot for warm calls.

**Rejected as functional changes, with measured savings:**
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`: ~−1.2s (n=3) before the pre-started CLI hid startup, but the prompt shrank to 20.9k tokens, so Claude sees something different.
- One long-lived CLI session reused for every call (stream-json kept open, or the Agent SDK's client): saves startup the same way, but each call would become another message in one growing conversation.
- Replacing Claude Code's system prompt or narrowing `--tools`: untested. This is where most of the remaining prompt lives (~24k tokens against ~300 of ours), and so the largest remaining lever, at the price of what the model sees and can do.

**Open:**
- A spare waiting for many minutes is untested; trials had calls ~20–40s apart. Human play can put tech choices 10+ minutes apart. A spare that died is replaced by a fresh process, so the risk is speed, not correctness.
- Each call still writes a session transcript under `~/.claude/projects/` (`--no-session-persistence` would stop that). Not a timing issue.

## Engine facts (from the BTS SDK source)

Read from `Beyond the Sword/Mods/The Road to War/CvGameCoreDLL` (stock for these files); not yet exercised live unless marked.

**Three tiers of control.** `AI_doTurnPre()` calls `AI_doResearch`, `AI_doCommerce` (sliders), `AI_doMilitary`, `AI_doCivics`, `AI_doReligion` and `AI_doCheckFinancialTrouble` with no Python dispatch at all. But every matching setter is exposed on `CyPlayer` (`setCommercePercent`, `setCivics`, `revolution`, `setLastStateReligion`, espionage), so:

| Tier | Mechanism | Covers |
| --- | --- | --- |
| Authoritative | the 5 callbacks | tech, production, war, diplo, unit orders |
| Last-writer-wins | setters applied *after* `AI_doTurnPre` | sliders, civics, religion, espionage |
| Unreachable | pure C++ | attitude internals, military posture, war-plan scoring |

`AI_doCivics` early-outs on a civic timer, so re-asserting civics each turn doesn't cause flip-flopping.

**Execution order.** In single-player, `doTurn()` runs when a turn *ends*, not when it starts:

```
setTurnActive(TRUE)  → doTurnUnits → AI_unitUpdate ×many
setTurnActive(FALSE) → doTurn:
    onBeginPlayerTurn → AI_doTurnPre (sliders/civics) → city doTurn → AI_chooseProduction
    → AI_doTurnPost → AI_doDiplo → onEndPlayerTurn
team level: CvTeamAI::AI_doTurnPre → AI_doWar
```

Consequences: a plan computed at `onBeginPlayerTurn` reaches production and diplomacy the same turn but **unit orders only the next turn** (⚠️ not measured). Sliders and civics must be set at `onEndPlayerTurn`, or `AI_doTurnPre` overwrites them.

⚠️ **`AI_unitUpdate` cost is unmeasured.** RFC disabled it for speed even with empty stubs. **B** (below) measures it; it gates city sites and any tactical control.

## Architecture

**One mode-switched mod, separate runtime folders.** `AdvisorStateWriter.py` is ~90% of the mod and the opponent needs it unchanged. A second mod folder would fork it, and would add a second junction on top of the one `CLAUDE.md` already records as hazardous. The runtimes share nothing: `ai-opponent/` sits beside `advisor/`, and `harness/` is shared.

```
mod/Assets/Python/
  AdvisorStateWriter.py       shared, unchanged
  CvCustomEventManager.py     + opponent export, mode guards
  CvAdvisorGameUtils.py       AI_* callback overrides
  LocalConfig.py              MODE, AI_OPPONENT_PLAYER_KEY
  EntryPoints/CvGameInterfaceFile.py   points GameUtils at CvAdvisorGameUtils
ai-opponent/                  decide_tech.py, claude_worker.py, decide_tech_log.jsonl
harness/rules.py              tech --available / available_techs() serve both projects
devtools/                     dev-only: unattended launch/autoplay, never shipped
```

**The mode check is folded into the identity check** (`_advisorPlayerId()` returns `None` when opponent mode is off), so hot callbacks pay one branch, not two.

`decide_production.py` and `decision_config.txt` in `ai-opponent/` are leftovers from the production stub spike; nothing calls them.

## Test platform

Two AI civs on a mirrored map, no human playing, running unattended.

- **Map:** `PublicMaps/Mirror.py` ships with the game. A symmetric two-civ game is set up as 4 civs in 2 teams: autoplay removes the human and `KILL_LEADERS` removes the fourth civ (`devtools/README.md` "Fixtures"). By hand, run **both** `gc.getPlayer(X).killCities()` and `.killUnits()` in the Python console: a leftover Settler keeps a civ alive.
- **The 2-team setup makes every tech 50% dearer unless corrected.** A team pays +50% per extra member it ever had, and a removed civ still counts, so both survivors research at two-thirds speed with no teammate's beakers to pay it back: every one of Alexander's 48 techs over a 500-turn run cost exactly 1.5× the solo formula. `devtools/run_trial.py` therefore sets `TECH_COST_EXTRA_TEAM_MEMBER_MODIFIER` to 0 for every trial, through the dev hook's `DEFINES`; costs then match the solo formula exactly (✅ live). Trials run before this change paid the tax, including the 200- and 500-turn runs. Starting techs still differ by the removed teammate's civ: Alexander gets Agriculture on Continents (from Darius) and Mining on Lakes (from Bismarck). Evidence in `REFERENCES.md` "Team size and tech cost".
- **Driving by hand:** `Game.AIPlay N` (cheat console, `` ` ``, needs `CheatCode = chipotle`) runs exactly N turns with full UI between batches. `Autorun = 1` runs forever with the UI locked, and `AutorunTurnLimit` doesn't work, so prefer `AIPlay` batches. The Python console is the separate `Shift+`` ` ``.
- **Driving unattended** (✅ live, 2026-09-28): `devtools/` launches straight into a save with `/FXSLOAD`, and its in-game hook starts autoplay from a one-shot control file, with no clicks. `devtools/run_trial.py` stops at a target turn (or on a stall or timeout) and writes a report. The launch command, prerequisites and pitfalls are in `devtools/README.md`.
- `LocalConfig.AI_OPPONENT_PLAYER_KEY = 'LEADER_ALEXANDER'` — first in the leader list, so easy to pick at setup.

## Work items

**B. Measure `AI_unitUpdate` overhead.** Empty stub, count units, time a turn. Decides whether city sites and tactical control are affordable at all.

**C. The plan-file loop** — for every decision that fires too often to call synchronously:

```
onBeginPlayerTurn(turn, aiPlayerId)
  → mod writes turn_NNNN.json, polls (bounded, ~30s) for plan_NNNN.json
  → watcher (ai-opponent/, outside the game) calls Claude, validates, writes plan atomically
callbacks → look up the plan by unit/city id → push order, return 1
          → miss or timeout → return 0 → stock AI
onEndPlayerTurn → apply sliders/civics
```

A missing plan means the game plays normally — the same fall-through safety tech choice relies on.

**E. Evaluation.** `calculateScore` per turn is free. Start with score curves and win rate over repeated mirrored runs. **One game is not a result**: identical inputs swung API time 39→74s, and behaviour varied a lot between runs.

Worth exporting before taking over decisions the AI makes with them: `AI_getAttitude`, war plans, `AI_getBonusValue`, financial-trouble flags.

## Open questions

- ❓ Does `setCommercePercent` from Python trigger the same recalculation as the C++ path?
- ❓ Subscription or API key for unattended runs? At the ~450k tokens per turn a tool-using call measured, a 300-turn game would hit a subscription's rate limits mid-run; the tech call sends ~26k tokens, ~24k of them read from cache.
- ❓ Is the one-turn lag on unit orders acceptable?
- ❓ `AI_doWar` is team-scoped — what happens in a team game?
- ❓ Does the opponent need its own setup entry point, separate from the player-facing `setup.ps1`?
- `decide_tech.py` has no unit tests; it is verified live and by `devtools/bench_decide_tech.py`, which replays it against saved trial turns.

## Deliberately not doing

- **A custom DLL.** If a design seems to need recompiling `CvGameCoreDLL`, re-scope instead.
- **Pathfinding or turns-to-arrive.** The engine repaths every turn and caches no ETA.
- **Replacing the whole AI.** CivBench's result comes from the hybrid: LLM on strategy, procedural AI on execution.
