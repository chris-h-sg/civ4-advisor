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

It now declares `pytest`, which also covers `mod/tests/`.

```
python -m pytest harness/tests mod/tests
```

## Tools

Document each tool here as it lands, written for an agent choosing between them: what it shows and when to reach for it.

### `render_map.py` — the map renderer

```
python harness/render_map.py <state.json> [--view NAME] [--around X,Y] [--radius N] [--brief]
```

Turns `map.tiles` into an ASCII grid. Pick a **view** (the decision you are making) and optionally a **region**. Each render carries its own legend and a `THIS VIEW OMITS` block, so you do not need this file open to read one.

| view | the question it answers | fog | also gives you |
|---|---|---|---|
| `settle` | Where do I found a city? | not shown | founding legality, your settlers, a resource list |
| `explore` | Where do I send the scout? | 3 states | the frontier with unexplored map, goody huts |
| `military` | What can reach me, and what can I even see? | 3 states | both sides listed: rival units by owner, and your own with the distance to the nearest threat |
| `yields` | Which tiles should my citizens work? | not shown | every city's 21 tiles with worked/unworked totals |
| `worker` | What should my workers build, and where? | not shown | unimproved resources in radius, roads, and any rival unit in sight so you don't walk an unarmed worker into one |

`--around X,Y` prints a **site report** for that tile — whether it can hold a city at all, coastal or not, fresh water, overlap with your existing cities, distance from each settler, a legality check, and the 21-tile city cross as a yield table. `--radius N` crops the *grid* only; the site report is always the full city radius. `--brief` drops the symbol legend and the grid-reading note but keeps the traps, the omissions, and — in `explore` and `military` — the fog key, since a fogged tile reports no enemies whether or not any are there — worth using after your first call in a session. Default view is `settle`; the header echoes what you actually invoked.

**Use `--around` before committing to a site.** Every agent trial converged on this: the whole-map grid is for narrowing candidates, the site report is for choosing between them. Overlap counts, coastal status and improved-yield marks exist only in the report, and each of them has flipped a ranking in testing.

**A symbol means the same thing in every view.** Each render opens its legend with a `SHARED SYMBOLS` block that is identical across all five, then adds only what is specific to that view. The column a glyph sits in says what *kind* of fact it is — that is what each legend's `cell = [...]` line is for — but no glyph ever changes meaning between views.

Reuse *across columns* is allowed, but only where the two roles are the same concept: `~` is ocean terrain and sea access, `*` is a resource and (in `worker`) a still-unimproved resource, `?` is a goody hut in both columns that can show one. Those three pairs are enumerated in a test, so adding a fourth is a deliberate act rather than an accident.

Three things to know before acting on a render:

- **North is up.** `y` increases northward, so rows run high `y` → low `y`.
- **The grid never replaces the JSON.** It is lossy on purpose — glyphs abbreviate, unit stacks collapse to one marker, and each view drops whole categories of fact. Confirm any tile you act on against `map.tiles`.
- **On `explore` and `military`, read the fog first.** `foreignUnits` reports units only on *currently visible* tiles, so a fogged region renders as "no enemies" whether or not any are there.

Renders are generated on demand and never committed — a stale grid that disagrees with the JSON misleads confidently with no way to notice.

<details>
<summary><b>Design notes</b> — why the views are cut this way (maintainers; not needed to use the tool)</summary>

**One fact per column, never a priority rule.** Tile facts coexist freely: grassland *hills* with *forest*, a *resource* and *fresh water* is one ordinary tile, not a corner case — 9 of 266 tiles in the baseline run at t40 carry both a resource and a feature. When facts share a slot the loser is **invisible**, not abbreviated, and nothing in the output hints that anything was dropped. So each view gives every fact it cares about its own column, and which facts get one is exactly what distinguishes the views: `settle` splits feature / resource / water / coast; `worker` splits feature from what is built, because clearing jungle is itself a worker order and stays true under an improvement; `military` splits feature from territory, since forest and jungle are +50% defence and hills +25%. Relief rides on the terrain letter's case, and `^` drops a peak's base terrain because a peak is impassable and unimprovable.

