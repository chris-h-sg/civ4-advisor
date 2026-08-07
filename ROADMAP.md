# Roadmap

**The single roadmap for the project, covering `mod/`, `harness/` and `samples/`.** Anything unbuilt lives here; the other READMEs describe what exists and why it is shaped the way it is. When an item lands, delete it from here and write the reasoning into the relevant README — this file is a queue, not a history.

Two sources feed it: the design-review items recorded while building each tool, and findings from **agent trials** — a fresh agent given the guide and a sample (or a live game) and asked a real question, then asked where a tool would have helped. Trial counts below are that evidence, and they are the strongest thing on this page. An item asked for by 7 of 10 agents is better evidenced than anything anyone predicted in advance.

**Items are identified by slug, not by number.** Numbers were a fossil of insertion order: they implied a sequence they did not carry, and every landed item punched a hole in the series that a cross-reference could not survive. A slug says what an item *is*, stays the same when its neighbours are deleted, and reads in a sentence ("I'm taking `city-approach-report`"). Ordering is a separate concern and lives in **Sequence rationale** at the bottom.

Every item carries a **`Target:`** line naming the files it will have to edit. That is what makes a collision visible before two agents pick up work: read the targets, not the prose. Items are grouped into **lanes** below by those targets, and one lane is explicitly serial.

---

## Index

| Slug | Lane / target | Evidence | Status |
| --- | --- | --- | --- |
| `same-turn-round-trips` | Correctness — schema + mod (design first) | 1 trial, sharpest finding on the page | Recorded, **not scheduled** — no affordable design yet |
| `city-approach-report` | Lane A — `run_history.py` | 4 of 6 `rules.py` trials; 2 wrote their own BFS | Ready, unblocked |
| `per-city-production-history` | Lane A — `run_history.py` | 4 of 6 trials read raw JSON for it | Ready, unblocked |
| `multi-site-comparison` | Lane B — `render_map.py` | Both trial rounds; one diffed 10 runs by eye | Needs a small interface decision first |
| `unit-animal-combat` | Lane C — `rules.py` (**serial**) | 1 trial, the one unconfident answer it gave | Ready, nearly free |
| `rules-lookup-gaps` | Lane C — `rules.py` (**serial**) | Five sub-gaps, 1–2 of 4 trials each | Ready, independent of everything else |
| `varied-setup-samples` | Lane D — `samples/` (capture) | Coverage holes identified, not trial-driven | Opportunistic — needs a game played |
| `trial-protocol` | Lane E — trial docs | The meta-finding behind three landed items | Ready, costs nothing |

`Deliberately not building` is below and carries no slugs — those entries are decisions, not work.

---

## Lanes

Grouped by `Target:`, so what can run concurrently is visible without reading the prose.

- **Lane A — `harness/run_history.py`.** `city-approach-report`, `per-city-production-history`. Both land in the same module and both touch `intel`; **treat as serial with each other**, though the collision is far smaller than Lane C's.
- **Lane B — `harness/render_map.py`.** `multi-site-comparison` alone. Parallel-safe against every other lane.
- **Lane C — `harness/rules.py` — SERIAL.** `unit-animal-combat`, `rules-lookup-gaps`. `rules.py` is a single ~3000-line module and both items add lookups into it and its tests. **Do not assign these to two agents at once.** The natural move is one agent taking the whole lane, since `unit-animal-combat` is nearly free once the file is open.
- **Lane D — `samples/`.** `varied-setup-samples`. Requires actual play; collides with nothing.
- **Lane E — trial/advisor documentation.** `trial-protocol`. Touches only `trial-template/` and `harness/AGENT_GUIDE.md`; parallel-safe.
- **Unlaned — `same-turn-round-trips`.** Would cross `mod/` and `schema/`, colliding with nothing currently queued, but it has no design yet.

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

### `per-city-production-history` — per-city production over the run

**Lane A.** **Target:** `harness/run_history.py` (both the `timeline` and `intel` views), `harness/tests/test_run_history.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`. The turns-to-complete half overlaps conceptually with a `rules-lookup-gaps` sub-item, but the arithmetic it wants already lives in `rules.py building` — *uncertain* whether that is imported (touching `harness/rules.py`, and so Lane C) or reimplemented; deciding that is part of the item.

**4 of 6 trials read raw JSON for this** after `intel` told them a city was empty. `timeline` reports techs, cities, units, contacts, sightings, tiles, territory and resources — but not what any city is *producing*, or when that changed.

One trial found Lisbon started a Warrior on t38 while both cities were empty and switched **back** to a Worker on t40 — the sharpest fact in the run, visible in no view, recovered with a throwaway loop over five files.

Two obvious halves: a `producing` change line in `timeline`, and current build plus turns-to-complete on `intel`'s garrison block.

### `multi-site-comparison` — multi-site `--around` comparison

**Lane B.** **Target:** `harness/render_map.py`, `harness/tests/test_render_map.py`, `harness/AGENT_GUIDE.md`, `harness/README.md`.

Asked in both trial rounds; one trial ran `--around` ten times and diffed by eye. **Tabulating the same facts across several sites is not ranking them** — the no-ranking line survives, which is what makes this buildable rather than refused.

