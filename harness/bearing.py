"""Compass bearing and distance between two map coordinates.

`render_map.py --view military` and `run_history.py --view intel` already print
a bearing beside every rival sighting, but only relative to a city (intel) or
the nearest rival in sight (military's own-unit line). Tracking anything else -
a scout against a moving rival, a settle candidate against a rival city seen
turns ago - meant working out north/south by hand, which is exactly the step
that has failed in every prior trial (see AGENT_GUIDE.md). This removes that
arithmetic for any two coordinates, not just the cases the other views cover.

Takes a state file so distance and wrap can be computed correctly for this
game's actual map (mapWidth, wrapX) instead of assumed.

Run it directly with the system Python; stdlib only, no setup:

    python harness/bearing.py 73,18 79,25 samples/baseline-early-game/turn_0040.json
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_map


def parse_point(text):
    try:
        x_str, y_str = text.split(",")
        return (int(x_str), int(y_str))
    except ValueError:
        raise argparse.ArgumentTypeError(
            "expected X,Y (e.g. 73,18), got %r" % text
        )


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bearing.py",
        description=__doc__.split("\n\n")[1],
    )
    parser.add_argument("origin", type=parse_point, help="X,Y - the 'from' point")
    parser.add_argument("target", type=parse_point, help="X,Y - the 'to' point")
    parser.add_argument("state", help="path to a state.json, for map width and wrap")
    args = parser.parse_args(argv)

    state = render_map.State(args.state)
    origin, target = args.origin, args.target

    if origin == target:
        print("same tile")
        return 0

    compass = state.bearing(origin, target)
    straight = state.distance(origin, target)
    unit = "tile" if straight == 1 else "tiles"
    line = "%s, %d %s straight" % (compass, straight, unit)

    steps = state.land_distance(origin, target)
    if steps is None:
        line += " / NO LAND ROUTE over revealed tiles - separated by water, peaks, or fog"
    elif steps != straight:
        line += " / %d by land" % steps

    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
