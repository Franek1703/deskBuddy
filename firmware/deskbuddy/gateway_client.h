#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include "settings.h"
#include "usage_data.h"

// Keeps Wi-Fi up and fetches /v1/usage. Call tick() from loop(); it never blocks longer than one HTTPS request.
class GatewayClient {
 public:
  void begin(Settings& s);      // non-const: schedule values received from the gateway are stored back to NVS
  void tick();
  void requestFetchNow() { nextFetchMs_ = 0; }
  void bounceWifi(uint32_t downMs);   // test helper: drop Wi-Fi, reconnect by itself afterwards
  void sleep(bool on);                // true: Wi-Fi off and no polling; false: reconnect and fetch right away
  bool sleeping() const { return sleeping_; }
  bool clockTrusted() const;          // clock verified by SNTP or the gateway (the build-time fallback does not count)

  const UsageData& data() const { return data_; }
  NetState net() const { return net_; }
  uint32_t lastOkMs() const { return lastOkMs_; }
  uint32_t fetchCount() const { return fetchCount_; }   // increments on every successful fetch
  int lastHttp() const { return lastHttp_; }
  bool timeSynced() const { return time(nullptr) > 1700000000; }

 private:
  bool fetchOnce();
  void ensureTime();
  void connectWifi();
  void applySleepConfig(JsonVariantConst sleep);
  Settings* s_ = nullptr;
  UsageData data_;
  NetState net_ = NET_UNCONFIGURED;
  uint32_t nextFetchMs_ = 0, lastWifiTryMs_ = 0, lastOkMs_ = 0, fetchCount_ = 0;
  uint32_t bounceUntilMs_ = 0;
  int lastHttp_ = 0;
  bool timeStarted_ = false;
  bool sleeping_ = false;
  mutable bool clockOk_ = false;
};
