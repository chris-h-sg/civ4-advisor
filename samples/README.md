# samples/

Real state JSON captured by `mod/` while playing actual turns in-game. Used as static input to develop and test `harness/` without needing Civ IV running.

Not synthetic fixtures — these come from real play sessions and should reflect what the mod actually produces.

## A sample is a run, not a turn

One sample = one folder of consecutive `turn_NNNN.json` files, copied out of `state/`. That's what the mod naturally produces now that it keeps per-game history, and the sequence is the point: some reasoning only works across turns.

The clearest case is inferring what a rival has. Each snapshot is deliberately forgetful — `foreignUnits` only reports units on currently-visible tiles, so a rival Axeman spotted on turn 14 is simply gone from turn 15. Across the run it's still there to be found, and spotting it at all implies Bronze Working. Same for tracking rival city growth and border expansion. A single-turn sample cannot exercise any of that.

Each file carries its own `game` setup section (difficulty, climate, sea level, options), so a run documents its own conditions — no separate metadata file needed.

## Available samples

Folder names say what a run is *for*, not which game produced it — the `{leader}_{gameId}` name it had under `state/` is meaningless once it's curated, and each file carries its own `game` setup section anyway.

- **`baseline-early-game/`** — turns 0–40, the default-settings reference run. Portugal (João), Emperor, Fractal, standard/temperate/medium, 7 civs, no game options set. Two cities: Lisbon founded t1 at (75,15), reaching pop 2 at t39; Oporto founded t36 at (78,14). Three rivals met — Greece t15, Rome t24, Ottoman t27 — all `ATTITUDE_CAUTIOUS`, never at war. 29 → 266 tiles revealed, 99 still visible at t40. Deliberately ordinary: it is the control the others are varied against.

  What it exercises:
  - **First-city decision** — `turn_0000`, no cities, no borders, 29 tiles.
  - **Second-city placement** — t34 and t35 both have a settler alive with only one city and 21 owned tiles as a hard constraint; ground truth is Oporto at (78,14) on t36.
  - **Fog staleness** — 167 of 266 tiles are remembered-but-not-visible by t40.
  - **History inference** — eight seen-then-gone foreign-unit events, five involving civ units. Roman `UNIT_ARCHER`s (t26→t27) are the best tech-implication case; a Greek `UNIT_SCOUT` goes t23→t24 and again t36→t37. Note `foreignUnits` entries carry no `id`, so cross-turn identity has to be inferred from type/owner/position — which is the inference the tool exists to do.
  - **Unit/city asymmetry** — at t26→t27 the Roman units vanish while Rome itself persists.
  - **Rival tracking** — Rome is visible for 15 consecutive turns (t26–t40), with population moving 4 → 5 → 3 (a non-monotonic case) and its borders expanding 2 → 4 → 8 tiles.
  - **Tech-gated resource reveal** — `BONUS_HORSE` first appears on t30, exactly the turn Animal Husbandry completes, demonstrating the team-aware bonus getter unhiding a resource.
  - **One real unit loss** — a warrior present at t37 is gone at t38, killed off-screen.

  What it does *not* cover: war, any attitude change, any non-default game option, a third city, any city beyond pop 2, or a resumed save (`onLoadGame`).

## What to capture

- **From `turn_0000`**, not just a convenient mid-game stretch. Files are numbered for the turn *about to be played*, so a run starts at `turn_0000` — the state before turn 1, which is the snapshot the first-city decision is actually made from. There are no cities, no borders, and barely any revealed map, so the tooling gets its hardest test where the least data exists. Later turns then cover second-city-onward placement, which has ownership and existing cities as constraints.
- **Varied setups** — the `game` section's climate/sea-level/barbarian options change turn-1–20 advice more than almost anything else in the file, so runs that differ there are worth more than repeats of the same conditions.
- **A few representative runs, not everything played.** These are committed, and a run grows with the revealed map (~27KB/turn by turn 12). Keep the set small and deliberate.

## Curating a run

- **Don't assume turn numbers are contiguous.** A failed export is logged and skipped rather than crashing the game (see root `CLAUDE.md`), so a run can legitimately have a gap.
- **Order by filename, never by mtime.** Loading a save re-exports that turn over its existing file, so timestamps within a run aren't monotonic. Such a file is identifiable by `meta.trigger` reading `onLoadGame`.
- **Run the mtime check in `state/` *before* copying, and treat content continuity as the durable one.** Copying stamps every file within the same second, and git does not store mtimes anyway — a fresh clone restamps everything at checkout, so no amount of care preserving timestamps survives the thing samples exist for. Two signals do survive, both in the file contents: any `meta.trigger` of `onLoadGame`, which says a resume happened somewhere; and continuity of `knownTechs`, `score`, `culture` and city state from one turn to the next, which is what actually reveals how far an abandoned tail extends, since it branched off a different history. Treat an `onLoadGame` anywhere as the cue to check continuity hard.
- **Validate committed runs against `schema/state.schema.json` as a test**, not as a separate tool someone remembers to run. `mod/tests/` already validates the full document, but only against mocked `Cy*` objects — a real capture can violate the schema in ways the mocks never produce, and these files are the only real output under version control.
- **Check a run for divergent timelines before committing it.** The same overwrite behaviour means reloading an *older* save rewrites that turn while later files from the abandoned timeline stay behind — a folder that looks like one continuous game but isn't. Save-scumming a bad turn is enough to cause it. A run spanning two timelines will produce advice that contradicts itself in ways nothing in the data explains, so prune the stale tail (or discard the run) rather than committing it and debugging it later.

`mod/` writes live state per turn into `state/` (see its README); curating a run means copying a per-game folder from there into here under a purpose-describing name, after the checks above.
