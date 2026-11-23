"""Sleep schedule the gateway relays to the device inside /v1/usage.

Each rule is `HH:MM-HH:MM` (start-end, local time; start > end wraps past midnight) or `off`.
`tz` is a POSIX TZ string (the device's C library understands it, so no tz database is needed here).
The device evaluates the schedule itself; the gateway only distributes it.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Mapping, Optional

log = logging.getLogger("deskbuddy.sleep")

DEFAULT_RULE = "22:00-07:00"
DEFAULT_TZ = "CET-1CEST,M3.5.0,M10.5.0/3"  # Europe/Warsaw incl. DST

_RULE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
# POSIX TZ: name offset [dst [offset] [,start[/time],end[/time]]]; checked loosely, the device validates it for real.
_TZ = re.compile(r"^[A-Za-z]{3,}[+-]?\d{1,2}(:\d{2}){0,2}([A-Za-z]{3,}([+-]?\d{1,2}(:\d{2}){0,2})?(,[^,\s]+,[^,\s]+)?)?$")


def parse_rule(text: Optional[str]) -> Optional[str]:
    """Return the normalised rule (`HH:MM-HH:MM` or `off`) or None when it is not valid."""
    if text is None:
        return None
    t = text.strip().lower()
    if t == "off":
        return "off"
    m = _RULE.match(t)
    if not m:
        return None
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59 or (h1, m1) == (h2, m2):
        return None
    return "%02d:%02d-%02d:%02d" % (h1, m1, h2, m2)


def parse_tz(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    t = text.strip()
    return t if t and len(t) <= 64 and _TZ.match(t) else None


class SleepConfig:
    def __init__(self, weekdays: str = DEFAULT_RULE, weekend: str = DEFAULT_RULE, tz: str = DEFAULT_TZ):
        self.weekdays, self.weekend, self.tz = weekdays, weekend, tz

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "SleepConfig":
        def pick(name: str, parser, default: str) -> str:
            raw = env.get(name)
            if raw is None or not raw.strip():
                return default
            value = parser(raw)
            if value is None:
                log.warning("ignoring invalid %s=%r, using %s", name, raw, default)
                return default
            return value

        return cls(pick("DESKBUDDY_SLEEP_WEEKDAYS", parse_rule, DEFAULT_RULE),
                   pick("DESKBUDDY_SLEEP_WEEKEND", parse_rule, DEFAULT_RULE),
                   pick("DESKBUDDY_TZ", parse_tz, DEFAULT_TZ))

    def as_dict(self) -> Dict[str, str]:
        return {"weekdays": self.weekdays, "weekend": self.weekend, "tz": self.tz}
