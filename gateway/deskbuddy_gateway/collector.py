"""Polls Codex and Claude and writes the normalized snapshot atomically."""
from __future__ import annotations

import argparse
import logging
import os
import shlex
import signal
import time
from typing import Any, Callable, Dict, Optional

from .model import SERVICES, WINDOWS, empty_window, load_snapshot, write_snapshot
from .sources import SourceError, Windows, fetch_claude, fetch_codex

log = logging.getLogger("deskbuddy.collector")
MAX_BACKOFF_S = 1800


class Collector:
    def __init__(self, data_path: str, sources: Dict[str, Callable[[], Windows]],
                 intervals: Dict[str, int], clock: Callable[[], float] = time.time):
        self.path = data_path
        self.sources = sources
        self.intervals = intervals
        self.clock = clock
        self.snapshot = load_snapshot(data_path)  # keep last good values across restarts
        for name, interval in intervals.items():
            self.snapshot["services"][name]["interval_s"] = interval

    def due(self, name: str, now: float) -> bool:
        svc = self.snapshot["services"][name]
        if svc["retry_at"] is not None:
            return now >= svc["retry_at"]
        last = svc["last_attempt_at"]
        return last is None or now - last >= self.intervals[name]

    def next_due_in(self, now: float) -> float:
        waits = []
        for name in self.sources:
            svc = self.snapshot["services"][name]
            if svc["retry_at"] is not None:
                waits.append(svc["retry_at"] - now)
            elif svc["last_attempt_at"] is None:
                waits.append(0)
            else:
                waits.append(svc["last_attempt_at"] + self.intervals[name] - now)
        return max(1.0, min(waits)) if waits else 30.0

    def poll(self, name: str) -> None:
        now = int(self.clock())
        svc = self.snapshot["services"][name]
        svc["last_attempt_at"] = now
        try:
            windows = self.sources[name]()
        except SourceError as exc:
            svc["failures"] += 1
            backoff = min(self.intervals[name] * 2 ** (svc["failures"] - 1), MAX_BACKOFF_S)
            wait = max(backoff, exc.retry_after or 0)
            svc["retry_at"] = now + wait
            svc["error"] = {"kind": exc.kind, "message": exc.message[:300], "at": now}
            log.warning("%s failed (%s): %s; retry in %ss, keeping previous values",
                        name, exc.kind, exc.message, wait)
        except Exception as exc:  # a bug in a source must not kill the loop
            svc["failures"] += 1
            svc["retry_at"] = now + min(self.intervals[name] * 2 ** (svc["failures"] - 1), MAX_BACKOFF_S)
            svc["error"] = {"kind": "failed", "message": "%s: %s" % (type(exc).__name__, exc), "at": now}
            log.exception("%s crashed", name)
        else:
            svc["windows"] = {w: dict(windows.get(w) or empty_window()) for w in WINDOWS}
            svc["last_success_at"] = now
            svc["failures"] = 0
            svc["retry_at"] = None
            svc["error"] = None
            log.info("%s ok: %s", name, ", ".join(
                "%s=%s%%" % (w, svc["windows"][w]["used_percent"]) for w in WINDOWS))
        self.snapshot["seq"] += 1
        self.snapshot["generated_at"] = now
        write_snapshot(self.path, self.snapshot)

    def run_due(self) -> int:
        n = 0
        for name in self.sources:
            if self.due(name, self.clock()):
                self.poll(name)
                n += 1
        return n


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="DeskBuddy limit collector")
    p.add_argument("--data-dir", default=os.environ.get("DESKBUDDY_DATA_DIR", "./data"))
    p.add_argument("--codex-bin", default=os.environ.get("DESKBUDDY_CODEX_BIN", "codex"))
    p.add_argument("--claude-cmd", default=os.environ.get("DESKBUDDY_CLAUDE_CMD", "claude -p /usage"),
                   help="command printing /usage; may be an ssh wrapper")
    p.add_argument("--codex-interval", type=int, default=120)
    p.add_argument("--claude-interval", type=int, default=300)
    p.add_argument("--only", choices=SERVICES, help="poll just one service")
    p.add_argument("--once", action="store_true", help="poll every service once and exit")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    claude_cmd = shlex.split(args.claude_cmd)
    sources = {
        "codex": lambda: fetch_codex(args.codex_bin),
        "claude": lambda: fetch_claude(claude_cmd),
    }
    intervals = {"codex": args.codex_interval, "claude": args.claude_interval}
    if args.only:
        sources = {args.only: sources[args.only]}
    col = Collector(os.path.join(args.data_dir, "usage.json"), sources, intervals)

    if args.once:
        for name in sources:
            col.poll(name)
        return 0
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    log.info("collector started, data=%s", col.path)
    while not stop["now"]:
        col.run_due()
        end = time.time() + min(col.next_due_in(time.time()), 30)
        while not stop["now"] and time.time() < end:
            time.sleep(0.5)
    log.info("collector stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
