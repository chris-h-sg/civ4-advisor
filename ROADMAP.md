# Roadmap

**The single roadmap for the project, covering `mod/`, `harness/` and `samples/`.** Anything unbuilt lives here; the other READMEs describe what exists and why it is shaped the way it is. When an item lands, delete it from here and write the reasoning into the relevant README — this file is a queue, not a history, and git holds whatever the deletion drops.

Two sources feed it: the design-review items recorded while building each tool, and findings from **agent trials** — a fresh agent given the guide and a sample (or a live game) and asked a real question, then asked where a tool would have helped. Trial counts below are that evidence, and they are the strongest thing on this page. An item asked for by 7 of 10 agents is better evidenced than anything anyone predicted in advance.

**Trial evidence comes in two kinds, and they are not equally reliable.** *Agent-asked* is what a trial reported when asked where a tool would have helped. *Player-observed* is what the human running the trial noticed the agent getting wrong — and the agent did not report, because it never noticed. The second kind is rarer and worth more: it is the only detector for the wrong-but-plausible class, which by construction never appears in an agent's own gap report. Items below name which kind they carry. See `trial-protocol`, and the **Findings** section for observations that are not build items at all.

**Read the source before queueing a gap.** A trial reporting something missing is evidence that it was not *found*, which is not the same as it not existing — `coastal-undetermined-wording` was drafted as a missing feature before anyone checked, and the capability was already there and already correct. `AGENT_GUIDE.md` gives the advising agent this rule ("before reporting something as a gap, confirm it's actually missing"); it applies with more force here, where the output is a build item rather than a sentence.

**Items are identified by slug, not by number.** Numbers were a fossil of insertion order: they implied a sequence they did not carry, and every landed item punched a hole in the series that a cross-reference could not survive. A slug says what an item *is*, stays the same when its neighbours are deleted, and reads in a sentence ("I'm taking `city-approach-report`"). Ordering is a separate concern and lives in **Sequence rationale** at the bottom.

Every item carries a **`Target:`** line naming the files it will have to edit. That is what makes a collision visible before two agents pick up work: read the targets, not the prose. Items are grouped into **lanes** below by those targets, and one lane is explicitly serial.

---

## Index

| Slug | Lane / target | Evidence | Status |
| --- | --- | --- | --- |
| `same-turn-round-trips` | Correctness — schema + mod (design first) | 1 trial, sharpest finding on the page | Recorded, **not scheduled** — no affordable design yet |
| `goody-hut-outcomes` | Lane C — `rules.py` (**serial**) | Agent-asked, 1 trial — cost a unit and ~10 turns | Ready; **data verified, 25% on Monarch** |
| `rules-improvement` | Lane C — `rules.py` (**serial**) | Agent-asked, 1 trial — the only flatly false number | Ready; data verified on disk |
| `trial-per-turn-checklist` | Lane E — trial docs | Player-observed ×2, plus the agent's own B5 lapse | Ready, costs nothing |
| `bearings-by-default` | Cross-tool — all three | Agent's own #1, and player-observed independently | Ready; needs a scope call (prose only) |
| `city-approach-report` | Lane A — `run_history.py` | 4 of 6 `rules.py` trials; 2 wrote their own BFS | Ready, unblocked |
| `per-city-production-history` | Lane A — `run_history.py` | 4 of 6 trials read raw JSON for it | Ready, unblocked |
| `garrison-posture` | Lane A — `run_history.py` | Follows increment ⑨; no tool reads the new fields | Ready, small |
| `coastal-undetermined-wording` | Lane B — `render_map.py` | Player-observed; the output was already right | Ready; wording only, will break one test assertion |
| `multi-site-comparison` | Lane B — `render_map.py` | Both trial rounds; one diffed 10 runs by eye | **Reframed** — the gap is the trigger, not the table |
| `unit-animal-combat` | Lane C — `rules.py` (**serial**) | 1 trial, the one unconfident answer it gave | Ready, nearly free |
| `rules-lookup-gaps` | Lane C — `rules.py` (**serial**) | Five sub-gaps, 1–2 of 4 trials each | Ready, independent of everything else |
| `varied-setup-samples` | Lane D — `samples/` (capture) | Coverage holes identified, not trial-driven | Opportunistic — needs a game played |
| `trial-protocol` | Lane E — trial docs | The meta-finding behind three landed items | Ready, costs nothing |

`Deliberately not building` is below and carries no slugs — those entries are decisions, not work. **Findings** likewise: observations about how the advisor reasons, held as an accumulator until one recurs. Each names what would promote it; the bar is a second occurrence, not a good argument.

