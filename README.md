# DeskBuddy

Monitor limitów subskrypcji **Codex (5 h i 7 dni)** oraz **Claude (5 h i 7 dni)** na ESP32‑C3 Super Mini z ekranem ST7735 128 × 160.
Każdy wiersz pokazuje procent wykorzystania i czas do resetu. Bramka na Macu zbiera dane z natywnych CLI i wystawia je po HTTPS w LAN,
a ESP32 tylko je pobiera i rysuje.

```
 codex app-server ─┐                                     ┌── GET /v1/usage (HTTPS, klucz urządzenia)
                   ├─ kolektor ─ usage.json ─ bramka ────┤
 claude -p /usage ─┘  (host, launchd)   (wolumen ro)  (Docker)   └── ESP32‑C3 + ST7735
```

## Struktura

| Katalog | Zawartość |
|---|---|
| `gateway/` | pakiet `deskbuddy_gateway` (tylko biblioteka standardowa Pythona): kolektor, serwer HTTPS, testy, `Dockerfile` |
| `firmware/deskbuddy/` | szkic Arduino (core ESP32 `3.3.11`, Adafruit ST7735/GFX, ArduinoJson) |
| `deploy/` | `compose.yaml`, generator certyfikatów, agent `launchd` kolektora |
| `tools/` | provisioning przez USB (`provision.py`), log z portu (`serial_log.py`), scenariusze testowe (`write_scenario.py`) |
| `examples/` | przykładowy `usage.json` |

## Dane

* **Codex** – `codex app-server`, JSON‑RPC `account/rateLimits/read`. Okna rozpoznawane po `windowDurationMins` (300 = 5 h, 10 080 = 7 dni), nie po kolejności `primary/secondary`. Odczyt co 2 min.
* **Claude** – `claude -p /usage` (natywny Claude Code, bez modelu i bez tokenów). Parser czyta wiersze `Current session` i `Current week (all models)` oraz czas resetu wraz ze strefą z nawiasu. Odczyt co 5 min.
  Polecenie jest konfigurowalne (`--claude-cmd`), więc kolektor może też uruchomić je przez SSH na innym Macu.
* Błąd odczytu **nie kasuje** poprzednich wartości. Kolektor ponawia z wykładniczym opóźnieniem (do 30 min) i uwzględnia czas ponowienia z komunikatu o ograniczeniu. Przy `rate_limited` lub po 3 pominiętych cyklach bramka oznacza usługę jako `stale`.
* Wygaśnięcie odliczania **nie zeruje** procentu; ekran pokazuje `0m` do następnego odczytu.

### Odpowiedź `GET /v1/usage`

Wymaga nagłówka `Authorization: Bearer <klucz urządzenia>`. `GET /healthz` jest otwarty.

```json
{"schema":1,"seq":12,"served":345,"now":1795426949,
 "services":{"codex":{"state":"fresh","last_success_at":1795426912,"age_s":37,"error":null,"retry_at":null,
   "windows":{"5h":{"percent":93,"resets_at":1795439673,"resets_in_s":12724,"expired":false},
              "7d":{"percent":23,"resets_at":1795955202,"resets_in_s":528253,"expired":false}}},
  "claude":{ "...": "..." }}}
```

`state`: `fresh` / `stale` / `missing`. `seq` to numer odczytu kolektora, `served` licznik odpowiedzi bramki.
Gotowa linia w logu bramki (`seq=12 served=345`) odpowiada linii `RENDER seq=12 served=345` z USB urządzenia.

## Uruchomienie lokalne (ten Mac)

