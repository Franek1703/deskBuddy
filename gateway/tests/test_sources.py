import json
import os
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from deskbuddy_gateway import sources as S  # noqa: E402

WAW = ZoneInfo("Europe/Warsaw")


def epoch(y, mo, d, h, mi):
    return int(datetime(y, mo, d, h, mi, tzinfo=WAW).timestamp())


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as fh:
        return fh.read()


class ResetTimeTests(unittest.TestCase):
    NOW = epoch(2026, 11, 23, 15, 0)

    def test_date_and_minutes(self):
        self.assertEqual(S.parse_reset_time("Nov 23 at 3:30pm (Europe/Warsaw)", self.NOW),
                         epoch(2026, 11, 23, 15, 30))

    def test_hour_only_and_am(self):
        self.assertEqual(S.parse_reset_time("Nov 30 at 2am (Europe/Warsaw)", self.NOW),
                         epoch(2026, 11, 30, 2, 0))

    def test_noon_and_midnight(self):
        self.assertEqual(S.parse_reset_time("Nov 24 at 12pm (Europe/Warsaw)", self.NOW), epoch(2026, 11, 24, 12, 0))
        self.assertEqual(S.parse_reset_time("Nov 24 at 12am (Europe/Warsaw)", self.NOW), epoch(2026, 11, 24, 0, 0))

    def test_time_only_rolls_to_tomorrow_when_long_past(self):
        self.assertEqual(S.parse_reset_time("2am (Europe/Warsaw)", self.NOW), epoch(2026, 11, 24, 2, 0))

    def test_time_only_today(self):
        self.assertEqual(S.parse_reset_time("6:45pm (Europe/Warsaw)", self.NOW), epoch(2026, 11, 23, 18, 45))

    def test_year_rollover(self):
        now = epoch(2026, 12, 30, 12, 0)
        self.assertEqual(S.parse_reset_time("Jan 3 at 9am (Europe/Warsaw)", now), epoch(2027, 1, 3, 9, 0))

    def test_24h_clock(self):
        self.assertEqual(S.parse_reset_time("Nov 23 at 17:05 (Europe/Warsaw)", self.NOW), epoch(2026, 11, 23, 17, 5))

    def test_other_timezone_is_honoured(self):
        got = S.parse_reset_time("Nov 23 at 9am (America/New_York)", self.NOW)
        self.assertEqual(got, int(datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()))

    def test_garbage(self):
        self.assertIsNone(S.parse_reset_time("soon", self.NOW))


class ClaudeParseTests(unittest.TestCase):
    NOW = epoch(2026, 11, 23, 15, 0)

    def test_real_output(self):
        w = S.parse_claude_usage(fixture("claude_usage_real.txt"), self.NOW)
        self.assertEqual(w["5h"], {"used_percent": 2.0, "resets_at": epoch(2026, 11, 23, 15, 30)})
        self.assertEqual(w["7d"], {"used_percent": 9.0, "resets_at": epoch(2026, 11, 30, 2, 0)})

    def test_week_only_uses_all_models_row_not_sonnet(self):
        w = S.parse_claude_usage(fixture("claude_usage_week_only.txt"), self.NOW)
        self.assertNotIn("5h", w)
        self.assertEqual(w["7d"]["used_percent"], 41.0)

    def test_ansi_is_stripped(self):
        text = "\x1b[1mCurrent session:\x1b[0m 100% used · resets 6:45pm (Europe/Warsaw)\n"
        w = S.parse_claude_usage(text, self.NOW)
        self.assertEqual(w["5h"]["used_percent"], 100.0)

    def test_zero_percent_without_reset(self):
        w = S.parse_claude_usage("Current session: 0% used\n", self.NOW)
        self.assertEqual(w["5h"], {"used_percent": 0.0, "resets_at": None})

    def test_auth_error(self):
        with self.assertRaises(S.SourceError) as cm:
            S.parse_claude_usage("Not logged in · Please run /login", self.NOW)
        self.assertEqual(cm.exception.kind, "auth")

    def test_rate_limited_with_retry(self):
        with self.assertRaises(S.SourceError) as cm:
            S.parse_claude_usage("API Error: 429 rate limit, try again in 2 minutes", self.NOW)
        self.assertEqual((cm.exception.kind, cm.exception.retry_after), ("rate_limited", 120))

    def test_unknown_format_is_parse_error(self):
        with self.assertRaises(S.SourceError) as cm:
            S.parse_claude_usage("something else entirely", self.NOW)
        self.assertEqual(cm.exception.kind, "parse")

    def test_fetch_runs_command(self):
        cmd = [sys.executable, "-c", "print(open(%r).read())" % os.path.join(HERE, "fixtures", "claude_usage_real.txt")]
        w = S.fetch_claude(cmd, now=self.NOW)
        self.assertEqual(w["7d"]["used_percent"], 9.0)

    def test_fetch_missing_binary(self):
        with self.assertRaises(S.SourceError) as cm:
            S.fetch_claude(["/nonexistent/claude", "-p", "/usage"])
        self.assertEqual(cm.exception.kind, "unavailable")


