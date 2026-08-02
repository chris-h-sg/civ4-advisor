# samples/

Real state JSON captured by `mod/` while playing actual turns in-game. Used as static input to develop and test `harness/` without needing Civ IV running.

Not synthetic fixtures — these come from real play sessions and should reflect what the mod actually produces.

## A sample is a run, not a turn

One sample = one folder of consecutive `turn_NNNN.json` files, copied out of `state/`. That's what the mod naturally produces now that it keeps per-game history, and the sequence is the point: some reasoning only works across turns.

The clearest case is inferring what a rival has. Each snapshot is deliberately forgetful — `foreignUnits` only reports units on currently-visible tiles, so a rival Axeman spotted on turn 14 is simply gone from turn 15. Across the run it's still there to be found, and spotting it at all implies Bronze Working. Same for tracking rival city growth and border expansion. A single-turn sample cannot exercise any of that.

Each file carries its own `game` setup section (difficulty, climate, sea level, options), so a run documents its own conditions — no separate metadata file needed.

## What to capture

- **From `turn_0000`**, not just a convenient mid-game stretch. Files are numbered for the turn *about to be played*, so a run starts at `turn_0000` — the state before turn 1, which is the snapshot the first-city decision is actually made from. There are no cities, no borders, and barely any revealed map, so the tooling gets its hardest test where the least data exists. Later turns then cover second-city-onward placement, which has ownership and existing cities as constraints.
- **Varied setups** — the `game` section's climate/sea-level/barbarian options change turn-1–20 advice more than almost anything else in the file, so runs that differ there are worth more than repeats of the same conditions.
- **A few representative runs, not everything played.** These are committed, and a run grows with the revealed map (~27KB/turn by turn 12). Keep the set small and deliberate.

## Curating a run

- **Don't assume turn numbers are contiguous.** A failed export is logged and skipped rather than crashing the game (see root `CLAUDE.md`), so a run can legitimately have a gap.
- **Order by filename, never by mtime.** Loading a save re-exports that turn over its existing file, so timestamps within a run aren't monotonic. Such a file is identifiable by `meta.trigger` reading `onLoadGame`.
- **Validate committed runs against `schema/state.schema.json` as a test**, not as a separate tool someone remembers to run. `mod/tests/` already validates the full document, but only against mocked `Cy*` objects — a real capture can violate the schema in ways the mocks never produce, and these files are the only real output under version control.
- **Check a run for divergent timelines before committing it.** The same overwrite behaviour means reloading an *older* save rewrites that turn while later files from the abandoned timeline stay behind — a folder that looks like one continuous game but isn't. Save-scumming a bad turn is enough to cause it. A run spanning two timelines will produce advice that contradicts itself in ways nothing in the data explains, so prune the stale tail (or discard the run) rather than committing it and debugging it later.

Empty for now — `mod/` writes live state per turn into `state/` (see its README), but no runs have been copied in here as curated samples yet.
