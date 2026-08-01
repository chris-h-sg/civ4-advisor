# mod/

Civ IV: Beyond the Sword mod. Runs inside the game's embedded **Python 2.4** interpreter.

## Constraints

- Python 2.4 only: no `json` module, no f-strings, no modern syntax. See root `CLAUDE.md` for the full list.
- Must never crash or hang the game. All fragile logic (network calls, retries) belongs in `harness/`, not here.
- File writes must be atomic: write to a temp file, then rename.

## Purpose

Hooks into the game's event system and writes a snapshot of player-visible game state to a JSON file on disk. That file is the only contract with `harness/` — nothing here is imported by or depends on `harness/` code.

## Structure

- `civ4-advisor.ini` — mod definition file, kept minimal (just `Name`/`Description`) so unset flags fall back to engine defaults. The engine rewrites this file with every flag spelled out whenever the mod is loaded in-game — expected and harmless. Restore it to the minimal two-line version before committing.
- `Assets/Python/EntryPoints/CvEventInterface.py` — copied from the base BTS install; only the event-manager import/instantiation at the top is changed, to point at our own `CvCustomEventManager` instead of the base `CvEventManager`.
- `Assets/Python/CvCustomEventManager.py` — our actual logic. Subclasses the base game's `CvEventManager` (imported, not copied) and overrides only the methods we need, calling the superclass method first in each to preserve base behavior.
- `Assets/Python/AdvisorStateWriter.py` — hand-rolled JSON serializer and atomic file writer (no `json` module in Python 2.4).
- `Assets/Python/LocalConfig.py` — gitignored, machine-specific. Holds `STATE_FILE_PATH`, the absolute path the mod writes state to. `LocalConfig.py.example` is the committed template.

Only files that override base game behavior need to exist here — everything else (including the base `CvEventManager.py` itself) falls back to the base install automatically.

## Event hook architecture

We do **not** copy and modify `CvEventManager.py` directly. The community-established pattern (see `REFERENCES.md`) instead:

1. Leave `CvEventManager.py` untouched.
2. Put mod-specific logic in a separate `CvCustomEventManager.py`, subclassing the base class.
3. Edit only the top of `CvEventInterface.py` (the entry point the C++ engine actually calls into) to import and instantiate the custom class instead of the base one.

The commonly-cited reason is compatibility with *other* mods stacking on top of yours, which doesn't really apply here (we're the only mod). It matters for us anyway: a full copy of `CvEventManager.py` is 1000+ lines with a handful changed — a lot of surface area to review and easy to drift from the original. `CvCustomEventManager.py` contains only what we actually added.

This does **not** solve the hot-reload/restart limitation below — the engine still holds a reference to an instantiated `CvCustomEventManager` object, so editing that file still needs a restart. No workaround for this exists anywhere in the community, as far as could be found (see `REFERENCES.md`).

## Deployment

This folder is deployed into the local Civ IV Mods folder via a **directory junction** (`mklink /J`), not a copy — edits here are live in-game immediately. Junctions don't require admin privileges on Windows, unlike symlinks.

Local install/Mods paths are machine-specific and not committed — see `config.local.json` (gitignored) at the repo root, templated by `config.local.json.example`.

## Current state

State is exported from three hooks, none of which is `onBeginPlayerTurn`/`onEndPlayerTurn` — those don't bound the player's actual interactive turn despite the naming (no hook fires during actual play; both only fire back-to-back once "End Turn" is clicked, for every player including AI, followed by `onBeginGameTurn`/`onEndGameTurn` — all at turn *end*, not beginning. Confirmed via in-game instrumentation, corroborated by TGA's Python Tutorial — see `REFERENCES.md`):

- **`onGameStart`** — fires once, before the game's true first turn has been played. No numbering adjustment needed.
- **`onLoadGame`** — `onGameStart` only fires for a new game, not a resumed save, so without this a loaded save would silently miss its first export.
- **`onEndGameTurn`** — fires *last* in a round's processing, after the human player and every AI civ. Freshest available snapshot of what the player is about to see once they regain control, since nothing marks that exact moment. Uses `iGameTurn + 1`, since the round it reports just finished.

Only `gameTurn`/`playerId` are written so far, to `state/current_turn.json` at the repo root — proving the pipeline works end to end. The real state schema is not designed yet — see root `CLAUDE.md`.

**Note on the state output path:** it's *not* derived from `__file__` — tried, doesn't work here. The embedded interpreter reports a mod's Python module paths relative to its own `Assets/Python` search root regardless of the module's real physical location, even through the deployment junction. The path comes from `LocalConfig.py` instead.

## Debugging

`Logs\PythonDbg.log` in the user's Civ IV folder is where `CvUtil.pyPrint(...)` output and Python exceptions actually land — but only if `LoggingEnabled = 1` is set in `CivilizationIV.ini`. With it left at the default `0`, most log files (including this one) only get written during initial startup and never updated again, even though the process is still running and dispatching events. `HidePythonExceptions` in the same file only suppresses the in-game popup, not the log.
