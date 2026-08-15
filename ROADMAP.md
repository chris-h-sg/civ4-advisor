# Roadmap

**The single roadmap for the project, covering `mod/`, `harness/` and `samples/`.** Anything unbuilt lives here; the other READMEs describe what exists and why it is shaped the way it is. When an item lands, delete it from here and write the reasoning into the relevant README — this file is a queue, not a history, and git holds whatever the deletion drops.

Two sources feed it: the design-review items recorded while building each tool, and findings from **agent trials** — a fresh agent given the guide and a sample (or a live game) and asked a real question, then asked where a tool would have helped. Trial counts below are that evidence, and they are the strongest thing on this page — better than anything predicted in advance.

**Trial evidence comes in two kinds, and they are not equally reliable.** *Agent-asked* is what a trial reported when asked where a tool would have helped. *Player-observed* is what the human running the trial noticed the agent getting wrong — and the agent did not report, because it never noticed. The second kind is rarer and worth more: it is the only detector for the wrong-but-plausible class, which by construction never appears in an agent's own gap report. Items below name which kind they carry. The protocol for capturing the second kind now lives in `trial-template/CLAUDE.md`; see the **Findings** section for observations that are not build items at all.

**Read the source before queueing a gap.** A trial reporting something missing is evidence that it was not *found*, which is not the same as it not existing — `coastal-undetermined-wording` was drafted as a missing feature before anyone checked, and the capability was already there and already correct. `AGENT_GUIDE.md` gives the advising agent this rule ("before reporting something as a gap, confirm it's actually missing"); it applies with more force here, where the output is a build item rather than a sentence.

**Items are identified by slug, not by number** — a slug survives its neighbours being deleted, where a numbered series does not. Ordering is a separate concern and lives in **Sequence rationale** at the bottom.

Every item carries a **`Target:`** line naming the files it will have to edit. That is what makes a collision visible before two agents pick up work: read the targets, not the prose. Items are grouped into **lanes** below by those targets, and each lane says whether its items can run concurrently.

---

## Index

| Slug | Lane / target | Evidence | Status |
| --- | --- | --- | --- |
| `same-turn-round-trips` | Correctness — schema + mod (design first) | 1 trial, sharpest finding on the page | Recorded, **not scheduled** — no affordable design yet |
| `city-approach-report` | Lane A — `run_history.py` | 4 of 6 `rules.py` trials; 2 wrote their own BFS | Ready, unblocked |
| `coastal-undetermined-wording` | Lane B — `render_map.py` | Player-observed; the output was already right | Ready; wording only, will break one test assertion |
| `multi-site-comparison` | Lane B — `render_map.py` | Both trial rounds; one diffed 10 runs by eye | **Reframed** — trigger landed; awaiting next trial |
| `rules-lookup-gaps` | Lane C — `rules.py` | Eight sub-gaps; 1–2 of 4 trials each, one player-raised | Ready — **not one item**, see its note |
| `varied-setup-samples` | Lane D — `samples/` (capture) | Coverage holes identified, not trial-driven | Opportunistic — needs a game played |

`Deliberately not building` is below and carries no slugs — those entries are decisions, not work. **Findings** likewise: observations about how the advisor reasons, held as an accumulator until one recurs. Each names what would promote it; the bar is a second occurrence, not a good argument.

---

## Lanes

Grouped by `Target:`, so what can run concurrently is visible without reading the prose.

- **Lane A — `harness/run_history.py`.** `city-approach-report` is the only item left in it, so it is serial with nothing. It lands in `intel`'s garrison block, which has been rewritten twice — read the current block before starting.
- **Lane B — `harness/render_map.py`.** `coastal-undetermined-wording`, `multi-site-comparison`. Both land in the site report, so treat as serial with each other; the wording fix is small enough to take first in the same sitting. Parallel-safe against every other lane.
- **Lane C — `harness/rules.py`.** `rules-lookup-gaps` is the only item left in it. `rules.py` is a single ~5600-line module, so anything landing here is serial with it by construction — if a second Lane C item ever appears, do not assign the two concurrently.
- **Lane D — `samples/`.** `varied-setup-samples`. Requires actual play; collides with nothing.
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

