# civ4-advisor

A harness that lets Claude observe game state from **Civilization IV: Beyond the Sword** and give strategic advice, with a longer-term goal of suggesting concrete actions the player can execute on its behalf.

Two independent parts connected only by a JSON file on disk:

- **`mod/`** — runs inside Civ IV's embedded Python 2.4 interpreter, writes a snapshot of game state to disk each turn.
- **`harness/`** — external Python 3 project: tooling an agent invokes to turn that state into forms it can reason over. No API client, by design.

Current scope is limited to advice-only for the first 50 turns of a game. See [`CLAUDE.md`](CLAUDE.md) for full architecture, constraints, and design decisions, [`ROADMAP.md`](ROADMAP.md) for what is unbuilt, and [`REFERENCES.md`](REFERENCES.md) for API docs and prior art.

## Status

`mod/` exports per-turn state to a JSON file, verified working in-game. The full state schema is specified in [`schema/`](schema/) (JSON Schema + synthetic example) and **mod-side extraction is complete against it** — every section is built, so live output validates against the whole document.

`harness/` has its three planned tools: `render_map.py` (spatial views), `run_history.py` (reasoning across turns) and `rules.py` (lookups against the game's XML, priced for the actual game). The advising agent's instructions are [`harness/AGENT_GUIDE.md`](harness/AGENT_GUIDE.md).

What is still outstanding is queued in [`ROADMAP.md`](ROADMAP.md), most of it evidenced by agent trials rather than predicted.

## License

MIT — see [`LICENSE`](LICENSE). Does not cover any Firaxis SDK headers, binaries, or game assets, which are never vendored in this repo.