---

## Lanes

Grouped by `Target:`, so what can run concurrently is visible without reading the prose.

- **Lane A — `harness/run_history.py`.** `city-approach-report`, `per-city-production-history`, `garrison-posture`. All land in the same module and all touch `intel`; **treat as serial with each other**, though the collision is far smaller than Lane C's. The last two both extend the garrison block, so one agent should take them together.
- **Lane B — `harness/render_map.py`.** `coastal-undetermined-wording`, `multi-site-comparison`. Both land in the site report, so treat as serial with each other; the wording fix is small enough to take first in the same sitting. Parallel-safe against every other lane.
- **Lane C — `harness/rules.py` — SERIAL.** `goody-hut-outcomes`, `rules-improvement`, `unit-animal-combat`, `rules-lookup-gaps`. `rules.py` is a single ~3300-line module and every one of these adds lookups into it and its tests. **Do not assign these to two agents at once.** The natural move is one agent taking the whole lane, since `unit-animal-combat` is nearly free once the file is open and `goody-hut-outcomes` extends a subcommand that already parses the right file. This is now the fullest lane on the page.
- **Lane D — `samples/`.** `varied-setup-samples`. Requires actual play; collides with nothing.
- **Lane E — trial/advisor documentation.** `trial-protocol`, `trial-per-turn-checklist`. Touches only `trial-template/`; parallel-safe against every code lane. The two are close enough in subject that one agent should take both.
- **Cross-tool — `bearings-by-default`.** Touches `render_map.py`, `run_history.py` and `rules.py`, so it **collides with Lanes A, B and C at once**. Run it alone, or accept a rebase. It is the one item that cannot be parallelized with anything.
- **Unlaned — `same-turn-round-trips`.** Would cross `mod/` and `schema/`, colliding with no active lane, but it has no design yet.

