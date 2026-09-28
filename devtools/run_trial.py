"""Run one unattended trial: launch Civ IV into a fixture save, autoplay N turns,
stop, and write a report. Development tooling - see devtools/README.md.

    python devtools/run_trial.py --fixture mirror_lakes --turns 30

Steps: preflight checks -> write the one-shot devtools/runs/control.py ->
launch the game with /FXSLOAD -> wait for the in-game hook to consume the
control file -> watch turn files arrive -> close the game at the target turn
(or on a stall/timeout, with a screenshot) -> copy everything the run produced
into devtools/runs/<run-id>/ and write report.md + report.json there.

Never touches a game it didn't start: refuses to run if Civ IV is already open.
Always disarms the control file on the way out, so a failed run can't leave
autoplay armed for the next save someone loads.

Exit codes: 0 = reached the target turn, 1 = the run failed, 2 = preflight failed.
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

DEVTOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DEVTOOLS)
RUNS = os.path.join(DEVTOOLS, "runs")
CONTROL = os.path.join(RUNS, "control.py")
HOOKS = os.path.join(DEVTOOLS, "game_hooks", "DevHooks.py")
MOD_NAME = "civ4-advisor"

# Which civ each fixture needs removed to leave Alexander and Boudica - see
# the Fixtures table in devtools/README.md.
FIXTURES = {
    "mirror_lakes": ("mirror_lakes_t0.CivBeyondSwordSave", ["LEADER_PERICLES"]),
    "mirror_continents": ("mirror_continents_t0.CivBeyondSwordSave", ["LEADER_BISMARCK"]),
}

TURN_FILE = re.compile(r"turn_(\d{4})\.json$")


class PreflightError(Exception):
    pass


# ---------------------------------------------------------------- preflight

def load_paths():
    """Resolve every machine-specific path from the repo's own config files."""
    cfg_path = os.path.join(REPO, "config.local.json")
    if not os.path.isfile(cfg_path):
        raise PreflightError("config.local.json missing - run setup.bat first")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    user_dir = os.path.dirname(os.path.normpath(cfg["civ4_mods_path"]))
    paths = {
        "exe": os.path.join(cfg["civ4_install_path"], "Beyond the Sword", "Civ4BeyondSword.exe"),
        "ini": os.path.join(user_dir, "CivilizationIV.ini"),
        "log": os.path.join(user_dir, "Logs", "PythonDbg.log"),
        "local_config": os.path.join(REPO, "mod", "Assets", "Python", "LocalConfig.py"),
        "tech_log": os.path.join(REPO, "ai-opponent", "decide_tech_log.jsonl"),
    }
    if not os.path.isfile(paths["exe"]):
        raise PreflightError("game executable not found: %s" % paths["exe"])
    return paths


def read_local_config(path):
    """LocalConfig.py is plain assignments, so exec'ing it under Python 3 is safe."""
    if not os.path.isfile(path):
        raise PreflightError("LocalConfig.py missing - the mod would export nothing")
    ns = {}
    with open(path, encoding="utf-8") as f:
        exec(compile(f.read(), path, "exec"), ns)
    return ns


def read_ini(path):
    values = {}
    with open(path, encoding="latin-1") as f:
        for line in f:
            m = re.match(r"\s*([A-Za-z]+)\s*=\s*(.*?)\s*$", line)
            if m:
                values[m.group(1)] = m.group(2)
    return values


def game_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Civ4BeyondSword.exe", "/NH"],
                         capture_output=True, text=True).stdout
    return "Civ4BeyondSword.exe" in out


def steam_logged_in():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as k:
            return winreg.QueryValueEx(k, "ActiveUser")[0] != 0
    except OSError:
        return False


