# mod/

Civ IV: Beyond the Sword mod. Runs inside the game's embedded **Python 2.4** interpreter.

## Constraints

- Python 2.4 only: no `json` module, no f-strings, no modern syntax. See root `CLAUDE.md` for the full list.
- Must never crash or hang the game. All fragile logic (network calls, retries) belongs in `harness/`, not here.
- File writes must be atomic: write to a temp file, then rename.

## Purpose

Hooks `onBeginPlayerTurn` and writes a snapshot of player-visible game state to a JSON file on disk. That file is the only contract with `harness/` — nothing here is imported by or depends on `harness/` code.

## Local install paths

This mod is deployed into your local Civ IV Mods folder for testing. Paths are machine-specific and not committed — see `config.local.json` (gitignored) at the repo root, templated by `config.local.json.example`.

Nothing is implemented yet — this is scaffolding only.