Every lane also touches `harness/README.md` or a sibling README on landing (this file's own rule: delete the item, write the reasoning into the README). **That is the real contention point** — the prose files, not the code. Expect to rebase documentation edits even when code lanes are disjoint.

---

## Correctness

### `same-turn-round-trips` — a unit's exported position can hide a real event

**Target:** `schema/state.schema.json`, `mod/Assets/Python/AdvisorStateWriter.py`, `mod/tests/test_state_writer.py`, `CLAUDE.md`, and — depending on the design chosen — `harness/run_history.py` to surface whatever gets exported. *Genuinely uncertain*: the harness side cannot be pinned down until the schema shape is decided, and a "tiles visited this turn" trail would touch `mod/Assets/Python/CvCustomEventManager.py` (which is not hot-reloadable) if it needs per-turn accumulation rather than a point-in-time read.

Found in the first Claude Code trial (Darius, t0–25), and the sharpest finding either trial has produced. A goody hut at (68,31) was popped for 60 gold on turn 22, but the scout that must have popped it was logged at (67,32) in **both** `turn_0021` and `turn_0022` — unchanged. With 2 movement, the only explanation that fits is a round trip within the same turn: move onto the hut, pop it, move back, netting zero displacement. Nothing in the export shows path, only final position, so the event was completely invisible until the player mentioned the gold out loud; the agent then had to reverse-engineer what must have happened from the treasury jump alone.

This is a sharper case of the same root cause already named in `run_history.py`'s `lost` view ("last position isn't where it died") — but that caveat covers a unit's *final* position being approximate. This is a *mid-game* event, silently erased, with no death or disappearance to even flag that something happened. A position snapshot cannot represent it; fixing this needs either a per-turn event log or a "tiles visited this turn" trail, which is a materially bigger schema ask than anything else queued here. Recording it now as a known limitation rather than a scheduled fix — the roadmap doesn't yet have a design for what "affordable" looks like for this one.

---

## `harness/` — tools

`harness/README.md`'s own "To build, in this order" list is folded in here. What survives of it is the item set below, not its ordering — see **Sequence rationale** at the bottom, which is the single place order is stated.

### `city-approach-report` — the best-evidenced gap in the folder

**Lane A.** **Target:** `harness/run_history.py`, `harness/tests/test_run_history.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`. Likely read-only against `harness/render_map.py` (`State.land_distance` lives there and is imported, not moved) — but if the walk machinery needs generalizing, that file is in scope too and this item then collides with Lane B.

**4 of 6 `rules.py` trials asked for it; 2 independently wrote their own BFS** over `map.tiles`, which is this repo's stated signal for a missing tool.

The specific failure: `intel` correctly refuses to judge whether an empty city is in danger and points at `--view military`; `military` renders a symbol grid and cannot answer it either, so the agent eyeballs a corridor off the grid — the derivation the guide says is unreliable.

Wanted is presentation, not a verdict: per city, distance to the nearest unowned land tile, how many reachable unowned land tiles lie within N walk, and whether a land route exists at all. The walk-distance machinery already exists in `run_history.py` and `State.land_distance`. **Hold the line `intel` already holds** — report the approach, never call a city safe or unsafe.

### `garrison-posture` — `intel` shows what is in a city, never whether it is dug in

**Lane A.** **Target:** `harness/run_history.py` (`intel`'s garrison block), `harness/tests/test_run_history.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`.

Increment ⑨ exports `units[].activity` and `units[].fortifyTurns`; **no harness tool reads either** (checked, not assumed), so the guide has to send the agent to raw JSON. `intel`'s garrison listing already prints `[NON-COMBAT]` and promotion tags — posture belongs on the same line, since a Warrior at `fortifyTurns: 5` carries +25% defence over one that just walked in.

Small, and it shares the garrison block with `per-city-production-history`. **Presentation only** — print the count, never a "this city is defended" verdict, per the line `intel` already holds.

### `per-city-production-history` — per-city production over the run

**Lane A.** **Target:** `harness/run_history.py` (both the `timeline` and `intel` views), `harness/tests/test_run_history.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`. The turns-to-complete half overlaps conceptually with a `rules-lookup-gaps` sub-item, but the arithmetic it wants already lives in `rules.py building` — *uncertain* whether that is imported (touching `harness/rules.py`, and so Lane C) or reimplemented; deciding that is part of the item.

**4 of 6 trials read raw JSON for this** after `intel` told them a city was empty. `timeline` reports techs, cities, units, contacts, sightings, tiles, territory and resources — but not what any city is *producing*, or when that changed.

One trial found Lisbon started a Warrior on t38 while both cities were empty and switched **back** to a Worker on t40 — the sharpest fact in the run, visible in no view, recovered with a throwaway loop over five files.

Two obvious halves: a `producing` change line in `timeline`, and current build plus turns-to-complete on `intel`'s garrison block.

### `bearings-by-default` — coordinates are the wrong interface for the human player

**Cross-tool — collides with Lanes A, B and C simultaneously.** **Target:** `harness/render_map.py`, `harness/run_history.py`, `harness/rules.py`, all three test modules, `harness/AGENT_GUIDE.md`, `harness/README.md`. Run alone.

**The agent's own #1 ask, and independently the player's** — the only item both reporters ranked at the top. At t5 the player said outright they cannot see (x,y) coordinates in-game and asked for relative descriptions ("the plains hill NW of the capital"). Every tool speaks coordinates natively, so from then on the agent called `bearing.py` on nearly every turn purely to translate tool output into something actionable. That is a translation step on every single turn of every session.

The machinery exists and is already trusted: `run_history` and `render_map --view military` print bearings, with wrap handling built in. Wanted is bearing-from-nearest-city as the **default** rendering — `render_map`'s RESOURCES REVEALED list, the `--around` site-report header, `foreignUnits` summaries — with raw coordinates kept as a secondary field, since they remain the input format for every tool.

**One scope decision to make first, and it is the reason this isn't already obvious.** The ask says "everywhere", but **grids are positional by construction** — a cell's meaning is its place in the render, and a bearing per cell is both impossible and pointless. Read this as *every prose and list line*, leaving grid cells alone. Getting that wrong turns the highest-value usability item into a broken renderer.

### `coastal-undetermined-wording` — the site report's undetermined coastal state leads with "no"

**Lane B.** **Target:** `harness/render_map.py` (`_site_header`), `harness/tests/test_render_map.py`, `harness/README.md`. Wording only — no new computation, and `State.is_coastal()` already returns the unrevealed-neighbour count this needs.

**Not a missing feature.** `--around` on a site with unrevealed neighbours already prints `coastal    no, but N adjacent tile(s) unrevealed - explore before ruling it out`, and it fires on real data (2 tiles at t5 of the baseline, checked). The Ramesses trial still read such sites as landlocked.

The diagnosis is the ordering: **the line leads with `no` and the qualifier trails behind it**, so the eye takes the negative and the rest reads as a footnote. That is the same failure this repo has now hit three times — walk-versus-straight-line (the leading number is the one that sticks, so the walk now leads), the garrison block scrolling past 7 of 10 trials until it moved up, and the compass. Each was fixed by changing what comes first, not by adding words.

So: lead with the uncertainty rather than the negative — an `UNDETERMINED` state alongside the existing `yes` and `no - landlocked`, with the explore-first action on its own line rather than trailing the verdict. **Check the test suite's expectations while doing it**: at least one test matches the literal string `coastal    no` as a proxy for "not coastal", which a rewording will break — correctly, since the property it means to assert is that sea in the city cross does not make a site coastal, not the wording. Fix the assertion to the property rather than the string.

### `multi-site-comparison` — multi-site `--around` comparison

**Lane B.** **Target:** `harness/render_map.py`, `harness/tests/test_render_map.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`.

Asked in both trial rounds; one trial ran `--around` ten times and diffed by eye. **Tabulating the same facts across several sites is not ranking them** — the no-ranking line survives, which is what makes this buildable rather than refused.

It outlived the cheap presentation fixes it was once grouped with (`--site-only` and the seam-description wording, both since landed — see `harness/README.md`) because it is a real interface question (how many sites, what shape the table takes), not a layout tweak.

**Reframed by the Ramesses trial, and worth reading before building it.** The player observed that the agent *"does comparative analysis of city sites when asked, has been very thorough considering tiles and strategic value vs rivals, produces a clear table — but only when asked."* So the agent already produces a good multi-site comparison on request, by hand, and the thing that fails is that nobody asks. Building the table buys a tidier version of something that works and leaves the actual failure untouched; the trigger belongs in `trial-per-turn-checklist`. **That is an argument about sequencing, not a cancellation** — the tool still removes hand-derivation and the wrap-handling risk that comes with it — but this item should follow the checklist rather than precede it.

### `goody-hut-outcomes` — `rules.py handicap` reads as authoritative on barbarians and is not

**Lane C (serial).** **Target:** `harness/rules.py`, `harness/tests/test_rules.py`, `harness/README.md`. No new data source — `CIV4HandicapInfo.xml` is the file the `handicap` subcommand already parses, and `CIV4GoodyInfo.xml` sits beside it in the base tree (BTS ships no override, checked).

**The most expensive single finding of the Ramesses trial** (Monarch, t0–36): a goody hut sat one tile from the scouting Warrior at t9. The agent ran `rules.py handicap`, read `iBarbarianCreationTurnsElapsed = 25`, and told the player popping it was safe for another 16 turns. The hut produced a hostile warband that killed the unit — the player's only unit at the time, leaving the capital undefended and unscouted for several turns.

**The numbers, verified against the install rather than taken from the trial report.** Each handicap carries a flat 20-entry `<Goodies>` table, and `GOODY_BARBARIANS_WEAK`/`GOODY_BARBARIANS_STRONG` carry `iBarbarianUnitProb` 20/40 with `iMinBarbarians` 1/2. Hostile entries per difficulty: Settler 0, Chieftain 1, Warlord 2, Noble 3, Prince 4, **Monarch 5**, Emperor 6, Immortal 7, Deity 8. So on the trial's own difficulty a hut was a **flat 25% hostile roll, from turn 1** — and `iBarbarianCreationTurnsElapsed` governs *map spawns*, not huts, so it gates none of it.

The agent named its own under-weighting of the OMITS list as part of the cause, which is fair but not the whole story: the block is titled "barbarian and animal rules" and **leads with a turn number that reads as a safety guarantee**, while the table that actually answers the question is parsed and discarded. Same shape as the `city`/`effective_known` bug (see `harness/README.md`): an authoritative-looking block whose omission is load-bearing, with nothing in the output able to contradict it.

Wanted is the outcome table for this handicap with the hostile rows visible, and a hard line that huts are ungated by the spawn timer. **Presentation, not a verdict** — print the distribution, never "safe" or "unsafe".

### `rules-improvement` — no improvement-yield model

**Lane C (serial).** **Target:** `harness/rules.py` (new subcommand), `harness/tests/test_rules.py`, `harness/AGENT_GUIDE.md` (rule 5's trigger table gains a row), `harness/README.md`. Reads `CIV4ImprovementInfos.xml` and `CIV4BuildInfos.xml`; the latter is also wanted by `rules-lookup-gaps`'s worker-build-times bullet, so **one of the two should build the file reader and the other use it**.

**The only gap in the Ramesses trial that produced a flatly false number.** A Worker completed a Farm on a Corn tile; asked what it yielded, the agent had no call to make, extrapolated from memory, invented a Despotism yield penalty (a Civ3 mechanic that does not exist in Civ4) and reported 4 food. The answer was 5, and the player corrected it.

`rules.py` covers `unit | tech | building | promotion | city | handicap` — nothing for improvements or builds. So `AGENT_GUIDE.md`'s rule 5 ("check the XML before stating a rule — don't recall one from memory") **had no landing place for this question**, and the fallback was exactly the memory-recall the rule forbids. That is the tooling's failure rather than the agent's.

**The data is on disk and structured** (verified): `<YieldChanges>` for the base improvement, `<BonusTypeStructs>` for the per-resource bonus — Farm-on-Corn is **+2 food from the Corn struct**, which is precisely the term memory dropped — `<TechYieldChanges>` for later upgrades (Farm +1 food at Biology), and `bRequiresFlatlands`/`bHillsMakesValid` plus the terrain/feature structs for legality.

With an `--on X,Y` argument against a state file this also answers **"can I build this here, right now"**, which is where it absorbs the trial's separate complaint about recommending a mine on a forested hill: legal only after the forest is chopped, which needs Bronze Working. The agent had already run `rules.py tech TECH_BRONZE_WORKING`, seen `remove FEATURE_FOREST`, and failed to join the two facts — and `render_map --view worker` explicitly punts that follow-up to the XML in its own OMITS block, stopping one field short of actionable after doing the hard part of locating the tiles.

### `unit-animal-combat` — `rules.py unit` doesn't read `iAnimalCombat`

**Lane C (serial).** **Target:** `harness/rules.py`, `harness/tests/test_rules.py`, `harness/README.md`. Probably `harness/AGENT_GUIDE.md` too, though the guide already tells agents to reach for `rules.py unit` — this only widens what that command prints, so the guide may need no edit at all.

Asked to weigh popping a goody hut next to a Lion, the Claude Code trial hand-estimated survival odds from raw strength and flagged the number as a guess — the one unconfident answer it gave all session, because it never saw the Scout's combat bonus against animals.

The bonus is not SDK-hidden: `CIV4UnitInfos.xml` carries a per-unit `<iAnimalCombat>`, `0` on nearly everything and **100 on `UNIT_SCOUT`** (+100% vs. `bAnimal` units) — an ordinary combat modifier of the kind `rules.py unit` already prints beside strength, moves and cost, simply absent from the parser's field list. A straightforward addition, not a design question.

### `rules-lookup-gaps` — smaller `rules.py` gaps

**Lane C (serial).** **Target:** `harness/rules.py`, `harness/tests/test_rules.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`. The worker-build-times sub-item reads `CIV4BuildInfos.xml` from the game install, which `rules.py` already opens (`BUILD_FILE`) — no new data source, and nothing in this repo. The turns-to-complete sub-item is the one that may also want `harness/run_history.py`; see `per-city-production-history`, which asks for the same join from the other side.

- **Worker action build times.** No build-time data for worker actions, so the live trial's road-versus-pasture-first answer was general BTS knowledge rather than tool-verified — flagged by the agent itself against the guide's own rule 5. **Cheaper than it sounds and not a mod change**: the data is in `CIV4BuildInfos.xml`, already on disk. A missing lookup in an existing tool, independent of everything else here.
- **The tech↔map resource join, positive direction — 2 of 4 trials.** `rules.py tech TECH_MASONRY` prints `resources usable BONUS_STONE` while the player already has stone inside their borders; one trial called it "a decisive fact printed nowhere". The `unit` view does this join; the `tech` view does not.
- **Turns-to-complete on what a city is currently building — 2 of 4.** The arithmetic already exists in `rules.py building`; `cities[].producing` plus `production`/`productionNeeded` is joined to it nowhere.
- **The research-switch rule — 1 of 4, but a rule-5 violation with no fallback.** Deciding whether to abandon a tech at 4/124 required knowing Civ IV banks partial research per tech; the agent asserted it from background knowledge and flagged that as exactly what the guide forbids. Nothing in any tool covers it.
- **Time-to-first-unit crossing tech *and* hammers**, which currently stops dead at the tech.
- **The production-switch rule — Ramesses trial, and a wrong-advice case.** Banked hammers stay parked against the original item across a switch rather than transferring; the agent believed otherwise and advised an emergency switch on it. Same shape as the research-switch rule above — a rule with no fallback anywhere in the tools — and the reason the `productionBankedFor` field was declined (see `Deliberately not building`). Wanted as a line at the point of decision, not a field.
- **Happiness and health have no forward-looking view — Ramesses trial.** Thebes at pop 3 read `happy: 5 / unhappy: 4 / healthy: 12 / unhealthy: 3`; the cap was about to become the binding constraint on every grow-versus-settle decision and `rules.py city` says nothing about it. Wanted: current cap, itemised sources, and what is one tech/building/resource away — mirroring the structure the build list already uses. Note the trial also could not tell whether `player.bonuses.happiness`/`health` were working, since both were empty for the whole window; **confirm that is genuinely empty rather than broken before building on it.**

---

## `samples/`

### `varied-setup-samples` — runs that vary the setup

**Lane D.** **Target:** a new run folder under `samples/`, plus `samples/README.md` for its provenance note. No code changes — this is a capture, not a build. *Uncertain*: if the new run exposes a `rules.py` fallback-path bug (which is part of the point), that spills into Lane C, but that is a consequence rather than a planned edit.

One curated sample exists — `baseline-early-game/`, turns 0–43 — and it "sits in the most default corner of the space": Emperor, Fractal, standard/temperate/medium, no game options set. The `game` section's climate, sea level and **barbarian options change turn-1–20 advice more than almost anything else in the file**, so runs differing there are worth more than repeats.

Two specific coverage holes worth targeting:

- **`wonders.built` is `[]` in all 44 files**, so that branch is validated synthetically and has never met real data. A run reaching a turn where any world wonder completes anywhere would fix it.
- **The `bFood`-build-after-a-completed-build case**, which the increment-⑥ backfill derivation would get wrong. Zero such rows exist in the baseline (checked, not assumed); a future run containing one needs a real capture rather than a derivation.

Also outstanding from the same caveat: the baseline's increment-⑤ and ⑥ fields are genuine only on `turn_0040`/`turn_0043` and backfilled elsewhere, so `rules.py`'s pre-⑥ fallback path has **no sample coverage at all** — only synthetic unit tests. A fresh capture from a mod that already has both increments would retire that caveat entirely.

---

## Process

### `trial-per-turn-checklist` — the advisor does several things well, but only when asked

**Lane E.** **Target:** `trial-template/CLAUDE.md`. Almost certainly not `harness/AGENT_GUIDE.md` — the guide describes the tools, and this is about the shape of a turn. Build it together with `trial-protocol`; they are the same file and the same subject.

**The cheapest item on the page and the one covering the most separate observations.** Three distinct findings share one cause — the advisor produces good work on request and does not self-prompt:

- **Unit movement.** *Player-observed:* the agent should give movement instructions each turn when a unit is ready to move, and often didn't.
- **What to build after founding.** *Player-observed:* a new city needs its first build chosen immediately, in that same turn, and the advice arrived late.
- **Site comparison.** *Player-observed:* thorough and well-tabulated when asked, absent otherwise — see `multi-site-comparison`, which this partly displaces.
- **Objectives drift.** *Agent-asked* (its B5, and its own lapse): `trial-template/CLAUDE.md` asks for a restatement every 5–10 turns; the agent wrote one at t0, updated through t10, then stopped — t15–t36 have none, spanning first contact with two civs, a completed Settler and a unit loss.

The last one has a cheap tool half worth pairing with the prose: a line in `run_history`'s header — `objectives.md last written: t10 (26 turns ago)` — makes the drift visible exactly when the advisor is already reading run state. **That half is Lane A**, so if it is taken, it goes with `per-city-production-history` rather than here.

**It also has a second job: making the `Findings` section testable.** Several findings resolve to "watch whether this recurs" — Warriors' movement, resource-versus-yield weighting, coastal status read past in the site report. Those are only checkable if someone is looking at the right moment, which is what a per-turn checklist is for. Adding them as explicit check lines converts a passive list of observations into something the next trial actively tests.

**A caution on how to write this.** The failure is not that the agent lacks instructions — `trial-template/CLAUDE.md` already asks for restatements and gets ignored. It is the same lesson the compass and the walk-vs-straight-line ordering both taught (see `harness/README.md`): **when a caveat does not stick, change the structure rather than adding words.** A per-turn checklist works because it is checkable at a fixed moment; a longer paragraph asking for diligence will not.

### `trial-protocol` — because out-of-band discovery is the real detector

**Lane E.** **Target:** `trial-template/CLAUDE.md` (the session brief the trial deploys), and probably `harness/README.md`'s trial section for the reasoning. *Uncertain* whether any of this belongs in `harness/AGENT_GUIDE.md`: the protocol is aimed at the **player**, not the agent, and the guide is the agent's file — so the honest answer is likely "no", but that is a call to make while writing it.

**The meta-finding, and the one with no obvious owner.** The mod-side gaps in the (now-resolved) `doTurn()` mutation-order audit (see `REFERENCES.md`), `same-turn-round-trips`, the now-built increment ⑦, and increment ⑧'s one-too-high `turnsLeft` all surfaced *only* because the player narrated or checked something the agent could not see — "it's actually healed", "here's the 60 gold", "it got two promotions", "that number is wrong against the UI". In a run where the player did not, those would have silently produced worse advice with nothing in the output able to catch it. The `turnsLeft` case is the sharpest: the value was wrong, plausible, and agreed with by a passing test suite.

That is the compass failure mode again: wrong-but-plausible, self-consistent, invisible from inside. Trials are currently the only detector for this class of problem, and they fire only when the player happens to mention the right thing.

The fix is not tooling. It is a protocol: during a trial, **note every time you tell the agent something the JSON should have carried.** That turns an accident into a repeatable finding mechanism, and it costs nothing. Belongs in the advisor instructions used to set up a session.

**One asymmetry this doesn't fix.** A trial can report itself confident and correct while the player observes real slips. The guide's "tell us what's missing" instruction only catches failures the agent *notices*, which structurally excludes the entire wrong-but-plausible class. Not fixable in the agent's instructions — it is the argument for the player-side protocol being more load-bearing than it looks.

---

## Findings

**How the advisor reasoned wrongly while every tool answered correctly.** No slugs, no targets — these are not work. **An accumulator, not a backlog:** one occurrence is noise, a second is a pattern, and only a pattern justifies building something. Each entry names what would promote it; the bar is recurrence, not a good argument. What to do with the section now is check these behaviours on the next run, which is `trial-per-turn-checklist`'s second job.

**All three are player-observed and none appeared in the agent's own gap report** — the agent reported what it noticed, the player reported what it didn't. That is the wrong-but-plausible class `trial-protocol` exists to catch, and this is the first clean sample of it.

- **Warrior movement, when not thinking about it.** The agent treated Warriors as having 2 moves in passing remarks, while `units[].moves` is exported and correct — a background prior overriding correctly-read data. *Promote when:* it recurs. A second sighting argues for restating unit stats per turn or a "verify movement before advising a move" checklist trigger; one justifies neither.

- **Resource tiles valued for the resource, not the yield.** Especially where no plantation or pasture is required and the raw tile is already strong. The yields are exported and rendered; the weighting is judgement. *Promote when:* it recurs, **or** a trial names a decision it changed. The hardest of the three to evidence, since "over-valued" is a claim about a counterfactual — so what promotes it is a case where the alternative was measurably better and said so at the time.

- **Growth cost of food-fed builds under-weighted.** Switching to a Settler or Worker stops growth, which matters most when the city is 1–2 turns from growing. `rules.py city` already prints `(+food, growth stops)` and the export already carries the split — the agent's own report calls that the best-designed thing in the export — so the information was there and simply not weighted. *Promote when:* it recurs. **The trap if it does:** the reflex is to add output emphasising the trade, but the caveat is already printed and was already read past. When a caveat does not stick, the fix is placement, not volume — see `coastal-undetermined-wording`, which is the same lesson applied to a line that *is* worth reordering.

---

## Deliberately not building

Carried forward from `harness/README.md` so they are not re-proposed. **These carry no slugs and no targets — they are decisions, not work.**

- **A generic JSON query tool.** The agent reads JSON fine; wanting this is the signal it should just read the file. Same reasoning keeps `--filter`/`--sort` out of the renderer.
- **Unit pathfinding / movement cost.** Action-phase, out of scope, and it would reopen a closed decision — `river` is a boolean precisely because edge geometry only matters for movement. (Noted as the largest thing a second-city decision has to guess at, so if anything ever forces this, that is the reason.)
- **Anything that scores or ranks decisions.** Tools present; the AI decides. Site evaluation is where that line gets crossed by accident.
- **A run linter.** Dissolved rather than deferred: run integrity is a constructor assert inside the history tool, sample schema validity is a test over `samples/`, live-capture validity is `mod/tests/`.
- **Action execution.** A future phase, not current scope. Do not implement until explicitly asked.
- **New renderer views.** Nothing in the live trial argued for any. `explore` is the weak one — trials open it rarely and get little from it — so if any view merges, that is the candidate.

- **A `productionBankedFor` field on `cities[]`.** Asked for by the Ramesses trial after it wrongly advised switching production to a Warrior on the belief that 40 hammers banked toward a Worker would complete it instantly. The misconception is real and recurring — "should I switch production" is a live question most turns. But Civ4 banks hammers **per build class with a decay rule**, so a single field cannot represent the behaviour faithfully, and a half-right field is worse than none: it would be read as authoritative on exactly the decision it gets wrong. This is a **rule**, not a state fact, and it belongs in `rules.py city`'s output as a line — which is the trial's own fallback suggestion. Folded into `rules-lookup-gaps` as the research-switch rule's sibling.
- **Score decomposition, or an unexplained-score detector.** The trial watched score move 45 → 65 → 72 → 98 and had to flag one jump as unexplained, and proposed either a pop/land/tech/wonder breakdown or a `timeline` anomaly line mirroring the existing gold-swing detector. Declined for the current window: score is a scoreboard number, not a decision input in turns 0–50 — nothing the advisor recommends changes on knowing whether a jump came from population or land. The trial ranked it last itself. Revisit only if the advising window widens far enough that victory-condition tracking matters.
- **The Bronze Working / copper reveal "gap" — not one.** The Claude Code trial recommended delaying Bronze Working until copper was revealed, inverting the dependency — Bronze Working *is* what reveals copper. But `BONUS_COPPER` carries `<TechReveal>TECH_BRONZE_WORKING</TechReveal>`, and `rules.py tech TECH_BRONZE_WORKING` against that session's own state file prints `resources revealed BONUS_COPPER` under `UNLOCKS` (verified). Tool and data were both already correct and simply unconsulted, which makes this evidence for the trial brief's trigger list (landed — now `trial-template/CLAUDE.md`) rather than a build item.

Also worth recording: across two live trials (Cowork and Claude Code, 25 turns each, same game) no ranking or scoring tool was ever requested — every finding was a presentation or data gap, never a request to have the tool decide. The bar in `harness/README.md` is holding.

---

## Sequence rationale

**Ordering is not identity.** The old integer numbers were doing both jobs at once, and that is exactly what broke: deleting a landed item left a gap that read as a missing step, and every cross-reference to a number went stale the moment the series shifted. Slugs name items; this section — and only this section — says what to do first. Neither the index table's row order nor the lane letters imply priority.

**Lane E first — `trial-protocol` and `trial-per-turn-checklist`.** Both cost nothing, both pay off on the very next trial, and the checklist addresses more separate observations than any other item here. Doing them first also means the next trial generates better evidence for everything below.

**Then Lane C, as one agent taking the whole lane.** `goody-hut-outcomes` leads it: it is the only queued item with a demonstrated unit loss behind it, the data is verified, and it extends a subcommand that already parses the right file. `rules-improvement` follows — the only gap that produced a flatly false number, and it absorbs the buildable-now question that `render_map --view worker` currently punts. Then `unit-animal-combat` (nearly free once the file is open) and `rules-lookup-gaps`. **These four are serial with each other by construction**; do not split them across agents.

**`bearings-by-default` needs its own window.** It touches all three tools and therefore collides with Lanes A, B and C at once. It is the highest-frequency usability item on the page — a translation step removed from every turn — but it cannot be parallelized, so it wants a slot where nothing else is running. Settle the prose-only scope question before starting.

**`city-approach-report` and `per-city-production-history`** remain the two substantial harness builds, both carrying 4-of-6 trial evidence and both unblocked; `per-city-production-history`'s `timeline`/`intel` additions should build on the current section order and gold-anomaly line (see `harness/README.md`) rather than the layout that predates them. They share Lane A, so run them one after the other rather than concurrently.

**`multi-site-comparison` now follows `trial-per-turn-checklist`** rather than standing alone — the trial evidence says the missing thing is the trigger, not the table. It still needs its interface decision.

**`varied-setup-samples`** happens whenever a game is played to a wonder completion — opportunistic rather than scheduled. The Ramesses trial raised its value: it ran at **Monarch on Fractal with 7 civs** while the only committed sample is Emperor and otherwise default, and at least one finding (`goody-hut-outcomes`) is difficulty-dependent in a way that changes the advice. A second sample at a different difficulty would be worth more than a repeat.

**`same-turn-round-trips` stays recorded, not scheduled** — the best-evidenced finding on this page, but it needs a design for what an affordable fix even looks like before it can be sequenced at all.
