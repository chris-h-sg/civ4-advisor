# Plan — an LLM-controlled AI opponent

A *sibling project* to the advisor, on branch `ai-opponent`: one AI civ's strategic decisions are made by Claude, and everything else stays stock procedural AI. Different runtime, prompts and output contract from the advisor. The advisor's era cutoff doesn't apply, and its fog-honesty rules are inverted. Keep it out of `ROADMAP.md`, which is the advisor's queue.

Prompted by [CivBench](https://arxiv.org/html/2604.07733v1) / [Vox Deorum](https://arxiv.org/abs/2512.18564), which did this for Civ V's strategic layer but needed a modified DLL. Civ 4 exposes the same seam in Python.

Markers: ✅ confirmed (live, unless marked "source") · ⚠️ needs confirmation · ❓ open.

## Where we stand

| Piece | State |
| --- | --- |
| Mode switch (`LocalConfig.MODE`: `advisor` / `opponent` / `both`) and targeting one AI by leader | ✅ live. The advisor path is unchanged when the mode is `advisor`, which `mod/tests/` asserts. |
| Per-turn export of the AI civ's own fog-honest state | ✅ live, `state/<leader>_<gameId>/turn_NNNN.json` |
| **Tech choice by Claude** (`AI_chooseTech`) | ✅ live — 100 turns, 13/13 decisions applied, ~10s per call |
| Production, city sites, war, diplomacy, unit orders, civics/sliders | stock AI |
| Unattended test platform (mirrored map, autoplay) | ✅ live, unattended: `devtools/run_trial.py` |
| Plan-file decision loop (**C**), evaluation (**E**) | not started |

## Next increments

Not yet scheduled, in no fixed order:

- **Timing and performance.** Break the ~10s per call down into API time, process startup and the `rules.py` call. `claude -p --output-format json` already returns `duration_api_ms` and similar; `decide_tech.py` discards them. Do this before any per-turn callback, where the freeze would repeat every turn.
- **Production.** Fires once per city per completed build, so it needs the plan-file loop (**C**), not a synchronous call.
- **City sites.** There is no callback for this. Where a Settler goes is decided in the engine's unit AI, so it most likely means taking over Settler orders via `AI_unitUpdate`, which needs **B** measured first, or by pushing missions to the Settler directly.
- **Richer context for the tech call.** It currently sees only known techs, current research, civics and the candidate list. Whether more context (connected resources, cities, what each candidate unlocks) improves the choices is an evaluation question (**E**).

## How tech choice works

```
AI_chooseTech(ePlayer, bFree)                 ← gated: opponent mode + matching leader
  └── os.popen: python ai-opponent/decide_tech.py <playerId>          (blocking)
        ├── latest state/<leader>_<gameId>/turn_NNNN.json
        ├── python harness/rules.py tech <state> --available          ← legal candidates
        ├── claude -p --output-format json --json-schema {enum: candidates}
        └── stdout: one TECH_ key            (+ a line in decide_tech_log.jsonl)
  └── resolves, not already known → return the TechTypes int
      anything else → base class → stock AI
```

The mod falls through to stock AI on any failure, so a broken call means ordinary play rather than a stuck game. **That also makes failures invisible in-game — the log is the only way to see them.**

## Lessons that constrain what comes next

**Getting a usable answer out of the LLM**
- **Constrain the output structurally; asking in the prompt isn't enough.** A first run asked for "only the bare key" and applied only 4 of 12 decisions. Five times Claude corrected itself in prose (`"TECH_AGRICULTURE... wait, that's already known... TECH_WRITING"`). Three times it picked a tech that was illegal (missing prerequisite) or already known. Two fixes brought it to 13/13: offer a pre-filtered candidate list (`rules.py tech --available`), and constrain the reply with `--json-schema` using an `enum` built from that same list. Apply the same pattern to every future decision: enumerate the legal options in code, then have the model choose one.
- **`is_error: false` is not a validity check.** Haiku on low effort returned fluent, well-formatted, entirely fabricated plans and reported success. The mod still re-validates every answer independently.
- **Don't economise on model or effort; shrink the context instead.** Haiku was unusable, and Sonnet on low effort broke the output contract. Cost is dominated by reading the input, not generating the answer.

**Calling `claude -p` from a script**
- **Call `claude.cmd` directly**, resolved with `shutil.which` and given an argument list via `subprocess.run`. Routing through `powershell -Command` breaks on a JSON schema: PowerShell reads `{`/`}` as a script block. It also avoids Git Bash's first-call shell-snapshot cost (measured at 12–38s).
- **Run with `cwd` outside this repo.** From inside, `claude -p` auto-loads CLAUDE.md and memory: ~67k tokens and ~$0.27 before the prompt is read.
- A tool-free call with a small prompt takes 9–14s. A tool-using advisor-style call took 71–142s.

**Blocking calls inside callbacks**
- A blocking call freezes the whole game for its duration (confirmed with an artificial 5s delay). The limit is how often the callback fires, not whether a freeze happens at all:

| Callback | Receives → returns | Fires | Synchronous LLM call? |
| --- | --- | --- | --- |
| `AI_chooseTech(ePlayer, bFree)` | player id → **`TechTypes` int**, `-1` falls through | per research choice | ✅ tolerable, confirmed |
| `AI_doWar(eTeam)` | **team** id → `1`/`0` | per team per turn | ⚠️ ~10s every turn |
| `AI_doDiplo(ePlayer)` | player id → `1`/`0` | per player per turn | ⚠️ ~10s every turn |
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
ai-opponent/                  decide_tech.py, decide_tech_log.jsonl
harness/rules.py              tech --available serves both projects
devtools/                     dev-only: unattended launch/autoplay, never shipped
```

**The mode check is folded into the identity check** (`_advisorPlayerId()` returns `None` when opponent mode is off), so hot callbacks pay one branch, not two.

`decide_production.py` and `decision_config.txt` in `ai-opponent/` are leftovers from the production stub spike; nothing calls them.

## Test platform

Two AI civs on a mirrored map, no human playing, running unattended.

- **Map:** `PublicMaps/Mirror.py` ships with the game. A symmetric two-civ game is set up as 4 civs in 2 teams: autoplay removes the human and `KILL_LEADERS` removes the fourth civ (`devtools/README.md` "Fixtures"). By hand, run **both** `gc.getPlayer(X).killCities()` and `.killUnits()` in the Python console: a leftover Settler keeps a civ alive.
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
- ❓ Subscription or API key for unattended runs? At the ~450k tokens per turn a tool-using call measured, a 300-turn game would hit a subscription's rate limits mid-run; the lean tech call is far smaller.
- ❓ Is the one-turn lag on unit orders acceptable?
- ❓ `AI_doWar` is team-scoped — what happens in a team game?
- ❓ Does the opponent need its own setup entry point, separate from the player-facing `setup.ps1`?
- `decide_tech.py` has no unit tests; it was verified live against real state files.

## Deliberately not doing

- **A custom DLL.** If a design seems to need recompiling `CvGameCoreDLL`, re-scope instead.
- **Pathfinding or turns-to-arrive.** The engine repaths every turn and caches no ETA.
- **Replacing the whole AI.** CivBench's result comes from the hybrid: LLM on strategy, procedural AI on execution.
