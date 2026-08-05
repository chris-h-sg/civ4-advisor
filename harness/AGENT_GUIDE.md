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

**5. Check the XML; never recall a rule from memory.** Unit prerequisites, tech costs, building requirements, civics and difficulty modifiers live in the game's XML. **Use `rules.py` rather than grepping** — it resolves the right file, walks prerequisites transitively, and prices techs for this game's actual setup. A previous session asserted from memory that a Roman Archer implies Bronze Working; it implies **Archery** (Bronze Working is the Axeman). Confident, plausible, wrong.

If you must grep by hand, the install holds ~18 copies of each file. Take `<install>/Beyond the Sword/Assets/XML/...`, falling back to `<install>/Assets/XML/...` — an expansion only ships the files it *changes*, so resources (`CIV4BonusInfos.xml`) live only in the base tree. Install path is in `config.local.json`; don't `find`, it is slow and hits the mod copies. Use large context windows: `PrereqTech` sits ~90 lines into a unit block.

## Map orientation

**North is up. Higher `y` is north, higher `x` is east. (0,0) is the southwest corner.**

In testing, **ten out of ten agents got this backwards** while reading coordinates correctly — calling a northern neighbour "south". East/west was never wrong; only the `y` axis. Coordinates stayed right, so nothing looked wrong and the whole strategic picture came out mirrored.

**All three tools now state direction so you don't have to derive it.** The map grid is bracketed by `N ^ NORTH` above and `S v SOUTH` below; `run_history` prints a bearing beside every position (`16 NNW of Lisbon`); `render_map.py --view military` prints one beside every rival-unit sighting and every own-unit row. **Use those words rather than working it out from the numbers** — that derivation is the step that has failed every time. For any other pair of coordinates, use `bearing.py` rather than doing the arithmetic by hand.

The map usually wraps in `x` (`game.wrapX`) and never in `y`, so the short way east may be around the seam. The printed bearings and distances already account for it.

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
python harness/run_history.py <run-folder> [--view timeline|intel|lost] [--from N] [--to M] [--as-of N]
```

Takes the **run folder**, not one turn.

- **`timeline`** — what changed each turn: techs, cities, units gained and lost, contacts, sightings, tiles revealed, territory, resources unhidden. Unchanged turns are skipped. `--from`/`--to` scope it.
- **`intel`** — per rival: recent sightings with positions, then every unit type ever fielded with the turn first seen. Plus barbarian sightings, and what's standing in each of your cities.
- **`lost`** — every unit of yours that disappeared: its track, damage history, the tiles revealed on its final turn, and what was in sight beforehand. Reach for this whenever a unit dies.

**A unit's last exported position is usually not where it died** — it moves during the turn it is lost, and the export is the previous turn's snapshot. `lost` gives you that turn's revealed tiles as evidence: a unit sees radius 1 from flat ground, radius 2 from a hill, so the reveal shape constrains where it got to. That inference is yours.

**Nothing can tell you what killed it.** No combat log, and a killer on a fogged tile is invisible by construction. Rival units listed near a loss are what you could *see*, which is rarely the answer — say so rather than naming a plausible culprit.

**`[NON-COMBAT]`** on a city's occupants means combat strength 0 (settlers, workers, work boats). A city holding only those is undefended however occupied it looks.

`intel`'s two per-rival sections differ in how fast they go stale. **Recent sightings** are perishable — read them before moving anything vulnerable. **Ever fielded** is permanent: a type seen once is one they can build, forever. That's how you read their tech level — run each type through `rules.py unit`.

**Barbarians are listed apart from civs** (they imply nothing about anyone's tech) but with full positions, since early on they're the main threat.

Positions carry **distance and bearing from your nearest city**. When the walk differs from the straight line the walk leads — `14 TO WALK NW of Lisbon (6 straight)` — because that is the number you act on. On the baseline map nearly half of all walkable tiles diverge, and the worst reads 4 straight against 17 on foot. **Neither figure is turns**; terrain costs more. `render_map.py`'s site report uses the same measure for settler-to-site distance.

`timeline` also reports **rival territory the first time you see it**, which is often the earliest hard evidence of where a rival city is: a border implies a city within about two tiles, possibly beyond your revealed edge. And it lists the **coordinates** of small reveals, which is what lets you work out where an unseen event happened.

**`--as-of N` makes turn N the present**, discarding later files entirely. Only needed when replaying a finished run; live, the newest file already is now. It affects every view, unlike `--from`/`--to`, which scope `timeline` only. `intel` ignores them on purpose — truncating a dossier drops the earliest sighting of a type, which is the fact that proves the capability.

The tool **exits non-zero on a run that isn't one continuous game**. That's a real problem with the files, not something to work around.

### `rules.py` — anything about the game's rules

```
python harness/rules.py unit|tech|building|city|handicap [TYPE] <state.json> [--show-known] [--depth N]
```

**The state file is required, and not a formality:** game speed, world size and difficulty multiply tech costs, so a raw XML cost is 1.0–4.5× wrong. Pass the turn you're advising on and every number is priced for the real game.

| subcommand | what it answers |
|---|---|
| `unit UNIT_AXEMAN` | What does this unit need — tech, resources — and what does *that* tech need? Plus combat stats and everything else the same tech unlocks. |
| `tech TECH_MONARCHY` | What does this tech need, transitively, and **everything** it unlocks — units, buildings, civics, worker actions, resources revealed, and abilities like bridge-building. |
| `building BUILDING_PYRAMID` | Buildings and wonders: cost in hammers and turns *per city*, prerequisites, effects, and whether it's an ordinary building, a national wonder or one-per-world. |
| `city Lisbon` | What this city can build **right now**, and what is blocking the rest. Takes a city name, not a TYPE. |
| `handicap` | The barbarian and animal rules for this game's difficulty. Type defaults to the state file's own. |

**Reach for `city` before advising on production** — what to build next, or whether to switch. It is the only call that answers *what the options are*; the others answer questions about an option you have already named. Guessing type names to find out what exists is the failure it replaces.

It lists what is available now **and** what is one tech away, each blocked row carrying its reason — a resource needing a road, a city that is not coastal, a prerequisite building. Things further off are counted, not listed. **Rows are alphabetical and deliberately unranked**; which to build is your judgement.

**`available` means available *this turn*.** A tech you are researching is not one you have, so a row blocked on it says `RESEARCHING NOW, ~N turns left` — that is a wait, not a plan, and it is usually the most useful line in the block.

**Settlers and workers eat the city's food surplus**, so their estimates are marked `(+food, growth stops)`: the build lands sooner *and* the city stops growing while it does. That trade is yours to weigh. On a capture too old to carry the exported food/hammer split, a header line warns that the other estimates in that city run slightly fast while such a build is queued; if there is no such line, the numbers are exact.

**Reach for it whenever you're about to state a rule.** Especially after `intel` shows you a rival unit: `rules.py unit UNIT_ARCHER <state>` turns a sighting into a dated tech conclusion, which is the join `intel` deliberately refuses to make for you.

**Guessed a type name and got an error? Read the suggestions, don't fall back to grep.** Unique units are civ-prefixed and inconsistently so — the Praetorian is `UNIT_ROME_PRAETORIAN`, not `UNIT_PRAETORIAN`.

**Routes to a tech are printed all-in and never ranked**, in XML order rather than cost order. The cheaper one is not automatically the right one; that judgement is yours.

**A building's `EFFECTS` list is never the whole story**, so read `THE GAME'S OWN SUMMARY` beside it — many effects, especially wonders' signature abilities, live in the game's C++ with no data field, and that prose is the only place they are written down. Neither source subsumes the other: for the Pyramids the fields have the culture and team-sharing, the summary has the any-civic unlock. **Absence from both is still not proof**; say so rather than concluding from silence. A world wonder **already finished anywhere in the world** is reported as gone — but one that is merely unbuilt is still a race, because nothing shows you rival *production*. "Not built yet" and "available to you" are different claims.

