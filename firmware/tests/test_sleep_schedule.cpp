// Host-side test of sleep_schedule.h:
//   clang++ -std=c++17 -I firmware/deskbuddy firmware/tests/test_sleep_schedule.cpp -o /tmp/t && /tmp/t
#include <cstdio>
#include "sleep_schedule.h"

static int failures = 0;
#define CHECK(cond)                                                   \
  do {                                                                \
    if (!(cond)) {                                                    \
      std::printf("FAIL line %d: %s\n", __LINE__, #cond);             \
      failures++;                                                     \
    }                                                                 \
  } while (0)

static SleepRule rule(const char* text) {
  SleepRule r;
  if (!parseSleepRule(text, r)) std::printf("unexpected parse failure: %s\n", text), failures++;
  return r;
}
static int hm(int h, int m) { return h * 60 + m; }

int main() {
  // parsing
  SleepRule r;
  CHECK(parseSleepRule("22:00-07:00", r) && r.enabled && r.startMin == 1320 && r.endMin == 420);
  CHECK(parseSleepRule("7:05-9:30", r) && r.enabled && r.startMin == 425 && r.endMin == 570);
  CHECK(parseSleepRule("off", r) && !r.enabled);
  CHECK(parseSleepRule("OFF", r) && !r.enabled);
  CHECK(parseSleepRule("", r) && !r.enabled);
  CHECK(parseSleepRule(nullptr, r) && !r.enabled);
  SleepRule keep;
  keep.enabled = true; keep.startMin = 1; keep.endMin = 2;
  const char* bad[] = {"22:00", "24:00-07:00", "22:60-07:00", "22:00-22:00", "22-7", "22:00-07:00x", "22:00-", "-07:00",
                       "2200-0700", "22:0-07:00", "offf", "22:00 - 07:00", "123:00-07:00"};
  for (const char* b : bad) {
    SleepRule t = keep;
    CHECK(!parseSleepRule(b, t));
    CHECK(t.enabled && t.startMin == 1 && t.endMin == 2);  // untouched on failure
  }

  // wrap-around window on all days: 22:00-07:00
  SleepRule night = rule("22:00-07:00");
  for (int wd = 0; wd < 7; wd++) {
    CHECK(!shouldSleep(night, night, wd, hm(21, 59)));
    CHECK(shouldSleep(night, night, wd, hm(22, 0)));
    CHECK(shouldSleep(night, night, wd, hm(23, 59)));
    CHECK(shouldSleep(night, night, wd, hm(0, 0)));
    CHECK(shouldSleep(night, night, wd, hm(6, 59)));
    CHECK(!shouldSleep(night, night, wd, hm(7, 0)));
    CHECK(!shouldSleep(night, night, wd, hm(12, 0)));
  }

  // weekday / weekend selection: weekdays 22:00-07:00, weekend 23:30-09:00 (0 = Sunday, 6 = Saturday)
  SleepRule wd = rule("22:00-07:00"), we = rule("23:30-09:00");
  CHECK(shouldSleep(wd, we, 1, hm(22, 15)));   // Monday evening: weekday rule
  CHECK(!shouldSleep(wd, we, 6, hm(22, 15)));  // Saturday evening: weekend rule says still awake
  CHECK(shouldSleep(wd, we, 6, hm(23, 30)));
  CHECK(!shouldSleep(wd, we, 6, hm(9, 0)));    // Saturday morning: awake from the weekend end time
  CHECK(shouldSleep(wd, we, 6, hm(8, 59)));
  CHECK(shouldSleep(wd, we, 0, hm(8, 0)));     // Sunday morning: weekend rule
  CHECK(!shouldSleep(wd, we, 1, hm(8, 0)));    // Monday morning: weekday rule, awake after 07:00
  CHECK(shouldSleep(wd, we, 5, hm(23, 0)));    // Friday 23:00: weekday rule, asleep

  // same-day window (no wrap): 13:00-14:30
  SleepRule nap = rule("13:00-14:30");
  CHECK(!shouldSleep(nap, nap, 3, hm(12, 59)));
  CHECK(shouldSleep(nap, nap, 3, hm(13, 0)));
  CHECK(shouldSleep(nap, nap, 3, hm(14, 29)));
  CHECK(!shouldSleep(nap, nap, 3, hm(14, 30)));
  CHECK(!shouldSleep(nap, nap, 3, hm(0, 0)));

  // disabled rule never sleeps; one disabled rule does not disable the other
  SleepRule off = rule("off");
  CHECK(!shouldSleep(off, off, 2, hm(3, 0)));
  CHECK(!shouldSleep(off, night, 2, hm(3, 0)));
  CHECK(shouldSleep(off, night, 6, hm(3, 0)));

  if (failures) {
    std::printf("%d check(s) failed\n", failures);
    return 1;
  }
  std::printf("all sleep schedule checks passed\n");
  return 0;
}
