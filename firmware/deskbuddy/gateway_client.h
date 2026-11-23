#pragma once
#include <Arduino.h>
#include "settings.h"
#include "usage_data.h"

// Keeps Wi-Fi up and fetches /v1/usage. Call tick() from loop(); it never blocks longer than one HTTPS request.
class GatewayClient {
 public:
  void begin(const Settings& s);
  void tick();
  void requestFetchNow() { nextFetchMs_ = 0; }
  void bounceWifi(uint32_t downMs);   // test helper: drop Wi-Fi, reconnect by itself afterwards

  const UsageData& data() const { return data_; }
  NetState net() const { return net_; }
  uint32_t lastOkMs() const { return lastOkMs_; }
  uint32_t fetchCount() const { return fetchCount_; }   // increments on every successful fetch
  int lastHttp() const { return lastHttp_; }
  bool timeSynced() const { return time(nullptr) > 1700000000; }

 private:
  bool fetchOnce();
  void ensureTime();
  const Settings* s_ = nullptr;
  UsageData data_;
  NetState net_ = NET_UNCONFIGURED;
  uint32_t nextFetchMs_ = 0, lastWifiTryMs_ = 0, lastOkMs_ = 0, fetchCount_ = 0;
  uint32_t bounceUntilMs_ = 0;
  int lastHttp_ = 0;
  bool timeStarted_ = false;
};
