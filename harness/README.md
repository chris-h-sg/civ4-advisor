# harness/

External Python 3 project: **tooling an agent invokes**, not an API client.

Reads the state JSON written by `mod/` and turns it into forms an agent can reason over. There is no Claude API client here and there will not be one — an agentic coding tool (Claude Code or Cowork) is pointed at this repo plus the game's XML and produces the advice itself. Root `CLAUDE.md` has the reasoning and what that choice deletes.

> **This README is for developers** — design rationale, measured findings, and the boundary that keeps this folder from growing into something else. The advising agent reads **[`AGENT_GUIDE.md`](AGENT_GUIDE.md)** instead.
>
> **Usage belongs in the guide; reasons belong here.** A paragraph here explaining how to invoke something is in the wrong file, and so is a line there justifying a design choice.

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

### `render_map.py` — the map renderer

```
python harness/render_map.py <state.json> [--view NAME] [--around X,Y] [--radius N] [--brief]
```

Five views — `settle`, `explore`, `military`, `yields`, `worker` — each cut to one decision, plus a `--around X,Y` site report. Usage is in `AGENT_GUIDE.md`; the reasoning is below.

Renders are generated on demand and never committed — a stale grid that disagrees with the JSON misleads confidently with no way to notice.

<details>
<summary><b>Design notes</b> — why the views are cut this way</summary>

**A symbol means the same thing in every view.** Each render opens its legend with a `SHARED SYMBOLS` block identical across all five, then adds only what is specific to that view. The column a glyph sits in says what *kind* of fact it is — that is what each legend's `cell = [...]` line is for — but no glyph ever changes meaning between views. Reuse *across columns* is allowed only where the two roles are the same concept: `~` ocean terrain and sea access, `*` resource and (in `worker`) still-unimproved resource, `?` goody hut in both columns that can show one. Those three pairs are enumerated in a test, so adding a fourth is deliberate rather than accidental.


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

### `run_history.py` — the run history

```
python harness/run_history.py <run-folder> [--view timeline|intel] [--from N] [--to M]
```

Takes a **run folder** of `turn_*.json` files — the whole game, not one turn. Three views: `timeline` (what changed, turn by turn), `intel` (per-rival dossier) and `lost` (own units that disappeared). Usage is in `AGENT_GUIDE.md`; the reasoning is below.

<details>
<summary><b>Design notes</b> — why it is cut this way</summary>

**`intel` splits each rival into two sections because they answer different questions and go stale at different rates.** `RECENT SIGHTINGS` is positional and perishable — where something was, most recent first, with the age in turns. `EVER FIELDED` is a permanent capability record: a unit type seen once is one they can build, and that stays true forever. The turn a type was **first** seen leads each line, since that is the fact that dates their tech. The two use cases that drove the split are not walking a vulnerable unit into a hostile, and reading a rival's tech level off what they have fielded.

**`intel` ignores `--from`/`--to` on purpose** and says so on stderr: a dossier truncated at turn M drops the earliest sighting of a unit type, which is precisely the fact that proves a capability. Clamping the *run* is a different thing and is what `--as-of` is for.

**Barbarians and animals are listed separately, and that split is load-bearing.** A Roman Archer implies Archery (`CIV4UnitInfos.xml` gives `UNIT_ARCHER` a `PrereqTech` of `TECH_ARCHERY`); a panther implies nothing about anyone. Both arrive through `foreignUnits` under the barbarian player id, so a single list would invite reading animal sightings as evidence about a civ. **They get full positions**, which they did not at first: the split was right and the barbarian half was under-built, printing a bare turn count. A trial called it "the section with no coordinates is the section I most needed coordinates from" — correctly, since in turns 0–50 the animals *are* the military threat, and it reconstructed the lion cluster at (71,17–18) by hand.

**The five changes after the first round of trials**, all from what agents did with the output rather than from review:

- **A settler consumed founding a city is no longer `LOST`.** Two trials read `LOST UNIT_SETTLER` as a casualty; one "nearly built an advisory around a second casualty that never happened". The pairing is an inference — the export never records which settler founded what — but safe at one settler and one city, and refused rather than guessed when either count is higher. It deliberately does **not** match on position: the settler moves and founds in the same turn, so its last exported position is a tile or more from the city (Oporto at (78,14), settler last at (77,15)), and a positional match would fail on the case it exists for.
- **`--as-of N` clamps the whole run** by discarding later files at load — the only version that cannot leak, since nothing downstream can reach a state never loaded. Three trials hit the footgun it fixes: a question set at t34 against a run reaching t40, with `intel`'s header asserting t40 was now. `--from`/`--to` remain `timeline` output scoping, which is a different thing.
- **Garrison counts** — three trials hand-joined `units` against `cities` by coordinate, one calling it the most important fact in its answer.
- **Distance from your nearest city.** Every trial computed Chebyshev by hand and one noted it could have got the `wrapX` term silently wrong. Nearest rather than per-city: one number is scannable, N numbers grow with the empire and mostly repeat.
- **The compass finding went to the guide, not the tool** — no output change can fix narration when the coordinates were already right.

