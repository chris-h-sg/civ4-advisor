# mod/

Civ IV: Beyond the Sword mod. Runs inside the game's embedded **Python 2.4** interpreter.

> [`docs/MODDING.md`](../docs/MODDING.md) is the narrative version of the API findings below, written for an outside modding audience. This file stays the working reference.

## Constraints

- Python 2.4 only: no `json` module, no f-strings, no modern syntax. See root `CLAUDE.md` for the full list.
- Must never crash or hang the game. All fragile logic (network calls, retries) belongs in `harness/`, not here. Export failures are swallowed — but logged, so a silent failure isn't mistaken for the mod not running.
- File writes go to a temp file, then rename over the target. Note this is *not* a fully atomic replace: Windows `os.rename` fails when the target exists and Python 2.4 has no `os.replace`, so the old file is removed first. There's a brief window where the state file is **absent**, never one where it's half-written — a missing file is detectable and retryable, a truncated one parses as garbage.

## Purpose

Hooks into the game's event system and writes a snapshot of player-visible game state to a JSON file on disk. That file is the only contract with `harness/` — nothing here is imported by or depends on `harness/` code.

## Structure

- `civ4-advisor.ini` — mod definition file. Committed in the **expanded** form the engine writes, every flag spelled out at its default. Don't revert it to the minimal `Name`/`Description` version: the engine rewrites it on every load, so the revert only makes the file show as modified again. The one value that matters is `AllowPublicMaps = 1` — setting it to `0` blocks "Play Now"/"Custom Game" by leaving no map scripts available. See root `CLAUDE.md`.
- `Assets/Python/EntryPoints/CvEventInterface.py` — copied from the base BTS install; only the event-manager import/instantiation at the top is changed, to point at our own `CvCustomEventManager` instead of the base `CvEventManager`.
- `Assets/Python/CvCustomEventManager.py` — our actual logic. Subclasses the base game's `CvEventManager` (imported, not copied) and overrides only the methods we need, calling the superclass method first in each to preserve base behavior.
- `Assets/Python/AdvisorStateWriter.py` — all state extraction, plus the hand-rolled JSON serializer and atomic file writer (no `json` module in Python 2.4). Everything schema-related lives here rather than in the event manager because this module is re-read from disk on every export, so edits take effect next turn without restarting the game (see "Editing while the game runs" below).
- `Assets/Python/LocalConfig.py` — gitignored, machine-specific. Holds `STATE_DIR`, the root directory the mod writes per-game state folders under, plus the optional `MOD_PYTHON_DIR` and `LOG_TIMINGS`. `LocalConfig.py.example` is the committed template.
- `tests/test_state_writer.py` — developer-side `unittest` suite (runs under **Python 3**, needs `jsonschema`) that execs the real `AdvisorStateWriter.py` against mocked `Cy*` objects, so extraction, serialization, and file writing can all be checked without launching the game. Run it with `python mod/tests/test_state_writer.py`.

  It covers the serializer (escaping, control characters, non-ASCII, inline-vs-broken layout, key sorting/determinism), extraction (every exported field, the no-research-selected path, entity sorting and the dead/foreign/invalid/unmet/fogged filters, the production-kind cascade, field-level omission at defaults, and that the right sentinel/overflow flags are passed), file writing (directory creation, UTF-8 bytes, no line-ending translation, overwrite, temp-file cleanup, `None`-path no-op), and validates the export against the **whole** of `schema/state.schema.json` — which is only possible now that no section is omitted, and which is what makes the schema's top-level `required` and `additionalProperties: false` bite.

  Where a method must *not* be called, the mock raises rather than returning a plausible value. `CyUnit.movesLeft` is set up that way, since reading it at export time would silently yield last turn's number; so are `CyPlot`'s live `getImprovementType`/`getRouteType`/`getOwner` (they see through fog — the revealed variants must be used), `getYield` (the non-displayed yield), `isBeingWorked`/`getWorkingCity` (no visibility check; worked tiles are read city-side), and `getPlotType` (the `PlotTypes.PLOT_*` constants are unverified in the Python layer). Same for the whole-map censuses that sit next to the safe setup getters — `CyMap.getLandPlots`/`getOwnedPlots`/`getNumBonuses`/`getNumAreas` and `CyGame.countCivPlayersAlive` — which describe the map as *generated*, including everything the player has never seen.

  The diplomacy sections add a second tier of these, because they are the ones handling other players' objects. A rival `CyPlayer` raises on their gold, research, civics, city/unit counts and power; a rival `CyCity` raises on every city-screen internal (stores, production, mood, worked tiles); a rival `CyTeam` raises on *everything*, because nothing should ever fetch one — `isHasMet` is symmetric, so the relation is asked of our own team instead. `CyUnit.getOwner` raises so that `getVisualOwner` is used and a hidden-nationality unit is never unmasked. And `CyPlot.getPlotCity`/`isCity` raise, which is the one that guards against a plausible-looking optimisation: folding foreign cities into the map sweep would read live truth and surface cities founded under fog that the player has never seen.

  The mission queue (`units[].mission`) adds its own shape of check rather than a tripwire: the mocked `CySelectionGroup` records which queue indices were read, so `test_only_the_head_of_a_multi_mission_queue_is_exported` asserts index 0 and nothing else — a walk over the whole queue fails rather than silently exporting a backlog. The `MISSION_MOVE_TO_UNIT` case has a dedicated test for the same reason the plot getters have tripwires: its `iData1`/`iData2` pair is a (player ID, unit ID), not a coordinate, so exporting it as a `destination` would produce a plausible, wrong map position.

  Two blind spots to keep in mind: it runs on a modern interpreter, so it **cannot catch Python 2.4 syntax violations** (check those by eye — no conditional expressions, `.format()`, or f-strings); and the mocked `Cy*` objects encode our *belief* about the game API, so it can't catch a wrong assumption about what a real game method returns. Only running the game does that — as it did for `movesLeft`, where the mocks were internally consistent and the assumption was still wrong, and again for `mission.turnsLeft`, which shipped one turn too high past a green suite until the number was checked against the game UI. **Check every new field against the game's own UI once before trusting it**; a passing suite is not evidence about the API.