### `city-approach-report` — the best-evidenced gap in the folder

**Lane A.** **Target:** `harness/run_history.py`, `harness/tests/test_run_history.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`. **Not** in scope against `harness/render_map.py`. An earlier draft said `State.land_distance` lives there and is imported here; that is wrong (checked while landing `per-city-production-history`) — `run_history.py` has its own `land_path`/`land_distances_from`, already used by `intel`. The walk machinery is local, so this does not collide with Lane B.

**4 of 6 `rules.py` trials asked for it; 2 independently wrote their own BFS** over `map.tiles`, which is this repo's stated signal for a missing tool.

The specific failure: `intel` correctly refuses to judge whether an empty city is in danger and points at `--view military`; `military` renders a symbol grid and cannot answer it either, so the agent eyeballs a corridor off the grid — the derivation the guide says is unreliable.

Wanted is presentation, not a verdict: per city, distance to the nearest unowned land tile, how many reachable unowned land tiles lie within N walk, and whether a land route exists at all. The walk machinery is already local to `run_history.py` (see the target line above). **Hold the line `intel` already holds** — report the approach, never call a city safe or unsafe.

### `coastal-undetermined-wording` — the site report's undetermined coastal state leads with "no"

**Lane B.** **Target:** `harness/render_map.py` (`_site_header`), `harness/tests/test_render_map.py`, `harness/README.md`. Wording only — no new computation, and `State.is_coastal()` already returns the unrevealed-neighbour count this needs.

**Not a missing feature.** `--around` on a site with unrevealed neighbours already prints `coastal    no, but N adjacent tile(s) unrevealed - explore before ruling it out`, and it fires on real data (2 tiles at t5 of the baseline, checked). The Ramesses trial still read such sites as landlocked.

The diagnosis is the ordering: **the line leads with `no` and the qualifier trails behind it**, so the eye takes the negative and the rest reads as a footnote. That is the same failure this repo has now hit three times — walk-versus-straight-line (the leading number is the one that sticks, so the walk now leads), the garrison block scrolling past 7 of 10 trials until it moved up, and the compass. Each was fixed by changing what comes first, not by adding words.

So: lead with the uncertainty rather than the negative — an `UNDETERMINED` state alongside the existing `yes` and `no - landlocked`, with the explore-first action on its own line rather than trailing the verdict. **Check the test suite's expectations while doing it**: at least one test matches the literal string `coastal    no` as a proxy for "not coastal", which a rewording will break — correctly, since the property it means to assert is that sea in the city cross does not make a site coastal, not the wording. Fix the assertion to the property rather than the string.

### `multi-site-comparison` — multi-site `--around` comparison

**Lane B.** **Target:** `harness/render_map.py`, `harness/tests/test_render_map.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`.

Asked in both trial rounds; one trial ran `--around` ten times and diffed by eye. **Tabulating the same facts across several sites is not ranking them** — the no-ranking line survives, which is what makes this buildable rather than refused.

It outlived the cheap presentation fixes it was once grouped with (`--site-only` and the seam-description wording, both since landed — see `harness/README.md`) because it is a real interface question (how many sites, what shape the table takes), not a layout tweak.

**Reframed by the Ramesses trial, and worth reading before building it.** The player observed that the agent *"does comparative analysis of city sites when asked, has been very thorough considering tiles and strategic value vs rivals, produces a clear table — but only when asked."* So the agent already produces a good multi-site comparison on request, by hand, and the thing that fails is that nobody asks. Building the table buys a tidier version of something that works and leaves the actual failure untouched.

**The trigger half has now landed** as item 5 of the per-turn checklist in `trial-template/CLAUDE.md` (a walking settler forces an explicit candidate table). So this item is **waiting on evidence rather than on a decision**: if the next trial produces good comparisons unprompted, what remains here is removing hand-derivation and its wrap-handling risk — real, but a smaller claim than the one this item was queued on. If the checklist item does *not* fire, that is the stronger argument for building the table. Either way the interface decision (how many sites, what shape) is still open and unmade.

### `rules-lookup-gaps` — smaller `rules.py` gaps

