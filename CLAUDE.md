# civ4-advisor

## What this is

A harness that lets an AI (Claude) observe game state from **Civilization IV: Beyond the Sword** and give strategic advice. Long-term goal: the AI eventually suggests concrete actions the player executes on its behalf. Current goal, much smaller: get advice-only working end to end, scoped to the **first 20 turns** of a game.

## Why Civ IV

Civ IV exposes a full Python 2.4 scripting layer (the `Cy*` API — `CyGame`, `CyPlayer`, `CyCity`, `CyUnit`, `CyPlot`, `CyTeam`) that the modding community has used for years to read and influence live game state. This lets us extract structured game state directly via the game's own event hooks, instead of relying on screenshots + vision models. The game is turn-based, so latency is a non-issue — no reflex/timing pressure on the AI call.

## Architecture: two independent parts, no shared code

- **`mod/`** — lives inside Civ IV's Python layer. Runs in the game's embedded **Python 2.4** interpreter. Windows-only, tied to the actual game install. Its only job: hook into the game's turn-cycle events and write a snapshot of player-visible game state to a JSON file on disk. (Not `onBeginPlayerTurn` alone, despite the name suggesting "start of turn" — see Design decisions below; the naming is misleading relative to actual firing order.)
- **`harness/`** — a normal external **Python 3** project. Reads the state file, sends it (plus static XML-derived rules data) to the Claude API, prints back strategic advice. No dependency on Civ IV being installed — developable/testable purely against saved fixture files.

The only contract between the two parts is **the JSON file on disk**. Neither part imports from or depends on the other's code.

## Current phase — what's actually being built right now

Building the **mod first**. Plan is to play a few real turns in-game to capture actual state-dump JSON files as samples in `samples/`. The harness, for now, reads a **single static file** — no polling, no file-watching, no live loop yet. That comes later once the mod produces real output.

Do not implement live-loop harness logic, action execution, or a finalized state schema until explicitly asked — these are future phases, not current scope.

## Scope for now

- Turns 1–20 only: exploration, first cities, early tech/civics.
- State categories to eventually cover: visible map tiles, unit info, city data, current research, civics, diplomacy status. **The field-level schema is not finalized** — it's being designed incrementally as the mod is built, not upfront.
- Advice only. No action execution yet.

## Key technical constraints

- **`mod/` targets Python 2.4.** No `json` module (postdates 2.4), no f-strings, no modern syntax. JSON serialization inside the mod must be hand-rolled or use a 2.4-compatible vendored library — never assume the standard `json` module is available here.
- **`harness/` targets modern Python 3.** Normal tooling, `json`, type hints, etc. all fine.
- File writes from the mod should be **atomic** (write to a temp file, then rename) so the harness never reads a half-written file.
- All fragile/networked code (API calls, retries, error handling) belongs in the harness. The mod must never crash or hang the actual game — it writes a file and returns control, full stop.
- Secrets (API keys) via env var or a local gitignored config file. Never hardcoded, never committed.

## Design decisions already made (don't relitigate without reason)

