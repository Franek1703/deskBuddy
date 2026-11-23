"""Builds the JSON that GET /v1/usage returns to the ESP32."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .model import SERVICES, WINDOWS

DEFAULT_STALE_AFTER_S = {"codex": 360, "claude": 900}


def stale_after_s(name: str, svc: Dict[str, Any]) -> int:
    interval = svc.get("interval_s")
    if interval:
        return int(interval) * 3
    return DEFAULT_STALE_AFTER_S.get(name, 600)


def service_state(name: str, svc: Dict[str, Any], now: int) -> str:
    """missing: nothing to show; stale: values exist but are not trustworthy; fresh: ok."""
    has_value = any(w["used_percent"] is not None for w in svc["windows"].values())
    if not has_value:
        return "missing"
    last = svc.get("last_success_at")
    if last is None:
        return "stale"
    err = svc.get("error") or {}
    if err.get("kind") == "rate_limited":
        return "stale"
    if now - last > stale_after_s(name, svc):
        return "stale"
    return "fresh"


def _window(w: Dict[str, Any], now: int) -> Dict[str, Any]:
    percent = w["used_percent"]
    resets_at = w["resets_at"]
    if percent is not None:
        percent = round(percent, 1)
        if percent == int(percent):
            percent = int(percent)
    return {
        "percent": percent,  # kept as-is after the reset time passes; never zeroed here
        "resets_at": resets_at,
        "resets_in_s": None if resets_at is None else max(0, resets_at - now),
        "expired": resets_at is not None and resets_at <= now,
    }


def build_usage_response(snapshot: Dict[str, Any], now: int, served: int) -> Dict[str, Any]:
    services: Dict[str, Any] = {}
    for name in SERVICES:
        svc = snapshot["services"][name]
        last: Optional[int] = svc.get("last_success_at")
        err = svc.get("error")
        services[name] = {
            "state": service_state(name, svc, now),
            "last_success_at": last,
            "age_s": None if last is None else max(0, now - last),
            "error": None if not err else err["kind"],
            "retry_at": svc.get("retry_at"),
            "windows": {w: _window(svc["windows"][w], now) for w in WINDOWS},
        }
    return {
        "schema": snapshot.get("schema", 1),
        "seq": snapshot.get("seq", 0),
        "served": served,
        "now": now,
        "services": services,
    }