**Lane C.** **Target:** `harness/rules.py`, `harness/tests/test_rules.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`. The worker-build-times sub-item reads `CIV4BuildInfos.xml` from the game install, which `rules.py` already opens (`BUILD_FILE`) — no new data source, and nothing in this repo. Cottage growth is the same shape: `CIV4ImprovementInfos.xml` is already parsed for yields, and the upgrade chain sits on the records the view has in hand. Both of those sub-items also need the **game-speed scaling** that `rules.py` does not read today (`iBuildPercent` for build times, `iImprovementPercent` for upgrade times, both in `CIV4GameSpeedInfo.xml`) — worth doing once for both rather than twice. The turns-to-complete sub-item is **partly answered**: `per-city-production-history` (landed) put the ETA on `intel`, reimplementing the arithmetic locally rather than importing from `rules.py` to keep the lanes decoupled (reasoning in `harness/README.md`). What remains is the `rules.py city` side — an accepted duplication of one small formula, not worth coupling the modules to remove.

- **Worker action build times.** No build-time data for worker actions, so the live trial's road-versus-pasture-first answer was general BTS knowledge rather than tool-verified — flagged by the agent itself against the guide's own rule 5. **Cheaper than it sounds and not a mod change**: the data is in `CIV4BuildInfos.xml`, already on disk. A missing lookup in an existing tool, independent of everything else here. **Two traps found while auditing the unit block:** `<iTime>` appears more than once per `BuildInfo`, the extra occurrences belonging to nested `<FeatureStructs>` (clearing forest before the improvement), so a flat `findall` returns the wrong number; and turning `iTime` into turns needs the worker's `iWorkRate` (100 on `UNIT_WORKER`, and the Indian Fast Worker differs) scaled by the game speed's `iBuildPercent` — `rules.py` reads none of these today. **Now has a waiting consumer:** `rules-improvement` (landed) shipped a tile view whose OMITS block promises exactly this number, and states the additive rule — a feature-clearing build costs the improvement’s `iTime` PLUS the nested clearing `iTime`, charged as one worker order (Mine 400 + forest 300 = 700), which is what the UI does when you click mine on a forested hill. The `improvement --at` view is where the figure belongs; parsing already reads the nested structs, so the trap above is handled and what remains is the `iWorkRate`×`iBuildPercent` arithmetic.
- **Cottage growth is a missing number, not just a missing caveat — player-raised, reviewing the `improvement` view.** The view prints `IMPROVEMENT_COTTAGE +1 commerce` and leaves it there; the agent sees a flat +1 with nothing to say it is the *worst* the tile will ever be. OMITS already names the gap ("the yield is a fresh Cottage") but only says a number is missing, not what it is. Wanted: a `grows` line beside the yield, for any improvement with an `ImprovementUpgrade` — chain and per-step commerce read straight from `CIV4ImprovementInfos.xml` (Cottage 1 → Hamlet 2 → Village 3 → Town 4, at `iUpgradeTime` 10/20/40). **Three caveats, and each one is why the note cannot be a static string.** The clock only advances while the tile is **worked** — `CvPlot::doImprovementUpgrade` gates on `isBeingWorked()`, verified byte-identical in both bundled SDK copies — so a built-but-unworked cottage never grows at all. `iUpgradeTime` scales by the game speed's `iImprovementPercent` (Marathon 300, Epic 150, Normal 100, Quick 67), so the raw XML figures are Normal-only; `game` carries the speed, so scaling is cheap and skipping it is a lie on three of four settings. And Village/Town carry a `TechYieldChanges` +1 commerce on `TECH_PRINTING_PRESS`, which is out of scope but must not be silently folded into the in-scope numbers. **Scope-shaping, worth stating:** within turns 0–50 a cottage realistically reaches Hamlet and maybe Village, so a line implying Town is the reason to build one would mislead in exactly the window we care about. Presentation only — it shows the chain, it does not rank Cottage against Farm. The same line covers every other upgrade chain for free; decide at build time whether to emit it for all of them or only where it changes a decision.
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
- **A real improvement standing on a feature.** The baseline has none — the only two improvement-plus-feature tiles are goody huts, excluded as not-real improvements — so `improvement_yield`'s feature handling is validated against the engine on zero tiles. A run where a worker farms flood plains or mines a forested hill would convert the flood-plains bug's whole class from synthetic coverage into swept coverage, since the improvement is a fact on the tile the turn after it is built. Cheap: it needs a worker and about ten turns, not a new setup.

