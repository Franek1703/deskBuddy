"""Container healthcheck: GET /healthz on the local port (certificate is not checked)."""
import json
import os
import ssl
import sys
import urllib.request


def main() -> int:
    port = os.environ.get("DESKBUDDY_PORT", "8443")
    tls = bool(os.environ.get("DESKBUDDY_CERT"))
    ctx = ssl._create_unverified_context() if tls else None
    url = "%s://127.0.0.1:%s/healthz" % ("https" if tls else "http", port)
    try:
        with urllib.request.urlopen(url, timeout=4, context=ctx) as r:
            return 0 if r.status == 200 and json.load(r).get("ok") else 1
    except Exception as exc:
        print("healthcheck failed:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
