#pragma once
// ESP32-C3 Super Mini -> 1.8" ST7735 128x160 (hardware SPI). Matches the wiring in the plan.
#define PIN_TFT_SCK   4   // SCK
#define PIN_TFT_MOSI  6   // SDA / MOSI
#define PIN_TFT_CS    7   // CS
#define PIN_TFT_DC    3   // A0 / DC
#define PIN_TFT_RST   1   // RESET
// VCC -> 3V3, GND -> GND. LED (backlight) is configured at runtime: SET bl_pin <gpio|-1>, SET bl_on <0|1>.

#define SCREEN_W 128
#define SCREEN_H 160
