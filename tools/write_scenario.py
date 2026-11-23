#!/usr/bin/env python3
"""Write a canned usage.json for display / failure testing without touching real accounts.

scenarios: normal zero full missing-window missing-service stale expired rate-limited
usage: tools/write_scenario.py <scenario> [--data-dir deploy/local/data]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gateway"))
from deskbuddy_gateway import model  # noqa: E402

H, D = 3600, 86400


def build(name, now):
    snap = model.empty_snapshot()
    snap["seq"] = int(now) % 100000  # distinct per run so a log line identifies the snapshot

    def fill(svc, w5, w7, age=5, interval=120):
        s = snap["services"][svc]
        s["interval_s"] = interval
        s["last_success_at"] = int(now) - age
        s["last_attempt_at"] = int(now) - age
        for key, val in (("5h", w5), ("7d", w7)):
            if val:
                s["windows"][key] = {"used_percent": val[0], "resets_at": int(now) + val[1]}
        return s

    if name == "normal":
        fill("codex", (93, 3 * H + 40 * 60), (23, 5 * D + 20 * H))
        fill("claude", (42, 2 * H + 5 * 60), (9, 6 * D + 3 * H), interval=300)
    elif name == "zero":
        fill("codex", (0, 5 * H), (0, 7 * D))
        fill("claude", (0, 5 * H), (0, 7 * D), interval=300)
    elif name == "full":
        fill("codex", (100, 1 * H + 5 * 60), (100, 2 * D))
        fill("claude", (100, 45 * 60), (100, 1 * D + 4 * H), interval=300)
    elif name == "missing-window":
        fill("codex", (61, 2 * H), None)
        fill("claude", None, (30, 3 * D), interval=300)
    elif name == "missing-service":
        fill("codex", (50, 2 * H), (20, 3 * D))
    elif name == "stale":
        fill("codex", (50, 2 * H), (20, 3 * D), age=20 * 60)
        fill("claude", (10, 2 * H), (5, 3 * D), age=90 * 60, interval=300)
    elif name == "expired":
        fill("codex", (93, -60), (23, -3600))
        fill("claude", (42, -5), (9, 6 * D), interval=300)
    elif name == "rate-limited":
        s = fill("codex", (50, 2 * H), (20, 3 * D), age=30)
        s["error"] = {"kind": "rate_limited", "message": "try again in 90 seconds", "at": int(now)}
        s["retry_at"] = int(now) + 90
        fill("claude", (10, 2 * H), (5, 3 * D), interval=300)
    else:
        sys.exit("unknown scenario " + name)
    return snap


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario")
    ap.add_argument("--data-dir", default="deploy/local/data")
    a = ap.parse_args()
    model.write_snapshot(os.path.join(a.data_dir, "usage.json"), build(a.scenario, time.time()))
    print("wrote %s/usage.json (%s)" % (a.data_dir, a.scenario))
