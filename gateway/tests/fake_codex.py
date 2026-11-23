#!/usr/bin/env python3
"""Stand-in for `codex app-server`. Behaviour is picked with FAKE_CODEX_MODE."""
import json, os, sys, time

mode = os.environ.get("FAKE_CODEX_MODE", "ok")
here = os.path.dirname(os.path.abspath(__file__))
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        print(json.dumps({"id": msg["id"], "result": {"userAgent": "fake"}}), flush=True)
        print(json.dumps({"method": "account/updated", "params": {}}), flush=True)
    elif msg.get("method") == "account/rateLimits/read":
        if mode == "hang":
            time.sleep(60)
        if mode == "exit":
            sys.exit(0)
        if mode == "ratelimited":
            print(json.dumps({"id": msg["id"], "error": {"code": 429, "message": "Too many requests, try again in 90 seconds"}}), flush=True)
        elif mode == "auth":
            print(json.dumps({"id": msg["id"], "error": {"code": 401, "message": "not logged in"}}), flush=True)
        else:
            with open(os.path.join(here, "fixtures", "codex_rate_limits_result.json")) as fh:
                print(json.dumps({"id": msg["id"], "result": json.load(fh)}), flush=True)