def ensure_steam(wait_seconds=120):
    """Without a logged-in Steam the game starts through Steam and drops mod=."""
    if steam_logged_in():
        return "already running"
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
        steam_exe = winreg.QueryValueEx(k, "SteamExe")[0]
    subprocess.Popen([steam_exe, "-silent"])
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(2)
        if steam_logged_in():
            return "started"
    raise PreflightError("Steam did not report a logged-in user within %ds" % wait_seconds)


def preflight(paths):
    """Returns (LocalConfig namespace, notes). Raises PreflightError on a blocker."""
    notes = []
    if game_running():
        raise PreflightError("Civ IV is already running - close it first (the runner never touches a game it didn't start)")
    local = read_local_config(paths["local_config"])
    hooks = local.get("DEV_HOOKS")
    if not hooks or os.path.normcase(os.path.abspath(hooks)) != os.path.normcase(HOOKS):
        raise PreflightError("LocalConfig.DEV_HOOKS must be %r (is %r)" % (HOOKS, hooks))
    if not local.get("STATE_DIR"):
        raise PreflightError("LocalConfig.STATE_DIR is not set")
    if local.get("MODE") not in ("opponent", "both"):
        notes.append("MODE is %r: no Claude decisions will be made (stock AI only)" % local.get("MODE"))
    ini = read_ini(paths["ini"])
    if ini.get("HideMinSpecWarning") != "1":
        raise PreflightError("CivilizationIV.ini needs HideMinSpecWarning = 1 - the min-spec dialog blocks the load")
    if ini.get("LoggingEnabled") != "1":
        notes.append("LoggingEnabled is not 1: PythonDbg.log won't update, so errors won't be detected")
    notes.append("Steam: %s" % ensure_steam())
    return local, notes


# ---------------------------------------------------------------- the run

def new_turn_files(state_dir, since):
    """{turn: path} for turn files written at or after `since`, newest wins."""
    found = {}
    for path in glob.glob(os.path.join(state_dir, "*", "turn_*.json")):
        m = TURN_FILE.search(path)
        if not m:
            continue
        mtime = os.path.getmtime(path)
        if mtime >= since - 1:
            turn = int(m.group(1))
            if turn not in found or mtime > os.path.getmtime(found[turn]):
                found[turn] = path
    return found


def read_scores(path):
    """{leader: {turn: score}} from the scores.csv DevHooks writes."""
    table = {}
    if not os.path.isfile(path):
        return table
    with open(path, encoding="latin-1") as f:
        next(f, None)
        for line in f:
            parts = line.strip().split(",")
            if len(parts) == 4:
                turn, _, leader, score = parts
                table.setdefault(leader, {})[int(turn)] = int(score)
    return table


def last_score_turn(path):
    turns = [t for by_turn in read_scores(path).values() for t in by_turn]
    return max(turns) if turns else -1


def screenshot(proc_id, out):
    script = os.path.join(DEVTOOLS, "capture_window.ps1")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
                        "-Out", out, "-ProcId", str(proc_id)], capture_output=True, text=True)
    return out if r.returncode == 0 and os.path.isfile(out) else None


def read_log(path, since):
    """The game truncates PythonDbg.log at startup, so only a log written after
    launch belongs to this run."""
    if not os.path.isfile(path) or os.path.getmtime(path) < since:
        return ""
    with open(path, encoding="latin-1") as f:
        return f.read()


def clean_env():
    """os.environ without the variables a Claude Code session exports to its
    children (CLAUDE_*, CLAUDECODE, MCP_*, and the desktop app's
    ANTHROPIC_BASE_URL/NODE_USE_SYSTEM_CA). Launched from inside a session,
    the game would otherwise pass them down to decide_tech.py's claude -p -
    changing its effort, entrypoint and auth path - where a game started from
    Steam has none, so a trial would not be measuring the real thing."""
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith(("CLAUDE", "MCP_"))
            and k.upper() not in ("ANTHROPIC_BASE_URL", "NODE_USE_SYSTEM_CA")}


