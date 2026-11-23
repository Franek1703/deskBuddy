#include "settings.h"
#include <Preferences.h>

static const char* NS = "deskbuddy";

bool settingsConfigured(const Settings& s) {
  return s.wifiSsid.length() && s.gwHost.length() && s.gwKey.length() && (!s.gwTls || s.gwCa.length());
}

void settingsLoad(Settings& s) {
  Preferences p;
  p.begin(NS, true);
  s.wifiSsid = p.getString("wifi_ssid", "");
  s.wifiPass = p.getString("wifi_pass", "");
  s.gwHost = p.getString("gw_host", "");
  s.gwPort = p.getUShort("gw_port", 8443);
  s.gwKey = p.getString("gw_key", "");
  s.gwCa = p.getString("gw_ca", "");
  s.gwTls = p.getBool("gw_tls", true);
  s.pollS = p.getUShort("poll_s", 30);
  s.tftTab = p.getUChar("tft_tab", 2);
  s.tftRot = p.getUChar("tft_rot", 0);
  s.swapRB = p.getBool("tft_swaprb", false);
  s.invert = p.getBool("tft_inv", false);
  s.tftMhz = p.getUChar("tft_mhz", 8);
  s.colOff = p.getUChar("col_off", 0);
  s.rowOff = p.getUChar("row_off", 0);
  s.blPin = (int8_t)p.getChar("bl_pin", -1);
  s.blOn = p.getBool("bl_on", true);
  p.end();
}

static bool parseBool(const String& v, bool& out) {
  if (v == "1" || v == "true" || v == "on") { out = true; return true; }
  if (v == "0" || v == "false" || v == "off") { out = false; return true; }
  return false;
}

static bool parseInt(const String& v, long lo, long hi, long& out) {
  if (!v.length()) return false;
  char* end = nullptr;
  long n = strtol(v.c_str(), &end, 10);
  if (*end || n < lo || n > hi) return false;
  out = n;
  return true;
}

bool settingsSet(Settings& s, const String& key, const String& value) {
  Preferences p;
  p.begin(NS, false);
  bool ok = true;
  long n = 0;
  bool b = false;
  if (key == "wifi_ssid") { s.wifiSsid = value; p.putString("wifi_ssid", value); }
  else if (key == "wifi_pass") { s.wifiPass = value; p.putString("wifi_pass", value); }
  else if (key == "gw_host") { s.gwHost = value; p.putString("gw_host", value); }
  else if (key == "gw_key") { s.gwKey = value; p.putString("gw_key", value); }
  else if (key == "gw_ca") {
    String pem = value;
    pem.replace("|", "\n");  // the provisioning tool sends the PEM on one line, newlines as '|'
    if (pem.length() && !pem.endsWith("\n")) pem += "\n";
    s.gwCa = pem;
    p.putString("gw_ca", pem);
  }
  else if (key == "gw_port" && parseInt(value, 1, 65535, n)) { s.gwPort = n; p.putUShort("gw_port", n); }
  else if (key == "gw_tls" && parseBool(value, b)) { s.gwTls = b; p.putBool("gw_tls", b); }
  else if (key == "poll_s" && parseInt(value, 5, 3600, n)) { s.pollS = n; p.putUShort("poll_s", n); }
  else if (key == "tft_tab" && parseInt(value, 0, 2, n)) { s.tftTab = n; p.putUChar("tft_tab", n); }
  else if (key == "tft_rot" && parseInt(value, 0, 2, n) && n != 1) { s.tftRot = n; p.putUChar("tft_rot", n); }
  else if (key == "tft_swaprb" && parseBool(value, b)) { s.swapRB = b; p.putBool("tft_swaprb", b); }
  else if (key == "tft_inv" && parseBool(value, b)) { s.invert = b; p.putBool("tft_inv", b); }
  else if (key == "tft_mhz" && parseInt(value, 1, 40, n)) { s.tftMhz = n; p.putUChar("tft_mhz", n); }
  else if (key == "col_off" && parseInt(value, 0, 40, n)) { s.colOff = n; p.putUChar("col_off", n); }
  else if (key == "row_off" && parseInt(value, 0, 40, n)) { s.rowOff = n; p.putUChar("row_off", n); }
  else if (key == "bl_pin" && parseInt(value, -1, 21, n)) { s.blPin = n; p.putChar("bl_pin", n); }
  else if (key == "bl_on" && parseBool(value, b)) { s.blOn = b; p.putBool("bl_on", b); }
  else ok = false;
  p.end();
  return ok;
}

void settingsClear() {
  Preferences p;
  p.begin(NS, false);
  p.clear();
  p.end();
}

static String mask(const String& v) {
  if (!v.length()) return "(unset)";
  return String("(set, ") + v.length() + " chars)";
}

void settingsPrint(const Settings& s, Print& out) {
  out.printf("wifi_ssid=%s\n", s.wifiSsid.length() ? s.wifiSsid.c_str() : "(unset)");
  out.printf("wifi_pass=%s\n", mask(s.wifiPass).c_str());
  out.printf("gw_host=%s gw_port=%u gw_tls=%d poll_s=%u\n", s.gwHost.length() ? s.gwHost.c_str() : "(unset)",
             s.gwPort, s.gwTls, s.pollS);
  out.printf("gw_key=%s\n", mask(s.gwKey).c_str());
  out.printf("gw_ca=%s\n", mask(s.gwCa).c_str());
  out.printf("tft_mhz=%u tft_tab=%u tft_rot=%u tft_swaprb=%d tft_inv=%d col_off=%u row_off=%u bl_pin=%d bl_on=%d\n", s.tftMhz, s.tftTab,
             s.tftRot, s.swapRB, s.invert, s.colOff, s.rowOff, s.blPin, s.blOn);
  out.printf("configured=%d\n", settingsConfigured(s));
}
