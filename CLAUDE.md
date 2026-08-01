# civ4-advisor

## What this is

A harness that lets an AI (Claude) observe game state from **Civilization IV: Beyond the Sword** and give strategic advice. Long-term goal: the AI eventually suggests concrete actions the player executes on its behalf. Current goal, much smaller: get advice-only working end to end, scoped to the **first 20 turns** of a game.

## Why Civ IV

Civ IV exposes a full Python 2.4 scripting layer (the `Cy*` API — `CyGame`, `CyPlayer`, `CyCity`, `CyUnit`, `CyPlot`, `CyTeam`) that the modding community has used for years to read and influence live game state. This lets us extract structured game state directly via the game's own event hooks, instead of relying on screenshots + vision models. The game is turn-based, so latency is a non-issue — no reflex/timing pressure on the AI call.

## Architecture: two independent parts, no shared code

- **`mod/`** — lives inside Civ IV's Python layer. Runs in the game's embedded **Python 2.4** interpreter. Windows-only, tied to the actual game install. Its only job: hook `onBeginPlayerTurn` (fires when control returns to the human player) and write a snapshot of player-visible game state to a JSON file on disk.
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

## See also

`REFERENCES.md` for API docs, prior art, and other links gathered during research.