def run(args, paths, local, run_dir):
    fixture_file, kill = FIXTURES[args.fixture]
    save = os.path.join(DEVTOOLS, "fixtures", fixture_file)
    os.makedirs(RUNS, exist_ok=True)
    scores = os.path.join(run_dir, "scores.csv")
    with open(CONTROL, "w", encoding="ascii") as f:
        f.write("KILL_LEADERS = %r\nAUTOPLAY_TURNS = %d\nSCORES_FILE = %r\n" % (kill, args.turns, scores))

    launched = time.time()
    cmd = '"%s" mod="\\%s" /FXSLOAD="%s"' % (paths["exe"], MOD_NAME, save)
    proc = subprocess.Popen(cmd, cwd=os.path.dirname(paths["exe"]), env=clean_env())
    result = {"status": None, "start_turn": None, "target_turn": None, "reached_turn": None,
              "launched": launched, "pid": proc.pid, "screenshot": None}

    def finish(status, shot=True):
        result["status"] = status
        if shot and proc.poll() is None:
            result["screenshot"] = screenshot(proc.pid, os.path.join(run_dir, "final.png"))
        return result

    try:
        # Phase 1: the in-game hook consumes the control file once the save loads.
        deadline = launched + args.load_timeout
        while os.path.exists(CONTROL):
            if proc.poll() is not None:
                return finish("game exited during load", shot=False)
            if "dev hook onLoadGame FAILED" in read_log(paths["log"], launched):
                return finish("dev hook failed - see PythonDbg.log")
            if time.time() > deadline:
                return finish("save did not load within %ds (hook never ran)" % args.load_timeout)
            time.sleep(2)

        # Phase 2: turn files arrive; stop at the target.
        state_dir = local["STATE_DIR"]
        last_progress, last_turn = time.time(), None
        hard_deadline = launched + args.max_minutes * 60
        while True:
            files = new_turn_files(state_dir, launched)
            if files:
                if result["start_turn"] is None:
                    result["start_turn"] = min(files)
                    result["target_turn"] = result["start_turn"] + args.turns
                newest = max(files)
                if newest != last_turn:
                    last_turn, last_progress = newest, time.time()
                    result["reached_turn"] = newest
                    print("  turn %d" % newest, flush=True)
                if newest >= result["target_turn"]:
                    # Scores are written at the very end of a round, after
                    # that round's turn file; give the last row a moment.
                    wait_until = time.time() + 15
                    while last_score_turn(scores) < result["target_turn"] and time.time() < wait_until:
                        time.sleep(1)
                    return finish("ok")
            if proc.poll() is not None:
                return finish("game exited early", shot=False)
            if time.time() - last_progress > args.stall_seconds:
                return finish("stalled: no new turn for %ds" % args.stall_seconds)
            if time.time() > hard_deadline:
                return finish("timed out after %d min" % args.max_minutes)
            time.sleep(2)
    finally:
        if os.path.exists(CONTROL):
            os.remove(CONTROL)   # never leave autoplay armed for a later load
        if proc.poll() is None:
            proc.terminate()
            proc.wait(30)


# ---------------------------------------------------------------- report

def parse_log(text):
    lines = text.splitlines()
    roster, current = [], None
    for line in lines:
        if "devtools: roster" in line:
            current = [line.split("PY:", 1)[-1]]
            roster.append(current)
        elif current is not None and re.match(r"\s{2}\d+ ", line):
            current.append(line.strip())
        else:
            current = None
    return {
        "roster": ["\n".join(block) for block in roster],
        "deaths": [l.split("PY:", 1)[-1] for l in lines if "alive status set to" in l],
        "tech_applied": [l.split("PY:", 1)[-1] for l in lines if "AI_chooseTech ordering" in l],
        "tech_fallbacks": [l.split("PY:", 1)[-1] for l in lines
                           if "falling through" in l or "AI_chooseTech FAILED" in l],
        "errors": [l for l in lines if "FAILED" in l or "Traceback" in l],
        # CvAdvisorGameUtils._decideTech: the whole os.popen freeze, as the game saw it.
        "round_trips": [float(m.group(1)) for m in
                        (re.search(r"decide_tech round trip ([\d.]+)s", l) for l in lines) if m],
    }


