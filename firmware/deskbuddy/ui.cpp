#include "ui.h"
#include "diag.h"
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>
#include "pins.h"

namespace {

// Subclass only to reach the protected panel offsets some 128x160 modules need.
class Panel : public Adafruit_ST7735 {
 public:
  using Adafruit_ST7735::Adafruit_ST7735;
  void setOffsets(uint8_t col, uint8_t row) { _colstart = col; _rowstart = row; }
};

Panel* tft = nullptr;
GFXcanvas16* canvas = nullptr;
bool swapRB = false;
uint32_t renderCount = 0;

uint16_t C(uint8_t r, uint8_t g, uint8_t b) {
  if (swapRB) { uint8_t t = r; r = b; b = t; }
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}

uint8_t mix(uint8_t a, uint8_t b, uint8_t pct) { return (a * (100 - pct) + b * pct) / 100; }

struct Rgb { uint8_t r, g, b; };
const Rgb BG{8, 10, 14}, CARD{22, 27, 36}, TRACK{44, 52, 66}, TEXT{238, 243, 248}, MUTED{120, 130, 146};
const Rgb MINT{74, 222, 170}, ORANGE{245, 150, 72}, AMBER{250, 204, 70}, RED{242, 84, 84}, GREEN{80, 210, 120};

uint16_t col(Rgb c, bool dim = false) {
  if (dim) c = {mix(c.r, CARD.r, 62), mix(c.g, CARD.g, 62), mix(c.b, CARD.b, 62)};
  return C(c.r, c.g, c.b);
}

void fmtDuration(int32_t s, char* out, size_t n) {
  if (s < 0) s = 0;
  int d = s / 86400, h = (s % 86400) / 3600, m = (s % 3600) / 60;
  if (d > 0) snprintf(out, n, "%dd%dh", d, h);
  else if (h > 0) snprintf(out, n, "%dh%02dm", h, m);
  else if (s == 0) snprintf(out, n, "0m");
  else if (m == 0) snprintf(out, n, "<1m");
  else snprintf(out, n, "%dm", m);
}

void fmtAge(int32_t s, char* out, size_t n) {
  if (s < 0) { snprintf(out, n, "?"); return; }
  if (s < 90) snprintf(out, n, "%ds", (int)s);
  else if (s < 5400) snprintf(out, n, "%dm", (int)(s / 60));
  else snprintf(out, n, "%dh", (int)(s / 3600));
}

void textAt(Adafruit_GFX& g, int x, int y, const char* s, uint16_t color, uint8_t size = 1) {
  g.setTextSize(size);
  g.setTextColor(color);
  g.setCursor(x, y);
  g.print(s);
}

void textRight(Adafruit_GFX& g, int xr, int y, const char* s, uint16_t color) {
  int16_t x1, y1;
  uint16_t w, h;
  g.setTextSize(1);
  g.getTextBounds(s, 0, 0, &x1, &y1, &w, &h);
  textAt(g, xr - w, y, s, color);
}

Rgb levelColor(float pct, Rgb accent) { return pct >= 90 ? RED : pct >= 75 ? AMBER : accent; }

void drawRow(Adafruit_GFX& g, int y, const char* label, const WindowData& w, Rgb accent, bool dim,
             int32_t elapsedS) {
  const int barX = 60, barW = 62;
  char buf[16];
  if (w.has) {
    snprintf(buf, sizeof buf, "%d%%", (int)lroundf(w.percent));
    textAt(g, 7, y + 4, buf, col(TEXT, dim), 2);
  } else {
    g.fillRect(9, y + 11, 14, 2, col(MUTED, dim));  // "—": no reading
  }
  textAt(g, barX, y + 2, label, col(MUTED, dim));
  if (w.hasReset) {
    int32_t left = w.resetsInS - elapsedS;
    fmtDuration(left, buf, sizeof buf);
  } else {
    snprintf(buf, sizeof buf, "--");
  }
  textRight(g, barX + barW, y + 2, buf, col(TEXT, dim));
  g.fillRoundRect(barX, y + 13, barW, 8, 3, col(TRACK, dim));
  if (w.has && w.percent > 0) {
    int fill = (int)lroundf(w.percent * barW / 100.0f);
    if (fill < 4) fill = 4;
    if (fill > barW) fill = barW;
    g.fillRoundRect(barX, y + 13, fill, 8, 3, col(levelColor(w.percent, accent), dim));
  }
}

void drawCard(Adafruit_GFX& g, int y, const char* name, Rgb accent, const ServiceData& sv, bool netOk,
              int32_t elapsedS) {
  bool dim = !netOk || sv.state != SVC_FRESH;
  g.fillRoundRect(2, y, 124, 72, 5, col(CARD));
  g.fillRoundRect(2, y + 2, 3, 10, 1, col(accent, dim));
  textAt(g, 9, y + 4, name, col(accent, dim));
  char badge[24] = "";
  char age[12];
  fmtAge(sv.ageS < 0 ? -1 : sv.ageS + elapsedS, age, sizeof age);
  if (sv.state == SVC_MISSING) snprintf(badge, sizeof badge, "NO DATA");
  else if (!netOk) snprintf(badge, sizeof badge, "OFFLINE %s", age);
  else if (sv.state == SVC_STALE) snprintf(badge, sizeof badge, "OLD %s", age);
  if (badge[0]) textRight(g, 122, y + 4, badge, col(sv.state == SVC_STALE || !netOk ? AMBER : MUTED, false));
  drawRow(g, y + 15, "5h", sv.w5, accent, dim, elapsedS);
  drawRow(g, y + 44, "7d", sv.w7, accent, dim, elapsedS);
}

}  // namespace

