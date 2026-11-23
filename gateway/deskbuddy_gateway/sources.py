"""Readers for the provider limits: Codex (app-server JSON-RPC) and Claude Code (/usage text)."""
from __future__ import annotations

import json
import os
import re
import select
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

Windows = Dict[str, Dict[str, Any]]  # {"5h": {"used_percent": 93.0, "resets_at": epoch}, ...}


class SourceError(Exception):
    """kind: auth | rate_limited | parse | unavailable | failed"""

    def __init__(self, kind: str, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retry_after = retry_after


# --------------------------------------------------------------------------- shared helpers

_AUTH_HINTS = ("not logged in", "log in", "login", "sign in", "unauthorized", "401", "authentication")
_RATE_HINTS = ("rate limit", "rate-limit", "too many requests", "429", "try again in", "retry after")


def classify_error_text(text: str) -> str:
    low = text.lower()
    if any(h in low for h in _RATE_HINTS):
        return "rate_limited"
    if any(h in low for h in _AUTH_HINTS):
        return "auth"
    return "failed"


def parse_retry_after(text: str) -> Optional[int]:
    """Pick 'try again in 90 seconds' / 'retry after 5 minutes' style hints out of an error."""
    m = re.search(r"(?:in|after)\s+(\d+)\s*(second|sec|s|minute|min|m|hour|h)\w*", text, re.I)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


# --------------------------------------------------------------------------- Codex

CODEX_MINUTES = {300: "5h", 10080: "7d"}


def _codex_window_name(position: str, minutes: Any) -> str:
    if isinstance(minutes, (int, float)) and not isinstance(minutes, bool):
        if minutes in CODEX_MINUTES:
            return CODEX_MINUTES[int(minutes)]
        return "5h" if minutes < 2880 else "7d"
    return "5h" if position == "primary" else "7d"


def parse_codex_rate_limits(result: Dict[str, Any]) -> Windows:
    """`account/rateLimits/read` result -> windows keyed by duration (not by primary/secondary)."""
    limits = (result.get("rateLimitsByLimitId") or {}).get("codex") or result.get("rateLimits")
    if not isinstance(limits, dict):
        raise SourceError("parse", "account/rateLimits/read returned no rateLimits")
    out: Windows = {}
    for position in ("primary", "secondary"):
        w = limits.get(position)
        if not isinstance(w, dict) or not isinstance(w.get("usedPercent"), (int, float)):
            continue
        name = _codex_window_name(position, w.get("windowDurationMins"))
        resets = w.get("resetsAt")
        out[name] = {
            "used_percent": float(w["usedPercent"]),
            "resets_at": int(resets) if isinstance(resets, (int, float)) else None,
        }
    if not out:
        raise SourceError("parse", "Codex returned no usable rate-limit windows")
    return out


class _LineReader:
    def __init__(self, fd: int):
        self.fd = fd
        self.buf = b""

    def readline(self, deadline: float) -> Optional[str]:
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([self.fd], [], [], left)
            if not ready:
                return None
            chunk = os.read(self.fd, 65536)
            if not chunk:
                return ""  # EOF
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode("utf-8", "replace")


def fetch_codex(codex_bin: str = "codex", timeout: float = 30.0) -> Windows:
    """Ask `codex app-server` for the account rate limits (JSON-RPC over stdio)."""
    try:
        proc = subprocess.Popen(
            [codex_bin, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SourceError("unavailable", "cannot start %s: %s" % (codex_bin, exc))
    try:
        def send(obj: Dict[str, Any]) -> None:
            proc.stdin.write((json.dumps(obj) + "\n").encode())
            proc.stdin.flush()

        try:
            send({"id": 1, "method": "initialize",
                  "params": {"clientInfo": {"name": "deskbuddy", "title": "DeskBuddy", "version": "0.1"}}})
            send({"method": "initialized"})
            send({"id": 2, "method": "account/rateLimits/read"})
        except OSError as exc:
            raise SourceError("failed", "codex app-server closed its stdin: %s" % exc)
        reader = _LineReader(proc.stdout.fileno())
        deadline = time.monotonic() + timeout
        while True:
            line = reader.readline(deadline)
            if line is None:
                raise SourceError("failed", "codex app-server timed out after %ss" % timeout)
            if line == "":
                raise SourceError("failed", "codex app-server exited before answering")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") != 2:
                continue
            if "error" in msg:
                text = json.dumps(msg["error"])[:300]
                kind = classify_error_text(text)
                raise SourceError(kind, text, parse_retry_after(text) if kind == "rate_limited" else None)
            return parse_codex_rate_limits(msg.get("result") or {})
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdout.close()


# --------------------------------------------------------------------------- Claude

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
_TIME24_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_DATE_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?\b")
_TZ_RE = re.compile(r"\(([A-Za-z0-9_+\-/]+)\)")


def parse_reset_time(text: str, now: float, default_tz=None) -> Optional[int]:
    """'Nov 23 at 3:30pm (Europe/Warsaw)' / '2am' / '15:30' -> epoch seconds, or None."""
    tzname = _TZ_RE.search(text)
    tz = default_tz or datetime.now().astimezone().tzinfo
    if tzname and ZoneInfo is not None:
        try:
            tz = ZoneInfo(tzname.group(1))
        except Exception:
            pass
    m = _TIME_RE.search(text)
    if m:
        hour, minute, ap = int(m.group(1)) % 12, int(m.group(2) or 0), m.group(3).lower()
        hour += 12 if ap == "pm" else 0
    else:
        m = _TIME24_RE.search(text)
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    local_now = datetime.fromtimestamp(now, tz)
    d = _DATE_RE.search(text)
    try:
        if d and d.group(1)[:3].lower() in _MONTHS:
            month, day = _MONTHS[d.group(1)[:3].lower()], int(d.group(2))
            year = int(d.group(3)) if d.group(3) else local_now.year
            when = datetime(year, month, day, hour, minute, tzinfo=tz)
            if not d.group(3) and when < local_now - timedelta(days=2):
                when = when.replace(year=year + 1)  # "Jan 3" seen in December
        else:
            when = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if when < local_now - timedelta(hours=12):
                when += timedelta(days=1)
    except ValueError:
        return None
    return int(when.astimezone(timezone.utc).timestamp())


_SESSION_RE = re.compile(r"current\s+session\s*:\s*(\d+(?:\.\d+)?)\s*%\s*used(?:\s*[·•|\-–]\s*resets?\s+(.*))?", re.I)
_WEEK_RE = re.compile(r"current\s+week\s*\(\s*all\s+models\s*\)\s*:\s*(\d+(?:\.\d+)?)\s*%\s*used(?:\s*[·•|\-–]\s*resets?\s+(.*))?", re.I)


def parse_claude_usage(text: str, now: float, default_tz=None) -> Windows:
    """Parse the output of `claude -p /usage` (current session = 5h window, current week = 7d)."""
    text = strip_ansi(text)
    out: Windows = {}
    for line in text.splitlines():
        for name, rx in (("5h", _SESSION_RE), ("7d", _WEEK_RE)):
            m = rx.search(line)
            if m and name not in out:
                reset = m.group(2)
                out[name] = {
                    "used_percent": float(m.group(1)),
                    "resets_at": parse_reset_time(reset, now, default_tz) if reset else None,
                }
    if out:
        return out
    kind = classify_error_text(text)
    snippet = " ".join(text.split())[:200]
    if kind == "failed":
        kind = "parse"
    raise SourceError(kind, "no usage rows in /usage output: " + snippet,
                      parse_retry_after(text) if kind == "rate_limited" else None)


def fetch_claude(command: List[str], timeout: float = 60.0, now: Optional[float] = None) -> Windows:
    """Run e.g. ['claude','-p','/usage'] (or an ssh wrapper around it) and parse its stdout."""
    try:
        res = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SourceError("failed", "claude /usage timed out after %ss" % timeout)
    except OSError as exc:
        raise SourceError("unavailable", "cannot run %s: %s" % (command[0], exc))
    stdout = res.stdout.decode("utf-8", "replace")
    stderr = res.stderr.decode("utf-8", "replace")
    if res.returncode != 0 and "current session" not in stdout.lower():
        text = (stdout + " " + stderr)
        kind = classify_error_text(text)
        raise SourceError(kind, "claude exited %d: %s" % (res.returncode, " ".join(text.split())[:200]),
                          parse_retry_after(text) if kind == "rate_limited" else None)
    return parse_claude_usage(stdout, time.time() if now is None else now)
