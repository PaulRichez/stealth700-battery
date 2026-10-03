"""Command-line entry point: print the headset battery level.

    python -m stealth700_battery            # one reading, e.g. "My Headset: 100%"
    python -m stealth700_battery --json      # machine-readable
    python -m stealth700_battery --watch 30  # refresh every 30 s until Ctrl-C
    python -m stealth700_battery --diagnose  # list HID collections and the raw status
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .reader import diagnostics, read_status


def _format(status) -> str:
    if status is None:
        return "No Turtle Beach transmitter found (is the dongle plugged in?)"
    state = ""
    if status.charging:
        state = " (charging)"
    elif not status.connected:
        state = " (headset off — last known)"
    return f"{status.name}: {status.battery}%{state}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="stealth700-battery",
        description="Read a Turtle Beach Stealth 700 Gen 3 battery level over USB.",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--watch", type=float, metavar="SECONDS",
                        help="keep printing every SECONDS until interrupted")
    parser.add_argument("--diagnose", action="store_true",
                        help="print what is visible on the HID bus")
    args = parser.parse_args(argv)

    if args.diagnose:
        print("\n".join(diagnostics()))
        return 0

    def emit() -> int:
        status = read_status()
        if args.json:
            print(json.dumps(None if status is None else {
                "name": status.name,
                "battery": status.battery,
                "connected": status.connected,
                "charging": status.charging,
            }))
        else:
            print(_format(status))
        return 0 if status is not None else 1

    if args.watch:
        try:
            while True:
                emit()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0
    return emit()


if __name__ == "__main__":
    sys.exit(main())
