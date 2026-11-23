#pragma once
#include <Arduino.h>

// Everything the device needs lives in NVS (namespace "deskbuddy"), written over USB serial.
struct Settings {
  String wifiSsid, wifiPass;
  String gwHost;           // IP or name; must be in the server certificate's SAN
  uint16_t gwPort = 8443;
  String gwKey;            // per-device bearer key
  String gwCa;             // PEM of the local CA (empty = no TLS trust configured)
  bool gwTls = true;
  uint16_t pollS = 30;
  uint8_t tftTab = 2;      // 0 green, 1 red, 2 black (Adafruit INITR_*)
  uint8_t tftRot = 0;      // 0..3
  bool swapRB = false;     // software red/blue swap if the panel is BGR
  bool invert = false;
  uint8_t tftMhz = 8;      // SPI clock; lower it if the picture is skewed or noisy
  uint8_t colOff = 0, rowOff = 0;
  int8_t blPin = -1;       // -1: backlight not driven by the MCU
  bool blOn = true;        // pin level that lights the backlight
};

bool settingsConfigured(const Settings& s);
void settingsLoad(Settings& s);
// Applies one `SET key value`; returns false when the key is unknown or the value is invalid.
bool settingsSet(Settings& s, const String& key, const String& value);
void settingsClear();
void settingsPrint(const Settings& s, Print& out);   // secrets masked