**Full cross-column glyph uniqueness was considered and rejected.** An audit of every glyph the renderers can emit found 62 in use with a dozen ASCII printables still free, so scarcity was never the constraint — but only one pairing carried genuinely unrelated meanings (`%` as both ice and a water state), and that one was fixed by moving ice to `I`. Making the remaining overlaps unique would have cost the mnemonic improvement letters — `F` farm, `M` mine, `P` pasture, `Q` quarry — replacing 14 guessable symbols with arbitrary punctuation, in the one view that already carries the most glyphs. The column disambiguates instead, and every legend states its own `cell = [...]` map, which is a stronger guarantee than uniqueness because it keeps holding when a 15th improvement is added. The property worth having is the cross-*view* one: an agent switching views carries meaning between renders, and never carries meaning between columns of the same cell.

**`settle`'s marker column answers one question, positively.** `A` you may found here · `x` a city within `MIN_CITY_RANGE` · `]` inside a rival's border · blank means the terrain rules it out, which column 2 already names. Availability is marked rather than left blank because the two failure directions are not symmetric: reading water as available is caught instantly by the terrain glyph, whereas reading an available tile as blocked **silently loses a site**. Terrain-unfoundable tiles stay blank on purpose — once `A` is positive, blank is unambiguous, and marking water too would spend ~23% of all cells restating column 2. The settler glyph `S` covers the marker on the one tile most worth knowing about, so the `YOUR SETTLERS` block states that tile's legality in words instead.

**The water column carries three independent bits, and river is not one of fresh water.** River, non-river fresh water (a lake or an oasis) and sea access are separate facts, so the grid encodes all six reachable combinations rather than ranking them: `_` neither · `:` fresh, no river · `/` river · `~` sea only · `%` sea + fresh but no river · `&` sea + river. River beats lake in the two combined states. **What a river is worth is bounded in the text, because an unbounded version broke a trial**: told only that a river "adds +1 commerce", an agent moved the capital one tile onto a river and onto its own wheat resource, paying a turn and the wheat for it. `CvPlot::calculateYield` floors a city tile at `iMinCity` 2/1/1, which absorbs that commerce entirely — so on the tile a city *stands* on, a river is worth exactly what a lake is. The legend and the site report both say so now, and the next trial reversed the ranking itself, calling it "a ranking I'd have got wrong." Flood plains are deliberately *not* a fresh-water source — `CIV4FeatureInfos.xml` gives them `bRequiresRiver=1` and `bAddsFreshWater=0`, so they sit on a river rather than supplying water. And river is not a subset of fresh water: a river crossing a **peak** reports `river=true, freshWater=false`, because a peak can never be farmed or settled, so treating river as "fresh, but stronger" would mis-glyph it. The cross table splits the same facts into two columns — `water` (`-`/`fresh`/`river`/`river+`) and `coast` (`-`/`sea`) — because farms-and-health and buildings-and-boats are different questions, and `sea` rather than `yes` so a row reads as a sentence without its header. All of this is explanatory: a river's +1 commerce (`RiverYieldChange` `0/0/1` on every land terrain) is already inside the exported yield, so the column tells you *why* a tile reads `2/0/1` and never changes the number.

**Yields that already include an improvement are marked `+`.** `map.tiles.yields` is the *displayed* yield, so a farmed tile reports the farmed number — wheat at (76,16) reads 2/1/1 at turn 0 and 5/1/1 at turn 34 once Lisbon farms it. Comparing two candidate sites then compares improved tiles inside your borders against raw tiles outside them, which **flatters whichever site overlaps a city you already own** — i.e. the site that costs you the most. Base yield is not recoverable from the export, so the honest fix is to mark the affected tiles rather than pretend the improvement can be undone; re-deriving base yield would mean reimplementing the engine's yield rules in the harness and getting them subtly wrong. Goody huts and city ruins are excluded (they sit in the `improvement` field but are not development), and so are roads — `CIV4RouteInfos.xml` gives `ROUTE_ROAD` and `ROUTE_RAILROAD` no `<Yields>` block at all, so a roaded tile's displayed yield *is* its raw yield. An agent trial confirmed the marker changes rankings: without it, it would have ranked a 6-tile-overlap site first on the strength of a wheat tile its own capital had farmed.

**The counts separate new land from land you already own.** Raw cross counts credit a site with tiles inside your existing cities' radii, which inflates exactly the sites that gain you least. At turn 34 two real candidates read 13 vs 12 workable land — near-identical — while the land actually *new* to the empire is 7 vs 11, and resources 2 vs 3. So when a cross overlaps, the block adds a second line reporting land / water / resources excluding the overlap. Same discipline as removing the yield `TOTAL`: the numbers stay descriptive, and the one that was quietly answering the wrong question gets its counterpart beside it rather than a caveat below it.