Also outstanding from the same caveat: the baseline's increment-⑤ and ⑥ fields are genuine only on `turn_0040`/`turn_0043` and backfilled elsewhere, so `rules.py`'s pre-⑥ fallback path has **no sample coverage at all** — only synthetic unit tests. A fresh capture from a mod that already has both increments would retire that caveat entirely.

---

## Findings

**How the advisor reasoned wrongly while every tool answered correctly.** No slugs, no targets — these are not work. **An accumulator, not a backlog:** one occurrence is noise, a second is a pattern, and only a pattern justifies building something. Each entry names what would promote it; the bar is recurrence, not a good argument.

**All six are now actively tested rather than passively held.** The landed per-turn checklist in `trial-template/CLAUDE.md` carries one row each in its quote-inline table, so each trial either produces another occurrence or leaves them where they are. That was the checklist's second job, and it is what makes this section resolvable instead of permanent — **a finding that survives several trials with the check in place is a candidate for deletion, not indefinite storage.**

**Two entries have now recurred *with a check in place*, which the bar above did not anticipate.** The rule was "a second occurrence promotes it"; what actually happened is that the recurrence indicted the *check* rather than the finding, since the instruction existed and was read past. So a recurrence under a check promotes the **mechanism**, not necessarily the tool — the response was to change how the check is written, and the next recurrence is what would argue for building something. Entries below say which bar they are on. **One of the two recurred inside a single trial, after a correction**, which is the shortest interval yet and the strongest form of this signal.

**All six are player-observed. Five never appeared in the agent's own gap report**; the sixth (the repeated recommendation) the agent did report unprompted and diagnosed accurately, having been corrected in the moment — the protocol working as intended rather than an exception to it. That is the wrong-but-plausible class the trial brief's out-of-band-fact protocol exists to catch, and the pattern has now held across two trials.

- **Warrior movement, when not thinking about it. RECURRED — Qin Shi Huang trial, with the check in place.** The agent treated Warriors as having 2 moves in passing remarks, while `units[].moves` is exported and correct — a background prior overriding correctly-read data. The second occurrence indicted the check, not the finding: the item existed, the block was open, and it was skimmed. **A silent check does not hold**, so the response was to require the value quoted inline. *Promote when:* it recurs **a third time, with quoting in place** — that rules out prose entirely and argues for movement on `intel`'s unit line, where it cannot be skipped.

- **Resource tiles valued for the resource, not the yield.** Especially where no plantation or pasture is required and the raw tile is already strong. The yields are exported and rendered; the weighting is judgement. *Promote when:* it recurs, **or** a trial names a decision it changed. The hardest here to evidence, since "over-valued" is a claim about a counterfactual — so what promotes it is a case where the alternative was measurably better and said so at the time.

- **Growth cost of food-fed builds under-weighted.** Switching to a Settler or Worker stops growth, which matters most when the city is 1–2 turns from growing. `rules.py city` already prints `(+food, growth stops)` and the export already carries the split — the agent's own report calls that the best-designed thing in the export — so the information was there and simply not weighted. *Promote when:* it recurs. **The trap if it does:** the reflex is to add output emphasising the trade, but the caveat is already printed and was already read past. When a caveat does not stick, the fix is placement, not volume — see `coastal-undetermined-wording`, which is the same lesson applied to a line that *is* worth reordering.

- **Proximity read as ownership.** *Qin Shi Huang trial, player-observed.* The agent called a Copper deposit "inside our border" from its 3-tile distance to the capital and repeated it after one correction; `map.tiles[].owner` and `--view military`'s territory column both settled it immediately. Now guide trap 7 and a table row. *Promote when:* it recurs. The tooling response if it does is **not** a new view — `military` already draws ownership — but plausibly an ownership mark in `improvement --at`'s header, which is where a resource question is usually asked and currently answers without mentioning whose land it is.

