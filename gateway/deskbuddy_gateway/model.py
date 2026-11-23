"""Snapshot model shared by the collector (writer) and the HTTP gateway (reader)."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Optional

SCHEMA_VERSION = 1
SERVICES = ("codex", "claude")
WINDOWS = ("5h", "7d")


def empty_window() -> Dict[str, Any]:
    return {"used_percent": None, "resets_at": None}


def empty_service() -> Dict[str, Any]:
    return {
        "windows": {w: empty_window() for w in WINDOWS},
        "interval_s": None,
        "last_success_at": None,
        "last_attempt_at": None,
        "failures": 0,
        "retry_at": None,
        # {"kind": "auth|rate_limited|parse|unavailable|failed", "message": str, "at": int}
        "error": None,
    }


def empty_snapshot() -> Dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "seq": 0,
        "generated_at": None,
        "services": {s: empty_service() for s in SERVICES},
    }


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int(value: Any) -> Optional[int]:
    n = _num(value)
    return None if n is None else int(n)


def clamp_percent(value: Any) -> Optional[float]:
    n = _num(value)
    if n is None:
        return None
    return max(0.0, min(100.0, n))


def normalize_snapshot(raw: Any) -> Dict[str, Any]:
    """Merge an untrusted snapshot dict onto the empty template; never raises."""
    snap = empty_snapshot()
    if not isinstance(raw, dict):
        return snap
    snap["seq"] = _int(raw.get("seq")) or 0
    snap["generated_at"] = _int(raw.get("generated_at"))
    raw_services = raw.get("services")
    if not isinstance(raw_services, dict):
        return snap
    for name in SERVICES:
        src = raw_services.get(name)
        if not isinstance(src, dict):
            continue
        dst = snap["services"][name]
        windows = src.get("windows")
        if isinstance(windows, dict):
            for w in WINDOWS:
                item = windows.get(w)
                if isinstance(item, dict):
                    dst["windows"][w] = {
                        "used_percent": clamp_percent(item.get("used_percent")),
                        "resets_at": _int(item.get("resets_at")),
                    }
        dst["interval_s"] = _int(src.get("interval_s"))
        dst["last_success_at"] = _int(src.get("last_success_at"))
        dst["last_attempt_at"] = _int(src.get("last_attempt_at"))
        dst["failures"] = _int(src.get("failures")) or 0
        dst["retry_at"] = _int(src.get("retry_at"))
        err = src.get("error")
        if isinstance(err, dict) and isinstance(err.get("kind"), str):
            dst["error"] = {
                "kind": err["kind"],
                "message": str(err.get("message", ""))[:300],
                "at": _int(err.get("at")),
            }
    return snap


def load_snapshot(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return normalize_snapshot(json.load(fh))
    except (OSError, ValueError):
        return empty_snapshot()


def write_snapshot(path: str, snapshot: Dict[str, Any]) -> None:
    """Atomic write: temp file in the same directory, fsync, rename."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".usage-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)  # the gateway container reads this as another user
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
