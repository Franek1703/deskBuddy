// DeskBuddy: Codex + Claude subscription limits on an ESP32-C3 Super Mini with a 1.8" ST7735 (128x160).
// Settings (Wi-Fi, gateway address/key/CA, panel variant) live in NVS and are written over USB serial:
// see tools/provision.py. Serial lines: FETCH ok ... / RENDER seq=.. served=.. are matched against gateway logs.
#include <WiFi.h>
#include "gateway_client.h"
#include "settings.h"
#include "ui.h"
#include "usage_data.h"

#define FW_VERSION "0.1.0"

static Settings settings;
static GatewayClient client;
static String line;
static uint32_t lastRenderMs = 0, lastRenderedFetch = 0;
static bool showingTest = false;

static const char* netName(NetState n) {
  switch (n) {
    case NET_OK: return "ok";
    case NET_UNCONFIGURED: return "unconfigured";
    case NET_NO_WIFI: return "no_wifi";
    case NET_GW_DOWN: return "gateway_down";
    case NET_UNAUTHORIZED: return "unauthorized";
    case NET_BAD_REPLY: return "bad_reply";
  }
  return "?";
}

static void printStatus() {
  const UsageData& d = client.data();
  Serial.printf("STATUS net=%s wifi=%s rssi=%d ip=%s time=%s http=%d fetches=%u seq=%u served=%u heap=%u up=%us\n",
                netName(client.net()), WiFi.status() == WL_CONNECTED ? "up" : "down", WiFi.RSSI(),
                WiFi.localIP().toString().c_str(), client.timeSynced() ? "synced" : "unsynced", client.lastHttp(),
                client.fetchCount(), d.seq, d.served, ESP.getFreeHeap(), millis() / 1000);
}

static void handleLine(String cmd) {
  cmd.trim();
  if (!cmd.length()) return;
  int sp = cmd.indexOf(' ');
  String verb = sp < 0 ? cmd : cmd.substring(0, sp);
  String rest = sp < 0 ? "" : cmd.substring(sp + 1);
  verb.toUpperCase();
  if (verb == "HELP") {
    Serial.println("OK commands: HELP STATUS GET SET <key> <value> CLEAR TEST (hold pattern) APPLY (re-init + resume) FETCH SCAN WIFI_BOUNCE [sec] REBOOT");
  } else if (verb == "STATUS") {
    printStatus();
  } else if (verb == "GET") {
    settingsPrint(settings, Serial);
    Serial.println("OK");
  } else if (verb == "SET") {
    int s2 = rest.indexOf(' ');
    String key = s2 < 0 ? rest : rest.substring(0, s2);
    String val = s2 < 0 ? "" : rest.substring(s2 + 1);
    Serial.println(settingsSet(settings, key, val) ? "OK saved" : "ERR unknown key or bad value");
  } else if (verb == "CLEAR") {
    settingsClear();
    settingsLoad(settings);
    Serial.println("OK cleared; REBOOT to apply");
  } else if (verb == "TEST" || verb == "APPLY") {
    ui::begin(settings);  // re-init the panel with the current tft_* values
    if (verb == "TEST") {
      ui::showTestPattern(settings, "TEST PATTERN", "bar1 must be RED");
      showingTest = true;  // held until APPLY or reboot
    } else {
      showingTest = false;
    }
    Serial.println("OK");
  } else if (verb == "FETCH") {
    client.requestFetchNow();
    Serial.println("OK");
  } else if (verb == "WIFI_BOUNCE") {
    int secs = rest.length() ? rest.toInt() : 20;
    client.bounceWifi((uint32_t)constrain(secs, 1, 300) * 1000UL);
    Serial.printf("OK wifi down for %ds\n", constrain(secs, 1, 300));
  } else if (verb == "SCAN") {  // 2.4 GHz networks only: what the ESP32 can actually join
    WiFi.mode(WIFI_STA);
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++)
      Serial.printf("AP ssid=%s rssi=%d ch=%d open=%d\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i),
                    WiFi.encryptionType(i) == WIFI_AUTH_OPEN);
    WiFi.scanDelete();
    Serial.printf("OK %d networks\n", n);
  } else if (verb == "REBOOT") {
    Serial.println("OK rebooting");
    Serial.flush();
    delay(100);
    ESP.restart();
  } else {
    Serial.println("ERR unknown command (HELP)");
  }
}

static void pollSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      handleLine(line);
      line = "";
    } else if (c != '\r' && line.length() < 6000) {
      line += c;
    }
  }
}

void setup() {
  Serial.setRxBufferSize(8192);  // the CA certificate arrives as one long line
  Serial.begin(115200);
  delay(300);
  settingsLoad(settings);
  ui::begin(settings);
  Serial.printf("BOOT fw=%s build=%s %s configured=%d\n", FW_VERSION, __DATE__, __TIME__, settingsConfigured(settings));
  if (!settingsConfigured(settings)) {
    ui::showTestPattern(settings, "NOT CONFIGURED", "run tools/provision.py");
    showingTest = true;
  }
  client.begin(settings);
}

void loop() {
  pollSerial();
  client.tick();
  uint32_t now = millis();
  if (!showingTest) {
    if (client.fetchCount() != lastRenderedFetch || now - lastRenderMs >= 1000) {
      ui::render(client.data(), client.net(), now, client.lastOkMs());
      lastRenderMs = now;
      if (client.fetchCount() != lastRenderedFetch) {
        lastRenderedFetch = client.fetchCount();
        const UsageData& d = client.data();
        auto pct = [](const WindowData& w) { return w.has ? (int)lroundf(w.percent) : -1; };
        Serial.printf("RENDER seq=%u served=%u net=%s codex5h=%d codex7d=%d claude5h=%d claude7d=%d\n", d.seq, d.served,
                      netName(client.net()), pct(d.codex.w5), pct(d.codex.w7), pct(d.claude.w5), pct(d.claude.w7));
      }
    }
  }
  delay(5);
}
