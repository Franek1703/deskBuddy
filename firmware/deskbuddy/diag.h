#pragma once
#include <Arduino.h>
#include <WiFi.h>

// Field diagnostics for "no Wi-Fi" problems when no USB host is attached: reset cause, a counter of abnormal resets
// (brownout / panic / watchdog) that survives resets but not a power cycle, and the last Wi-Fi disconnect reason.
namespace diag {

void begin();                          // call first thing in setup()
const char* resetName();               // POWERON, BROWNOUT, PANIC, ...
uint16_t abnormalResets();             // abnormal resets since the last power-on
char abnormalLetter();                 // 'B' brownout, 'P' panic, 'W' watchdog, 0 otherwise
uint8_t lastDisconnectReason();        // 0 = none yet; own disconnects (reason 8) are not recorded
uint32_t disconnectCount();
uint32_t firstIpMs();                  // millis() at the first GOT_IP, 0 = never
const char* disconnectName(uint8_t reason);

}  // namespace diag
