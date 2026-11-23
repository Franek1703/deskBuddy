#pragma once
// Pure sleep-schedule logic (no Arduino dependency) so it can be unit tested on a computer:
//   clang++ -std=c++17 -I firmware/deskbuddy firmware/tests/test_sleep_schedule.cpp -o /tmp/t && /tmp/t
#include <stdint.h>

struct SleepRule {
  bool enabled = false;
  uint16_t startMin = 0;  // minutes after local midnight
  uint16_t endMin = 0;
};

namespace sleepsched_detail {

inline bool isOff(const char* t) {
  return (t[0] == 'o' || t[0] == 'O') && (t[1] == 'f' || t[1] == 'F') && (t[2] == 'f' || t[2] == 'F') && t[3] == 0;
}

// "H:MM" or "HH:MM"; advances p past the time.
inline bool time(const char*& p, uint16_t& minutes) {
  int h = 0, digits = 0;
  while (*p >= '0' && *p <= '9' && digits < 2) {
    h = h * 10 + (*p - '0');
    p++;
    digits++;
  }
  if (digits == 0 || *p != ':') return false;
  p++;
  if (!(p[0] >= '0' && p[0] <= '9' && p[1] >= '0' && p[1] <= '9')) return false;
  int m = (p[0] - '0') * 10 + (p[1] - '0');
  p += 2;
  if (h > 23 || m > 59) return false;
  minutes = (uint16_t)(h * 60 + m);
  return true;
}

}  // namespace sleepsched_detail

// Accepts "HH:MM-HH:MM" (start-end) or "off"; an empty string means "off" as well. Returns false when malformed
// (out is left untouched in that case). start == end is rejected: it would be ambiguous (never or always asleep).
inline bool parseSleepRule(const char* text, SleepRule& out) {
  SleepRule r;
  if (!text || !*text || sleepsched_detail::isOff(text)) {
    out = r;
    return true;
  }
  const char* p = text;
  if (!sleepsched_detail::time(p, r.startMin)) return false;
  if (*p++ != '-') return false;
  if (!sleepsched_detail::time(p, r.endMin)) return false;
  if (*p != 0 || r.startMin == r.endMin) return false;
  r.enabled = true;
  out = r;
  return true;
}

// tmWday: 0 = Sunday .. 6 = Saturday (struct tm). The rule is picked by the local calendar day of the moment being
// evaluated: Saturday and Sunday use `weekend`, the other days `weekday`. A rule with start > end wraps past midnight,
// so on that day the device sleeps from `start` until midnight and from midnight until `end`.
inline bool shouldSleep(const SleepRule& weekday, const SleepRule& weekend, int tmWday, int minuteOfDay) {
  const SleepRule& r = (tmWday == 0 || tmWday == 6) ? weekend : weekday;
  if (!r.enabled) return false;
  if (r.startMin > r.endMin) return minuteOfDay >= r.startMin || minuteOfDay < r.endMin;
  return minuteOfDay >= r.startMin && minuteOfDay < r.endMin;
}
