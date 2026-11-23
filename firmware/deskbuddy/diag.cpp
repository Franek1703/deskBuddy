#include "diag.h"
#include <esp_attr.h>
#include <esp_system.h>

namespace diag {

static RTC_NOINIT_ATTR uint32_t rtcMagic;
static RTC_NOINIT_ATTR uint16_t rtcAbnormal;
static RTC_NOINIT_ATTR uint8_t rtcLetter;
static const uint32_t MAGIC = 0xD35CB0DD;

static esp_reset_reason_t reason_ = ESP_RST_UNKNOWN;
static volatile uint8_t lastDisc_ = 0;
static volatile uint32_t discCount_ = 0, firstIpMs_ = 0;

static void onEvent(arduino_event_id_t ev, arduino_event_info_t info) {
  if (ev == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    uint8_t r = info.wifi_sta_disconnected.reason;
    if (r == 8) return;  // WIFI_REASON_ASSOC_LEAVE: we asked for it (our own retry), not a link problem
    lastDisc_ = r;
    discCount_++;
    Serial.printf("WIFI disconnected reason=%u (%s) t=%lus\n", r, disconnectName(r), (unsigned long)(millis() / 1000));
  } else if (ev == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    if (!firstIpMs_) firstIpMs_ = millis();
    Serial.printf("WIFI got_ip t=%lus\n", (unsigned long)(millis() / 1000));
  }
}

void begin() {
  reason_ = esp_reset_reason();
  if (reason_ == ESP_RST_POWERON || rtcMagic != MAGIC) {
    rtcMagic = MAGIC;
    rtcAbnormal = 0;
    rtcLetter = 0;
  }
  switch (reason_) {
    case ESP_RST_BROWNOUT: rtcAbnormal++; rtcLetter = 'B'; break;
    case ESP_RST_PANIC: rtcAbnormal++; rtcLetter = 'P'; break;
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: rtcAbnormal++; rtcLetter = 'W'; break;
    default: break;  // software reset, USB/EXT reset, deep sleep: not counted
  }
  WiFi.onEvent(onEvent);
}

const char* resetName() {
  switch (reason_) {
    case ESP_RST_POWERON: return "POWERON";
    case ESP_RST_SW: return "SW";
    case ESP_RST_PANIC: return "PANIC";
    case ESP_RST_INT_WDT: return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT: return "WDT";
    case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    case ESP_RST_EXT: return "EXT";
    case ESP_RST_USB: return "USB";
    default: return "OTHER";
  }
}

uint16_t abnormalResets() { return rtcMagic == MAGIC ? rtcAbnormal : 0; }
char abnormalLetter() { return abnormalResets() ? (char)rtcLetter : 0; }
uint8_t lastDisconnectReason() { return lastDisc_; }
uint32_t disconnectCount() { return discCount_; }
uint32_t firstIpMs() { return firstIpMs_; }

const char* disconnectName(uint8_t r) {
  switch (r) {
    case 2: return "AUTH_EXPIRE";
    case 4: return "ASSOC_EXPIRE";
    case 6: return "NOT_AUTHED";
    case 15: return "4WAY_HANDSHAKE_TIMEOUT";
    case 200: return "BEACON_TIMEOUT";
    case 201: return "NO_AP_FOUND";
    case 202: return "AUTH_FAIL";
    case 203: return "ASSOC_FAIL";
    case 204: return "HANDSHAKE_TIMEOUT";
    case 205: return "CONNECTION_FAIL";
    default: return "OTHER";
  }
}

}  // namespace diag
