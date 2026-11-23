#!/usr/bin/env bash
# Create the private CA, the server certificate and a device key in deploy/local/secrets (git-ignored).
# Put EVERY LAN IP the gateway may run on into the certificate (this Mac and the Mac mini), so that
# switching the ESP32 between them only needs a new gw_host, not a new certificate.
# usage: deploy/init_secrets.sh 192.168.0.246 192.168.0.188
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="$here/local/secrets"
"$here/make_certs.sh" "$out" "$@"
if [ ! -f "$out/device_keys.txt" ]; then
  umask 077
  printf 'esp32:%s\n' "$(openssl rand -hex 24)" > "$out/device_keys.txt"
  chmod 644 "$out/device_keys.txt"
  echo "created $out/device_keys.txt"
fi