def tech_calls(path, since):
    if not os.path.isfile(path):
        return []
    since_utc = datetime.datetime.fromtimestamp(since, datetime.timezone.utc)
    calls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                when = datetime.datetime.strptime(entry["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
            except (ValueError, KeyError):
                continue
            if when.replace(tzinfo=datetime.timezone.utc) >= since_utc - datetime.timedelta(seconds=1):
                calls.append(entry)
    return calls


def collect(paths, local, result, run_dir):
    """Copy what this run produced into run_dir, then summarise it."""
    launched = result["launched"]
    files = new_turn_files(local["STATE_DIR"], launched)
    if files:
        # The game can write another turn between the target check and closing.
        result["reached_turn"] = max(files)
    state_out = os.path.join(run_dir, "state")
    os.makedirs(state_out, exist_ok=True)
    for turn, path in sorted(files.items()):
        shutil.copy2(path, state_out)
    log =read_log(paths["log"], launched)
    with open(os.path.join(run_dir, "PythonDbg.log"), "w", encoding="utf-8") as f:
        f.write(log)
    calls = tech_calls(paths["tech_log"], launched)
    with open(os.path.join(run_dir, "decide_tech.jsonl"), "w", encoding="utf-8") as f:
        for c in calls:
            f.write(json.dumps(c) + "\n")
    return {"log": parse_log(log), "tech_calls": calls,
            "all_scores": read_scores(os.path.join(run_dir, "scores.csv"))}


def score_table(all_scores, every=5):
    """Markdown lines: every civ's score at every `every`th turn plus the last,
    and the final gap between the top two."""
    if not all_scores:
        return ["", "## Score", "", "No scores recorded."]
    leaders = sorted(all_scores)
    turns = sorted({t for by_turn in all_scores.values() for t in by_turn})
    shown = [t for t in turns if t % every == 0 or t == turns[-1]]
    name = lambda leader: leader.replace("LEADER_", "").title()
    md = ["", "## Score (every AI civ, from DevHooks - ignores fog of war)", "",
          "| Turn | " + " | ".join(name(l) for l in leaders) + " |",
          "| --- |" + " --- |" * len(leaders)]
    for t in shown:
        md.append("| %d | " % t + " | ".join(str(all_scores[l].get(t, "")) for l in leaders) + " |")
    final = sorted(((all_scores[l][turns[-1]], l) for l in leaders if turns[-1] in all_scores[l]), reverse=True)
    if len(final) >= 2:
        (s1, l1), (s2, l2) = final[0], final[1]
        md += ["", "**Turn %d:** %s leads %s by %d (%d vs %d)" % (turns[-1], name(l1), name(l2), s1 - s2, s1, s2)]
    return md


def timing_table(calls, round_trips):
    """Markdown lines: each tech call's time breakdown (decide_tech.py's
    `timing`/`claude` log fields) beside the game's own round-trip figure.
    Round trips pair with calls by order, which holds as long as every call
    both logged and returned - an unpaired row shows as blank."""
    md = ["", "## Tech call timing (seconds)", "",
          "| Turn | round trip | total | startup | rules | claude CLI | CLI duration | API | turns | cache read / created |",
          "| --- |" + " --- |" * 9]
    for i, c in enumerate(calls):
        t, cl = c.get("timing") or {}, c.get("claude") or {}
        ms = lambda k: ("%.2f" % (cl[k] / 1000.0)) if isinstance(cl.get(k), (int, float)) else ""
        sec = lambda k: ("%.2f" % t[k]) if isinstance(t.get(k), (int, float)) else ""
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s |" % (
            c.get("gameTurn"), ("%.2f" % round_trips[i]) if i < len(round_trips) else "",
            sec("total"), sec("startupToMain"), sec("rules"), sec("claudeCli"),
            ms("durationMs"), ms("durationApiMs"), cl.get("numTurns", ""),
            cl.get("cacheReadTokens", ""), cl.get("cacheCreationTokens", "")))
    return md