```bash
# 1. Certyfikaty i klucz urządzenia (SAN: adresy IP wszystkich hostów bramki)
deploy/init_secrets.sh 192.168.0.246 192.168.0.188

# 2. Kolektor (Codex lokalnie, Claude lokalnie albo przez SSH)
cd gateway
python3 -m deskbuddy_gateway.collector --data-dir ../deploy/local/data \
  --claude-cmd 'ssh -o BatchMode=yes mini "~/.local/bin/claude -p /usage"'

# 3. Bramka
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

Piny: `SCK→GPIO4`, `SDA/MOSI→GPIO6`, `CS→GPIO7`, `A0/DC→GPIO3`, `RESET→GPIO1`, `VCC→3V3`, `GND→GND`. Pin `LED` (podświetlenie): zob. niżej.

### Konfiguracja urządzenia przez USB (NVS)

Wi‑Fi, adres bramki, klucz i CA trafiają do pamięci NVS; zmiana adresu bramki nie wymaga ponownego flashowania.
ESP32‑C3 łączy się **tylko z 2,4 GHz** (komenda `SCAN` na USB pokazuje, co widzi układ).

```bash
python3 tools/provision.py --ssid <SSID_2.4GHz> --gw-host 192.168.0.246   # hasło Wi‑Fi: pytanie w terminalu
python3 tools/provision.py --gw-host 192.168.0.188                       # tylko przełączenie bramki
python3 tools/serial_log.py --seconds 60                                 # BOOT / FETCH / RENDER / STATUS
```

Komendy portu szeregowego (115200): `HELP STATUS GET SET <klucz> <wartość> CLEAR TEST APPLY FETCH SCAN WIFI_BOUNCE [s] REBOOT`.
Ustawienia panelu: `tft_tab` (0 green, 1 red, 2 black), `tft_rot` (0 lub 2), `tft_swaprb`, `tft_inv`, `col_off`, `row_off`, `bl_pin`, `bl_on`.
`TEST` rysuje planszę (8 pasków, ramka, znaczniki rogów), `APPLY` wraca do ekranu limitów po zmianie ustawień.

**Podświetlenie.** Producent modułu zaznacza, że opis pinu `LED` jest niespójny i nie wolno go podłączać do 3,3 V ani 5 V bez sprawdzenia wymagań.
Jeśli ekran jest ciemny, ale pod skosem w silnym świetle widać obraz, logika działa, a brakuje tylko podświetlenia.

## Testy

```bash
cd gateway && python3 -m unittest discover -s tests -t . -v
```

Pokrywają parsery (w tym zanonimizowane próbki `/usage` i prawdziwą odpowiedź Codex), protokół z atrapą `codex app-server`,
ponawianie i zachowanie ostatnich wartości, autoryzację oraz TLS z prywatnym CA i SAN z adresem IP.

Scenariusze wyświetlania bez dotykania kont: `python3 tools/write_scenario.py <normal|zero|full|missing-window|missing-service|stale|expired|rate-limited>`.

## Bramka na Macu mini (Docker + launchd)

```bash
git clone https://github.com/Franek1703/deskBuddy.git && cd deskBuddy
deploy/init_secrets.sh 192.168.0.188          # albo skopiuj deploy/local/secrets z obecnego Maca
deploy/install_collector_launchd.sh <ścieżka/codex> <ścieżka/claude>
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps       # healthy
```

Kolektor działa na hoście (potrzebuje zalogowanych CLI), a kontener czyta `usage.json` z wolumenu tylko do odczytu.
Certyfikat serwera jest wystawiony na adresy IP z `init_secrets.sh`; po zmianie adresu LAN wygeneruj go ponownie
(`ca.pem` na urządzeniu pozostaje ten sam, jeśli nie kasujesz `ca.key`).

## Rzeczy świadomie pominięte

* `cad/`, dane środowiska i sekrety są poza Git (`.gitignore`).
* Brak odczytu `/usage` w pseudoterminalu: `claude -p /usage` zwraca czysty tekst bez TUI, więc parser nie zależy od sekwencji sterujących.
* Zegar urządzenia pochodzi z NTP (potrzebny do sprawdzenia ważności certyfikatu). Bez internetu w LAN połączenie TLS nie ruszy.