It outlived the cheap presentation fixes it was once grouped with (`--site-only` and the seam-description wording, both since landed — see `harness/README.md`) because it is a real interface question (how many sites, what shape the table takes), not a layout tweak.

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

### `trial-protocol` — because out-of-band discovery is the real detector

**Lane E.** **Target:** `trial-template/CLAUDE.md` (the session brief the trial deploys), and probably `harness/README.md`'s trial section for the reasoning. *Uncertain* whether any of this belongs in `harness/AGENT_GUIDE.md`: the protocol is aimed at the **player**, not the agent, and the guide is the agent's file — so the honest answer is likely "no", but that is a call to make while writing it.

**The meta-finding, and the one with no obvious owner.** The mod-side gaps in the (now-resolved) `doTurn()` mutation-order audit (see `REFERENCES.md`), `same-turn-round-trips`, and the now-built increment ⑦ all surfaced *only* because the player narrated something the agent could not see — "it's actually healed", "here's the 60 gold", "it got two promotions". In a run where the player did not narrate, those would have silently produced worse advice with nothing in the output able to catch it.

That is the compass failure mode again: wrong-but-plausible, self-consistent, invisible from inside. Trials are currently the only detector for this class of problem, and they fire only when the player happens to mention the right thing.

The fix is not tooling. It is a protocol: during a trial, **note every time you tell the agent something the JSON should have carried.** That turns an accident into a repeatable finding mechanism, and it costs nothing. Belongs in the advisor instructions used to set up a session.

**One asymmetry this doesn't fix.** A trial can report itself confident and correct while the player observes real slips. The guide's "tell us what's missing" instruction only catches failures the agent *notices*, which structurally excludes the entire wrong-but-plausible class. Not fixable in the agent's instructions — it is the argument for the player-side protocol being more load-bearing than it looks.

---

## Deliberately not building

Carried forward from `harness/README.md` so they are not re-proposed. **These carry no slugs and no targets — they are decisions, not work.**

- **A generic JSON query tool.** The agent reads JSON fine; wanting this is the signal it should just read the file. Same reasoning keeps `--filter`/`--sort` out of the renderer.
- **Unit pathfinding / movement cost.** Action-phase, out of scope, and it would reopen a closed decision — `river` is a boolean precisely because edge geometry only matters for movement. (Noted as the largest thing a second-city decision has to guess at, so if anything ever forces this, that is the reason.)
- **Anything that scores or ranks decisions.** Tools present; the AI decides. Site evaluation is where that line gets crossed by accident.
- **A run linter.** Dissolved rather than deferred: run integrity is a constructor assert inside the history tool, sample schema validity is a test over `samples/`, live-capture validity is `mod/tests/`.
- **Action execution.** A future phase, not current scope. Do not implement until explicitly asked.
- **New renderer views.** Nothing in the live trial argued for any. `explore` is the weak one — trials open it rarely and get little from it — so if any view merges, that is the candidate.

- **The Bronze Working / copper reveal "gap" — not one.** The Claude Code trial recommended delaying Bronze Working until copper was revealed, inverting the dependency — Bronze Working *is* what reveals copper. But `BONUS_COPPER` carries `<TechReveal>TECH_BRONZE_WORKING</TechReveal>`, and `rules.py tech TECH_BRONZE_WORKING` against that session's own state file prints `resources revealed BONUS_COPPER` under `UNLOCKS` (verified). Tool and data were both already correct and simply unconsulted, which makes this evidence for the trial brief's trigger list (landed — now `trial-template/CLAUDE.md`) rather than a build item.

Also worth recording: across two live trials (Cowork and Claude Code, 25 turns each, same game) no ranking or scoring tool was ever requested — every finding was a presentation or data gap, never a request to have the tool decide. The bar in `harness/README.md` is holding.

---

## Sequence rationale

**Ordering is not identity.** The old integer numbers were doing both jobs at once, and that is exactly what broke: deleting a landed item left a gap that read as a missing step, and every cross-reference to a number went stale the moment the series shifted. Slugs name items; this section — and only this section — says what to do first. Neither the index table's row order nor the lane letters imply priority.

**`same-turn-round-trips` is recorded, not scheduled** — the best-evidenced finding on this page, but it needs a design for what an affordable fix even looks like before it can be sequenced at all. **`trial-protocol` now**, since it costs nothing and pays off on the very next trial. **`city-approach-report` and `per-city-production-history`** are the two substantial harness builds, both carrying 4-of-6 trial evidence and both unblocked; `per-city-production-history`'s `timeline`/`intel` additions should build on the current section order and gold-anomaly line (see `harness/README.md`) rather than the layout that predates them. They share Lane A, so run them one after the other rather than concurrently. **`unit-animal-combat` and `rules-lookup-gaps`** are independent of the rest and belong to whenever `rules.py` is next open — the `iAnimalCombat` fix in particular is nearly free — but they are Lane C and therefore serial with each other; one agent should take both. **`multi-site-comparison`** needs a small design decision first, and is parallel-safe with everything once it has one. **`varied-setup-samples`** happens whenever a game is played to a wonder completion — opportunistic rather than scheduled.
