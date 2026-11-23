#include "gateway_client.h"
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_sntp.h>
#include <sys/time.h>

// Epoch of the firmware build; used as a floor for the clock so certificate "not before" checks can pass
// even if NTP is unreachable. (Approximate: __DATE__/__TIME__ are local time of the build machine.)
// Pure arithmetic (days from civil date) on purpose: mktime() would depend on the TZ environment variable,
// which now holds the user's time zone.
static time_t buildEpoch() {
  static const char* months = "JanFebMarAprMayJunJulAugSepOctNovDec";
  char mon[4] = {__DATE__[0], __DATE__[1], __DATE__[2], 0};
  int m = (int)((strstr(months, mon) - months) / 3) + 1;
  int d = atoi(__DATE__ + 4);
  int y = atoi(__DATE__ + 7);
  y -= m <= 2;
  int era = y / 400;
  unsigned yoe = (unsigned)(y - era * 400);
  unsigned doy = (unsigned)((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1);
  unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  long days = (long)era * 146097L + (long)doe - 719468L;
  return (time_t)(days * 86400L + atoi(__TIME__) * 3600L + atoi(__TIME__ + 3) * 60L + atoi(__TIME__ + 6));
}

void GatewayClient::begin(Settings& s) {
  s_ = &s;
  if (!settingsConfigured(s)) {
    net_ = NET_UNCONFIGURED;
    return;
  }
  connectWifi();
}

void GatewayClient::connectWifi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);
  WiFi.begin(s_->wifiSsid.c_str(), s_->wifiPass.c_str());
  // Super Mini boards drop the link at full power, hence the 8.5 dBm default; `SET wifi_tx <dBm>` overrides it.
  WiFi.setTxPower(s_->wifiTx ? (wifi_power_t)(s_->wifiTx * 4) : WIFI_POWER_8_5dBm);  // quarter-dBm units
  lastWifiTryMs_ = millis();
  net_ = NET_NO_WIFI;
}

void GatewayClient::sleep(bool on) {
  if (on == sleeping_) return;
  sleeping_ = on;
  if (!s_ || !settingsConfigured(*s_)) return;
  if (on) {
    WiFi.disconnect(true, false);
    WiFi.mode(WIFI_OFF);
    net_ = NET_NO_WIFI;
  } else {
    nextFetchMs_ = 0;  // fetch as soon as the link is up
    connectWifi();
  }
}

// The clock is trusted once either SNTP reported a sync or the gateway's own clock (its "now" field; the gateway host
// runs NTP) has been applied. The build-time floor never counts. sntp_get_sync_status() is unreliable on this core
// (it can report RESET even though the time was set), so the gateway time is the dependable source.
bool GatewayClient::clockTrusted() const {
  if (!clockOk_ && sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED) clockOk_ = true;
  return clockOk_;
}

void GatewayClient::bounceWifi(uint32_t downMs) {
  WiFi.disconnect(false, false);
  bounceUntilMs_ = millis() + downMs;
  net_ = NET_NO_WIFI;
}

void GatewayClient::ensureTime() {
  if (timeSynced()) return;
  if (!timeStarted_) {
    struct timeval tv = {buildEpoch(), 0};
    settimeofday(&tv, nullptr);
    configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
    timeStarted_ = true;
  }
}

void GatewayClient::tick() {
  if (!s_ || !settingsConfigured(*s_)) {
    net_ = NET_UNCONFIGURED;
    return;
  }
  if (sleeping_) return;  // Wi-Fi is off during the sleep window
  uint32_t now = millis();
  if (bounceUntilMs_) {
    if ((int32_t)(now - bounceUntilMs_) < 0) return;
    bounceUntilMs_ = 0;
    WiFi.begin(s_->wifiSsid.c_str(), s_->wifiPass.c_str());
    lastWifiTryMs_ = now;
  }
  if (WiFi.status() != WL_CONNECTED) {
    net_ = NET_NO_WIFI;
    if (now - lastWifiTryMs_ > 15000) {  // auto-reconnect sometimes gives up; kick it
      WiFi.disconnect(false, false);
      WiFi.begin(s_->wifiSsid.c_str(), s_->wifiPass.c_str());
      lastWifiTryMs_ = now;
    }
    return;
  }
  ensureTime();
  if ((int32_t)(now - nextFetchMs_) < 0) return;
  bool ok = fetchOnce();
  uint32_t period = (uint32_t)s_->pollS * 1000UL;
  nextFetchMs_ = millis() + (ok ? period : min<uint32_t>(period, 10000UL));  // retry sooner after a failure
}

