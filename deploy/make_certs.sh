#!/usr/bin/env bash
# Private CA + server certificate whose SANs are the gateway's LAN IPs (the ESP32 connects by IP).
# usage: make_certs.sh <out-dir> <ip-or-dns> [<ip-or-dns> ...]
# Writes ca.pem (give this to the device), ca.key (keep offline), server.pem, server.key.
set -euo pipefail
out="${1:?usage: make_certs.sh <out-dir> <ip-or-dns>...}"; shift
[ "$#" -ge 1 ] || { echo "give at least one IP or DNS name for the SAN" >&2; exit 2; }
mkdir -p "$out"; umask 077
san="DNS:localhost,IP:127.0.0.1"
for h in "$@"; do
  if [[ "$h" =~ ^[0-9.]+$ || "$h" == *:* ]]; then san="$san,IP:$h"; else san="$san,DNS:$h"; fi
done
if [ ! -f "$out/ca.key" ]; then
  openssl ecparam -name prime256v1 -genkey -noout -out "$out/ca.key"
  openssl req -x509 -new -key "$out/ca.key" -sha256 -days 3650 -subj "/CN=DeskBuddy local CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$out/ca.pem"
fi
openssl ecparam -name prime256v1 -genkey -noout -out "$out/server.key"
openssl req -new -key "$out/server.key" -subj "/CN=deskbuddy-gateway" -out "$out/server.csr"
printf "subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=serverAuth\n" "$san" > "$out/server.ext"
openssl x509 -req -in "$out/server.csr" -CA "$out/ca.pem" -CAkey "$out/ca.key" -CAcreateserial \
  -sha256 -days 1825 -extfile "$out/server.ext" -out "$out/server.pem" 2>/dev/null
rm -f "$out/server.csr" "$out/server.ext" "$out/ca.srl"
chmod 644 "$out/ca.pem" "$out/server.pem" "$out/server.key"  # the container user must be able to read the key
echo "SAN: $san"
