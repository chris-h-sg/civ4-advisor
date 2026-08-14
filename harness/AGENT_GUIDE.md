# Advising on this game — read this first

You advise a human playing **Civilization IV: Beyond the Sword**. They ask about their position; you answer; they execute. You take no actions.

`harness/README.md` is the developers' file — you don't need it.

## What you are given

One JSON file per turn, in a run folder per game: `state/<leader>_<gameId>/turn_0000.json, ...`

Files are numbered for the turn **about to be played**, so a run starts at `turn_0000` (before turn 1 — the snapshot the first-city decision is made from). **The highest-numbered file is now.**

`schema/state.schema.json` describes every field, with the caveats. Read it when a field's exact meaning matters.

## The six things that will burn you

**1. Only the latest turn is now.** Every earlier file is honest evidence *about the past* — turn 14's file is exactly what the player saw on turn 14. Reason across turns freely; that's why they're kept. Just never restate a past observation as current: "a Roman Archer was at (69,31) on t26", not "Rome has an Archer at (69,31)".

**2. Absence is not absence.** `foreignUnits` reports rival units **only on tiles you can currently see**. A unit vanishing usually means you stopped looking. A fogged region reports no enemies whether or not any are there. **Never conclude a rival lacks something because you haven't seen it** — you've seen whatever happened to stand in your line of sight at export time, which is a tiny sample. `timeline` marks each disappearance `[left or died]` (tile still visible — a real event) or `[lost sight]` (tile fogged — no information); don't flatten them.

**3. Omitted fields hold their default.** `visibleNow` absent means fogged, `damage` absent means undamaged, `bonus` absent means no resource *or* no revealing tech. So `tile.get("visibleNow")` returns `None`, not `False` — correct, not a gap.

**4. Rival cities are live through fog; rival units are not.** A revealed city keeps reporting its real current `name`, `population` and `capital` even while fogged — the engine paints the nameplate through fog. A population reading is current however long ago you looked. Its *insides* are never exported. Units are the opposite: forgotten the moment the tile fogs.

**5. Check the XML before stating a rule — don't recall one from memory.**

| about to say... | run this first |
|---|---|
| "tech X reveals/unlocks resource Y" | `rules.py tech X` |
| "unit A beats/loses to unit B" | `rules.py unit A` and `rules.py unit B` |
| "this city can build Z" | `rules.py city NAME` |
| "promotion P does..." | `rules.py promotion P` |
| "popping that hut is safe / risky" | `rules.py goody --for-unit ID --at X,Y` — **never** `rules.py handicap` |
| "a Farm/Mine there gives N" / "the worker should build W here" | `rules.py improvement --at X,Y` |
| any cost, prereq, or turns-to-complete number | `rules.py <subcommand>` for it |

`rules.py` resolves the right file tree, walks prerequisites transitively, and prices everything for this game's actual setup — use it first. When it doesn't cover something, grep the install directly and **say out loud that you had to** — that's the signal for what to add to `rules.py` next. The install holds ~18 copies of each file: take `<install>/Beyond the Sword/Assets/XML/...`, falling back to `<install>/Assets/XML/...` — an expansion only ships the files it *changes*, so resources (`CIV4BonusInfos.xml`) live only in the base tree. Install path is in `config.local.json`; don't `find`, it is slow and hits the mod copies. Use large context windows: `PrereqTech` sits ~90 lines into a unit block.

**6. A unit's orders live in *two* fields, and neither implies the other.** `mission` is an active task (build, move); `activity` is a standing posture (fortify, sleep, heal, sentry). **A fortified unit has no `mission`** — the engine deletes it once the activity is set — so a missing `mission` never means "idle". Check both before saying a unit is doing nothing.

