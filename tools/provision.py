#!/usr/bin/env python3
"""Write Wi-Fi, gateway address, device key and the local CA into the ESP32's NVS over USB.

The Wi-Fi password is read from a prompt, $DESKBUDDY_WIFI_PASS or --wifi-pass-file; it is never echoed or logged.
Examples:
  tools/provision.py --ssid MyWifi --gw-host 192.168.0.246 --secrets deploy/local/secrets
  tools/provision.py --gw-host 192.168.0.188 --secrets deploy/local/secrets   # switch gateway only
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deskbuddy_serial import Serial, find_port  # noqa: E402


def read_key(path, device):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            name, _, key = line.strip().partition(":")
            if name == device and key:
                return key
    sys.exit("no key for device %r in %s" % (device, path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--ssid")
    ap.add_argument("--wifi-pass-file")
    ap.add_argument("--gw-host", required=True)
    ap.add_argument("--gw-port", type=int, default=8443)
    ap.add_argument("--no-tls", action="store_true", help="plain HTTP (testing only)")
    ap.add_argument("--secrets", default="deploy/local/secrets", help="dir with ca.pem and device_keys.txt")
    ap.add_argument("--device", default="esp32")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="extra setting, e.g. tft_swaprb=1")
    ap.add_argument("--no-reboot", action="store_true")
    args = ap.parse_args()

    settings = [("gw_host", args.gw_host), ("gw_port", str(args.gw_port)), ("gw_tls", "0" if args.no_tls else "1"),
                ("gw_key", read_key(os.path.join(args.secrets, "device_keys.txt"), args.device))]
    if not args.no_tls:
        with open(os.path.join(args.secrets, "ca.pem"), encoding="utf-8") as fh:
            settings.append(("gw_ca", fh.read().strip().replace("\n", "|")))
    if args.ssid:
        if args.wifi_pass_file:
            with open(args.wifi_pass_file, encoding="utf-8") as fh:
                password = fh.read().strip()
        else:
            password = os.environ.get("DESKBUDDY_WIFI_PASS") or getpass.getpass("Wi-Fi password for %s: " % args.ssid)
        settings += [("wifi_ssid", args.ssid), ("wifi_pass", password)]
    for item in args.set:
        key, _, value = item.partition("=")
        settings.append((key, value))

    ser = Serial(args.port or find_port())
    try:
        for key, value in settings:
            reply = ser.command("SET %s %s" % (key, value))
            print("%-10s %s" % (key, reply))
            if not reply.startswith("OK"):
                sys.exit("device rejected %s" % key)
        if not args.no_reboot:
            print("reboot:", ser.command("REBOOT"))
    finally:
        ser.close()


if __name__ == "__main__":
    main()
