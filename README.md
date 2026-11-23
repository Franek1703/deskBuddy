# DeskBuddy

A monitor for **Codex (5 h and 7 days)** and **Claude (5 h and 7 days)** subscription limits on an ESP32‑C3 Super Mini with a 128 × 160 ST7735 display.
Each row shows the usage percentage and the time until reset. A gateway on a Mac collects the data from the native CLIs and serves it over HTTPS on the LAN;
the ESP32 only fetches and draws it.

```
 codex app-server ─┐                                   ┌── GET /v1/usage (HTTPS, device key)
                   ├─ collector ─ usage.json ─ gateway ┤
 claude -p /usage ─┘  (host, launchd)  (ro volume)  (Docker)   └── ESP32‑C3 + ST7735
```

## Layout

| Directory | Contents |
|---|---|
| `gateway/` | the `deskbuddy_gateway` package (Python standard library only): collector, HTTPS server, tests, `Dockerfile` |
| `firmware/deskbuddy/` | Arduino sketch (ESP32 core `3.3.11`, Adafruit ST7735/GFX, ArduinoJson) |
| `deploy/` | `compose.yaml`, certificate generator, `launchd` agent for the collector |
| `tools/` | USB provisioning (`provision.py`), serial log (`serial_log.py`), test scenarios (`write_scenario.py`) |
| `examples/` | example `usage.json` |

## Data

* **Codex**: `codex app-server`, JSON‑RPC `account/rateLimits/read`. Windows are identified by `windowDurationMins` (300 = 5 h, 10 080 = 7 days), not by `primary`/`secondary` order. Polled every 2 min.
* **Claude**: `claude -p /usage` (native Claude Code; no model call, no tokens). The parser reads the `Current session` and `Current week (all models)` rows and the reset time with the time zone from the parentheses. Polled every 5 min.
  The command is configurable (`--claude-cmd`), so the collector can also run it over SSH on another Mac.
* A failed read **does not erase** the previous values. The collector retries with exponential backoff (up to 30 min) and honours a retry time found in a rate‑limit message. On `rate_limited`, or after 3 missed cycles, the gateway marks the service `stale`.
* An expired countdown **does not reset** the percentage to zero; the screen shows `0m` until the next reading.

### `GET /v1/usage` response

Requires the header `Authorization: Bearer <device key>`. `GET /healthz` is open.

```json
{"schema":1,"seq":12,"served":345,"now":1795426949,
 "services":{"codex":{"state":"fresh","last_success_at":1795426912,"age_s":37,"error":null,"retry_at":null,
   "windows":{"5h":{"percent":93,"resets_at":1795439673,"resets_in_s":12724,"expired":false},
              "7d":{"percent":23,"resets_at":1795955202,"resets_in_s":528253,"expired":false}}},
  "claude":{ "...": "..." }}}
```

`state` is `fresh`, `stale` or `missing`. `seq` is the collector's reading number and `served` is the gateway's response counter.
A gateway log line (`seq=12 served=345`) matches the `RENDER seq=12 served=345` line on the device's USB serial output.

## Running locally (this Mac)

```bash
# 1. Certificates and device key (SAN: the LAN IPs of every host that may run the gateway)
deploy/init_secrets.sh 192.168.0.246 192.168.0.188

# 2. Collector (Codex locally; Claude locally or over SSH)
cd gateway
python3 -m deskbuddy_gateway.collector --data-dir ../deploy/local/data \
  --claude-cmd 'ssh -o BatchMode=yes mini "~/.local/bin/claude -p /usage"'

# 3. Gateway
S=../deploy/local/secrets
DESKBUDDY_DATA_DIR=../deploy/local/data DESKBUDDY_KEYS_FILE=$S/device_keys.txt \
DESKBUDDY_CERT=$S/server.pem DESKBUDDY_KEY=$S/server.key python3 -m deskbuddy_gateway.server
```

### Firmware

```bash
FQBN="esp32:esp32:esp32c3:CDCOnBoot=cdc,PartitionScheme=no_fs"
arduino-cli compile --fqbn "$FQBN" firmware/deskbuddy
arduino-cli upload  --fqbn "$FQBN" -p /dev/cu.usbmodem3101 firmware/deskbuddy
```

Pins: `SCK→GPIO4`, `SDA/MOSI→GPIO6`, `CS→GPIO7`, `A0/DC→GPIO3`, `RESET→GPIO1`, `VCC→3V3`, `GND→GND`. The `LED` (backlight) pin: see below.