**Resource prerequisites are resolved against your trade network**, not just the map — `CONNECTED` means you can build the thing today, and where a resource is visible but unusable the tool names which of borders / improvement / road is missing. A resource you cannot see yet is a different answer again: `NOT YET REVEALED` means zero visible is evidence of nothing either way.

Prerequisites you already have are hidden — `--show-known` restores them. Every block prints its source as `file:line`, states what it omits, and attaches its own caveats to the numbers. Read those in place; they are not repeated here.

### `bearing.py` — direction and distance between two arbitrary tiles

```
python harness/bearing.py X1,Y1 X2,Y2 <state.json>
```

For pairs neither other tool covers — your scout versus a moving rival, a settle candidate versus a rival city seen ten turns ago. Takes a state file for `mapWidth`/`wrapX`, same wrap handling as the other tools. Prints straight-line compass and distance, plus land-route distance when it differs (or `NO LAND ROUTE` when none exists over revealed tiles).

### What needs no tool

Reading the JSON directly. Filtering units, comparing city yields, checking research all work fine unaided. There's deliberately no query tool — wanting one is the signal to just read the file.

## How to answer

**Separate observation, inference and guess, and label which is which.** "Two Archers were in Rome on t26" is observation. "Rome had Archery by t26" is inference from the XML. "Rome may be going for Praetorians" is a guess.

**State your confidence and what would change it** — the player can look at things you can't.

**Never manufacture a cause for something you can't see.** If a unit died with no hostile in sight, say something killed it off-screen and you can't tell what. In testing an agent built a mechanism out of two unrelated timeline lines that happened to sit near each other.

**Reachability before alarm.** `intel` counts what's standing in each city — a count, not a verdict. What matters is what can actually *reach* it: a threat across water is a different kind of threat, not a nearer one, and a city on an open land approach may be exposed even with a defender in it. Barbarians also need unowned, unwatched land to spawn in. Say which case it is, and don't call the player safe just because a count looks fine.

**Land distances are the best *known* route.** Computed over revealed tiles only, never routed through fog — so an unrevealed shortcut could make one shorter, never longer.

**One strong tile usually decides an early city site, not a total** — a city works `pop + 1` tiles. Yields shown are *displayed* yields, so an improved tile reports its improved number, flattering sites that overlap land you've already developed.

## Tell us what's missing

**When a tool would have helped and didn't, say so at the end of your answer.** This is the main evidence for what gets built next; the current set is a starting guess.

Worth reporting: you read many turn files to answer one question; you derived the same thing by hand more than once; output was ambiguous or you read it twice; you wanted a view or flag that doesn't exist; something misled you, even briefly. Be specific about which call and what you wanted instead.