- File-based IPC over sockets/HTTP — simplest thing that works for a turn-based, single-machine setup.
- XML rules data (unit stats, building costs, tech tree, civics) is static: parse once, cache in the harness, don't re-send the full file every turn.
- Turn-20 cutoff logic belongs in the harness, not the mod — keeps the mod dumb and avoids redeploying it in-game every time scope changes.
- Log each turn's state + returned advice somewhere durable (append-only JSON lines is fine) for debugging prompt quality over time.
- If/when this becomes a public portfolio repo: never vendor Firaxis SDK headers/binaries or copyrighted game assets — reference them as "install into your own Civ IV directory," don't bundle them.
- Local Civ IV install/Mods folder paths live in `config.local.json` (gitignored, machine-specific — other contributors' paths will differ). `config.local.json.example` documents the expected shape and is committed.
- Saved real state-dump JSON captured from actual play sessions are called **samples**, stored in `samples/` (not "fixtures").
- Mod name is `civ4-advisor`, matching the repo. Its `.ini` lives at `mod/civ4-advisor.ini`, kept minimal (just `Name`/`Description`) — explicit `.ini` flags like `AllowPublicMaps = 0` blocked "Play Now"/"Custom Game" (no map scripts available), so we let everything else fall back to engine defaults rather than guessing at "safe" values. Confirmed against `Next War`, a working full (non-scenario-locked) mod, whose `.ini` is similarly near-empty.
- `mod/` is the source of truth; it's deployed into the real Mods folder via a **directory junction** (`mklink /J`), not a copy step and not a symlink (symlinks need admin privileges on Windows; junctions don't). Edits in the repo are live in-game immediately.
- A mod only needs to ship the specific files it overrides — not a full copy of the base game's `Assets/Python/` tree. Currently that's `Assets/Python/EntryPoints/CvEventInterface.py` (base file, only its event-manager import/instantiation changed), `CvCustomEventManager.py` (new), and `AdvisorStateWriter.py` (new).
- **Event hooks go through `CvCustomEventManager.py`, subclassing the base (imported, not copied) `CvEventManager.CvEventManager`** — not a modified copy of the base file. This is the community-established pattern (see `REFERENCES.md`): `CvEventInterface.py` (the real C++ entry point) only has its top changed, `import CvCustomEventManager` / `normalEventManager = CvCustomEventManager.CvCustomEventManager()`, the four functions below untouched. Each override calls the superclass method first to preserve base behavior. Rationale: a full copied `CvEventManager.py` is 1000+ lines with a handful changed — a lot of surface area to review and easy to drift from the original; `CvCustomEventManager.py` contains only what we added. Does **not** solve the hot-reload limitation below — the engine still holds a reference to an instantiated custom-manager object either way.
- **`onBeginPlayerTurn`/`onEndPlayerTurn` do not bound the player's actual interactive turn, despite the naming** — no hook fires during the player's actual interactive play. `onBeginPlayerTurn(N, human)`/`onEndPlayerTurn(N, human)` only fire back-to-back once "End Turn" is clicked (matching turn N, the one just concluding, no numbering offset), followed by the same pair for every AI civ in player-ID order, only then followed by `onBeginGameTurn(N)`/`onEndGameTurn(N)` — all at turn *end*, not beginning. Confirmed via in-game instrumentation and independently corroborated by TGA's Python Tutorial (see `REFERENCES.md`). Net effect: no hook fires at the exact moment the player gains fresh control for a new turn — hence the export strategy below.
- **State export uses `onGameStart` + `onLoadGame` + `onEndGameTurn` — not `onBeginPlayerTurn`.** `onGameStart` fires once, before the game's true first turn has been played (no numbering adjustment needed). `onLoadGame` covers the same case for a resumed save, since `onGameStart` only fires for a new game. `onEndGameTurn` fires *last* in a round's processing (after human + every AI civ) — the freshest available proxy for "what the player is about to see" once they silently regain control — using `iGameTurn + 1` since the round it reports just finished. All three share a common `_exportState` helper on `CvCustomEventManager`, wrapped in `try/except: pass` per the "mod must never crash" constraint above.
- Live per-turn state is written to `state/current_turn.json` at the repo root (gitignored — regenerated live output, distinct from the curated, committed `samples/`).
- `_exportState` calls Python 2's `reload()` builtin on `AdvisorStateWriter` (which itself reloads `LocalConfig`) every export, as a dev convenience — edits to those two files take effect next turn without restarting the game. Does **not** extend to `CvCustomEventManager.py` itself: the engine holds a reference to an already-instantiated object, and `reload()` can't retroactively update it, so hook-logic edits need a full restart. No workaround for this exists anywhere in the community (checked — see `REFERENCES.md`) or in the base game's own scripts.
- **`__file__`-relative path derivation does not work inside the embedded interpreter** — the engine reports a mod's Python module paths relative to its own `Assets/Python` search root, not the real physical file location, even through the deployment junction. State output path instead comes from `mod/Assets/Python/LocalConfig.py` (gitignored, machine-specific — `LocalConfig.py.example` is the committed template), a plain Python module the mod imports directly rather than a parsed config format, since Python 2.4 has no `json` module. If `LocalConfig.py` is missing, `getStateFilePath()` returns `None` and `writeStateFile` no-ops rather than crashing.
- **`Logs\PythonDbg.log` only updates continuously if `LoggingEnabled = 1` is set in `CivilizationIV.ini`** (default `0`) — with it off, most log files only get written once during initial startup and never again, even though the process keeps running and dispatching events. `HidePythonExceptions` in the same file only suppresses the in-game popup, not the log.

## See also

`REFERENCES.md` for API docs, prior art, and other links gathered during research.
