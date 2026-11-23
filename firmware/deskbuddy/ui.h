#pragma once
#include <Arduino.h>
#include "settings.h"
#include "usage_data.h"

namespace ui {
void begin(const Settings& s);                       // (re)initialise the panel and backlight
void showTestPattern(const Settings& s, const char* line1, const char* line2);
void render(const UsageData& d, NetState net, uint32_t nowMs, uint32_t lastOkMs);
}  // namespace ui