**A non-coastal site gets a note under the counts, not a column.** The temptation is to split the water count into coastal/non-coastal, but "water is wasted for a landlocked city" is false: `CvCity::canWork` gates water on `CvTeam::isWaterWork()`, which `TECH_FISHING` sets **team-wide**, not on the city being coastal. A landlocked city works its water tiles normally. What it actually loses is the Harbour and Lighthouse (both `bWater`, coastal-only), work boats — so seafood in the cross is unimprovable — plus naval production and overseas trade routes. A column named "wasted water" would have taught a false rule; the note states the real one and leaves the trade open.

**The site report flags a site one tile off the coast, and only then.** Radius 1, because beyond one step you are choosing a different site rather than nudging this one — and because a general nearest-X search is the first step toward the query language this folder refuses to grow. It reports and does not judge: one off the coast is often an accident but sometimes deliberate (fresh water, a resource, a chokepoint), so the line states the fact and hands the trade back.

**`settle` shows no fog, deliberately.** What constrains city placement is ownership and existing cities, not whether you happen to be looking. It is also the only view that draws settlers — the settler is the actor for that decision and where it stands is how far it has to walk.

**`worker` stops short of the tech tree.** The bonus → build → tech chain lives in the game's XML; walking it is the rules-lookup tool's job (below), and doing it here would make the tool depend on a Civ IV install. It names the XML files instead.

**What it hardcodes, and why that is bounded.** The founding rules — `MIN_CITY_RANGE`, which terrains and features can hold a city, the foreign-ownership block — are transcribed from `CvPlayer::canFound` and the game's XML **at development time**, so nothing is read from an install at runtime. One documented over-report: the engine only counts a nearby city on the *same landmass*, and no area id is exported, so a city two tiles away across water is marked blocked when founding is really legal. It never under-reports.

**How this was tested, and what the trials changed.** Fourteen agent trials, each given the same two turns of the baseline run — turn 0 (found the capital) and turn 34 (place the second city) — with the state JSON withheld so only the renders could carry the decision. Turn 0 came back correct in every trial but one - and that one is instructive, see the river note above. Turn 34 landed on or adjacent to the tile the human actually settled once the agent could crop with `--around`, and wandered when it could not.

Nearly every decision below is a trial finding rather than a prediction, which is why they are recorded with their evidence:

- Tables dropped relief and lake-ness, so a **peak printed as grassland yielding 0/0/0** — one tool contradicting itself between grid and table.
- **Coastal, overlap and settler-distance were being derived by hand** — coastal seven times in one session, because two near-identical candidate tiles differed only in it.
- The **improved-yield `+`** exists because a trial was about to rank a 6-tile-overlap site first on the strength of a wheat tile its own capital had farmed.
- **Horizontal indexing** was the persistent failure: trials repeatedly described a tile as its left neighbour. Cell separators, `||` grouping and repeated headers each helped and none fixed it; **cropping did**. The tool's advice to reach for `--around` is the conclusion of that, not a preference.

Two things trials asked for and did not get. **Overlap drawn on the `settle` grid**: a city works pop+1 tiles, so "6 tiles shared" describes contention that will not exist for 30+ turns — it is reported where it matters and would be over-weighted as the most prominent thing in the view. **Which city triggers an `x`**: `x` means "cannot found", and the cause does not change which alternative you pick.

**Why the cross reports counts and not a yield total.** It used to print `TOTAL: 27 food / 19 prod / 13 commerce`. That number was removed, not reformatted, because it ranked sites and ranked them wrongly. Coast is `1/0/2` forever and already at its ceiling; grass-jungle reads `1/0/0` today and `2/0/0` once a worker clears it — so summing *current* yields rewards finished tiles and punishes improvable ones. On the two real candidates at turn 34 it called the coast-heavy site the stronger one while quietly counting six tiles already inside Lisbon's radius as an asset. And a sum cannot see the thing that actually decides an early site: a city works pop+1 tiles, so one or two great tiles and a handful of good ones is enough, and 21 mediocre tiles is not better.

What replaced it is a count of what is *there* — workable land, workable water, unworkable, never revealed, overlapping your cities, carrying a resource. A count says how many chances the site gives you; the table above says how good they are; the reader weighs them against its own strategic horizon, which is exactly the judgement a tool must not make. **Unworkable means peaks only.** Deep ocean reading `0/0/0` is the engine quirk documented in the schema, and jungle reading `0/1/0` is a worker's to-do item — counting either as unworkable would smuggle the same bias back in through the counts.

