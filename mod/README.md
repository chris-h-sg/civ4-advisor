# mod/

Civ IV: Beyond the Sword mod. Runs inside the game's embedded **Python 2.4** interpreter.

## Constraints

- Python 2.4 only: no `json` module, no f-strings, no modern syntax. See root `CLAUDE.md` for the full list.
- Must never crash or hang the game. All fragile logic (network calls, retries) belongs in `harness/`, not here. Export failures are swallowed — but logged, so a silent failure isn't mistaken for the mod not running.
- File writes go to a temp file, then rename over the target. Note this is *not* a fully atomic replace: Windows `os.rename` fails when the target exists and Python 2.4 has no `os.replace`, so the old file is removed first. There's a brief window where the state file is **absent**, never one where it's half-written — a missing file is detectable and retryable, a truncated one parses as garbage.

## Purpose

Hooks into the game's event system and writes a snapshot of player-visible game state to a JSON file on disk. That file is the only contract with `harness/` — nothing here is imported by or depends on `harness/` code.

## Structure

- `civ4-advisor.ini` — mod definition file, kept minimal (just `Name`/`Description`) so unset flags fall back to engine defaults. The engine rewrites this file with every flag spelled out whenever the mod is loaded in-game — expected and harmless. Restore it to the minimal two-line version before committing.
- `Assets/Python/EntryPoints/CvEventInterface.py` — copied from the base BTS install; only the event-manager import/instantiation at the top is changed, to point at our own `CvCustomEventManager` instead of the base `CvEventManager`.
- `Assets/Python/CvCustomEventManager.py` — our actual logic. Subclasses the base game's `CvEventManager` (imported, not copied) and overrides only the methods we need, calling the superclass method first in each to preserve base behavior.
- `Assets/Python/AdvisorStateWriter.py` — all state extraction, plus the hand-rolled JSON serializer and atomic file writer (no `json` module in Python 2.4). Everything schema-related lives here rather than in the event manager because this module is re-read from disk on every export, so edits take effect next turn without restarting the game (see "Editing while the game runs" below).
- `Assets/Python/LocalConfig.py` — gitignored, machine-specific. Holds `STATE_FILE_PATH`, the absolute path the mod writes state to, plus the optional `MOD_PYTHON_DIR` and `LOG_TIMINGS`. `LocalConfig.py.example` is the committed template.
- `tests/test_state_writer.py` — developer-side `unittest` suite (runs under **Python 3**, needs `jsonschema`) that execs the real `AdvisorStateWriter.py` against mocked `Cy*` objects, so extraction, serialization, and file writing can all be checked without launching the game. Run it with `python mod/tests/test_state_writer.py`.

  It covers the serializer (escaping, control characters, non-ASCII, inline-vs-broken layout, key sorting/determinism), extraction (every exported field, the no-research-selected path, entity sorting and the dead/foreign/invalid/unmet/fogged filters, the production-kind cascade, field-level omission at defaults, and that the right sentinel/overflow flags are passed), file writing (directory creation, UTF-8 bytes, no line-ending translation, overwrite, temp-file cleanup, `None`-path no-op), and validates the export against the **whole** of `schema/state.schema.json` — which is only possible now that no section is omitted, and which is what makes the schema's top-level `required` and `additionalProperties: false` bite.

  Where a method must *not* be called, the mock raises rather than returning a plausible value. `CyUnit.movesLeft` is set up that way, since reading it at export time would silently yield last turn's number; so are `CyPlot`'s live `getImprovementType`/`getRouteType`/`getOwner` (they see through fog — the revealed variants must be used), `getYield` (the non-displayed yield), `isBeingWorked`/`getWorkingCity` (no visibility check; worked tiles are read city-side), and `getPlotType` (the `PlotTypes.PLOT_*` constants are unverified in the Python layer). Same for the whole-map censuses that sit next to the safe setup getters — `CyMap.getLandPlots`/`getOwnedPlots`/`getNumBonuses`/`getNumAreas` and `CyGame.countCivPlayersAlive` — which describe the map as *generated*, including everything the player has never seen.

  The diplomacy sections add a second tier of these, because they are the ones handling other players' objects. A rival `CyPlayer` raises on their gold, research, civics, city/unit counts and power; a rival `CyCity` raises on every city-screen internal (stores, production, mood, worked tiles); a rival `CyTeam` raises on *everything*, because nothing should ever fetch one — `isHasMet` is symmetric, so the relation is asked of our own team instead. `CyUnit.getOwner` raises so that `getVisualOwner` is used and a hidden-nationality unit is never unmasked. And `CyPlot.getPlotCity`/`isCity` raise, which is the one that guards against a plausible-looking optimisation: folding foreign cities into the map sweep would read live truth and surface cities founded under fog that the player has never seen.

  Two blind spots to keep in mind: it runs on a modern interpreter, so it **cannot catch Python 2.4 syntax violations** (check those by eye — no conditional expressions, `.format()`, or f-strings); and the mocked `Cy*` objects encode our *belief* about the game API, so it can't catch a wrong assumption about what a real game method returns. Only running the game does that — as it did for `movesLeft`, where the mocks were internally consistent and the assumption was still wrong.

Only files that override base game behavior need to exist here — everything else (including the base `CvEventManager.py` itself) falls back to the base install automatically.

## Event hook architecture

We do **not** copy and modify `CvEventManager.py` directly. The community-established pattern (see `REFERENCES.md`) instead:

1. Leave `CvEventManager.py` untouched.
2. Put mod-specific logic in a separate `CvCustomEventManager.py`, subclassing the base class.
3. Edit only the top of `CvEventInterface.py` (the entry point the C++ engine actually calls into) to import and instantiate the custom class instead of the base one.