def write_report(args, result, summary, notes, run_dir, elapsed):
    log, calls = summary["log"], summary["tech_calls"]
    secs = [c.get("wallClockSeconds", 0) for c in calls]
    valid = [c for c in calls if c.get("shapeValid") and c.get("inCandidateList")]
    turns_played = (result["reached_turn"] or 0) - (result["start_turn"] or 0)
    md = [
        "# Trial %s" % os.path.basename(run_dir),
        "",
        "- **Status:** %s" % result["status"],
        "- **Fixture:** %s, %d turns requested" % (args.fixture, args.turns),
        "- **Turns:** start %s, target %s, reached %s" % (result["start_turn"], result["target_turn"], result["reached_turn"]),
        "- **Wall time:** %.0fs%s" % (elapsed, (", %.1fs per turn" % (elapsed / turns_played)) if turns_played > 0 else ""),
        "- **Tech calls:** %d, %d valid; %d applied in-game, %d fell back to stock AI" % (
            len(calls), len(valid), len(log["tech_applied"]), len(log["tech_fallbacks"])),
    ]
    if secs:
        md.append("- **Call time:** mean %.1fs, max %.1fs" % (sum(secs) / len(secs), max(secs)))
    md += ["- **Errors in log:** %d" % len(log["errors"])]
    md += ["- **Note:** %s" % n for n in notes]
    if calls:
        md += ["", "## Tech choices", ""]
        md += ["- turn %s: %s (%.1fs)" % (c.get("gameTurn"), c.get("rawAnswer"), c.get("wallClockSeconds", 0)) for c in calls]
        md += timing_table(calls, log["round_trips"])
    md += score_table(summary["all_scores"])
    if log["roster"]:
        md += ["", "## Roster", "", "```"] + log["roster"] + ["```"]
    if log["deaths"]:
        md += ["", "## Alive-status changes", ""] + ["- %s" % d for d in log["deaths"]]
    if log["errors"]:
        md += ["", "## Errors", "", "```"] + log["errors"][:50] + ["```"]
    if result["screenshot"]:
        md += ["", "Final screenshot: `final.png`"]
    text = "\n".join(md) + "\n"
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    report = dict(result, fixture=args.fixture, turns=args.turns, elapsed=elapsed, notes=notes,
                  scores=summary["all_scores"], log=log, tech_calls=len(calls), tech_valid=len(valid))
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", required=True, choices=sorted(FIXTURES))
    ap.add_argument("--turns", type=int, required=True, help="turns of autoplay")
    ap.add_argument("--load-timeout", type=int, default=240, help="seconds for the save to load")
    ap.add_argument("--stall-seconds", type=int, default=300, help="seconds without a new turn before giving up")
    ap.add_argument("--max-minutes", type=int, default=60, help="hard limit for the whole run")
    args = ap.parse_args(argv)
    if args.turns < 1:
        ap.error("--turns must be at least 1")

    try:
        paths = load_paths()
        local, notes = preflight(paths)
    except PreflightError as e:
        print("preflight failed: %s" % e, file=sys.stderr)
        return 2

    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "_" + args.fixture
    run_dir = os.path.join(RUNS, run_id)
    os.makedirs(run_dir)
    print("run %s: %s, %d turns" % (run_id, args.fixture, args.turns), flush=True)
    started = time.time()
    result = run(args, paths, local, run_dir)
    summary = collect(paths, local, result, run_dir)
    print(write_report(args, result, summary, notes, run_dir, time.time() - started))
    print("report: %s" % os.path.join(run_dir, "report.md"))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
