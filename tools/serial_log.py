#!/usr/bin/env python3
"""Print the device's USB log for N seconds (default 60): BOOT / FETCH / RENDER / STATUS lines."""
import argparse
import sys

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from deskbuddy_serial import Serial, find_port  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port")
ap.add_argument("--seconds", type=float, default=60)
ap.add_argument("--send", action="append", default=[], help="command to send first (repeatable)")
args = ap.parse_args()
ser = Serial(args.port or find_port())
for cmd in args.send:
    ser.write_line(cmd)
for line in ser.read_lines(args.seconds):
    print(line, flush=True)
