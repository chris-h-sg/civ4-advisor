# Plan — an LLM-controlled AI opponent

**Status: research complete, nothing built.** This is a *sibling project* to the advisor, not a phase of it — different runtime, different prompts, different output contract. The advisor's era cutoff is meaningless to a civ that has to play to turn 300, and its fog-honesty rules are inverted here. Keep it out of `ROADMAP.md`, which is the advisor's queue.

**Sibling in runtime, shared in the mod** — see [Repo layout](#repo-layout) for why those pull in opposite directions.

Prompted by [CivBench](https://arxiv.org/html/2604.07733v1) / [Vox Deorum](https://arxiv.org/abs/2512.18564), which put an LLM in charge of Civ V's *strategic* layer and left tactical execution to the existing procedural AI. The question was whether Civ 4 allows the same. It does, and with a finer-grained seam than Civ V offered — but Civ V's team still needed a modified DLL, and the shape of the Civ 4 version is different enough to be worth writing down.

Everything below is read from the BTS SDK source bundled at `Beyond the Sword/Mods/The Road to War/CvGameCoreDLL` (stock for these files) and cross-checked against `Rhye's and Fall of Civilization/CvGameCoreDLL` where they differ. **Almost none of it has been run in-game.** Items are marked ✅ verified in source / ⚠️ needs live confirmation / ❓ open question.

---

## What the engine gives us

### The five AI callbacks

Civ 4 ships Python override points for AI decisions in `Assets/Python/CvGameUtils.py`. Stock BTS dispatches all five; RFC comments them out for speed, which is itself evidence about cost.

| Callback | Receives | Returns | Fires |
| --- | --- | --- | --- |
| `AI_chooseTech(ePlayer, bFree)` | player id | **a `TechTypes` int**; `-1` → fall through | per research choice |
| `AI_chooseProduction(pCity)` | `CyCity` | `1` = handled / `0` = fall through | per city, per build |
| `AI_doWar(eTeam)` | **team** id | `1` / `0` | once per team per turn |
| `AI_doDiplo(ePlayer)` | player id | `1` / `0` | once per player per turn |
| `AI_unitUpdate(pUnit)` | `CyUnit` | `1` = abort loop, wait for next slice / `0` | **every unit, every update slice** |

✅ The contract is real delegation: return 0 and the built-in AI runs exactly as before. That makes every level of adoption optional — you can take over tech alone and leave everything else stock.

✅ They are **not** in the `USE_*_CALLBACK` gating list in `XML/PythonCallbackDefines.xml` (25 flags, all defaulting to 0). The `AI_*` five are always live.

⚠️ `AI_unitUpdate` fires per unit per slice, from `CvGame.cpp:6564`. RFC disabled it for performance on 2007 hardware with *empty* Python stubs, so the cost is call overhead, not our work. **Unmeasured. Measure before relying on it.**

### Three tiers of control, not one

Not everything has a callback. `AI_doTurnPre()` (`CvPlayerAI.cpp:296`) calls a set of pure-C++ methods with **zero** Python dispatch — verified by grepping each for `callFunction`:

```
AI_doResearch()   AI_doCommerce()   AI_doMilitary()
AI_doCivics()     AI_doReligion()   AI_doCheckFinancialTrouble()
```

`AI_doCommerce` is where the science/gold/culture/espionage sliders get set; `AI_doCivics` is government; `AI_doReligion` is state religion.

But ✅ every corresponding **setter** is exposed to Python on `CyPlayer`: `setCommercePercent`, `changeCommercePercent`, `setCivics`, `revolution`, `setEspionageSpendingWeightAgainstTeam`, `doEspionageMission`, `setLastStateReligion`. Also `AI_civicValue`, so the AI's own valuation is readable.

So:

| Tier | Mechanism | Covers |
| --- | --- | --- |
| **Authoritative** | the 5 callbacks, return 1 | tech, production, war, diplo, unit orders |
| **Last-writer-wins** | Python setters, applied *after* `AI_doTurnPre` | sliders, civics, religion, espionage targeting |
| **Unreachable** | pure C++, no setter | attitude internals, `AI_doMilitary` posture, war-plan scoring |

The middle tier is overwrite-not-intercept: you re-assert each turn rather than replacing the logic. Cheap (`setCommercePercent` is one call), and ✅ `AI_doCivics` early-outs on `AI_getCivicTimer()`, so civics don't thrash.

Nothing in the third tier is early-game critical, and `AI_chooseProduction` largely neutralises `AI_doMilitary` by simply choosing what gets built.

### Execution order — the trap

✅ Traced through `CvPlayer::doTurn()` and `CvPlayer::setTurnActive()`. **In sequential (single-player) games `doTurn()` runs on turn *deactivation*, not activation** — the activation-branch call is gated on `MPOPTION_SIMULTANEOUS_TURNS`.

```
setTurnActive(TRUE)                       ← AI turn begins
  └── doTurnUnits()
        └── AI_unitUpdate()  ×many        ← PYTHON callback #5

      ... AI plays ...

setTurnActive(FALSE)                      ← turn ends
  └── doTurn()
        ├── onBeginPlayerTurn             ← PYTHON event   (CvPlayer.cpp:2492)
        ├── AI_doTurnPre()                ← sliders/civics set HERE (2498)
        ├── pLoopCity->doTurn()
        │     └── AI_chooseProduction()   ← PYTHON callback #2
        ├── AI_doTurnPost()
        │     └── AI_doDiplo()            ← PYTHON callback #4
        └── onEndPlayerTurn               ← PYTHON event
```

Team level, separately: `CvTeamAI::AI_doTurnPre()` → `AI_doWar()` → callback #3.

**Two consequences.**

1. This is the same misleading naming the advisor already documents in `CLAUDE.md` for the human player. It does **not** go away for AI players. An earlier read in this research said it did; that was wrong.
2. **A plan computed at `onBeginPlayerTurn` reaches production and diplomacy the same turn, but unit orders only next turn** — `AI_unitUpdate` already ran, during activation. There is a structural **one-turn lag on the tactical layer**. Probably acceptable given the pace and the fall-through safety net, but design around it rather than discovering it.
3. Global settings (sliders, civics) must be applied at **`onEndPlayerTurn`**, after `AI_doTurnPre` has had its say. Setting them at `onBeginPlayerTurn` gets overwritten the same turn.

### Targeting one AI only

✅ The callbacks are global dispatch points, not per-player registrations — every AI flows through the same five functions, so gate on identity inside each:

- `AI_chooseTech` / `AI_doDiplo` → player id passed directly
- `AI_chooseProduction` / `AI_unitUpdate` → `pCity.getOwner()` / `pUnit.getOwner()` (both verified exposed)
- `AI_doWar` → **team** id. 1:1 with players in a standard game, but in a team game this covers several civs. Check explicitly.

Everyone else returns 0 and plays stock, with no special casing.

For *which* AI is ours: ✅ `getScriptData`/`setScriptData` are exposed on `CyPlayer`. Tag the chosen AI once at `onGameStart` and read the tag thereafter — same trick the mod already uses for `gameId`, and it survives save/reload for the same reason. `getLeaderType()` is the simpler alternative if no two civs share a leader.

---

## The test platform

Goal: mirrored map, one LLM civ, one stock civ, no human, runs unattended.

✅ **Mirrored map ships with the game.** `PublicMaps/Mirror.py` — "Generates half a map, then mirrors it," by Bob Thomas. Three custom options, four reflection modes in source (horizontal, rotational, two offset variants). Nothing to build.

⚠️ **No-human games are supported, two routes.** `CvGame::update()` ends the game when `countHumanPlayersAlive() == 0` *unless* autoplay or autorun is on:

- `CyGame.setAIAutoPlay(N)` — ✅ exposed to Python, decrements per game turn, calls `reviveActivePlayer()` at 0.
- `Autorun = 1` in `CivilizationIV.ini` — already present in the local ini at line 210, with `AutorunTurnLimit = 0` at 207. Engine-side, **not** Python-exposed.

⚠️ **Stock `setAIAutoPlay` destroys the active player's units and cities** on activation:

```cpp
if ((iOldValue == 0) && (getAIAutoPlay() > 0))
{ GET_PLAYER(getActivePlayer()).killUnits(); killCities(); }
```

RtW's SDK replaces this with `setDisableHuman()`; stock does not. So the human slot must be a **third, empty observer**, never one of the two contestants. `Autorun` avoids the kill entirely and may be the better route.

Observation is free — the existing exporter already writes every turn, and `calculateScore` gives a crude per-turn metric immediately (the cheap version of CivBench's victory-probability estimator).

---

## Repo layout

Built on a branch, framed as **"add AI-opponent mode"** rather than "add a second mod" — that keeps the diff honest about what is actually changing, and the exporter fix (item A) is a change to *shared* code both projects then depend on.

```
mod/                          ← ONE mod, mode-switched
  Assets/Python/
    AdvisorStateWriter.py     ← shared; untouched except item A
    CvCustomEventManager.py   ← gains 2 hooks + mode guards (~65 lines)
    CvAdvisorGameUtils.py     ← NEW: the five AI_* callbacks
    LocalConfig.py            ← gains MODE + which civ we drive
    EntryPoints/
      CvEventInterface.py     ← unchanged
      CvGameInterfaceFile.py  ← NEW: one-line indirection (see below)
harness/                      ← shared, unchanged
advisor/                      ← human-advisor runtime
ai-opponent/                  ← NEW: opponent runtime, prompts, watcher
docs/AI_OPPONENT_PLAN.md
```

### One mod, not two

The runtime halves share nothing worth sharing — different prompts, triggers and output contract, and `advisor/CLAUDE.md` is 9 KB of human-facing formatting rules that are pure per-turn cost to an opponent. So `ai-opponent/` is a clean sibling.

The **mod** goes the other way:

1. **The overlap is nearly total.** 1,805 of the mod's 2,004 lines are `AdvisorStateWriter.py`, which the opponent needs *unchanged*. What differs is a ~65-line event-manager delta and a new `CvGameUtils` subclass.
2. **`buildState(gameTurn, playerId, trigger)` is already parameterised by player.** Only `_requireActivePlayer` (item A) stops it serving an AI civ; a second caller with a different id is not a modification.
3. **A Civ 4 mod is a whole-directory switch.** Two mod folders could never both be live, so separate mods buy isolation you can't use while costing two `.ini`s, two junctions, two `setup.ps1` paths and two `LocalConfig.py`s. Sharing between them means junctions-within-junctions or a copy step — and `CLAUDE.md` records the junction as load-bearing and quietly hazardous (the OneDrive ReadOnly discovery). Do not add a second layer to it.
4. **It would fork the file we most want single** — two copies of the 1,805-line hot-reloadable writer, against `CLAUDE.md`'s rule that new extraction logic goes in `AdvisorStateWriter` (hot-reloadable) rather than `CvCustomEventManager` (isn't).

### The two entry points don't collide

✅ The `AI_*` callbacks do **not** route through `CvEventInterface.py`. They go via `EntryPoints/CvGameInterface.py`, which delegates through an indirection file the base game ships *for exactly this purpose*:

> "MODDERS - If you create a GameUtils file, update the CvGameInterfaceFile reference to point to your new file"

So `CvGameInterface.py` is never modified; we add:

```python
import CvAdvisorGameUtils
GameUtils = CvAdvisorGameUtils.CvAdvisorGameUtils()   # was CvGameUtils.CvGameUtils()
```

A cleaner seam than the advisor got — `CvEventInterface.py` had to be copied and edited; this one is a designated hook. The two projects never contend for the same file.

### Mode gating

```python
MODE = 'advisor'   # | 'opponent' | 'both'   (LocalConfig.py, default 'advisor')
```

Sketched against the real file, the delta to `CvCustomEventManager.py` is **+62 lines added, ~3 changed** (one `if _advising():` per existing hook), **0 removed**.

Two rules the sketch settled:

- **Default `advisor`, and every new branch dead when it is.** The advisor path must be byte-identical with opponent mode off — a property `mod/tests/` should *assert*, not one we claim. ⚠️ This is the mitigation for adding a second mode to a mod whose hard constraint is never crashing the game; treat it as a requirement, not a nicety.
- **No separate mode check on the hot path.** `AI_unitUpdate` fires per unit per slice, so `isDriven()` returns False for everyone when the mode is off — folding the mode test into the ownership test. One branch, not two.

---

## Work items

### A. Unblock the exporter for non-active players — *prerequisite for everything*

`buildState` refuses to run when the exported player isn't the active player (`_requireActivePlayer`), because of two getters. Both turn out to be fixable rather than blocking:

- ✅ **`calculateYield(bDisplay=True)`** — read `CvPlot::calculateYield` (`CvPlot.cpp:5873`). The active-team reference lives *entirely* inside the `if (bDisplay)` branch; the `else` branch uses `getOwnerINLINE()`/`getImprovementType()`/`getRouteType()`, no active team anywhere. `bDisplay=False` is a clean fix, and for an AI player true values are what we want.
- ✅ **`getVisualOwner()`** — `CvUnit.cpp:10954` takes `TeamTypes eForTeam` and only falls back to the active team on `NO_TEAM`. The C++ is fine; the *Python binding* drops the argument. For our own AI there's nothing to hide, so `getOwner()` is the honest call.

❓ This changes the export's central invariant. Decide whether it's a flag on the existing path or a separate fog-free export mode. **Do not** quietly relax `_requireActivePlayer` for the advisor's path — that guard exists for a reason.

Also worth exporting, since the AI consults it and we'd be replacing a decision that had access: `AI_getAttitude`, war plans, `AI_getBonusValue`, financial-trouble flags.

### B. Measure `AI_unitUpdate` overhead — *gate on the tactical layer*

Empty Python stub, count units, time a turn. ~20 minutes. If it's bad, the strategic-only version (callbacks 1–4, no unit hook) is closer to what CivBench actually did anyway and needs none of it.

### B2. Mode gating and the callback surface

Build out the files listed under [Repo layout](#repo-layout), plus a `mod/tests/` case asserting the advisor path is unchanged with `MODE == 'advisor'`. `CvAdvisorGameUtils` subclasses the base `CvGameUtils` — imported, not copied, the same convention the event manager already follows. Sketched and checked for Python 2.4 (no f-strings, ternaries, `with`, decorators, or `except X as e`).

**Return-contract trap.** ✅ `AI_chooseTech` returns a **`TechTypes` int**, not a boolean — `CvPlayerAI` does `eBestTech = (TechTypes)lResult` and falls back to `AI_bestTech()` only on `NO_TECH`. Writing `return False` there by reflex silently means "tech 0". The other four are `1`/`0`.

Every hook and callback needs the never-crash wrapper: one raising in `AI_unitUpdate` would do so once per unit per slice.

### C. The decision loop

**Never call the LLM synchronously inside a callback.** These are blocking C++→Python calls inside turn processing; a live call freezes the game and violates the standing "mod must never crash or hang the game" constraint.

```
onBeginPlayerTurn(turn, aiPlayerId)
  → mod writes turn_NNNN.json, polls (bounded, ~30s) for plan_NNNN.json
  → watcher (ai-opponent/, Python 3, outside the game) sees state, calls Claude
  → watcher validates, writes plan_NNNN.json atomically
  → mod caches plan, returns
callbacks → dict lookup by unit/city id → push order, return 1
          → miss or timeout → return 0 → stock AI plays it
onEndPlayerTurn → apply sliders/civics (after AI_doTurnPre has had its say)
```

The fall-through is the whole safety design: a missing plan means the game plays normally.

`ai-opponent/` holds the watcher, the prompt, the plan schema and the validator. Nothing in it is shared with `advisor/`.

⚠️ Python 2.4 side: `socket`, `threading`, `httplib`, `urllib` ship in `Assets/Python/System/` (185 modules); **`subprocess` does not**. Use `os.spawnv(os.P_NOWAIT, ...)` or `os.popen` if spawning, though file-based needs neither.

❓ Whether `setCommercePercent` from Python triggers the same dirty flags / cache recalculation as the C++ path. The binding calls straight through so it probably does — "probably" isn't measured.

### D. Headless Claude — measured, with caveats

Verified working: `claude -p` with `--output-format json` and `--json-schema` returns a validated `structured_output` object. `--permission-mode acceptEdits` plus a pre-seeded allowlist ran 9–18 tool-using turns with zero denials, unattended.

Measured on a real advisor call (turn 34, `d:\joao`):

| | |
| --- | --- |
| wall clock | 71–142 s per call |
| model time | ~40–75 s (the dominant term) |
| tool time | ~23 s |
| fixed startup | ~5 s |
| **first Bash call** | **12.5–37.7 s** |
| API-equivalent cost | $0.37–0.67 |

Findings that matter for a 300-turn loop:

- ⚠️ **Use PowerShell, not Git Bash.** `CLAUDE_CODE_USE_POWERSHELL_TOOL=1` plus `--disallowed-tools "Bash"`, and parallel `PowerShell(...)` allowlist rules — the existing ones are Bash-specific. Git Bash pays a one-off **shell snapshot** on first Bash call, base64-encoding each of 84 shell functions in its own ~86 ms process, then **fails and discards the work**. Measured: 112 s → 88 s wall, worst tool call 12.5 s → 4.9 s.
- ⚠️ **Run the watcher's cwd *outside* this repo.** `claude -p` from here auto-loads CLAUDE.md + auto-memory: 66,722 cache-creation tokens, ~$0.27, *before reading the prompt*. A trivial prompt exhausted a $0.15 budget cap and returned `error_max_budget_usd`.
- ⚠️ **`is_error: false` is not a validity check.** Haiku/low produced fluent, well-formatted, entirely fabricated output — wrong turn number, invented units, invented sites — and reported success. **Validate every plan against the state file** (turn number, unit ids, coordinates) before acting on it.
- **Don't economise on model or effort.** Haiku cost 58% of Sonnet's price and was unusable; Sonnet/low twice broke the output contract (85- and 111-character answers). The floor is context ingestion, not generation, so **shrink the context instead** — pre-render the diff and map in the watcher and hand the model a compact brief.
- ❓ Subscription vs API key. This ran on Pro, so `total_cost_usd` is a usage meter, not a bill — but 300 turns × ~450k tokens would exhaust rate limits mid-game and silently corrupt a benchmark run. Probably: subscription for interactive work, API key for unattended runs.
- Fast mode is unavailable headlessly (`sdk_opt_in_required`); no CLI flag or env var reaches it.

### E. Evaluation

`calculateScore` per turn is free and immediate. CivBench's contribution was a trained per-turn victory-probability estimator over 24 features; that's a much later concern. Start with score curves and win rate across repeated mirrored runs.

⚠️ **n=1 is not a result.** Repeated runs in this research showed `api_ms` swinging 39 → 74 s on *identical* inputs, and the two Sonnet/low runs differed wildly in behaviour. Any claim about LLM-vs-stock needs many games.

---

## Sequence

Branch first; everything below lands on it.

1. **B** (measure `AI_unitUpdate`) — cheapest, and decides whether the tactical layer is in scope at all.
2. ⚠️ **Confirm `Autorun` actually works from a normal game start.** Referenced in three SDK places and present in the ini, but may be intended for a specific launch path. 10-minute test, and the whole platform depends on it.
3. **A** (exporter for non-active players) — prerequisite for everything else; nothing can be observed without it. Shared-code change, so it lands before the mode scaffolding.
4. **B2** (mode gating + callback surface), with the advisor-path-unchanged test written *first*.
5. **Spike: `AI_chooseTech` only.** One callback, once per tech, one AI civ, everything else stock. Proves the whole chain — export → watcher → Claude → plan file → callback — on the cheapest possible decision.
6. **C** (the full loop) and the mirrored-map platform.
7. **E** (evaluation) once games run end to end.

Steps 1 and 2 are both throwaway measurements that can kill or reshape the design; do them before writing anything that assumes the answer.

## Open questions

- ❓ Does the export need a fog-free mode, or a flag on the existing path? (A)
- ❓ Does `setCommercePercent` from Python fire the same side effects as the C++ path? (C)
- ❓ Subscription or API key for unattended runs? (D)
- ❓ Is the one-turn unit-order lag acceptable, or does it want a same-turn workaround?
- ❓ `AI_doWar` is team-scoped — what happens in a team game?
- ❓ Does `setup.ps1` / `new_game.ps1` need an `ai-opponent` equivalent, or a `--mode` flag? Those are written for a non-coding player; a benchmark harness has a different audience and probably wants its own entry point.
- ⚠️ The `AI_unitUpdate` lag specifically is a reading of the source, not measured. Confirm with a logging stub before building on it.

## Deliberately not doing

- **A custom DLL.** Vox Deorum needed one because Civ V's strategic module lives in C++; Civ 4 hands us the callbacks in Python. If a design ever seems to require recompiling `CvGameCoreDLL`, that is the signal to re-scope, not to start compiling.
- **Pathfinding / turns-to-arrive.** Already on the advisor's not-building list; the engine repaths each turn and caches no ETA.
- **Replacing the whole AI.** The point of the CivBench result is the *hybrid*: LLM on strategy, procedural AI on execution. Taking over everything discards the thing that makes it work.