### Device configuration over USB (NVS)

Wi‑Fi credentials, the gateway address, the device key and the CA are stored in NVS; changing the gateway address does not require reflashing.
The ESP32‑C3 joins **2.4 GHz networks only** (the `SCAN` command over USB shows what the chip can see).

```bash
python3 tools/provision.py --ssid <2.4GHz_SSID> --gw-host 192.168.0.246   # Wi‑Fi password is prompted in the terminal
python3 tools/provision.py --gw-host 192.168.0.188                        # only switch the gateway
python3 tools/serial_log.py --seconds 60                                  # BOOT / FETCH / RENDER / STATUS
```

Serial commands (115200): `HELP STATUS GET SET <key> <value> CLEAR TEST APPLY FETCH SCAN WIFI_BOUNCE [s] REBOOT`.
Panel settings: `tft_tab` (0 green, 1 red, 2 black; this module works with 2), `tft_mhz` (SPI clock, default 8; at 24 MHz the picture was garbled), `tft_rot` (0 or 2), `tft_swaprb`, `tft_inv`, `col_off`, `row_off`, `bl_pin`, `bl_on`.
`TEST` draws a test plate (8 colour bars, a frame, corner markers); `APPLY` returns to the limits screen after changing settings.

**Wi‑Fi TX power.** `wifi_tx` sets the transmit power in whole dBm (2–20); `0` keeps the 8.5 dBm default. The default is low because Super Mini boards can drop the link at full power,
but on some USB power sources (e.g. a lamp's built‑in port) 8.5 dBm was not enough to finish authentication (`d2`), while `SET wifi_tx 13` connected within 5–6 s.

**Wi‑Fi diagnostics without a computer.** While Wi‑Fi is down the status line reads e.g. `NO WIFI d201 B2`: `d<n>` is the last Wi‑Fi disconnect reason
(201 no AP found, 202 auth failed, 15 4‑way handshake timeout, 200 beacon timeout; the device's own retries are not counted) and `B`/`P`/`W` + count is the number of
brownout / panic / watchdog resets since the last power‑on (the counter survives a reset but not a power cycle). Over USB, `BOOT` and `STATUS` also print `reset=`,
`abnormal=`, `disc=`, `discn=` and `firstip=` (seconds until the first IP), and `WIFI disconnected reason=…` / `WIFI got_ip` lines appear as events happen.
Do not send `SCAN` while the device is still connecting: it interrupts the connection attempt.

**Backlight.** Connect the module's `LED` pin (red "1.8 TFT SPI 128*160 V1.1" board) to `3V3` through a 47–100 Ω resistor; without it the screen stays dark.
Do not drive it from a GPIO (too much current) or from 5 V. The manufacturer notes that the description of this pin is inconsistent, so check the requirements of any other module.

## Tests

```bash
cd gateway && python3 -m unittest discover -s tests -t . -v
```

They cover the parsers (including anonymised `/usage` samples and a real Codex response), the protocol against a fake `codex app-server`,
retry behaviour and keeping the last good values, authorisation, and TLS with a private CA and an IP‑address SAN.

Display scenarios that do not touch real accounts: `python3 tools/write_scenario.py <normal|zero|full|missing-window|missing-service|stale|expired|rate-limited>`.

## Gateway on a Mac mini (Docker + launchd)

```bash
git clone https://github.com/Franek1703/deskBuddy.git && cd deskBuddy
deploy/init_secrets.sh 192.168.0.188          # or copy deploy/local/secrets from the other Mac
deploy/install_collector_launchd.sh <path/to/codex> <path/to/claude>
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps       # healthy
```

The collector runs on the host (it needs the logged‑in CLIs); the container reads `usage.json` from a read‑only volume.
The server certificate is issued for the IP addresses passed to `init_secrets.sh`; after a LAN address change, generate it again
(the device's `ca.pem` stays the same as long as you keep `ca.key`).

## Deliberate omissions

* `cad/`, environment data and secrets are kept out of Git (`.gitignore`).
* `/usage` is not read through a pseudo‑terminal: `claude -p /usage` prints plain text without the TUI, so the parser does not depend on control sequences.
* The device clock comes from NTP (needed to check certificate validity). Without internet access on the LAN the TLS connection will not start.