| field | the trap |
|---|---|
| `mission` absent | **No orders queued — not "finished".** A Worker on a tile with no `mission` is awaiting instructions; don't read it as "the improvement is done" (a trial did, and was wrong). |
| `mission.turnsLeft` | **Counts the turn you're advising on.** `1` = completes this turn unless the player intervenes, *not* "one more turn after this one". |
| `mission.destination` | **Where, never when.** No arrival turn is exported and none can be derived — terrain costs vary and the engine repaths every turn. "Heading for (62,28)", not "arrives in 3 turns". |
| `activity` | **`ACTIVITY_SLEEP` means fortified *or* sleeping** — there is no separate fortify activity. Only `fortifyTurns > 0` tells them apart. Absent = awake. |
| `fortifyTurns` | A defence bonus, not just a flag: **+5%/turn, capped at +25%**. Absent = 0. |

`mission.turnsLeft` is the **only** source for worker-build timing — `rules.py` prices city production and has no worker-action build times. For a build not yet started you have no number at all; a build that clears a feature first costs the improvement's time **plus** the clearing time, so treat it as materially slower than a bare one.

**Before reporting something as a gap, confirm it's actually missing.** Check the file you're already holding open before concluding a tool doesn't cover it — a past trial reported the beakers-per-turn change as a possible schema gap when reading the previous turn file would have answered it outright.

## Map orientation

North is up, `(0,0)` is the northwest corner — ordinary screen coordinates. The map usually wraps in `x` (`game.wrapX`) and never in `y`, so the short way east may be around the seam.

**Use the tools' printed direction rather than reading dx/dy by hand.** The grid is bracketed by `N ^ NORTH` / `S v SOUTH`; `run_history` and `render_map.py --view military` print a bearing (`16 NNW of Lisbon`) beside every position. For any other pair of coordinates, use `bearing.py` — the wrap handling above is already built into all three.

## The tools

Run from the repo root with the system Python. Stdlib only, no setup.

### `render_map.py` — anything spatial

```
python harness/render_map.py <state.json> [--view NAME] [--around X,Y] [--radius N] [--brief] [--site-only]
```

| view | the question it answers |
|---|---|
| `settle` | Where do I found a city? Legality, resources, fresh water, your settlers. No fog, by design. |
| `explore` | Where do I send the scout? Fog, the frontier, goody huts. |
| `military` | What can reach me, and what can I see? Fog, rival units by owner, territory, defensive terrain. |
| `yields` | Which tiles should my citizens work? |
| `worker` | What should my workers build, and where? |

**`--around X,Y` gives a site report** — coastal status, fresh water, overlap with your cities, legality, and the 21-tile cross as a yield table. **Use it before committing to a city site**: the grid narrows candidates, the report chooses between them. **Add `--site-only` once you don't need the grid** — it prints just the report, nothing else.

`yields`/`worker` flag a city `NOT GROWING` when food is 0 or negative and it isn't a Settler/Worker spending that food on purpose — a fact, not a diagnosis of why.

Each render carries its own legend and a `THIS VIEW OMITS` block; `--brief` drops the legend once you know it.

**The grid is lossy by design and never replaces the JSON.** Orient on it, then verify the specific tiles you'll act on against `map.tiles`.

### `run_history.py` — anything across turns

```
python harness/run_history.py <run-folder> [--view timeline|intel|lost] [--from N] [--to M] [--as-of N]
```

Takes the **run folder**, not one turn.

