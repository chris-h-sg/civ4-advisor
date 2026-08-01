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

- **Event hook entry point:** `onBeginPlayerTurn` in `CvEventManager.py` — fires when control returns to the human player. Confirmed via community modding discussion as the first relevant event each turn cycle.

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
