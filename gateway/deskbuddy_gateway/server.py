"""HTTPS gateway: GET /v1/usage (device key required) and GET /healthz."""
from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple

from .model import load_snapshot
from .payload import build_usage_response

log = logging.getLogger("deskbuddy.gateway")


class KeyStore:
    """device_keys file: one `name:key` per line, reloaded when the file changes."""

    def __init__(self, path: str):
        self.path = path
        self._mtime = None
        self._keys: Dict[str, str] = {}

    def _load(self) -> None:
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            self._keys, self._mtime = {}, None
            return
        if mtime == self._mtime:
            return
        keys = {}
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and ":" in line:
                    name, key = line.split(":", 1)
                    if key.strip():
                        keys[name.strip()] = key.strip()
        self._keys, self._mtime = keys, mtime

    def identify(self, presented: str) -> Optional[str]:
        self._load()
        found = None
        for name, key in self._keys.items():  # compare every key: no early exit
            if hmac.compare_digest(key.encode(), presented.encode()):
                found = name
        return found


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: Tuple[str, int], data_path: str, keys: KeyStore,
                 ssl_context: Optional[ssl.SSLContext] = None):
        self.data_path = data_path
        self.keys = keys
        self.ssl_context = ssl_context
        self.served = 0
        self.lock = threading.Lock()
        super().__init__(addr, Handler)

    def get_request(self):
        sock, addr = super().get_request()
        if self.ssl_context is not None:
            sock = self.ssl_context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        log.warning("connection from %s dropped: %s: %s", client_address[0], type(exc).__name__, exc)


class Handler(BaseHTTPRequestHandler):
    server_version = "DeskBuddyGateway/0.1"
    protocol_version = "HTTP/1.1"

    def setup(self):
        if isinstance(self.request, ssl.SSLSocket):  # handshake in the worker thread, not accept()
            self.request.settimeout(10)
            self.request.do_handshake()
        super().setup()
        self.request.settimeout(10)

    def log_message(self, fmt, *args):  # replaced by explicit access lines below
        pass

    def _send(self, code: int, body: dict, extra: str = "") -> int:
        raw = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if code == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True
        return len(raw)

    def _access(self, code: int, device: str, size: int, extra: str = "") -> None:
        log.info("%s GET %s -> %d device=%s bytes=%d%s", self.client_address[0], self.path, code,
                 device, size, extra)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            snap = load_snapshot(self.server.data_path)
            body = {"ok": True, "seq": snap["seq"], "snapshot_age_s":
                    None if snap["generated_at"] is None else max(0, int(time.time()) - snap["generated_at"])}
            return self._access(200, "-", self._send(200, body))
        if path != "/v1/usage":
            return self._access(404, "-", self._send(404, {"error": "not_found"}))
        header = self.headers.get("Authorization", "")
        presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
        device = self.server.keys.identify(presented) if presented else None
        if device is None:
            return self._access(401, "unknown", self._send(401, {"error": "unauthorized"}))
        snap = load_snapshot(self.server.data_path)
        with self.server.lock:
            self.server.served += 1
            served = self.server.served
        body = build_usage_response(snap, int(time.time()), served)
        size = self._send(200, body)
        self._access(200, device, size, " seq=%d served=%d" % (snap["seq"], served))


def make_ssl_context(cert: str, key: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def main(argv: Optional[list] = None) -> int:
    env = os.environ.get
    p = argparse.ArgumentParser(description="DeskBuddy gateway")
    p.add_argument("--data-dir", default=env("DESKBUDDY_DATA_DIR", "./data"))
    p.add_argument("--keys-file", default=env("DESKBUDDY_KEYS_FILE", "./secrets/device_keys.txt"))
    p.add_argument("--cert", default=env("DESKBUDDY_CERT"), help="server certificate (PEM); omit for plain HTTP")
    p.add_argument("--key", default=env("DESKBUDDY_KEY"))
    p.add_argument("--host", default=env("DESKBUDDY_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(env("DESKBUDDY_PORT", "8443")))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ctx = make_ssl_context(args.cert, args.key) if args.cert else None
    if ctx is None:
        log.warning("no --cert given: serving plain HTTP (testing only)")
    srv = Gateway((args.host, args.port), os.path.join(args.data_dir, "usage.json"),
                  KeyStore(args.keys_file), ctx)
    log.info("gateway listening on %s:%d (%s)", args.host, args.port, "https" if ctx else "http")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