**The garrison section counts and refuses to judge.** Whether an empty city is in danger depends on what can reach it, and **none of that is computable from the export** — no landmass id, so "can a land unit walk here" is unanswerable, the same gap that makes `settle` over-report founding legality across water. Printing "UNDEFENDED" would assert a threat model the tool cannot evaluate, and on a city reachable only by sea it would simply be wrong. So it reports who stands where and points at `--view military`. Same present-don't-decide line as refusing to rank sites, in a place where the wrong call looks helpful.

**Distance was Chebyshev, always labelled a lower bound**, ignoring terrain and borders; anything better is the pathfinding this folder declines to build. `render_map.py`'s site report said "a LOWER BOUND on turns, terrain costs more" — two tools disagreeing on what a distance means would be worse than neither printing one.

**That consistency argument was then broken by the tool that made it, and is now repaired.** `run_history` gained a land figure while the site report kept Chebyshev alone, so the two tools disagreed about the same map — exactly the failure the paragraph above warns against. `State.land_distance` gives the site report the same measure, and `test_land_distance_matches_run_history` asserts both implementations return the same number, so the two cannot drift apart again silently. The settler-to-site line was the one that mattered: it is the number an agent acts on before committing a settler, and an agent trial found a route whose straight-line figure implied open ground while the real walk crossed a one-tile isthmus.

**When the walk differs from the straight line, the walk leads.** Both figures were already printed side by side, straight line first, and two independent trials reported that the leading number is the one the eye takes — one saying it "still caught me on first read" *despite its instructions warning about exactly this*. Measured on the baseline map at t34: 62 of 135 walkable tiles diverge, and the worst reads 4 straight against 17 on foot, so the misleading ordering was the common case rather than a corner. Same lesson as the compass — when a caveat does not stick, move the layout instead of adding words.

**Then a second round of trials showed the label was not enough, so land distance was added beside it.** Two agents independently found that a lion sitting 6 tiles from Lisbon is a **14-step walk** — a bay forces the route right around — and both called the bare Chebyshev figure the most misleading number they were given: *"6 tiles is an emergency, 14 tiles is a non-issue."* Four of five trials wrote their own flood fill over `map.tiles` to recover it, one writing the same BFS three times, which is this repo's stated signal for a missing tool. So `intel` now prints the land walk whenever it differs, and says outright when there is no land route at all. **It is still not pathfinding**: no terrain costs, no unit rules, no routing through fog — a plain BFS over revealed non-water, non-peak tiles, which is what the agents were writing anyway. Fog is the honest limit and is stated rather than papered over: the figure is the best *known* route, so an unrevealed shortcut can only make it shorter.

This also corrected something the guide had asserted. It told agents reachability was "unanswerable from the export" because no landmass id is exported — and four of five answered it anyway in about ten lines. What is genuinely unanswerable is connectivity *through unrevealed land*, which is a much weaker claim. Teaching a limitation that is not real is its own kind of wrong.

**The compass is drawn on the output because prose demonstrably does not fix it.** Ten trials across two rounds read coordinates correctly and then narrated north and south inverted — **all ten**, including five given the orientation in bold, first in their instructions, with a worked example and a warning naming this exact failure. East/west was never once wrong. The asymmetry is the diagnosis: `x` behaves as expected and `y` does not, so the sign gets normalised away silently while every coordinate stays right, which is why no amount of correct output catches it. The fix is therefore to remove the derivation: the grid is bracketed by `N ^ NORTH` / `S v SOUTH` rules on the edges they name, and `run_history` prints a bearing (`16 NNW of Lisbon`) so direction is read rather than computed. The compass survives `--brief`, because it is orientation, not legend.

**`lost` is scoped to an event, not to an object, and that is what keeps it from becoming a query tool.** The ask was `--unit <id>`; what got built answers the question that is actually asked. "What happened to my unit" came up in both trial rounds, cost three ad-hoc scripts each time, and a unit dying is one of the most advice-triggering events in the early game — but a general per-id browser is one step from the `--filter`/`--sort` language this folder refuses, whereas "units that disappeared" cannot grow into one. It gives the track, the damage history, the final turn's reveal diff and what was in sight, then stops. **It deliberately does not infer the death tile** from the reveal pattern, though a trial did that well twice: weighing which tile explains a reveal shape is judgement, and a heuristic in here would get it wrong quietly. The view hands over the evidence and states the rule (radius 1 flat, radius 2 on a hill) instead.