Only files that override base game behavior need to exist here — everything else (including the base `CvEventManager.py` itself) falls back to the base install automatically.

## Event hook architecture

We do **not** copy and modify `CvEventManager.py` directly. The community-established pattern (see `REFERENCES.md` and `CLAUDE.md` for the full reasoning): leave `CvEventManager.py` untouched, put mod logic in `CvCustomEventManager.py` subclassing it, and edit only the top of `CvEventInterface.py` to point at the custom class.

This does **not** buy the event manager the live-editing that `AdvisorStateWriter.py` gets (see below) — the engine holds a reference to an object instantiated from the old class, so editing this file still needs a restart. That's why `_exportState` is kept deliberately thin: logic put here is logic you have to restart to iterate on.

## Editing while the game runs

The three Python files have **different** rules. The asymmetry is worth internalizing — it caused real confusion, because a restart always works and so masks a broken reload.

| file | edit applies |
|---|---|
| `AdvisorStateWriter.py` | next export, no restart |
| `CvCustomEventManager.py` | **full game restart required** |
| `LocalConfig.py` | **full game restart required** |

`reload()` does **not** work in this interpreter — it returns successfully and silently leaves the old code in place, with no exception and nothing in the log (measured in-game; see `REFERENCES.md`). Suspect a restart-in-disguise any time hot-reload appears to work.

What does work, and what `_refreshStateWriter()` in `CvCustomEventManager.py` does, is `execfile` the source into the existing module's `__dict__` — the module object stays the same, its functions are just rebound from current source text. It needs a real absolute path, which neither `__file__` nor `sys.path` can supply here, so it comes from `MOD_PYTHON_DIR` in `LocalConfig.py`. That setting is optional: omit it and everything still works, you just restart to pick up edits.

The event manager can't be fixed this way at any price — the engine holds an object instantiated from the old class, and re-executing the source can't re-class it. `LocalConfig` is imported *by* `AdvisorStateWriter`, so it comes back from the import cache even though `AdvisorStateWriter` itself is re-read.

## Deployment

This folder is deployed into the local Civ IV Mods folder via a **directory junction** (`mklink /J`), not a copy — edits here are live in-game immediately. Junctions don't require admin privileges on Windows, unlike symlinks.

Local install/Mods paths are machine-specific and not committed — see `config.local.json` (gitignored) at the repo root, templated by `config.local.json.example`.

## Current state

State is exported from three hooks — `onGameStart`, `onLoadGame` and `onEndGameTurn`, **not** `onBeginPlayerTurn`/`onEndPlayerTurn`, which don't bound the player's actual interactive turn despite the naming. Full reasoning for the three-hook choice, the `iGameTurn + 1` numbering, and why those two don't work is in root `CLAUDE.md`.

State is written one file per turn (`turn_0001.json`, `turn_0002.json`, ...) inside a per-game folder under `state/` at the repo root, against the schema in `schema/state.schema.json`. The folder is named `{leader}_{gameId}`, `gameId` being a synthetic value the mod writes into `CvGame.scriptData` the first time it's empty (the engine exposes no readable persistent game ID) — see root `CLAUDE.md` for the full reasoning and the read-only alternative that was rejected. **Every schema section is implemented**, so the exported file validates against the full schema and an empty list means what it says (this was not always true — see `CLAUDE.md` on field vs. section omission for how a missing field still differs from a missing section).

Output is pretty-printed (2-space indent, keys sorted) rather than compact, so a turn's export can be eyeballed against the game UI and consecutive turns diff cleanly. Map tiles are the exception: each is forced onto a single line, leading with `x`/`y`, since they're rows of one long homogeneous table.

The map scan touches every plot on the grid (4368 on a standard map), so it's timed on every export. A slow one warns to `PythonDbg.log` unconditionally; set `LOG_TIMINGS = True` in `LocalConfig.py` for the full per-section breakdown.

**Note on the state output path:** it's *not* derived from `__file__` — tried, doesn't work here (see `CLAUDE.md`). The path comes from `LocalConfig.py` instead.

## Debugging

`Logs\PythonDbg.log` in the user's Civ IV folder is where `CvUtil.pyPrint(...)` output and Python exceptions actually land — but only if `LoggingEnabled = 1` is set in `CivilizationIV.ini`. With it left at the default `0`, most log files (including this one) only get written during initial startup and never updated again, even though the process is still running and dispatching events. `HidePythonExceptions` in the same file only suppresses the in-game popup, not the log.
