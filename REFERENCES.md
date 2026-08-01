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

## Prior art (context, not direct dependencies)

These informed the design but nothing here is being reused directly as of this point in the project:

- **Reinforcement-Learning Infrastructure for Civilization IV (Microsoft-published, 2009):** narrow scope — only extracts city `(x,y)` + founding rank for a single city-placement RL task, not general state. Confirms the SDK-hook approach works, but not a useful code base to build on (old, narrow, unmaintained).
  Associated thesis with full technical detail: Stefan Wender, "Integrating Reinforcement Learning into Strategy Games" (University of Auckland, 2009) — `https://www.cs.auckland.ac.nz/research/gameai/dissertations/Wender_MSc_09.pdf`

- **BUG Mod** (`https://civ4bug.sourceforge.net/`): the source of the Python API reference above. The mod itself (UI/QoL overlay for players) is not something we're building on top of — old SourceForge-era codebase, scope mismatch (player-facing UI, not a state-export tool). Only the API docs it produced are directly useful.

- **CivRealm** (ICLR 2024) and **CivBench** (2026): academic LLM/RL benchmarks built on Freeciv and Civilization V respectively — not Civ IV, and not something we're integrating with. Useful only as evidence that "AI plays Civilization via structured state" is a validated approach elsewhere, and as a conceptual reference for schema/prompt design if useful later.

## Not yet investigated

- Exact location/format of Civ IV: Beyond the Sword's XML asset files on a real install (pending mod scaffolding + local install inspection).
- Whether any 2.4-compatible JSON serialization library is worth vendoring into `mod/`, vs. hand-rolling serialization for the fields we actually need.

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
  General mod structure/workflow guide. No hot-reload or live-editing technique described for Python changes — consistent with what we found: `CvEventManager`-level edits (or, if adopted, `CvCustomEventManager`-level edits) require a full game restart, no known workaround exists in the community.
- **`onGameStart`/`onLoadGame` — citation is weak, be aware:** the only support found for "re-initialize in both" is one unelaborated forum line from a single poster ("platyping," using `onGameLoad` rather than `onLoadGame`) in `Free Technology granted at a specific Year: a Python solution`: `https://forums.civfanatics.com/threads/free-technology-granted-at-a-specific-year-a-python-solution.493414/`. Not a documented community-known issue — don't cite it as one. Exporting from `onLoadGame` is still correct on its own logic regardless (`onGameStart`'s own docs say "called at the start of the game," which excludes resuming a save).