**Legends carry decode tables and traps, not rationale.** Every legend line costs on every call, and the grid has to stay much cheaper than the JSON it saves you reading. Why a glyph is what it is belongs here and in the code comments — both read once. What belongs in a render is the decode table plus any trap that would cause a *wrong action* if missed.

</details>

### The bar

**A tool earns its place only where the agent is *unreliable* reading the raw JSON — not merely where automation is possible.** The agent reads JSON well; filtering units, comparing city yields and checking research all work unaided, so most of the export needs no tooling. The gaps are spatial reasoning, aggregation across many files, and consistent arithmetic over many rows. That is why this list is short, and it should stay short.

**Tools present; the AI decides.** Showing a candidate city site's worked radius with yield totals, resources and minimum-distance legality is *rendering*. Ranking candidate sites is *deciding* — the strategic judgement then lives in Python and the AI only reads out its conclusions, which defeats the premise. Site evaluation is where that line gets crossed by accident.

### To build, in this order

1. ~~**Map renderer.**~~ **Done** — `render_map.py` above, five views, exercised across fourteen agent trials (see the design notes). The view set has held up: `settle` and its `--around` site report carry the city-placement decision, `military` gets opened whenever a settler has to walk, and `yields`/`worker` were worth splitting out of the original `empire` because "which tile should this citizen work" and "what should this worker build" want almost disjoint data. `explore` is the weak one — trials open it rarely and get little from it — so if any view merges, that is the candidate.

   **What trials keep asking for and has not been built.** Three requests recur, all presentation rather than judgement, and all deferred rather than refused: a way to compare several `--around` sites in one call instead of holding six site reports in your head; a `--site-only`/`--no-grid` flag (four separate trials independently discovered `--radius 1` as the workaround and one piped through `sed`); and movement cost rather than Chebyshev distance, which is the largest thing a second-city decision has to guess at — though that one edges into the pathfinding this folder declines to build.

2. **Run history.** Two views: `timeline`, what changed between turns N and M (tiles revealed, units appeared or vanished, cities founded or grown, techs completed, rivals first met); and `intel`, everything ever observed about each rival across the run, tagged with the turn it was seen. Highest value after the map — root `CLAUDE.md` calls reasoning across the turn history a first-class use of the export, but answering "when did I last see an Axeman" currently means reading every file in the run, which is expensive enough that it won't happen reliably, leaving that capability theoretical. It must also **validate the run it is given rather than assume one**: reloading an older save rewrites that turn and leaves later files from the abandoned timeline behind, so ordinary save-scumming can leave a live run divergent mid-game; turn gaps are legitimate but change what a diff means. Both checks belong here rather than in a step run beforehand — a precondition the agent has to remember is one it will skip, and this is the tool that gets fooled. Report them, don't silently span them.

3. **Rules lookup — narrow.** Reverse and transitive lookups against the game's XML, which is what XML is bad at: "which tech does `UNIT_AXEMAN` require, and what does *that* require" is a closure walk. Forward lookups the agent greps fine on its own, so this stays scoped to reverse and transitive only. Feeds `intel` directly — spotting a unit is worthless without the tech implication.

### Deliberately not building

- **A generic JSON query tool.** Same reasoning that keeps `--filter`/`--sort` out of the renderer: the agent reads JSON fine, and wanting this is the signal that it should just read the file.
- **Unit pathfinding / movement cost.** Action-phase, out of current scope, and it would reopen a closed decision — `river` is a boolean precisely because edge geometry only matters for movement.
- **Anything that scores or ranks decisions.** See the boundary above.
- **A run linter.** Dissolved rather than deferred: run integrity is a precondition inside the history tool, schema validity of committed samples is a test over `samples/`, and schema validity of live captures is mod verification that `mod/tests/` already does against mocks. None of those is turning game state into a form an agent can reason over, which is what this folder is for.

### When the agent instructions get written

They must (a) name these tools and when to reach for each, since a tool the agent doesn't know about is a tool that doesn't exist, and (b) ask it to **flag any point where a tool would have helped** — many files read to answer one question, the same derivation repeated, a format worked around. Those reports are the real evidence for what to build next; the list above is a starting guess.