class CodexTests(unittest.TestCase):
    FAKE = os.path.join(HERE, "fake_codex.py")

    def setUp(self):
        self.result = json.loads(fixture("codex_rate_limits_result.json"))

    def test_parse_real_result(self):
        w = S.parse_codex_rate_limits(self.result)
        self.assertEqual(w["5h"], {"used_percent": 93.0, "resets_at": 1795439673})
        self.assertEqual(w["7d"], {"used_percent": 23.0, "resets_at": 1795955202})

    def test_windows_are_picked_by_duration_not_position(self):
        lim = self.result["rateLimitsByLimitId"]["codex"]
        lim["primary"], lim["secondary"] = lim["secondary"], lim["primary"]
        w = S.parse_codex_rate_limits(self.result)
        self.assertEqual(w["5h"]["used_percent"], 93.0)
        self.assertEqual(w["7d"]["used_percent"], 23.0)

    def test_weekly_only_plan(self):
        lim = self.result["rateLimitsByLimitId"]["codex"]
        lim["primary"] = {"usedPercent": 5, "windowDurationMins": 10080, "resetsAt": 1795955202}
        lim["secondary"] = None
        w = S.parse_codex_rate_limits(self.result)
        self.assertEqual(list(w), ["7d"])

    def test_empty_is_error(self):
        with self.assertRaises(S.SourceError):
            S.parse_codex_rate_limits({"rateLimits": {"primary": None, "secondary": None}})

    def _run(self, mode, timeout=10):
        os.environ["FAKE_CODEX_MODE"] = mode
        try:
            return S.fetch_codex(self.FAKE, timeout=timeout)
        finally:
            os.environ.pop("FAKE_CODEX_MODE", None)

    def test_fetch_ok(self):
        self.assertEqual(self._run("ok")["5h"]["used_percent"], 93.0)

    def test_fetch_rate_limited(self):
        with self.assertRaises(S.SourceError) as cm:
            self._run("ratelimited")
        self.assertEqual((cm.exception.kind, cm.exception.retry_after), ("rate_limited", 90))

    def test_fetch_auth(self):
        with self.assertRaises(S.SourceError) as cm:
            self._run("auth")
        self.assertEqual(cm.exception.kind, "auth")

    def test_fetch_exit_before_answer(self):
        with self.assertRaises(S.SourceError) as cm:
            self._run("exit")
        self.assertEqual(cm.exception.kind, "failed")

    def test_fetch_timeout(self):
        with self.assertRaises(S.SourceError) as cm:
            self._run("hang", timeout=1.5)
        self.assertIn("timed out", cm.exception.message)

    def test_missing_binary(self):
        with self.assertRaises(S.SourceError) as cm:
            S.fetch_codex("/nonexistent/codex")
        self.assertEqual(cm.exception.kind, "unavailable")


if __name__ == "__main__":
    unittest.main()
