# samples/

Real state JSON captured by `mod/` while playing actual turns in-game. Used as static input to develop and test `harness/` without needing Civ IV running.

Not synthetic fixtures — these come from real play sessions and should reflect what the mod actually produces.

## A sample is a run, not a turn

One sample = one folder of consecutive `turn_NNNN.json` files, copied out of `state/`. That's what the mod naturally produces now that it keeps per-game history, and the sequence is the point: some reasoning only works across turns.

The clearest case is inferring what a rival has. Each snapshot is deliberately forgetful — `foreignUnits` only reports units on currently-visible tiles, so a rival Axeman spotted on turn 14 is simply gone from turn 15. Across the run it's still there to be found, and spotting it at all implies Bronze Working. Same for tracking rival city growth and border expansion. A single-turn sample cannot exercise any of that.

Each file carries its own `game` setup section (difficulty, climate, sea level, options), so a run documents its own conditions — no separate metadata file needed.

## Available samples

Folder names say what a run is *for*, not which game produced it — the `{leader}_{gameId}` name it had under `state/` is meaningless once it's curated, and each file carries its own `game` setup section anyway.

- **`baseline-early-game/`** — turns 0–43, the default-settings reference run. Portugal (João), Emperor, Fractal, standard/temperate/medium, 7 civs, no game options set. Two cities: Lisbon founded t1 at (75,36), reaching pop 2 at t39; Oporto founded t36 at (78,37). Three rivals met — Greece t15, Rome t24, Ottoman t27 — all `ATTITUDE_CAUTIOUS`, never at war. 29 → 266 tiles revealed, 108 still visible at t43. Deliberately ordinary: it is the control the others are varied against.

  What it exercises:
  - **First-city decision** — `turn_0000`, no cities, no borders, 29 tiles.
  - **Second-city placement** — t34 and t35 both have a settler alive with only one city and 21 owned tiles as a hard constraint; ground truth is Oporto at (78,37) on t36.
  - **Fog staleness** — 158 of 266 tiles are remembered-but-not-visible by t43.
  - **History inference** — 23 seen-then-gone foreign-unit events by `(owner, type, x, y)`, 15 of them civ units. Roman `UNIT_ARCHER`s (t26→t27) are the best tech-implication case. `foreignUnits` entries carry no `id`, so cross-turn identity has to be inferred from type/owner/position — the inference the tool exists to do. **Most of those 23 are not disappearances at all**: a unit that merely moved leaves one key and arrives at another. Only the fog state of the vacated tile separates "left or died" from "we stopped looking" — see `harness/README.md` on `run_history.py`.
  - **Unit/city asymmetry** — at t26→t27 the Roman units vanish while Rome itself persists.
  - **Resumed saves** — `turn_0000`, `turn_0040` and `turn_0043` carry `meta.trigger: onLoadGame`; t40 and t43 because the run was resumed from saves to extend it. Their mtimes are days newer than the turns around them, which is why the curation rules below insist on ordering by filename. Continuity of `knownTechs`, `score` and city state across both boundaries was checked — one timeline, not two.
  - **Rival tracking through fog** — Rome is revealed from t26 but `visibleNow` **only on t26**, yet its population still moves (5 → 3 → 4 across t39–t41). **None of those values is stale**: `foreignCities` fields are exported live, since the engine paints the nameplate through fog. The clearest case in the run that "fogged" and "stale" are different things.
  - **Tech-gated resource reveal** — `BONUS_HORSE` first appears on t30, exactly the turn Animal Husbandry completes: the team-aware bonus getter unhiding a resource.
  - **Resource *connection*, a different event from reveal** — and the reason the run goes to t43. The Horse at (79,37) is visible from t30 and pastured by t40, but stays out of `player.bonuses` until its road completes on **t43**, the first turn `strategic` is non-empty. Wheat (76,35) connects t27 (farm t25 + road t27); Cow (75,34) connects t34 (road t29 + pasture t34). Improvements and roads are visible per-tile throughout, so "in the fat cross" versus "connected" can be checked against ground truth — they diverge for 13 turns on the Horse alone.
  - **A city joining the trade network** — Oporto is founded t36 with nothing connected and picks up both of Lisbon's resources on **t37**, when the road at (77,36) closes the chain. Per-city `bonuses` differ from the empire's for exactly one turn: the case that shows why the field is per-city.
  - **One real unit loss** — a warrior present at t37 is gone at t38, killed off-screen.

  What it does *not* cover: war, any attitude change, any non-default game option, a third city, any city beyond pop 2, or any world wonder built anywhere (`wonders.built` is `[]` throughout, so that field is only exercised empty).

  **Second provenance caveat — the increment ⑥ fields are genuine on `turn_0040` and `turn_0043` and derived on every other turn.** `cities[].productionFromHammers` and `cities[].productionFromFood` were added after this run was captured; those two saves were reopened and re-exported to obtain real values, and the remaining 41 city-bearing turns were **backfilled from data already in each file**. As with the five fields below, nothing in the files records this, so it is written down here.

  The derivation, and why it is trustworthy where it is:

  - `productionFromFood` = `max(0, Σ food yield of workedTiles − 2 × population)` when `producing` is a `bFood` unit (`UNIT_SETTLER`, `UNIT_WORKER` — confirmed against `CIV4UnitInfos.xml`), else `0`.
  - `productionFromHammers` = `productionPerTurn − productionFromFood`, i.e. **by subtraction from the exported total**, deliberately not from tile hammers × trait modifier.

  **Validated against the two genuine turns**: stripping the real fields and recomputing reproduces all four city rows exactly (t40 Lisbon `6+6`, t40 Oporto `5+0`, t43 Lisbon `7+6`, t43 Oporto `6+1`). A second, independent model — tile hammers scaled by João's Imperialist +50% Settler / Expansive +25% Worker modifiers, from `CIV4UnitInfos.xml`'s `ProductionTraits` — agrees with the subtraction on **48 of 51** rows, and the three disagreements are all turns right after a build completed, where the subtraction is the correct one because it inherits the carried-over overflow that the multiplier model cannot see. No row yields negative hammers.

  **The one case this derivation would get wrong does not occur in this run**, and was checked for rather than assumed: a `bFood` build on the turn immediately after another build completed. There the overflow inflates `productionPerTurn`, and subtraction attributes all of it to the hammer half. Zero such rows exist here. A future run containing one would need a real capture.

  Two further limits worth knowing before reusing the formula elsewhere: food consumption is taken as a flat `2 × population`, which is right only while no city is unhealthy (the engine's actual figure is `pop × 2 − healthRate`, `CvCity.cpp:4504`) — no city in this run ever is, and the formula matches the exported `foodPerTurn` on every turn where that value is not clamped. And the 15 turns where a `bFood` build shows a derived surplus of `0` are genuinely zero (a size-1 city working two 1-food tiles), not an unresolved ambiguity.

  **Consequence for testing:** the fallback branch in `harness/rules.py`, which handles captures lacking these fields, is **no longer exercised by this sample at all** — every turn now carries them. Its coverage is the synthetic unit tests in `harness/tests/test_rules.py`. Equally, the sample-sweep assertion that the two halves sum to `productionPerTurn` is satisfied **by construction** on the 41 derived turns and is a real check only on t40 and t43. To validate the *mod* rather than the harness, re-capture rather than trusting the derived turns.

  **Provenance caveat — turns 0–39, 41 and 42 have five fields that were derived, not exported.** Only `turn_0040` and `turn_0043` came from a mod with `player.bonuses`, `cities[].bonuses`, `cities[].buildings`, `cities[].coastal` and `wonders`; the rest predate those fields and were backfilled from the tile improvement/route history already in each file, using the connection turns above. Nothing in the files records this, so it is written down here. The derivation checks out where it can be checked: t39's values match the real t40 export exactly, and t42's match t43 except for the Horse. Everything else in these files is untouched mod output. To validate the *mod* rather than the harness, re-capture rather than trusting these five fields.

  **Third provenance note — every coordinate in this run was migrated when `meta.schemaVersion` bumped 1 → 2**, inverting `y` so `(0,0)` is northwest instead of southwest (see root `CLAUDE.md`). Only coordinates and `meta.schemaVersion` changed, re-serialized through the mod's own `toJson`/`_Record` for a byte-clean diff — the two provenance caveats above are otherwise untouched. Landmark coordinates in this file already reflect the migrated values.

### Single-turn exceptions: `promotions-taken.json`, `promotions-available.json`

Two loose single-turn captures, not runs — a deliberate exception to "a sample is a run, not a turn" above, which is a rule for curated reference material, not for a one-off capture made to validate one export against real data. Both are real mod output from the same Darius game, unrelated to `baseline-early-game/`. `promotions-taken.json` (t25) has `UNIT_SCOUT` id 16385 carrying `PROMOTION_WOODSMAN1`/`PROMOTION_WOODSMAN2`; `promotions-available.json` (t16) has the same scout with `promotionsAvailable: 1` and no promotions taken yet. Captured to confirm schema increment ⑦ (`units[].level`/`experience`/`experienceToNextLevel`/`promotions`/`promotionsAvailable`) against a real game rather than only the synthetic fixtures in `mod/tests/`, and used to verify `rules.py promotion --for-unit` and `run_history.py intel`'s promotion display end to end.

## What to capture

- **From `turn_0000`**, not just a convenient mid-game stretch. Files are numbered for the turn *about to be played*, so a run starts at `turn_0000` — the state before turn 1, which is the snapshot the first-city decision is actually made from. There are no cities, no borders, and barely any revealed map, so the tooling gets its hardest test where the least data exists. Later turns then cover second-city-onward placement, which has ownership and existing cities as constraints.
- **Varied setups** — the `game` section's climate/sea-level/barbarian options change turn-1–20 advice more than almost anything else in the file, so runs that differ there are worth more than repeats of the same conditions. **Which specific gaps are worth targeting next is in [`ROADMAP.md`](../ROADMAP.md)** — currently a wonder completing anywhere (`wonders.built` has never met real data) and a `bFood` build the turn after another build completes.
- **A few representative runs, not everything played.** These are committed, and a run grows with the revealed map (~27KB/turn by turn 12). Keep the set small and deliberate.

## Curating a run

- **Don't assume turn numbers are contiguous.** A failed export is logged and skipped rather than crashing the game (see root `CLAUDE.md`), so a run can legitimately have a gap.
- **Order by filename, never by mtime.** Loading a save re-exports that turn over its existing file, so timestamps within a run aren't monotonic. Such a file is identifiable by `meta.trigger` reading `onLoadGame`. Don't try to preserve mtimes when copying either: git doesn't store them, so a fresh clone restamps everything anyway.
- **Check for divergent timelines, using file contents rather than timestamps.** Reloading an *older* save rewrites that turn while later files from the abandoned timeline stay behind — a folder that looks like one continuous game but isn't, and save-scumming one bad turn is enough to cause it. Two signals survive into the committed files: any `meta.trigger` of `onLoadGame`, which says a resume happened somewhere, and continuity of `knownTechs`, `score`, `culture` and city state turn to turn, which reveals how far an abandoned tail extends. Treat an `onLoadGame` as the cue to check continuity hard, and prune the stale tail rather than committing it and debugging it later.
- **Validate committed runs against `schema/state.schema.json` as a test**, not as a tool someone remembers to run. `mod/tests/` validates the full document, but only against mocked `Cy*` objects — a real capture can violate the schema in ways the mocks never produce, and these files are the only real output under version control.
- **Re-serialize with the mod's own `toJson` if a file is ever edited outside the game.** Python's `json` module explodes short containers onto separate lines, turning a five-field addition into a whole-file diff. Round-tripping an untouched export through `toJson` should be byte-identical — that's the check that it's the mod's format and not a lookalike.

`mod/` writes live state per turn into `state/` (see its README); curating a run means copying a per-game folder from there into here under a purpose-describing name, after the checks above.