- **A recommendation repeated without revalidating it. RECURRED within one trial.** *Qin Shi Huang, player-observed.* The agent recommended an unselectable tech, was corrected, then recommended it again after two intervening techs had landed — still without running `rules.py tech`, which prints the missing prereq immediately. **The repeat is the finding**, not the first miss: a conclusion already stated reads as settled rather than unverified, so it skips the check its first statement got. Now the general case in guide trap 1, plus a rule-5 row and a table row. *Promote when:* it recurs with those in place. **Note before building anything for this: `timeline` already prints a `research` line on every change of target, including `now nothing selected`** — which is precisely the state an unselectable pick leaves behind, so the evidence was already rendered and simply not consulted. That makes this a reading failure rather than a tooling gap, and argues the promotion response is placement (surfacing current research where the turn's advice is composed) rather than new output.

- **Silent scope narrowing.** *Qin Shi Huang trial, player-observed.* Asked what would improve yields, the agent answered for the four currently-worked tiles only, without saying so, and missed a Horse recorded in `objectives.md` twelve turns earlier. Every quoted number was correct; the answer was wrong by omission. **This is the one finding here that no field or view can fix** — the data was present and read correctly — so it is a discipline row in the brief's table and nothing more. *Promote when:* it recurs, though note that promotion has nowhere obvious to go: a tool cannot detect a question it was not asked.

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
- **The Bronze Working / copper reveal "gap" — not one.** The Claude Code trial recommended delaying Bronze Working until copper was revealed, inverting the dependency — Bronze Working *is* what reveals copper. But `BONUS_COPPER` carries `<TechReveal>TECH_BRONZE_WORKING</TechReveal>`, and `rules.py tech TECH_BRONZE_WORKING` against that session's own state file prints `resources revealed BONUS_COPPER` under `UNLOCKS` (verified). Tool and data were both already correct and simply unconsulted, which makes this evidence for the guide's rule-5 trigger table (landed) rather than a build item.

Also worth recording: across two live trials (Cowork and Claude Code, 25 turns each, same game) no ranking or scoring tool was ever requested — every finding was a presentation or data gap, never a request to have the tool decide. The bar in `harness/README.md` is holding.

---

## Sequence rationale

**Ordering is not identity.** The old integer numbers were doing both jobs at once, and that is exactly what broke: deleting a landed item left a gap that read as a missing step, and every cross-reference to a number went stale the moment the series shifted. Slugs name items; this section — and only this section — says what to do first. Neither the index table's row order nor the lane letters imply priority.

**Run a trial before building anything.** The per-turn checklist and the out-of-band-fact protocol in `trial-template/CLAUDE.md` are both unmeasured, and the Findings checks either fire or don't — so **the next trial is worth more than the next build**, and items below have their evidence gated on it (`multi-site-comparison` outright, the Findings section entirely).

**Then Lane C — `rules-lookup-gaps`**, whose eight sub-bullets are **not one item**: five are genuine lookups, two (the research- and production-switch rules) are prose assertions about engine behaviour with no XML field behind them, and the happiness/health view carries an unverified precondition. Cottage growth is the fifth lookup and the best-specified of them — data source, caveats and scaling rule are all settled in its bullet, so it is the cheapest place to start in this lane. **All of these are serial with each other by construction**; do not split them across agents.

**`city-approach-report`** is now the one substantial harness build left — 4-of-6 trial evidence, unblocked, and cleanly Lane A.

**`multi-site-comparison` is now gated on the next trial** rather than standing alone — the trial evidence said the missing thing was the trigger, not the table, and the trigger has landed in the checklist. Whether the table is still worth building is a question that trial answers. It also still needs its interface decision.

**`varied-setup-samples`** happens whenever a game is played to a wonder completion — opportunistic rather than scheduled. The Ramesses trial raised its value: it ran at **Monarch on Fractal with 7 civs** while the only committed sample is Emperor and otherwise default, and `rules.py goody` (landed) is difficulty-dependent in a way that changes the advice — its output differs on every one of the nine handicaps, and only Emperor is covered by a committed sample. A second sample at a different difficulty would be worth more than a repeat.

**`same-turn-round-trips` stays recorded, not scheduled** — the best-evidenced finding on this page, but it needs a design for what an affordable fix even looks like before it can be sequenced at all.
