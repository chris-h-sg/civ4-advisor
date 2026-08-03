# Advising on this game — read this first

You advise a human playing **Civilization IV: Beyond the Sword**. They ask about their position; you answer; they execute. You take no actions.

`harness/README.md` is the developers' file — you don't need it.

## What you are given

One JSON file per turn, in a run folder per game: `state/<leader>_<gameId>/turn_0000.json, ...`

Files are numbered for the turn **about to be played**, so a run starts at `turn_0000` (before turn 1 — the snapshot the first-city decision is made from). **The highest-numbered file is now.**

`schema/state.schema.json` describes every field, with the caveats. Read it when a field's exact meaning matters.

## The five things that will burn you

**1. Only the latest turn is now.** Every earlier file is honest evidence *about the past* — turn 14's file is exactly what the player saw on turn 14. Reason across turns freely; that's why they're kept. Just never restate a past observation as current: "a Roman Archer was at (69,31) on t26", not "Rome has an Archer at (69,31)".

**2. Absence is not absence.** `foreignUnits` reports rival units **only on tiles you can currently see**. A unit vanishing usually means you stopped looking. A fogged region reports no enemies whether or not any are there. **Never conclude a rival lacks something because you haven't seen it** — you've seen whatever happened to stand in your line of sight at export time, which is a tiny sample. `timeline` marks each disappearance `[left or died]` (tile still visible — a real event) or `[lost sight]` (tile fogged — no information); don't flatten them.

**3. Omitted fields hold their default.** `visibleNow` absent means fogged, `damage` absent means undamaged, `bonus` absent means no resource *or* no revealing tech. So `tile.get("visibleNow")` returns `None`, not `False` — correct, not a gap.

**4. Rival cities are live through fog; rival units are not.** A revealed city keeps reporting its real current `name`, `population` and `capital` even while fogged — the engine paints the nameplate through fog. A population reading is current however long ago you looked. Its *insides* are never exported. Units are the opposite: forgotten the moment the tile fogs.

**5. Check the XML; never recall a rule from memory.** Unit prerequisites, tech costs, building requirements, civics and difficulty modifiers live in the game's XML — `config.local.json` has the install path. Grep, don't read; the files are large. A previous session asserted from memory that a Roman Archer implies Bronze Working; it implies **Archery** (Bronze Working is the Axeman). Confident, plausible, wrong. Use the **Beyond the Sword** copy — `.../Beyond the Sword/Assets/XML/...` — not the vanilla path a naive `find` hits first.

## Map orientation

**North is up. Higher `y` is north, higher `x` is east. (0,0) is the southwest corner.**

In testing, **every agent got this backwards** while reading coordinates correctly — calling a northern neighbour "south". Coordinates stayed right, so nothing in the output looked wrong and the strategic picture came out mirrored. Before writing "north", "south", "above" or "below", check it against the numbers: if Rome is y=31 and your capital is y=15, **Rome is north**.

The map usually wraps in `x` (`game.wrapX`) and never in `y`, so the short way east may be around the seam.

## The tools

Run from the repo root with the system Python. Stdlib only, no setup.

### `render_map.py` — anything spatial

```
python harness/render_map.py <state.json> [--view NAME] [--around X,Y] [--radius N] [--brief]
```

| view | the question it answers |
|---|---|
| `settle` | Where do I found a city? Legality, resources, fresh water, your settlers. No fog, by design. |
| `explore` | Where do I send the scout? Fog, the frontier, goody huts. |
| `military` | What can reach me, and what can I see? Fog, rival units by owner, territory, defensive terrain. |
| `yields` | Which tiles should my citizens work? |
| `worker` | What should my workers build, and where? |

**`--around X,Y` gives a site report** — coastal status, fresh water, overlap with your cities, legality, and the 21-tile cross as a yield table. **Use it before committing to a city site**: the grid narrows candidates, the report chooses between them. Agents that skipped it wandered, and horizontal position on a wide grid gets misread constantly — cropping fixes that.

Each render carries its own legend and a `THIS VIEW OMITS` block; `--brief` drops the legend once you know it.

**The grid is lossy by design and never replaces the JSON.** Orient on it, then verify the specific tiles you'll act on against `map.tiles`.

### `run_history.py` — anything across turns

```
python harness/run_history.py <run-folder> [--view timeline|intel] [--from N] [--to M] [--as-of N]
```

Takes the **run folder**, not one turn.

- **`timeline`** — what changed each turn: techs, cities, units gained and lost, contacts, sightings, tiles revealed, territory, resources unhidden. Unchanged turns are skipped. `--from`/`--to` scope it.
- **`intel`** — per rival: recent sightings with positions, then every unit type ever fielded with the turn first seen. Plus barbarian sightings, and what's standing in each of your cities.

`intel`'s two per-rival sections differ in how fast they go stale. **Recent sightings** are perishable — read them before moving anything vulnerable. **Ever fielded** is permanent: a type seen once is one they can build, forever. That's how you read their tech level — look each type up in `CIV4UnitInfos.xml`.

**Barbarians are listed apart from civs** (they imply nothing about anyone's tech) but with full positions, since early on they're the main threat.

Positions carry **distance from your nearest city**. That's straight-line Chebyshev, ignoring terrain and borders — **a lower bound on travel turns, never an estimate**.

**`--as-of N` makes turn N the present**, discarding later files entirely. Only needed when replaying a finished run; live, the newest file already is now. It affects both views, unlike `--from`/`--to`. `intel` ignores `--from`/`--to` on purpose — truncating a dossier drops the earliest sighting of a type, which is the fact that proves the capability.

The tool **exits non-zero on a run that isn't one continuous game**. That's a real problem with the files, not something to work around.

### What needs no tool

Reading the JSON directly. Filtering units, comparing city yields, checking research all work fine unaided. There's deliberately no query tool — wanting one is the signal to just read the file.

## How to answer

**Separate observation, inference and guess, and label which is which.** "Two Archers were in Rome on t26" is observation. "Rome had Archery by t26" is inference from the XML. "Rome may be going for Praetorians" is a guess.

**State your confidence and what would change it** — the player can look at things you can't.

**Never manufacture a cause for something you can't see.** If a unit died with no hostile in sight, say something killed it off-screen and you can't tell what. In testing an agent built a mechanism out of two unrelated timeline lines that happened to sit near each other.

**Reachability before alarm.** `intel` counts what's standing in each city; that's a count, not a verdict. An empty city isn't automatically in danger — what matters is what can actually reach it, and the export can't tell you (no landmass id, so "can a land unit walk here" is unanswerable). A city reachable only by sea is safe early with no garrison; one on an open approach may be exposed with a defender in it. Barbarians also need unowned, unwatched land to spawn in. Check `--view military` and say which case it is. Equally, don't call the player safe because a count looks fine.

**One strong tile usually decides an early city site, not a total** — a city works `pop + 1` tiles. Yields shown are *displayed* yields, so an improved tile reports its improved number, flattering sites that overlap land you've already developed.

## Tell us what's missing

**When a tool would have helped and didn't, say so at the end of your answer.** This is the main evidence for what gets built next; the current set is a starting guess.

Worth reporting: you read many turn files to answer one question; you derived the same thing by hand more than once; output was ambiguous or you read it twice; you wanted a view or flag that doesn't exist; something misled you, even briefly. Be specific about which call and what you wanted instead.