**The loss line now says `last exported at`, and carries distance and bearing.** Two trials read the old `last at (69,18)` as the death tile; it is the last position ever *exported*, from the previous turn's snapshot, and a unit moves during the turn it dies. The same line also had no distance while every rival sighting three sections above had one — backwards, given that "how far away was this" decides the response, and it was the one number a trial wrote a BFS to recover.

**Non-combat occupants are flagged.** Two trials read `Lisbon (75,15) SETTLER` as a garrison before registering that a settler has combat 0, so the count was quietly overstating the position. The unit list is transcribed at development time like `render_map.py`'s founding rules, and is deliberately short — a unit missing from it is simply unflagged, which is the safe direction, since the tool never claims something *can* fight.

**Rival territory needed its own branch, not a wider diff.** Borders of a civ you have never met arrive **already owned on the turn the tile is first revealed**, so there is no previous value and an owner-*change* diff never fires. The Greek border at (66,17–19) on t35–36 — the first hard evidence of a Greek city's location in the whole sample, and the basis for a trial's strongest inference — produced zero lines. It now reports the tiles and notes that a border implies a city within about two tiles, possibly beyond the revealed edge. **Small reveals also list their coordinates** (up to `MAX_REVEALED_LISTED`): a trial reconstructed where a unit died from exactly those five tiles, having written Python to recover what the tool had reduced to a count. Above the cap a reveal is a scouting sweep rather than evidence, and the coordinates would bury the block.


**Continuity is a constructor assert, not a view.** Save-scumming into a different branch is out of scope: reloading an older save rewrites that turn and leaves later files from the abandoned timeline behind, producing a folder that looks continuous but is not. Rather than report and work around it, `Run.__init__` raises and `main()` exits 2. It was briefly designed as a third `check` view; that collapsed once branch support was ruled out, because nobody asks "is this run sound?" as a question when the answer is enforced on every call. **Fatal:** setup-signature disagreement, duplicate or backwards turn numbers, techs unlearned, revealed tiles forgotten, a city id reused under a new name. **Not fatal:** a turn gap — a failed export is logged and skipped rather than crashing the game, so gaps are legal. They are reported in the header *and* labelled on the block that spans them, since a diff across a two-turn gap covers two turns of change and would otherwise read as one.

**The fog distinction is the whole tool, and a position-keyed diff without it is mostly noise.** Measured on the baseline run: at t35–t40 two rival scouts are continuously observed *while moving*, so a diff keyed on `(owner, type, x, y)` reports them vanishing and reappearing every single turn — six turns of "gone!" about units that never left sight. Classifying each departure against the *next* turn's `visibleNow` is what separates that from the real case, and the same run has both on one turn: at t27 Rome's garrison reads `lost sight` (its tile fogged) while a lion two tiles away reads `left or died` (its tile stayed visible).

**Own units and rivals' units need different machinery, because only ours have ids.** Our `units` and `cities` carry stable engine ids, so their diff is exact — the warrior lost at t38 is an unambiguous id disappearance, and the settler consumed into Lisbon at t1 is visible as id 8192 leaving `units` as a city of the same id appears. `foreignUnits` has no id at all, so nothing there can be tracked, only observed. Every asymmetry in the output follows from that one fact.

**`intel` reports observations and never concludes.** It says a Roman Archer was seen on t26; it does not say Rome has Archery. That join belongs to the rules-lookup tool plus the agent's judgement — so the section names `CIV4UnitInfos.xml` and stops, the same way `render_map.py`'s `worker` view names the XML rather than walking the tech tree itself. This is not pedantry about where a lookup lives: writing these notes, I asserted from memory that an Archer implies *Bronze Working*, which is the Axeman's prerequisite. The XML says `TECH_ARCHERY`. A tool that printed a confident tech conclusion would have printed that same wrong one.

**Foreign city population needed no staleness treatment, contrary to first appearances.** Rome's tile is visible only at t26 and fogged for the remaining fourteen turns, yet its population moves 4 → 5 → 3. That is not stale data: the schema exports `foreignCities` fields **live**, because the engine paints the real nameplate through fog with no visibility gate. So the latest value genuinely is current, and only the turn it was recorded is printed, for provenance. Marking these "possibly stale" would have taught a false rule about the export.

**Stacks collapse to one line with a count.** Two Roman archers on one tile at t26 printed as two identical lines, which reads as a rendering fault rather than as the militarily relevant fact that it is a stack.

**Tile changes are tracked on five fields and terrain is deliberately not one.** `improvement`, `route`, `owner`, `bonus` and `feature` change meaningfully; terrain never changes, so a change would mean a broken run, which the continuity guard owns. `visibleNow` is excluded because it flips constantly by design — that is the fog, not the world moving. `bonus` appearing gets its own wording (`RESOURCE NOW VISIBLE`) because the resource was always there and a tech is what unhid it: in the baseline run `BONUS_HORSE` appears on two tiles the same turn Animal Husbandry completes, and both facts land in the same block, which is what makes the causation readable without joining two files by hand. The two `feature` changes in the run (jungle t29, forest t39) are the engine's feature-growth mechanic; the tool reports the observation and does not guess the cause.