bool GatewayClient::fetchOnce() {
  uint32_t t0 = millis();
  WiFiClientSecure secure;
  WiFiClient plain;
  HTTPClient http;
  http.setConnectTimeout(6000);
  http.setTimeout(8000);
  http.setReuse(false);
  bool began;
  if (s_->gwTls) {
    secure.setCACert(s_->gwCa.c_str());
    began = http.begin(secure, s_->gwHost, s_->gwPort, "/v1/usage", true);
  } else {
    began = http.begin(plain, s_->gwHost, s_->gwPort, "/v1/usage");
  }
  if (!began) {
    net_ = NET_GW_DOWN;
    return false;
  }
  http.addHeader("Authorization", String("Bearer ") + s_->gwKey);
  int code = http.GET();
  lastHttp_ = code;
  if (code <= 0) {  // connect, TLS or timeout failure
    Serial.printf("FETCH fail err=%s (%d) ms=%u\n", HTTPClient::errorToString(code).c_str(), code, millis() - t0);
    http.end();
    net_ = NET_GW_DOWN;
    return false;
  }
  if (code == 401) {
    Serial.printf("FETCH unauthorized http=401 ms=%u\n", millis() - t0);
    http.end();
    net_ = NET_UNAUTHORIZED;
    return false;
  }
  String body = http.getString();
  http.end();
  if (code != 200) {
    Serial.printf("FETCH bad http=%d ms=%u\n", code, millis() - t0);
    net_ = NET_BAD_REPLY;
    return false;
  }
  JsonDocument doc;
  if (deserializeJson(doc, body) || !doc["services"].is<JsonObject>()) {
    Serial.printf("FETCH bad json bytes=%u\n", (unsigned)body.length());
    net_ = NET_BAD_REPLY;
    return false;
  }
  UsageData d;
  d.valid = true;
  d.seq = doc["seq"] | 0;
  d.served = doc["served"] | 0;
  d.fetchedAtMs = millis();
  auto readWindow = [](JsonVariantConst w, WindowData& out) {
    out = WindowData();
    if (!w["percent"].isNull()) {
      out.has = true;
      out.percent = w["percent"].as<float>();
    }
    if (!w["resets_in_s"].isNull()) {
      out.hasReset = true;
      out.resetsInS = w["resets_in_s"].as<int32_t>();
    }
  };
  auto readService = [&](const char* name, ServiceData& out) {
    JsonVariantConst s = doc["services"][name];
    const char* st = s["state"] | "missing";
    out.state = !strcmp(st, "fresh") ? SVC_FRESH : !strcmp(st, "stale") ? SVC_STALE : SVC_MISSING;
    out.ageS = s["age_s"].isNull() ? -1 : s["age_s"].as<int32_t>();
    readWindow(s["windows"]["5h"], out.w5);
    readWindow(s["windows"]["7d"], out.w7);
  };
  readService("codex", d.codex);
  readService("claude", d.claude);
  applySleepConfig(doc["sleep"]);
  long long gwNow = doc["now"] | 0LL;
  if (gwNow > 1700000000LL) {
    long long diff = (long long)time(nullptr) - gwNow;
    if (diff > 3 || diff < -3) {  // ignore request latency jitter, correct real drift or a missing NTP sync
      struct timeval tv = {(time_t)gwNow, 0};
      settimeofday(&tv, nullptr);
      Serial.printf("CLOCK set from gateway (was off by %llds)\n", diff);
    }
    clockOk_ = true;
  }
  data_ = d;
  net_ = NET_OK;
  lastOkMs_ = d.fetchedAtMs;
  fetchCount_++;
  Serial.printf("FETCH ok http=200 seq=%u served=%u ms=%u\n", d.seq, d.served, millis() - t0);
  return true;
}

// The gateway distributes the sleep schedule; the device keeps the last values in NVS and evaluates them itself.
// NVS is only written when a value actually changed.
void GatewayClient::applySleepConfig(JsonVariantConst sleep) {
  if (!sleep.is<JsonObjectConst>()) return;
  auto apply = [&](const char* jsonKey, const char* nvsKey, const String& current) {
    const char* v = sleep[jsonKey] | (const char*)nullptr;
    if (v && current != v && settingsSet(*s_, nvsKey, v)) Serial.printf("SLEEPCFG %s=%s (from gateway)\n", nvsKey, v);
  };
  apply("weekdays", "sleep_wd", s_->sleepWd);
  apply("weekend", "sleep_we", s_->sleepWe);
  apply("tz", "tz", s_->tz);
}