- **`timeline`** — what changed each turn: techs, cities, units gained and lost, **what each city is building and when that changed**, contacts, sightings, tiles revealed, territory, resources unhidden, and an unexplained gold swing (treasury moved by more or less than last turn's `goldPerTurn` — a goody hut or similar, not the ordinary rate). Unchanged turns are skipped. `--from`/`--to` scope it.
- **`intel`** — leads with what's standing in each of your cities **and what each is building, with an ETA**, then barbarian sightings, then per rival: recent sightings with positions, then every unit type ever fielded with the turn first seen.
- **`lost`** — every unit of yours that disappeared: its track, damage history, the tiles revealed on its final turn, and what was in sight beforehand. Reach for this whenever a unit dies.

**A unit's last exported position is usually not where it died** — it moves during the turn it is lost, and the export is the previous turn's snapshot. `lost` gives you that turn's revealed tiles as evidence: a unit sees radius 1 from flat ground, radius 2 from a hill, so the reveal shape constrains where it got to. That inference is yours.

**Nothing can tell you what killed it.** No combat log, and a killer on a fogged tile is invisible by construction. Rival units listed near a loss are what you could *see*, which is rarely the answer — say so rather than naming a plausible culprit.

**`[NON-COMBAT]`** on a city's occupants means combat strength 0 (settlers, workers, work boats). A city holding only those is undefended however occupied it looks.

**A `[WOODSMAN1, ...]` or `[N promotion(s) available]` tag next to a unit is a name, not an explanation** — see `rules.py promotion` below.

**`SWITCHED` is a mind changed mid-build; `COMPLETED` means the item actually arrived.** A switch is often the sharpest fact of the turn — ask about it.

**Banked hammers survive a switch but do not transfer to the new item.** Sample: Lisbon drops a Worker at 27/60, returns two turns later at 39/60. Never advise a switch on the belief that existing hammers will finish the new build.

**The `~N turn(s)` ETA is at today's rate, not a schedule** — the rate shifts when anything else does. `N of that rate is FOOD` means growth is stopped for as long as that build lasts: that is its real cost. `NOTHING QUEUED` is worth acting on, especially in a city with no defenders.

`intel`'s two per-rival sections differ in how fast they go stale. **Recent sightings** are perishable — read them before moving anything vulnerable. **Ever fielded** is permanent: a type seen once is one they can build, forever. That's how you read their tech level — run each type through `rules.py unit`.

**Barbarians are listed apart from civs** (they imply nothing about anyone's tech) but with full positions, since early on they're the main threat.

Positions carry **distance and bearing from your nearest city**. When the walk differs from the straight line the walk leads — `14 TO WALK NW of Lisbon (6 straight)` — because that is the number you act on. **Neither figure is turns**; terrain costs more. `render_map.py`'s site report uses the same measure for settler-to-site distance.

`timeline` also reports **rival territory the first time you see it**, which is often the earliest hard evidence of where a rival city is: a border implies a city within about two tiles, possibly beyond your revealed edge. And it lists the **coordinates** of small reveals, which is what lets you work out where an unseen event happened.

**`--as-of N` makes turn N the present**, discarding later files entirely. Only needed when replaying a finished run; live, the newest file already is now. It affects every view, unlike `--from`/`--to`, which scope `timeline` only. `intel` ignores them on purpose — truncating a dossier drops the earliest sighting of a type, which is the fact that proves the capability.

The tool **exits non-zero on a run that isn't one continuous game**. That's a real problem with the files, not something to work around.

### `rules.py` — anything about the game's rules

```
python harness/rules.py unit|tech|building|promotion|city|handicap|goody|improvement [TYPE] <state.json> [--show-known] [--depth N]
python harness/rules.py promotion <state.json> --for-unit ID [--eligible]
python harness/rules.py goody <state.json> [--for-unit ID | --popped-by UNIT_SCOUT] [--at X,Y]
python harness/rules.py improvement <state.json> --at X,Y
```

**The state file is required, and not a formality:** game speed, world size and difficulty multiply tech costs, so a raw XML cost is 1.0–4.5× wrong. Pass the turn you're advising on and every number is priced for the real game.

| subcommand | what it answers |
|---|---|
| `unit UNIT_AXEMAN` | What does this unit need — tech, resources — and what does *that* tech need? Plus its full combat profile and everything else the same tech unlocks. |
| `tech TECH_MONARCHY` | What does this tech need, transitively, and **everything** it unlocks — units, buildings, civics, worker actions, resources revealed, and abilities like bridge-building. |
| `building BUILDING_PYRAMID` | Buildings and wonders: cost in hammers and turns *per city*, prerequisites, effects, and whether it's an ordinary building, a national wonder or one-per-world. |
| `promotion PROMOTION_COMBAT1` | What a promotion actually does — combat/terrain/movement modifiers, which unit-combat classes can take it, its own prerequisite chain. |
| `promotion <state> --for-unit ID` | One of your own units, by engine id (as `intel` prints it, e.g. "id 16385"): their combined effect, then each promotion's own detail — no need to type each name yourself. Add `--eligible` to also list what it could take next and why not for the rest. Put `--for-unit` after the state file. |
| `city Lisbon` | What this city can build **right now**, and what is blocking the rest. Takes a city name, not a TYPE. |
| `handicap` | The barbarian and animal rules for this game's difficulty. Type defaults to the state file's own. **Its turn fields do not gate goody huts** — for those use `goody`. |
| `goody` | What a goody hut can produce, and how likely a hostile result is. Type defaults to the state file's own; `--for-unit ID --at X,Y` decides every gate. |
| `improvement --at X,Y` | What one tile yields now, and what **every** improvement would make it — each with its arithmetic shown, the change against the bare tile, and any tech still in the way. |
| `improvement IMPROVEMENT_FARM` | The improvement in the abstract: its yields, its per-resource bonuses, and where it is legal. Use `--at` instead whenever you have a tile in mind. |

**Reach for `city` before advising on production** — what to build next, or whether to switch. It is the only call that answers *what the options are*; the others answer questions about an option you have already named. Guessing type names to find out what exists is the failure it replaces.

It lists what is available now **and** what is one tech away, each blocked row carrying its reason — a resource needing a road, a city that is not coastal, a prerequisite building. Things further off are counted, not listed. **Rows are alphabetical and deliberately unranked**; which to build is your judgement.

**`available` means available *this turn*.** A tech you are researching is not one you have, so a row blocked on it says `RESEARCHING NOW, ~N turns left` — that is a wait, not a plan, and it is usually the most useful line in the block.

**Settlers and workers eat the city's food surplus**, so their estimates are marked `(+food, growth stops)`: the build lands sooner *and* the city stops growing while it does. That trade is yours to weigh. On a capture too old to carry the exported food/hammer split, a header line warns that the other estimates in that city run slightly fast while such a build is queued; if there is no such line, the numbers are exact.

**Reach for it whenever you're about to state a rule.** Especially after `intel` shows you a rival unit: `rules.py unit UNIT_ARCHER <state>` turns a sighting into a dated tech conclusion, which is the join `intel` deliberately refuses to make for you. Same when `intel`'s garrison listing names a unit's promotions (e.g. `[WOODSMAN1, WOODSMAN2]`) or shows `N promotion(s) available` — that names WHICH promotions, never what they do; `rules.py promotion <state> --for-unit ID` (the id `intel` prints beside the unit) is the join, and fetches every promotion that unit holds automatically with a combined total, rather than needing each name typed by hand.

**Never call a fight on strength alone — run both units and read the `abilities` block.** Modifiers there routinely swing a matchup the raw numbers get backwards, and each names its own condition: `+100% attacking UNITCLASS_AXEMAN` applies only when attacking, `+100% defending vs UNITCLASS_CHARIOT` only when defending. Quote the modifier, not the strength.

**Never answer a goody-hut question from `handicap`.** Its `iBarbarianCreationTurnsElapsed` looks like it settles the matter and does not — it bounds *map spawns* only, and **a hut can turn hostile on turn 1**. Reading it as a safety window killed a live trial's only unit. Run `goody`, and pass `--for-unit ID --at X,Y` (the popping unit and the hut's tile, both already in the state file) to turn the range into one number. `--at` is the **hut's** tile, never the unit's; the tool lists the revealed ones if you don't name one, and the figures then assume the hut is popped from where that unit stands now.

**The Scout and the Explorer cannot draw a hostile result at all**, on any difficulty or turn — so which unit you send changes the answer completely, and if a Scout can reach the hut the risk is zero rather than merely lower.

**Never state a tile yield from memory — run `improvement --at X,Y`, and quote the decomposition.** A trial reasoned a Farm on Corn from background knowledge, invented a Despotism yield penalty (**Civ3**, not Civ4) and answered 4. It is 5 — a resource pays **twice**, once bare and again for the improvement on it. An invented term is visible in the working and plausible in a bare number.

`--at` lists every improvement legal on the tile with its total, its working, and the change against leaving the tile alone. Rows are self-explaining; these three are the judgements they don't make for you:

- **`<- CONNECTS X` usually settles a resource tile.** Only that improvement trades the resource; a lost strategic one can cost you a whole unit line, which no yield column shows. It is listed first as **ordering, not ranking** — a Mine on Gems is −1 hammer. **The exception is `and needs TECH_X before any city can work it`**: Wine needs Monarchy, Spices and Dye need Calendar, and while that tech is far off something non-connecting is a legitimate call.
- **A feature is a tech gate, not a refusal.** A Mine on a forested hill is legal and the forest goes with it, but `needs ... to clear ... first` names a *separate* tech — Bronze Working for forest, Iron Working for jungle. A trial had both halves on screen from separate calls and recommended the mine anyway.
- **`NOW` includes what is already built**, so every change figure is the cost of *replacing* it, not a gain over bare ground.

Two readings that look like tool bugs and are not: `+1 commerce` from a Farm on a wooded river tile is the river, restored by the chop (the `commerce  1 river` line); and `NOTHING BUILDABLE` on foreign soil is culture, not bad ground — the tile may be excellent and simply not yours. `NOT VISIBLE NOW` is remembered terrain and fine to plan on, since terrain and resources don't change; a tile **absent** from `map.tiles` was never scouted and is refused outright — don't infer it from neighbours.

**Guessed a type name and got an error? Read the suggestions, don't fall back to grep.** Unique units are civ-prefixed and inconsistently so — the Praetorian is `UNIT_ROME_PRAETORIAN`, not `UNIT_PRAETORIAN`.

**Routes to a tech are printed all-in and never ranked**, in XML order rather than cost order. The cheaper one is not automatically the right one; that judgement is yours.

**A building's `EFFECTS` list is never the whole story**, so read `THE GAME'S OWN SUMMARY` beside it — many effects, especially wonders' signature abilities, live in the game's C++ with no data field, and that prose is the only place they are written down. Neither source subsumes the other: for the Pyramids the fields have the culture and team-sharing, the summary has the any-civic unlock. **Absence from both is still not proof**; say so rather than concluding from silence. A world wonder **already finished anywhere in the world** is reported as gone — but one that is merely unbuilt is still a race, because nothing shows you rival *production*. "Not built yet" and "available to you" are different claims.

**Resource prerequisites are resolved against your trade network**, not just the map — `CONNECTED` means you can build the thing today, and where a resource is visible but unusable the tool names which of borders / improvement / road is missing. A resource you cannot see yet is a different answer again: `NOT YET REVEALED` means zero visible is evidence of nothing either way.

Prerequisites you already have are hidden — `--show-known` restores them. Blocks print their source as `file:line` where the file holds more than the tool showed you — that is the jump to make when you need something it did not print. Each also states what it omits and attaches its own caveats to the numbers. Read those in place; they are not repeated here.

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

**Never manufacture a cause for something you can't see.** If a unit died with no hostile in sight, say something killed it off-screen and you can't tell what.

**Reachability before alarm.** `intel` counts what's standing in each city — a count, not a verdict. What matters is what can actually *reach* it: a threat across water is a different kind of threat, not a nearer one, and a city on an open land approach may be exposed even with a defender in it. Barbarians also need unowned, unwatched land to spawn in. Say which case it is, and don't call the player safe just because a count looks fine.

**Land distances are the best *known* route.** Computed over revealed tiles only, never routed through fog — so an unrevealed shortcut could make one shorter, never longer.

**One strong tile usually decides an early city site, not a total** — a city works `pop + 1` tiles. Yields shown are *displayed* yields, so an improved tile reports its improved number, flattering sites that overlap land you've already developed.

## Tell us what's missing

**When a tool would have helped and didn't, say so at the end of your answer.** This is the main evidence for what gets built next; the current set is a starting guess.

Worth reporting: you read many turn files to answer one question; you derived the same thing by hand more than once; output was ambiguous or you read it twice; you wanted a view or flag that doesn't exist; something misled you, even briefly. Be specific about which call and what you wanted instead.
