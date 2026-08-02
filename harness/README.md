# harness/

External Python 3 project: **tooling an agent invokes**, not an API client.

Reads the state JSON written by `mod/` and turns it into forms an agent can reason over. There is no Claude API client here and there will not be one — an agentic coding tool (Claude Code or Cowork) is pointed at this repo plus the game's XML and produces the advice itself. Root `CLAUDE.md` has the reasoning and what that choice deletes.

## Constraints

- Modern Python 3 — nothing inherited from `mod/`.
- Offline file processing. No network calls, no API keys, no secrets.
- No dependency on Civ IV being installed. Developable and testable against saved runs in `samples/`.
- Take a state-file path as an argument. `mod/` writes one file per turn into a per-game folder under `state/` — don't hardcode a path or a naming scheme.
- Output is generated on demand, never committed. A stale rendering that disagrees with the JSON misleads confidently with no way to notice.

## Running these

Tools take no setup — run them directly with the system Python:

```
python harness/render_map.py state/<game>/turn_0007.json --view settle
```

That is a constraint, not a convenience. An agent running one mid-session will not think to activate a venv first, so a tool that needs one fails with an `ImportError` and turns a strategy question into an environment-debugging detour. **Tools are stdlib-only**, and a proposed dependency is a reason to reconsider the tool.

Tests are the exception and may use dependencies; `requirements.txt` covers those:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

It is currently empty even though `mod/tests/` already needs `pytest` — an undeclared dev dependency to write down when anything is first added here.

## Tools

Nothing is implemented yet. Document each tool here as it lands, written for an agent choosing between them: what it shows and when to reach for it.

### The bar

**A tool earns its place only where the agent is *unreliable* reading the raw JSON — not merely where automation is possible.** The agent reads JSON well; filtering units, comparing city yields and checking research all work unaided, so most of the export needs no tooling. The gaps are spatial reasoning, aggregation across many files, and consistent arithmetic over many rows. That is why this list is short, and it should stay short.

**Tools present; the AI decides.** Showing a candidate city site's worked radius with yield totals, resources and minimum-distance legality is *rendering*. Ranking candidate sites is *deciding* — the strategic judgement then lives in Python and the AI only reads out its conclusions, which defeats the premise. Site evaluation is where that line gets crossed by accident.

### To build, in this order

1. **Map renderer.** `map.tiles` is a flat list of per-tile objects — the right export format, but the one part of the state an agent cannot reason over spatially. ASCII grid views selected by a named `--view` per decision, optionally cropped around a point. Design rules and the per-view fog-of-war constraints are in root `CLAUDE.md`; the view set itself is still to be proposed. Presenting a site's worked radius is this tool's `--around` view, not a separate tool.

2. **Run history.** Two views: `timeline`, what changed between turns N and M (tiles revealed, units appeared or vanished, cities founded or grown, techs completed, rivals first met); and `intel`, everything ever observed about each rival across the run, tagged with the turn it was seen. Highest value after the map — root `CLAUDE.md` calls reasoning across the turn history a first-class use of the export, but answering "when did I last see an Axeman" currently means reading every file in the run, which is expensive enough that it won't happen reliably, leaving that capability theoretical. It must also **validate the run it is given rather than assume one**: reloading an older save rewrites that turn and leaves later files from the abandoned timeline behind, so ordinary save-scumming can leave a live run divergent mid-game; turn gaps are legitimate but change what a diff means. Both checks belong here rather than in a step run beforehand — a precondition the agent has to remember is one it will skip, and this is the tool that gets fooled. Report them, don't silently span them.

3. **Rules lookup — narrow.** Reverse and transitive lookups against the game's XML, which is what XML is bad at: "which tech does `UNIT_AXEMAN` require, and what does *that* require" is a closure walk. Forward lookups the agent greps fine on its own, so this stays scoped to reverse and transitive only. Feeds `intel` directly — spotting a unit is worthless without the tech implication.

### Deliberately not building

- **A generic JSON query tool.** Same reasoning that keeps `--filter`/`--sort` out of the renderer: the agent reads JSON fine, and wanting this is the signal that it should just read the file.
- **Unit pathfinding / movement cost.** Action-phase, out of current scope, and it would reopen a closed decision — `river` is a boolean precisely because edge geometry only matters for movement.
- **Anything that scores or ranks decisions.** See the boundary above.
- **A run linter.** Dissolved rather than deferred: run integrity is a precondition inside the history tool, schema validity of committed samples is a test over `samples/`, and schema validity of live captures is mod verification that `mod/tests/` already does against mocks. None of those is turning game state into a form an agent can reason over, which is what this folder is for.

### When the agent instructions get written

They must (a) name these tools and when to reach for each, since a tool the agent doesn't know about is a tool that doesn't exist, and (b) ask it to **flag any point where a tool would have helped** — many files read to answer one question, the same derivation repeated, a format worked around. Those reports are the real evidence for what to build next; the list above is a starting guess.