The commonly-cited reason is compatibility with *other* mods stacking on top of yours, which doesn't really apply here (we're the only mod). It matters for us anyway: a full copy of `CvEventManager.py` is 1000+ lines with a handful changed — a lot of surface area to review and easy to drift from the original. `CvCustomEventManager.py` contains only what we actually added.

This does **not** buy the event manager the live-editing that `AdvisorStateWriter.py` gets (see below) — the engine holds a reference to an object instantiated from the old class, so editing this file still needs a restart. That's why `_exportState` is kept deliberately thin: logic put here is logic you have to restart to iterate on.

## Editing while the game runs

The three Python files have **different** rules. The asymmetry is worth internalizing — it caused real confusion, because a restart always works and so masks a broken reload.

| file | edit applies |
|---|---|
| `AdvisorStateWriter.py` | next export, no restart |
| `CvCustomEventManager.py` | **full game restart required** |
| `LocalConfig.py` | **full game restart required** |

`reload()` does **not** work in this interpreter — it returns successfully and silently leaves the old code in place, with no exception and nothing in the log. Measured in-game, not assumed; see `REFERENCES.md`. Suspect a restart-in-disguise any time hot-reload appears to work.

What does work, and what `_refreshStateWriter()` in `CvCustomEventManager.py` does, is `execfile` the source into the existing module's `__dict__` — the module object stays the same, its functions are just rebound from current source text. It needs a real absolute path, which neither `__file__` nor `sys.path` can supply here, so it comes from `MOD_PYTHON_DIR` in `LocalConfig.py`. That setting is optional: omit it and everything still works, you just restart to pick up edits.

The event manager can't be fixed this way at any price — the engine holds an object instantiated from the old class, and re-executing the source can't re-class it. `LocalConfig` is imported *by* `AdvisorStateWriter`, so it comes back from the import cache even though `AdvisorStateWriter` itself is re-read.

## Deployment

This folder is deployed into the local Civ IV Mods folder via a **directory junction** (`mklink /J`), not a copy — edits here are live in-game immediately. Junctions don't require admin privileges on Windows, unlike symlinks.

Local install/Mods paths are machine-specific and not committed — see `config.local.json` (gitignored) at the repo root, templated by `config.local.json.example`.

## Current state

State is exported from three hooks, none of which is `onBeginPlayerTurn`/`onEndPlayerTurn` — those don't bound the player's actual interactive turn despite the naming (no hook fires during actual play; both only fire back-to-back once "End Turn" is clicked, for every player including AI, followed by `onBeginGameTurn`/`onEndGameTurn` — all at turn *end*, not beginning. Confirmed via in-game instrumentation, corroborated by TGA's Python Tutorial — see `REFERENCES.md`):

- **`onGameStart`** — fires once, before the game's true first turn has been played. No numbering adjustment needed.
- **`onLoadGame`** — `onGameStart` only fires for a new game, not a resumed save, so without this a loaded save would silently miss its first export.
- **`onEndGameTurn`** — fires *last* in a round's processing, after the human player and every AI civ. Freshest available snapshot of what the player is about to see once they regain control, since nothing marks that exact moment. Uses `iGameTurn + 1`, since the round it reports just finished.

State is written to `state/current_turn.json` at the repo root, against the schema in `schema/state.schema.json`. **Every section is now implemented** — `meta`/`game`/`player` (increment ①), `units`/`cities` (②), `map` (③), and `contacts`/`foreignUnits`/`foreignCities` (④) of the build order in root `CLAUDE.md` — so the exported file validates against the full schema, and an empty list now means what it says.

That is worth stating explicitly because the rule used to be the opposite. **While a section was unimplemented it was omitted entirely, never written as an empty list** — an empty `contacts` array would otherwise have been indistinguishable from "this player has genuinely met nobody". The omission was what kept `[]` honest, and now that nothing is omitted, `[]` is unambiguous on its own.

**Inside a tile, a unit or a foreign city, a missing field means something different**: that the field holds its documented default. In `map.tiles` only `x`, `y`, `terrain` and `yields` are always written, which keeps that section to roughly a quarter of its written-out size; `damage` is omitted from any undamaged unit (ours or a rival's), and `capital` from any foreign city that isn't one. See root `CLAUDE.md` for why, and `schema/state.schema.json` for the per-field defaults.

Output is pretty-printed (2-space indent, keys sorted) rather than compact, so a turn's export can be eyeballed against what the game UI shows, and so consecutive turns diff cleanly. Map tiles are the exception on both counts: each is forced onto a single line however wide, since they're rows of one long homogeneous table, and each leads with `x`/`y` before its sorted remaining keys, so the coordinates aren't buried at the end of the line. Key order stays fixed either way, which is what diffability actually needs.

The map scan touches every plot on the grid (4368 on a standard map), so it's timed on every export. A slow one warns to `PythonDbg.log` unconditionally; set `LOG_TIMINGS = True` in `LocalConfig.py` for the full per-section breakdown. Worth turning on periodically rather than once — the cost grows with how much map the player has revealed.

**Note on the state output path:** it's *not* derived from `__file__` — tried, doesn't work here. The embedded interpreter reports a mod's Python module paths relative to its own `Assets/Python` search root regardless of the module's real physical location, even through the deployment junction. The path comes from `LocalConfig.py` instead.

## Debugging

`Logs\PythonDbg.log` in the user's Civ IV folder is where `CvUtil.pyPrint(...)` output and Python exceptions actually land — but only if `LoggingEnabled = 1` is set in `CivilizationIV.ini`. With it left at the default `0`, most log files (including this one) only get written during initial startup and never updated again, even though the process is still running and dispatching events. `HidePythonExceptions` in the same file only suppresses the in-game popup, not the log.
