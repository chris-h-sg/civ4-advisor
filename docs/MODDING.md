# Notes from writing a state exporter for BTS

This is the game-side half of [civ4-advisor](../README.md), a project that has an AI read your position each turn and advise you on it. The mod half has nothing to do with the AI: it hooks the turn cycle and writes a JSON snapshot of what the player can see to disk. Anyone writing an exporter, a logger, a stats tracker or any external tool hits the same walls, so these notes are about those.

What follows is what worked for me and how I established it. Several conclusions are the kind that look settled until someone who has been doing this for fifteen years points at the obvious thing I missed. One of them ([§3](#3-export-timing-makes-a-class-of-getters-stale)) is a straight contradiction I could not resolve. Corrections, better approaches and "you know there's a thread about that" are all very welcome.

Background reading I leaned on is in [`REFERENCES.md`](../REFERENCES.md) — the BUG Python API reference, the Modiki pages on `CvEventInterface`/`CvEventManager`, TGA's Python tutorial.

## 1. What the mod does

Three event hooks, one JSON file per turn, into a per-game folder. It reads state, writes a file, returns. It is wrapped so that no failure inside it can take the game down; a failed export logs a traceback and leaves no file, which is deliberately distinguishable from a stale file left looking current.

Event logic is in a `CvCustomEventManager` subclassing the base `CvEventManager`, with only the import and instantiation changed at the top of `CvEventInterface.py`.

<details>
<summary>What comes out — excerpts from one real turn</summary>

Turn 34 of a game, exported the moment the player regains control: a settler has just been completed and needs somewhere to go. Pretty-printed with sorted keys, because the file gets read by eye against the game UI and consecutive turns have to diff cleanly.

```jsonc
{
  "cities": [
    {
      "bonuses": {"happiness": [], "health": ["BONUS_COW", "BONUS_WHEAT"], "strategic": []},
      "buildings": ["BUILDING_PALACE"],
      "coastal": false,
      "culture": 68,
      "food": 16,
      "foodPerTurn": 5,
      "growthThreshold": 22,
      "name": "Lisbon",
      "population": 1,
      "producing": null,
      "productionFromFood": 0,
      "productionFromHammers": 5,
      "productionNeeded": null,
      "productionPerTurn": 5,
      "workedTiles": [[75, 36], [76, 35]],
      "x": 75,
      "y": 36
    }
  ],
```

`producing` is `null` because the settler finished on the turn that just ended and nothing has been queued behind it yet — this snapshot is taken before the player has touched anything. `productionNeeded` is `null` for the same reason: the engine reports `MAX_INT` for an empty queue, which is not a number worth passing on.

Units carry what they are, where they are, and how far they can move. `moves` is moves *per turn*, not moves remaining — the engine resets the remaining count after this hook fires, so reading it here would report the round that just ended ([§3](#3-export-timing-makes-a-class-of-getters-stale)).

```jsonc
  "units": [
    {"id": 16385, "moves": 1, "type": "UNIT_WARRIOR", "x": 68, "y": 30},
    {"id": 24576, "moves": 1, "type": "UNIT_WARRIOR", "x": 78, "y": 39},
    {"id": 32770, "moves": 2, "type": "UNIT_WORKER", "x": 75, "y": 34},
    {"id": 40963, "moves": 2, "type": "UNIT_SETTLER", "x": 75, "y": 36}
  ],
```

Map tiles are one object per line, leading with `x`/`y`, with every default-valued field omitted — 246 revealed tiles here, of which 95 are currently visible. These four are the ground the settler is being sent to:

```jsonc
  "map": {
    "tiles": [
      ...
      {"x": 77, "y": 38, "bonus": "BONUS_STONE", "terrain": "TERRAIN_PLAINS", "visibleNow": true, "yields": [1, 2, 0]},
      {"x": 78, "y": 38, "terrain": "TERRAIN_PLAINS", "visibleNow": true, "yields": [1, 1, 0]},
      {"x": 79, "y": 38, "terrain": "TERRAIN_GRASS", "visibleNow": true, "yields": [2, 0, 0]},
      {"x": 79, "y": 37, "bonus": "BONUS_HORSE", "terrain": "TERRAIN_PLAINS", "yields": [1, 2, 0]},
      ...
    ]
  },
  "meta": {"schemaVersion": 2, "trigger": "onEndGameTurn"},
```

**The last of those four tiles is the point of the whole exercise.** It has no `visibleNow`, while its three neighbours do — nobody is looking at the horse right now, so what the file reports is what the player last saw there, not what is there. The export never fills that gap in, and the advice built on this turn carries the caveat out to the player: re-check the site on arrival, because the coast is still partly fogged.

</details>

## 2. No hook fires during your turn

`onBeginPlayerTurn` and `onEndPlayerTurn` do not bound the player's interactive turn, despite the names. Measured by instrumenting every hook and watching the log:

1. You click **End Turn**.
2. `onBeginPlayerTurn(N, you)` then `onEndPlayerTurn(N, you)` fire back-to-back — `N` being the turn just concluded, no offset.
3. The same pair fires for every AI civ, in player-ID order.
4. `onBeginGameTurn(N)` then `onEndGameTurn(N)`.
5. You silently get control for turn N+1, with no hook firing at all.

**How it's solved here:** export from `onGameStart`, `onLoadGame` and `onEndGameTurn`. `onEndGameTurn` fires last in the round, making it the freshest proxy for what the player is about to see; it passes `iGameTurn + 1` since the round it reports has finished. `onGameStart` covers a new game and `onLoadGame` a resumed save, both passing `getGameTurn()` directly.

Two consequences for anything reading the output:

- **A run starts at `turn_0000`** — the state before turn 1 is played. Not an off-by-one; it is the snapshot the opening decision is actually made from, and the most useful file in the run.
- **Loading a save re-exports that turn and overwrites its file.** File mtimes within a run are therefore not monotonic. Order by filename, never by mtime.

## 3. Export timing makes a class of getters stale

`CvUnit::doTurn()` resets moves and applies healing in the same per-player pass that runs *after* the export hook fires. So at export time:

- **`movesLeft()` describes the round that just ended.** A warrior that had moved exported `0`. I found this by checking an exported number against the game UI, not from the tests — the mocks were internally consistent and the assumption behind them was simply wrong. The export uses `baseMoves()` now, i.e. moves per turn rather than moves remaining.
- **`getDamage()` is one heal tick stale**, and here there was no live equivalent to switch to: `CyUnit` has no `healRate()` binding at all (confirmed live: `AttributeError`). So the post-heal value is reconstructed from the engine's own `CvUnit::healRate()` formula, component by component, against the SDK source. Derivation and citations: [`REFERENCES.md`](../REFERENCES.md) "Unit heal-rate reconstruction".

The transferable lesson is **anything mutated in `doTurn()` is suspect at this hook** — and a unit test cannot catch it, because the mocks encode our belief about the API rather than the API. The same shape bit me again later with `getBuildTurnsLeft`, which is calibrated for a mid-turn read and overcounts by one at this timing (not staleness, but the same root cause: an engine getter tuned for when the interface calls it).

### The bit I can't explain

I audited whether anything else shares this. In the SDK source, `CvPlayer::doTurn()` calls `pLoopCity->doTurn()` and the unit heal/move-reset in the *same function*, with no ordering gap in the code — which reads as though cities should be exactly as stale as units.

**They aren't.** City growth, production completion, culture, research progress and Great Person points have all been watched directly in game, matching the in-game state at export time. I took live behaviour as authoritative and stopped there, since the conclusion doesn't depend on resolving it, but I don't know *why* the source disagrees.

## 4. `__file__` and `sys.path` cannot locate your own source

Both automatic routes to "where am I actually installed" are dead ends, measured:

- **`__file__` is reported relative to the engine's `Assets/Python` search root**, regardless of which physical folder supplied the file — including through a deployment junction.
- **`sys.path` is no better**: every entry failed `os.path.isfile` for a module I knew existed.

An absolute path from a config module was the only route I found. That is what forces a gitignored `LocalConfig.py` holding the output directory, and it is why a missing config is a silent failure for this mod where everything loads, runs, and writes nothing.

If there's a real way to resolve a mod's own path at runtime, I'd love to know.

## 5. There is no readable persistent game ID

I wanted stable per-game output folders and could not find anything to key them on: no UUID, no save identity, no readable map seed, nothing that survives a save/load and distinguishes two games started the same way.

**So the mod writes one.** It generates an ID from `time.time()` the first time `CvGame.getScriptData()` comes back empty, then writes it back once. Every later load of that save returns what was written, including across a full game restart.

This is the one place the mod writes anything to game state rather than only reading, which I thought hard about before doing. `scriptData` is unused free-form storage with no gameplay effect, so I think it's safe, but if there's a reason not to lean on that field I'd love to hear it. The read-only alternatives I considered and why they failed are in [`REFERENCES.md`](../REFERENCES.md) "No readable persistent game ID".

## 6. The exported y-axis is flipped

The engine's y increases north. The export inverts it, so `(0,0)` is the northwest corner and y increases south, matching the screen/image/matrix convention.

Mechanically this is one transform applied once, after every section is built and immediately before the state document is returned, so no extraction code is touched and the flip is unit-testable as a single function.

The *reason* is not a modding one, but about how language models read coordinates, and it's in [`ADVISOR.md`](ADVISOR.md#the-compass-problem). Noted here because it's the one thing in the export that deliberately disagrees with the engine, and because **anything writing a coordinate back to the engine needs exactly one inverse** at that boundary.

## 7. Smaller things that took me time

- **Hand-rolled JSON.** Python 2.4 predates the `json` module, so serialization is written out. Pretty-printed with sorted keys rather than compact — the file gets eyeballed against the game UI, and 2.4 dicts have no insertion order, so sorting is what makes consecutive turns diff meaningfully. Map tiles are forced one per line, leading with `x`/`y`, since they're rows of one long homogeneous table.
- **Temp-file-then-rename is not an atomic replace here.** Windows `os.rename` fails when the target exists, and 2.4 has no `os.replace` (`ctypes` arrived in 2.5), so the old file gets removed first. That leaves a brief window where the state file is *absent* but never one where it's half-written — a missing file is detectable and retryable by the reader, a truncated one parses as garbage. I'd take a better approach if one exists at this Python version.
- **`LoggingEnabled = 1` in `CivilizationIV.ini` is not optional for debugging.** At the default `0`, `PythonDbg.log` is written during startup and then never updated again, even though the process is happily running and dispatching events — so your `pyPrint` output goes nowhere and it looks like your hook isn't firing. `HidePythonExceptions` only suppresses the in-game popup, not the log.
- **Deployment is a junction (`mklink /J`), not a copy.** Edits in the repo are live in-game with no deploy step, and unlike symlinks it needs no admin rights.
- **`reload()` appears to work and doesn't.** Trying to avoid a game restart on every Python edit, I called `reload()` on my own module: it returned successfully, logged nothing, and went on running the old code. A restart always works and so hides this, which is why it took a while to spot. `execfile(path, module.__dict__)` does work; re-executing the source into the existing module's namespace keeps the module identity, so anything holding a reference just sees rebound functions. It doesn't help for the event manager, since the engine holds an object already instantiated from the old class. I never established *why* `reload()` behaves this way (it's stock CPython 2.4, and stale bytecode is ruled out), so if this is known behaviour with a known cause I'd like to hear it.
- **OneDrive sets the ReadOnly attribute on a junction inside a synced folder**, some time *after* creation. Very specific to my setup, but worth knowing if your Documents folder is synced: a fresh junction doesn't carry it, so removing it works right after install and fails weeks later with "Access to the path is denied" — which reads as a permissions problem and isn't one. Clearing that one bit fixes it. Anything that deletes under a synced Documents folder inherits this.

## 8. The other half, briefly

Everything the AI side needs is downstream of the file and none of it is a Civ IV concern: a set of external Python 3 scripts, stdlib only, that read the JSON and render it — an ASCII map, cross-turn history, and lookups against the game's own XML. The mod deliberately renders nothing itself. A grid is far better to hand a model than raw objects, but objects-from-grid is impossible while grid-from-objects is trivial, and presentation logic has no business living in the process that must never crash the game.

If that side is what interests you: [`ADVISOR.md`](ADVISOR.md), and [`harness/README.md`](../harness/README.md) for the developer version.

## Feedback welcome

If something here is wrong, already solved, or solved better elsewhere, please say so — particularly [§3](#the-bit-i-cant-explain)'s contradiction, [§4](#4-__file__-and-syspath-cannot-locate-your-own-source), and whether leaning on `scriptData` in [§5](#5-there-is-no-readable-persistent-game-id) is as harmless as I think. The code is [`mod/`](../mod/); design decisions with their reasoning are in [`CLAUDE.md`](../CLAUDE.md), and the measurements and citations behind every claim above are in [`REFERENCES.md`](../REFERENCES.md).
