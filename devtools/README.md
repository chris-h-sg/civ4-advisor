# devtools

Development and debugging tooling: launching and driving the game unattended, so a change can be tested without anyone clicking through menus. **Not part of anything shipped.** The advisor and the AI opponent are packaged without this folder.

## The boundary

- Nothing outside `devtools/` imports from it, reads its files, or depends on it existing.
- The one crossing is the mod's `_runDevHook` (`mod/Assets/Python/CvCustomEventManager.py`). It calls into `game_hooks/DevHooks.py` only when `LocalConfig.DEV_HOOKS` names that file. `setup.ps1` never writes that key, so a normal install has no dev behaviour at all.
- In-game automation goes in `DevHooks.py`, not in the mod. Deciding things for the game belongs in the product; *starting and stopping* the game belongs here.

## Running a trial

```bash
python devtools/run_trial.py --fixture mirror_lakes --turns 30
```

What it does:
1. **Checks:** Civ IV isn't already open (it never touches a game it didn't start), `LocalConfig.DEV_HOOKS` points here, `HideMinSpecWarning = 1`, and Steam is logged in (starting Steam if not).
2. **Runs:** writes the one-shot control file, launches into the fixture, and watches turn files arrive.
3. **Stops:** closes the game at the target turn, or on a stall, load failure or timeout, taking a final screenshot either way.
4. **Reports** into `runs/<run-id>/`:
   - `report.md` / `report.json`: status, turns, wall time, Claude's tech calls (valid, applied, fell back to stock AI, timing), every AI civ's score every 5 turns with the final gap (from `scores.csv`), the roster before and after setup, and errors from `PythonDbg.log`;
   - copies of the run's turn files, its log, and its `decide_tech` entries.

It always removes an unconsumed control file on exit. Exit code 0 means the target turn was reached, 1 means the run failed, 2 means preflight failed. The run needs `MODE = 'opponent'` (or `'both'`) in `LocalConfig.py` for Claude to make decisions; otherwise it's a stock-AI run and the report says so.

## Files

| File | Runs in | Does |
| --- | --- | --- |
| `run_trial.py` | Python 3 | The trial runner, above. |
| `game_hooks/DevHooks.py` | the game (Python 2.4) | On load, reads the one-shot `runs/control.py` and renames it to `control.consumed.py`. It removes the civs listed in `KILL_LEADERS`, starts AI autoplay (`AUTOPLAY_TURNS = N`), and logs the civ list before and after. At the end of every round it appends each AI civ's score to `SCORES_FILE`, the same number as the in-game scoreboard. That deliberately ignores fog of war: it's for judging a run, never for a decision. |
| `capture_window.ps1` | Windows PowerShell | Screenshots the game window while it's in the background. |
| `post_input.ps1` | Windows PowerShell | Sends a click or Enter to the game window without moving the real mouse or taking focus. A fallback for popups; prefer Python. |
| `fixtures/` | — | Start-point saves for trial runs (below). |
| `runs/` | — | Per-run working files, gitignored. |

To enable the hook on your machine, add to `mod/Assets/Python/LocalConfig.py` (needs a game restart, like any `LocalConfig` change):

```python
DEV_HOOKS = r'C:\path\to\civ4-advisor\devtools\game_hooks\DevHooks.py'
```

## Fixtures

Normal saves, never taken during a trial: a trial's autosaves remember an unfinished autoplay count (see below). All are on the `Mirror` map script (tiny, 32×20, no wrap, so x mirrors to 31 − x), 4000 BC, with default settings except **No Random Events**. A two-civ mirrored game is set up as 4 civs in 2 teams. Autoplay removes the human, and `KILL_LEADERS` removes the fourth civ, leaving Alexander and Boudica. Each survivor inherits its dead teammate's turn-0 map knowledge. Mirrored starts took several map rolls to get.

| Save | Setup | Control settings |
| --- | --- | --- |
| `mirror_lakes_t0.CivBeyondSwordSave` | Mirror Lakes. Human Bismarck (0) + Alexander (1) vs. Boudica (2) + Pericles (3). Alexander and Boudica share a landmass and meet early: x 12 ↔ 19, y 9, exact. Bismarck and Pericles are only roughly mirrored. | `KILL_LEADERS = ['LEADER_PERICLES']` |
| `mirror_continents_t0.CivBeyondSwordSave` | Mirror Continents. Human Darius (0) + Alexander (1) vs. Bismarck (2) + Boudica (3). Alexander and Boudica start on separate continents with no land bridge (checked in WorldBuilder): x 19 ↔ 12, y 12, exact. Early boats can cross the water between them, so they aren't fully isolated before Astronomy. Contact just comes later and by sea. Darius and Bismarck are exact too (x 29 ↔ 2, y 16). | `KILL_LEADERS = ['LEADER_BISMARCK']` |

## Launching unattended — measured 2026-09-28

- **Command:** `Civ4BeyondSword.exe mod="\civ4-advisor" /FXSLOAD="<full path to .CivBeyondSwordSave>"`, with the working directory set to the exe's folder. This loads straight into the save. An unquoted lowercase `/fxsload=` was ignored and the game stopped at the main menu; whether the quoting or the case fixed it wasn't isolated.
- **Steam must already be running and logged in**, or Steam starts and the game loses the `mod=` argument. It's ready when `HKCU:\Software\Valve\Steam\ActiveProcess` → `ActiveUser` is non-zero. `steam.exe -silent` straight after boot once produced a "steamwebhelper is not responding" dialog; it didn't affect the game.
- **`HideMinSpecWarning = 1` is required** in `CivilizationIV.ini`. The "below recommended specifications" dialog is modal and appears before the save loads, so it blocks an unattended start. It fires on hardware that's far above spec.
- **WorldBuilder saves don't work as a start point.** `/FXSLOAD` accepts them but stops at a "Select a Civilization" screen. Use a normal save, converted from a WorldBuilder scenario once if needed.
- **Don't use `/ALTROOT`.** On a fresh folder it *moved* the contents of the real `My Games\Beyond the Sword` (saves, logs, screenshots) into the new root. On later launches it still removed folders from the real one. It also can't see the normal Mods folder.
- **The game keeps running in the background** at normal speed without focus.

## Autoplay behaviour

- `setAIAutoPlay(N)` is the same as the cheat console's `Game.AIPlay N`. It removes the human civ for the duration. When the count runs out the game revives it with a single placeholder Lion at the map's bottom-left corner, then waits for input with no other side effects, so a run can be stopped at any point.
- **Saves remember an unfinished autoplay count.** Loading an autosave taken mid-run plays out the remaining turns without any input, so autosaves from a trial aren't ordinary saves.
- Popups (Dawn of Man, first contact) don't block autoplay.