**What was considered and not built.** An `own` view — your own empire's trajectory across the run — was dropped: that is four numbers per turn, and an agent reading five JSON files gets it unaided. The bar is where the agent is *unreliable*, and the expensive cases are the ones that span many files. Whether it is wanted is left to the agent trials to report rather than guessed at now.

**This tool makes none of the renderer's three deferred requests cheaper.** Comparing several `--around` sites, a `--no-grid` flag, and movement cost are all single-turn spatial concerns; nothing here touches them.

</details>

### The bar

**A tool earns its place only where the agent is *unreliable* reading the raw JSON — not merely where automation is possible.** The agent reads JSON well; filtering units, comparing city yields and checking research all work unaided, so most of the export needs no tooling. The gaps are spatial reasoning, aggregation across many files, and consistent arithmetic over many rows. That is why this list is short, and it should stay short.

**Tools present; the AI decides.** Showing a candidate city site's worked radius with yield totals, resources and minimum-distance legality is *rendering*. Ranking candidate sites is *deciding* — the strategic judgement then lives in Python and the AI only reads out its conclusions, which defeats the premise. Site evaluation is where that line gets crossed by accident.

### To build, in this order

1. ~~**Map renderer.**~~ **Done** — `render_map.py` above, five views, exercised across fourteen agent trials (see the design notes). The view set has held up: `settle` and its `--around` site report carry the city-placement decision, `military` gets opened whenever a settler has to walk, and `yields`/`worker` were worth splitting out of the original `empire` because "which tile should this citizen work" and "what should this worker build" want almost disjoint data. `explore` is the weak one — trials open it rarely and get little from it — so if any view merges, that is the candidate.

   **What trials keep asking for and has not been built.** Three requests recur, all presentation rather than judgement, and all deferred rather than refused: a way to compare several `--around` sites in one call instead of holding six site reports in your head; a `--site-only`/`--no-grid` flag (four separate trials independently discovered `--radius 1` as the workaround and one piped through `sed`); and movement cost rather than Chebyshev distance, which is the largest thing a second-city decision has to guess at — though that one edges into the pathfinding this folder declines to build.

2. ~~**Run history.**~~ **Done** — `run_history.py` above, `timeline` and `intel` as sketched. Two departures from the original sketch, both from measuring the baseline run rather than predicting: run validation became a **constructor assert that exits non-zero** rather than something reported and worked around, once branch-divergence support was ruled out of scope (gaps stay legal and are labelled where they matter); and every rival-unit departure is **classified against the next turn's fog**, without which a position-keyed diff is mostly noise — two scouts moving in sight across t35–t40 otherwise report as vanishing and reappearing every turn. A third `check` view was designed and dropped when the assert absorbed it. `intel`'s two-section split — recent-and-positional versus ever-fielded-and-permanent — comes from the two stated use cases: not walking into a hostile, and reading a rival's tech level off what they have fielded.

3. **Rules lookup — narrow.** Reverse and transitive lookups against the game's XML, which is what XML is bad at: "which tech does `UNIT_AXEMAN` require, and what does *that* require" is a closure walk. Forward lookups the agent greps fine on its own, so this stays scoped to reverse and transitive only. Feeds `intel` directly — spotting a unit is worthless without the tech implication.

### Deliberately not building

- **A generic JSON query tool.** Same reasoning that keeps `--filter`/`--sort` out of the renderer: the agent reads JSON fine, and wanting this is the signal that it should just read the file.
- **Unit pathfinding / movement cost.** Action-phase, out of current scope, and it would reopen a closed decision — `river` is a boolean precisely because edge geometry only matters for movement.
- **Anything that scores or ranks decisions.** See the boundary above.
- **A run linter.** Dissolved rather than deferred: run integrity is a precondition inside the history tool, schema validity of committed samples is a test over `samples/`, and schema validity of live captures is mod verification that `mod/tests/` already does against mocks. None of those is turning game state into a form an agent can reason over, which is what this folder is for.

### The agent instructions — written, in `AGENT_GUIDE.md`

Both requirements this section used to specify are there: it names each tool and when to reach for it, and asks the agent to **flag where a tool would have helped**.

That second one is validated rather than assumed — five trials produced those reports unprompted. Three independently asked for a defender-count join, two misread a consumed settler as a combat loss, and the unanimous failure was **compass direction**, which no correct output can catch. Hence the guide's ordering.

It contains no rationale by design; the reasons live here.
