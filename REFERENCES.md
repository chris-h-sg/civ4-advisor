# References

Links and prior art gathered while scoping this project. Kept here so they don't get lost to chat history.

## Civ IV Python API

- **Python class reference (BUG mod project, community-hosted):**
  `https://civ4bug.sourceforge.net/PythonAPI/index.html`
  Full documented surface of the `Cy*` classes — `CyGame`, `CyPlayer`, `CyCity`, `CyUnit`, `CyPlot`, `CyTeam`, `CyMap`, etc. This is the primary reference for what state is queryable and how. Individual class pages follow the pattern `.../PythonAPI/Classes/CyCity.html`, etc.
  Also referred to in older community threads as "Locutus' API" — same thing, just an older name for this reference.

- **Community modding wikibook (background/tutorial context, not authoritative API docs):**
  `https://en.wikibooks.org/wiki/Civ/Civilization_IV/Modding/Tutorials/Python_Tutorial`
  Useful for general orientation on how Python hooks into the game (event flow, debugging via `PythonDbg`/`PythonErr` logs), not for field-level specifics.

## Game's own XML rules data

Static reference data (unit stats, building costs, tech tree, civic effects) lives in the game/mod's `Assets` folder as plain XML. To be parsed once and cached by the harness — not part of the per-turn state payload. Exact paths depend on install location; confirm once `mod/` scaffolding exists and we can inspect a real install.

## Research-rate mechanics (verified for schema's `beakersPerTurn`/`turnsLeft` semantics)

Verified 2026-08 directly against the vanilla BTS game-core C++ source — **`https://github.com/dguenms/beyond-the-sword-sdk`** ("Unedited CvGameCoreDLL sources for Civ IV Beyond the Sword"), `CvGameCoreDLL/CvPlayer.cpp` — not against forum folklore. Read only, never vendored (per the no-Firaxis-code rule in CLAUDE.md). Key findings:

- **The "hidden research bonuses" are real, and they scale the *rate*, not the tech cost.** `CvPlayer::calculateResearchModifier(eTech)` returns `100 + TECH_COST_TOTAL_KNOWN_TEAM_MODIFIER × (met alive teams that know eTech) / (alive teams) + TECH_COST_KNOWN_PREREQ_MODIFIER × (eTech's OR-prerequisites the team already knows)`. `calculateBaseNetResearch` then computes `(BASE_RESEARCH_RATE + research-slider commerce) × modifier / 100` — so raw city beakers get multiplied by the modifier, plus a flat free base beaker, before anything is applied to the tech.
- **Constant values** (confirmed in the local install's `Beyond the Sword\Assets\XML\GlobalDefines.xml`, not assumed): `BASE_RESEARCH_RATE = 1`, `TECH_COST_TOTAL_KNOWN_TEAM_MODIFIER = 30`, `TECH_COST_KNOWN_PREREQ_MODIFIER = 20`.
- **`getResearchTurnsLeft` ≈ ceil(remaining team cost / Σ calculateResearchRate), min 1 — but research overflow from the previously finished tech is subtracted from the remaining cost first** (modifier-adjusted, via `getOverflowResearch`), so displayed turns-left can undershoot naive division right after a tech completes. Team-mate rates are summed too (irrelevant single-player).
- **Schema consequence:** `player.beakersPerTurn` = `CyPlayer.calculateResearchRate(-1)` — the modifier-inclusive figure consistent with `turnsLeft` — NOT the raw slider split of commerce, which would silently understate research by the hidden bonuses. All needed methods (`calculateResearchRate`, `calculateResearchModifier`, `calculateGoldRate`, `getResearchTurnsLeft`, `getOverflowResearch`) are confirmed exposed on `CyPlayer` per the BUG API reference (`.../PythonAPI/Classes/CyPlayer.html`).

## Python hot-reload inside the embedded interpreter (measured, not documented anywhere found)

Established in-game 2026-08-01 by controlled test, because nothing in the community docs surveyed covers it and the failure mode is silent.

- **`reload(module)` returns successfully and does not update the module's code.** No exception, no log line, no partial effect — the next call runs the pre-edit function bodies. This makes it indistinguishable from the mod not being loaded, and it means any apparent hot-reload success is worth suspecting as a game restart in disguise (that is exactly what ours turned out to be).
- **The interpreter is stock CPython 2.4** (`python24.dll` ships at the install root and under `Beyond the Sword\`), so `reload()` is the standard implementation and not a Firaxis reimplementation. The base install ships `.pyc` only for the bundled stdlib under `Assets\Python\System`; game modules have none, and there's no user-side Python cache directory, so stale bytecode isn't the explanation either. Remaining suspect: the engine's own import hook serving cached module source — consistent with the `__file__` behaviour below, though not directly proven.
- **`execfile(path, module.__dict__)` does work**, and is what the mod uses now. Re-executing the source into the *existing* module's namespace keeps the module object's identity, so references held elsewhere (`import AdvisorStateWriter` in the event manager) stay valid and simply see rebound functions. Verified in both directions in a single game session: an edit applied on the next export, and reverting it applied on the export after.
- **Neither `__file__` nor `sys.path` can locate a mod's own source at runtime.** `__file__` is relative to the engine's `Assets/Python` search root regardless of which physical folder supplied the file (even through a deployment junction). `sys.path` is no better — every entry failed `os.path.isfile` for a module known to exist. An absolute path from a config module is the only route found.
- **Reloading is per-module and does not rescue the event manager.** `CvCustomEventManager.py` still needs a full game restart no matter the mechanism: the engine holds an already-instantiated object built from the old class, and re-executing the source can't re-class it. Likewise a module imported *by* the re-executed module (our `LocalConfig`) comes back from the import cache and needs a restart.

## Prior art (context, not direct dependencies)

These informed the design but nothing here is being reused directly as of this point in the project:

- **Reinforcement-Learning Infrastructure for Civilization IV (Microsoft-published, 2009):** narrow scope — only extracts city `(x,y)` + founding rank for a single city-placement RL task, not general state. Confirms the SDK-hook approach works, but not a useful code base to build on (old, narrow, unmaintained).
  Associated thesis with full technical detail: Stefan Wender, "Integrating Reinforcement Learning into Strategy Games" (University of Auckland, 2009) — `https://www.cs.auckland.ac.nz/research/gameai/dissertations/Wender_MSc_09.pdf`

- **BUG Mod** (`https://civ4bug.sourceforge.net/`): the source of the Python API reference above. The mod itself (UI/QoL overlay for players) is not something we're building on top of — old SourceForge-era codebase, scope mismatch (player-facing UI, not a state-export tool). Only the API docs it produced are directly useful.

- **CivRealm** (ICLR 2024) and **CivBench** (2026): academic LLM/RL benchmarks built on Freeciv and Civilization V respectively — not Civ IV, and not something we're integrating with. Useful only as evidence that "AI plays Civilization via structured state" is a validated approach elsewhere, and as a conceptual reference for schema/prompt design if useful later.

## Not yet investigated

- Exact location/format of Civ IV: Beyond the Sword's XML asset files on a real install (pending mod scaffolding + local install inspection).
- Whether any 2.4-compatible JSON serialization library is worth vendoring into `mod/`, vs. hand-rolling serialization for the fields we actually need.

## State-extraction prior art (surveyed before designing the state schema)

Searched (2026-08) for anything in the Civ4 community or academia that already dumps structured game state for external consumption. Verdict: **nothing found that exports live Civ4 game state as structured data** — every adjacent project either targets a different game, parses save files offline, or writes human-readable logs. The schema is ours to design, but CivRealm's observation decomposition is worth borrowing (see below). Verification level noted per item; all claims below checked against the project's own README/docs, not just search summaries.

- **civ4save** (`https://github.com/danofsteel32/civ4save`, PyPI `civ4save`, last release 0.7.0, Nov 2022): Python 3 library that parses `.CivBeyondSwordSave` files (zlib-compressed binary "memory dump") and can emit JSON — the closest thing to a Civ4-state-to-JSON tool that exists. Offline save parsing, not live export, and per its own README incomplete: vanilla BTS only (no mods), plot parsing "buggy/inconsistent" past ~136KB saves, CvPlayer/CvTeam parsing not implemented, CvArea "under construction". *Verified against README + PyPI metadata.* Two takeaways: (1) the fragility of binary save parsing is indirect validation of our live-Python-export approach — we read state through the game's own API instead of reverse-engineering the save format; (2) its `xml` CLI command (transforms game XML into Python enums / JSON mappings) is prior art for our planned parse-XML-once-and-cache harness step.
- **pyconsole** (`https://github.com/civ4-mp/pyconsole`): mod + client that opens a local TCP socket (default port 3333) into Civ4's embedded Python via a `CvEventManager` hook, letting an external client run arbitrary Python in the live game. *Verified against README.* No serialization/schema — it avoids the problem by sharing the runtime. Proves live external programmatic access to a running Civ4 game is viable; doesn't change our file-based-IPC decision (sockets add a listener + threading surface inside the game process, exactly the fragility we're avoiding), but worth knowing it exists if file IPC ever becomes limiting.
- **BUG Autolog** (option surface verified via the vendored copy in karadoc's MMod: `https://github.com/karadoc/Civ4-MMod/blob/master/Assets/xml/Text/Autolog%20Options.xml`): BUG logs game *events* (tech acquired, city founded/grown/razed, war declared, first contact, attitude changes, GP born, builds completed, etc.) to a text file, formats "Plain | HTML Tags | Forum Tags" — human-readable output aimed at forum session reports, not machine-readable state. Precedent that per-event file writing from Python hooks is safe and long-established, but no schema to reuse. Its loggable-event list is a good checklist of "what the game considers a notable event" if we ever add an `events` (turn-over-turn changes) section to the state schema.
- **CivRealm observation schema** (`https://bigai-ai.github.io/civrealm/advanced_materials/fullgame_observation.html`): the one directly useful structural reference found. Freeciv, not Civ4, and tensor-oriented (map as per-layer M×N grids), but its decomposition transfers cleanly: top-level `map` / `unit` / `city` / `player`, with **common fields for any observed entity vs. extra fields only for player-owned entities** (e.g. any visible unit has position/owner/HP/type, only own units have moves-left/upkeep; any visible city has name/position/owner/size, only own cities have stocks/production/mood), and `player` aggregating diplomacy + government + technology. *Verified against the linked docs page.* That common-vs-owned split is exactly the fog-of-war/visibility distinction our schema needs.
- **CivAgent / "Digital Player" paper** (`https://github.com/fuxiAIlab/CivAgent`, fuxiAIlab): LLM agent playing Unciv (open-source Civ5-like) — conceptually the closest project to our harness side (game state → LLM prompt → decisions). *README verified; it contains no concrete state schema* — the paper describes prompts combining background, turn context, role profile, event log, and JSON-encoded "skills," but field-level detail would require reading the paper/source. Park as a harness-phase reference for prompt structure, not a mod-phase schema source.

## Python event modding tutorials (found while diagnosing turn-numbering behavior)

- **TGA's Python Tutorial** (CivFanatics): `https://forums.civfanatics.com/threads/tgas-python-tutorial.154130/`
  Confirms (independently of our own in-game testing) that `onEndPlayerTurn` fires at the end of the *start* of a turn, not the end of the turn itself, and that both `onBeginGameTurn` and `onEndGameTurn` fire at turn end rather than beginning — matches what we measured empirically. Also recommends a custom event manager over editing `CvEventManager.py` directly (see below), and covers debug `.ini` flags (`HidePythonExceptions`, `ShowPythonDebugMsgs`, `LoggingEnabled`) and log file locations (`PythonDbg.log`, `PythonErr.log`, `PythonErr2.log`).
- **CvEventInterface** (Civilization Modding Wiki): `https://modiki.civfanatics.com/index.php?title=CvEventInterface`
  Documents the recommended pattern for hooking events without editing `CvEventManager.py`: create `CvCustomEventManager.py`, then edit only the top of `CvEventInterface.py` to import it and point `normalEventManager` at your custom class instead of the base one.
- **CvEventManager** (Civilization Modding Wiki): `https://modiki.civfanatics.com/index.php/CvEventManager`
  Reference list of ~90 event triggers. Explicitly notes it's missing firing-order/timing detail beyond the one-line description of each hook — our own in-game instrumentation is more precise than any docs found so far.
- **"How to make a Python mod" thread** (CivFanatics, page 4): `https://forums.civfanatics.com/threads/how-to-make-a-python-mod.374238/page-4`
  Practical discussion of the custom-event-manager pattern; notes that modules needing live game state (`gc.getGame()`, etc.) at import time should be imported from inside an event handler (e.g. `onGameStart`), not at module top-level, since top-level imports run before the game is fully initialized. Doesn't appear to affect us currently (`AdvisorStateWriter` only touches `gc` inside functions, never at import time).
- **Modders Guide to Beyond the Sword** (CivFanatics): `https://forums.civfanatics.com/threads/modders-guide-to-beyond-the-sword.229557/`
  General mod structure/workflow guide. No hot-reload or live-editing technique described for Python changes, and none found anywhere else in the community either. Event-manager-level edits do genuinely require a full game restart. For every *other* module we since found one that works — `execfile` into the live module's `__dict__`; see "Python hot-reload inside the embedded interpreter" above.
- **`onGameStart`/`onLoadGame` — citation is weak, be aware:** the only support found for "re-initialize in both" is one unelaborated forum line from a single poster ("platyping," using `onGameLoad` rather than `onLoadGame`) in `Free Technology granted at a specific Year: a Python solution`: `https://forums.civfanatics.com/threads/free-technology-granted-at-a-specific-year-a-python-solution.493414/`. Not a documented community-known issue — don't cite it as one. Exporting from `onLoadGame` is still correct on its own logic regardless (`onGameStart`'s own docs say "called at the start of the game," which excludes resuming a save).