namespace ui {

void begin(const Settings& s) {
  swapRB = s.swapRB;
  if (s.blPin >= 0) {
    pinMode(s.blPin, OUTPUT);
    digitalWrite(s.blPin, s.blOn ? HIGH : LOW);
  }
  SPI.begin(PIN_TFT_SCK, -1, PIN_TFT_MOSI, PIN_TFT_CS);
  if (!tft) tft = new Panel(&SPI, PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);
  static const uint8_t tabs[] = {INITR_GREENTAB, INITR_REDTAB, INITR_BLACKTAB};
  tft->initR(tabs[s.tftTab > 2 ? 2 : s.tftTab]);
  tft->setSPISpeed((uint32_t)s.tftMhz * 1000000UL);  // initR runs at the library default (24 MHz); drop it now
  if (s.colOff || s.rowOff) tft->setOffsets(s.colOff, s.rowOff);
  tft->setRotation(s.tftRot);
  tft->invertDisplay(s.invert);
  tft->fillScreen(0);
  if (!canvas) canvas = new GFXcanvas16(SCREEN_W, SCREEN_H);
}

void showTestPattern(const Settings& s, const char* line1, const char* line2) {
  Adafruit_GFX& g = *canvas;
  g.fillScreen(C(0, 0, 0));
  // 8 bars: RED GREEN BLUE WHITE CYAN MAGENTA YELLOW GREY. If bar 1 is blue, set tft_swaprb 1.
  const Rgb bars[8] = {{255, 0, 0}, {0, 255, 0}, {0, 0, 255}, {255, 255, 255},
                       {0, 255, 255}, {255, 0, 255}, {255, 255, 0}, {110, 110, 110}};
  for (int i = 0; i < 8; i++) g.fillRect(i * 16, 22, 16, 44, C(bars[i].r, bars[i].g, bars[i].b));
  for (int x = 0; x < SCREEN_W; x++) {  // grey ramp: banding / inversion check
    uint8_t v = x * 255 / (SCREEN_W - 1);
    g.drawFastVLine(x, 68, 8, C(v, v, v));
  }
  textAt(g, 4, 12, "R G B W C M Y", C(255, 255, 255));
  textAt(g, 14, 84, "DeskBuddy", C(255, 255, 255), 2);
  textAt(g, 4, 108, line1, C(255, 255, 0));
  textAt(g, 4, 120, line2, C(0, 255, 255));
  char buf[40];
  snprintf(buf, sizeof buf, "tab%u rot%u rb%u inv%u %uM", s.tftTab, s.tftRot, s.swapRB, s.invert, s.tftMhz);
  textAt(g, 4, 132, buf, C(160, 160, 160));
  // 1 px frame + asymmetric corner marks: frame cut off = offset wrong, mirrored text = rotation wrong.
  g.drawRect(0, 0, SCREEN_W, SCREEN_H, C(255, 255, 255));
  textAt(g, 3, 3, "TL", C(255, 80, 80));
  textRight(g, SCREEN_W - 3, 3, "TR", C(80, 255, 80));
  textAt(g, 3, SCREEN_H - 11, "BL", C(80, 160, 255));
  textRight(g, SCREEN_W - 3, SCREEN_H - 11, "BR", C(255, 255, 80));
  tft->drawRGBBitmap(0, 0, canvas->getBuffer(), SCREEN_W, SCREEN_H);
}

void render(const UsageData& d, NetState net, uint32_t nowMs, uint32_t lastOkMs) {
  Adafruit_GFX& g = *canvas;
  bool netOk = net == NET_OK;
  int32_t elapsedS = d.valid ? (int32_t)((nowMs - d.fetchedAtMs) / 1000) : 0;
  g.fillScreen(col(BG));
  drawCard(g, 2, "CODEX", MINT, d.codex, netOk, elapsedS);
  drawCard(g, 77, "CLAUDE", ORANGE, d.claude, netOk, elapsedS);

  char buf[32];
  char age[12];
  const char* msg = "";
  Rgb c = MUTED;
  switch (net) {
    case NET_OK: msg = "LIVE"; c = GREEN; break;
    case NET_UNCONFIGURED: msg = "SETUP VIA USB"; c = AMBER; break;
    case NET_NO_WIFI: msg = "NO WIFI"; c = RED; break;
    case NET_GW_DOWN: msg = "GATEWAY DOWN"; c = RED; break;
    case NET_UNAUTHORIZED: msg = "BAD KEY"; c = RED; break;
    case NET_BAD_REPLY: msg = "BAD REPLY"; c = RED; break;
  }
  char diagTxt[16] = "";
  if (net == NET_NO_WIFI) {  // field diagnostics: d<last disconnect reason> B/P/W<abnormal resets since power-on>
    int n = 0;
    if (diag::lastDisconnectReason()) n += snprintf(diagTxt + n, sizeof diagTxt - n, " d%u", diag::lastDisconnectReason());
    if (diag::abnormalResets()) snprintf(diagTxt + n, sizeof diagTxt - n, " %c%u", diag::abnormalLetter(), diag::abnormalResets());
  }
  if (!netOk && lastOkMs) {
    fmtAge((nowMs - lastOkMs) / 1000, age, sizeof age);
    snprintf(buf, sizeof buf, "%s %s%s", msg, age, diagTxt);
  } else {
    snprintf(buf, sizeof buf, "%s%s", msg, diagTxt);
  }
  textAt(g, 4, 152, buf, col(c));
  if (d.valid) {
    snprintf(buf, sizeof buf, "#%u", (unsigned)d.seq);
    textRight(g, 124, 152, buf, col(MUTED));
  }
  tft->drawRGBBitmap(0, 0, canvas->getBuffer(), SCREEN_W, SCREEN_H);
  renderCount++;
}

}  // namespace ui
