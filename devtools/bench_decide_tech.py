"""Offline benchmark for ai-opponent/decide_tech.py: replays it against saved
trial turn files and reports medians and spread per timing component.

    python devtools/bench_decide_tech.py -n 5 --label baseline
    python devtools/bench_decide_tech.py -n 20 --stub-claude     # local parts only

Each repetition runs decide_tech.py exactly as the mod does (a fresh Python
process, `<playerId>` argument, stdout read back), against a throwaway state
folder holding one saved turn file, and with its log redirected to a
throwaway file, so the real decide_tech_log.jsonl and state/ are untouched.
Inputs cycle through the turns Alexander actually chose research on in the
saved trial runs, so every configuration sees the same prompts in the same
order. Latency is noisy (identical inputs have varied up to 2x): compare
medians over several repetitions, never single calls.

Every repetition without --stub-claude is a real `claude -p` call and costs
quota. --stub-claude puts a fake `claude` first on PATH that answers
instantly, which measures everything except the CLI for free.

Results are appended to devtools/runs/bench_decide_tech.jsonl (gitignored,
under runs/) with the label, so configurations can be compared later.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

from run_trial import clean_env

DEVTOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DEVTOOLS)
RUNS = os.path.join(DEVTOOLS, "runs")
DECIDE_TECH = os.path.join(REPO, "ai-opponent", "decide_tech.py")
RESULTS = os.path.join(RUNS, "bench_decide_tech.jsonl")

# The research choices Alexander made in the saved mirrored trials. Paths are
# relative to runs/; a missing one is skipped with a warning.
DEFAULT_INPUTS = [
    "20260928-103002_mirror_lakes/state/turn_0001.json",
    "20260928-101359_mirror_continents/state/turn_0013.json",
    "20260928-103002_mirror_lakes/state/turn_0010.json",
    "20260928-101359_mirror_continents/state/turn_0021.json",
    "20260928-101359_mirror_continents/state/turn_0001.json",
]

STUB_CLAUDE = r"""@echo off
more > nul
echo {"type":"result","is_error":false,"duration_ms":0,"duration_api_ms":0,"num_turns":1,"structured_output":{"tech":"%STUB_TECH%"},"usage":{}}
"""

COMPONENTS = ["startupToMain", "stateLoad", "rules", "promptBuild", "claudeCli", "total", "outer"]
CLAUDE_FIELDS = ["durationMs", "durationApiMs", "numTurns", "inputTokens", "outputTokens",
                 "cacheReadTokens", "cacheCreationTokens", "costUsd"]


def run_once(state_file, work, env):
    """One decide_tech.py run against state_file. Returns its log entry with
    an extra timing.outer: this process's view of the whole round trip."""
    game_dir = os.path.join(work, "state", "LEADER_ALEXANDER_bench")
    shutil.rmtree(game_dir, ignore_errors=True)
    os.makedirs(game_dir)
    shutil.copy(state_file, game_dir)
    log = os.path.join(work, "log.jsonl")
    if os.path.exists(log):
        os.remove(log)
    env = dict(env, CIV4_ADVISOR_STATE_DIR=os.path.join(work, "state"), CIV4_ADVISOR_TECH_LOG=log)
    start = time.time()
    result = subprocess.run([sys.executable, DECIDE_TECH, "1"], capture_output=True, text=True, env=env)
    outer = time.time() - start
    entry = {}
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            entry = json.loads(f.readline())
    entry.setdefault("timing", {})["outer"] = round(outer, 3)
    entry["stdout"] = result.stdout
    if result.returncode != 0:
        entry["benchError"] = result.stderr.strip()
    return entry


def spread(values):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None
    return {"median": statistics.median(values), "min": min(values), "max": max(values), "n": len(values)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-n", type=int, default=5, help="repetitions (cycles through the inputs)")
    ap.add_argument("--label", default="unlabelled", help="name for this configuration in the results file")
    ap.add_argument("--stub-claude", action="store_true", help="replace claude with an instant fake (free)")
    ap.add_argument("--gap", type=float, default=0,
                    help="seconds to wait between repetitions: real tech choices are minutes apart, "
                         "which gives ai-opponent/claude_worker.py time to pre-start the next claude")
    ap.add_argument("--inputs", nargs="*", help="turn files (default: the saved trials' research turns)")
    args = ap.parse_args(argv)

    inputs = args.inputs or [os.path.join(RUNS, p) for p in DEFAULT_INPUTS]
    missing = [p for p in inputs if not os.path.isfile(p)]
    for p in missing:
        print("warning: missing input %s" % p, file=sys.stderr)
    inputs = [p for p in inputs if p not in missing]
    if not inputs:
        print("no inputs", file=sys.stderr)
        return 2

    work = tempfile.mkdtemp(prefix="bench_decide_tech_")
    env = clean_env()
    if args.stub_claude:
        stub_dir = os.path.join(work, "bin")
        os.makedirs(stub_dir)
        with open(os.path.join(stub_dir, "claude.cmd"), "w") as f:
            f.write(STUB_CLAUDE)
        env["PATH"] = stub_dir + os.pathsep + env["PATH"]

    entries = []
    try:
        for i in range(args.n):
            if i and args.gap:
                time.sleep(args.gap)
            state_file = inputs[i % len(inputs)]
            if args.stub_claude:
                with open(state_file, encoding="utf-8") as f:
                    known = set(json.load(f)["player"]["knownTechs"])
                # Any tech the state doesn't know passes the shape check; the
                # candidate check may reject it, which is fine for timing.
                env["STUB_TECH"] = next(t for t in ("TECH_MASONRY", "TECH_MYSTICISM", "TECH_SAILING") if t not in known)
            entry = run_once(state_file, work, env)
            entry["input"] = os.path.relpath(state_file, RUNS)
            entries.append(entry)
            t, c = entry["timing"], entry.get("claude", {})
            print("%2d  %-55s %-22s total %6.2fs  cli %6.2fs  api %s  turns %s  %s  %s" % (
                i + 1, entry["input"], entry.get("rawAnswer", "-"), t.get("total", 0), t.get("claudeCli", 0),
                c.get("durationApiMs"), c.get("numTurns"), entry.get("claudePath", ""),
                entry.get("benchError", "")), flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    summary = {
        "label": args.label,
        "stub": args.stub_claude,
        "n": len(entries),
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "timing": {k: spread([e["timing"].get(k) for e in entries]) for k in COMPONENTS},
        "claude": {k: spread([e.get("claude", {}).get(k) for e in entries]) for k in CLAUDE_FIELDS},
        "valid": sum(1 for e in entries if e.get("inCandidateList")),
        "models": sorted({m for e in entries for m in e.get("claude", {}).get("models", [])}),
    }
    print("\n%s (n=%d, %d valid, models %s)" % (args.label, summary["n"], summary["valid"], summary["models"]))
    print("%-22s %9s %9s %9s" % ("component", "median", "min", "max"))
    for group in ("timing", "claude"):
        for k, s in summary[group].items():
            if s:
                print("%-22s %9.3f %9.3f %9.3f" % (k, s["median"], s["min"], s["max"]))
    os.makedirs(RUNS, exist_ok=True)
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(summary, entries=entries)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
