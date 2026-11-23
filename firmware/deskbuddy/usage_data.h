#pragma once
#include <Arduino.h>

enum SvcState : uint8_t { SVC_MISSING = 0, SVC_FRESH = 1, SVC_STALE = 2 };

struct WindowData {
  bool has = false;        // percent known
  float percent = 0;
  bool hasReset = false;   // countdown known
  int32_t resetsInS = 0;   // seconds until reset, as of fetchedAtMs
};

struct ServiceData {
  SvcState state = SVC_MISSING;
  int32_t ageS = -1;       // seconds since the gateway's last successful read, as of fetchedAtMs
  WindowData w5, w7;
};

struct UsageData {
  bool valid = false;      // at least one successful fetch since boot
  uint32_t seq = 0;        // collector snapshot number
  uint32_t served = 0;     // gateway response counter (matches the gateway log line)
  uint32_t fetchedAtMs = 0;
  ServiceData codex, claude;
};

enum NetState : uint8_t {
  NET_OK = 0,
  NET_UNCONFIGURED,  // no Wi-Fi / gateway settings in NVS
  NET_NO_WIFI,
  NET_GW_DOWN,       // connect/TLS/timeout failure
  NET_UNAUTHORIZED,  // HTTP 401: wrong device key
  NET_BAD_REPLY      // HTTP error or unparsable JSON
};
