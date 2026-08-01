# civ4-advisor

A harness that lets Claude observe game state from **Civilization IV: Beyond the Sword** and give strategic advice, with a longer-term goal of suggesting concrete actions the player can execute on its behalf.

Two independent parts connected only by a JSON file on disk:

- **`mod/`** — runs inside Civ IV's embedded Python 2.4 interpreter, writes a snapshot of game state to disk each turn.
- **`harness/`** — external Python 3 project that reads that state, calls Claude, and returns advice.

Current scope is limited to advice-only for the first 20 turns of a game. See [`CLAUDE.md`](CLAUDE.md) for full architecture, constraints, and design decisions, and [`REFERENCES.md`](REFERENCES.md) for API docs and prior art.

## Status

`mod/` exports per-turn state to a JSON file, verified working in-game — currently just `gameTurn`/`playerId` as a proof of the pipeline, real state schema not designed yet. `harness/` is still scaffolding, nothing implemented.

## License

MIT — see [`LICENSE`](LICENSE). Does not cover any Firaxis SDK headers, binaries, or game assets, which are never vendored in this repo.
