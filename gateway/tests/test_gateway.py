import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from deskbuddy_gateway import model, payload  # noqa: E402
from deskbuddy_gateway.collector import Collector  # noqa: E402
from deskbuddy_gateway.server import Gateway, KeyStore, make_ssl_context  # noqa: E402
from deskbuddy_gateway.sources import SourceError  # noqa: E402

NOW = 1_800_000_000


def snap_with(codex=None, claude=None, **svc_over):
    s = model.empty_snapshot()
    s["seq"] = 7
    for name, w in (("codex", codex), ("claude", claude)):
        if w:
            svc = s["services"][name]
            for k, v in w.items():
                svc["windows"][k] = {"used_percent": v[0], "resets_at": v[1]}
            svc["last_success_at"] = NOW - 10
            svc["interval_s"] = 120
    return s


class PayloadTests(unittest.TestCase):
    def test_zero_and_full(self):
        s = snap_with(codex={"5h": (0, NOW + 60), "7d": (100, NOW + 86400)})
        r = payload.build_usage_response(s, NOW, 1)
        w = r["services"]["codex"]["windows"]
        self.assertEqual(w["5h"]["percent"], 0)
        self.assertEqual(w["7d"]["percent"], 100)
        self.assertEqual(r["services"]["codex"]["state"], "fresh")
        self.assertEqual(w["7d"]["resets_in_s"], 86400)

    def test_missing_service_and_missing_window(self):
        s = snap_with(codex={"5h": (50, NOW + 60)})
        r = payload.build_usage_response(s, NOW, 1)
        self.assertEqual(r["services"]["claude"]["state"], "missing")
        self.assertIsNone(r["services"]["codex"]["windows"]["7d"]["percent"])
        self.assertIsNone(r["services"]["codex"]["windows"]["7d"]["resets_in_s"])

    def test_expired_reset_keeps_percent(self):
        s = snap_with(codex={"5h": (93, NOW - 5), "7d": (23, NOW + 5)})
        w = payload.build_usage_response(s, NOW, 1)["services"]["codex"]["windows"]["5h"]
        self.assertEqual((w["percent"], w["resets_in_s"], w["expired"]), (93, 0, True))

    def test_staleness_by_age_and_by_rate_limit(self):
        s = snap_with(codex={"5h": (10, NOW + 60)})
        self.assertEqual(payload.service_state("codex", s["services"]["codex"], NOW), "fresh")
        self.assertEqual(payload.service_state("codex", s["services"]["codex"], NOW + 3 * 120), "stale")
        s["services"]["codex"]["error"] = {"kind": "rate_limited", "message": "", "at": NOW}
        self.assertEqual(payload.service_state("codex", s["services"]["codex"], NOW), "stale")

    def test_transient_failure_alone_is_not_stale(self):
        s = snap_with(codex={"5h": (10, NOW + 60)})
        s["services"]["codex"]["error"] = {"kind": "failed", "message": "x", "at": NOW}
        self.assertEqual(payload.service_state("codex", s["services"]["codex"], NOW), "fresh")


class SnapshotIoTests(unittest.TestCase):
    def test_roundtrip_and_garbage(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "usage.json")
            self.assertEqual(model.load_snapshot(p)["seq"], 0)
            model.write_snapshot(p, snap_with(codex={"5h": (150, NOW)}))
            got = model.load_snapshot(p)
            self.assertEqual(got["services"]["codex"]["windows"]["5h"]["used_percent"], 100.0)  # clamped
            self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o644")
            self.assertEqual([f for f in os.listdir(d) if f != "usage.json"], [])
            with open(p, "w") as fh:
                fh.write("{broken")
            self.assertEqual(model.load_snapshot(p)["seq"], 0)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "usage.json")
        self.t = [NOW]
        self.addCleanup(shutil.rmtree, self.dir)

    def make(self, codex, claude=lambda: {}):
        return Collector(self.path, {"codex": codex, "claude": claude},
                         {"codex": 120, "claude": 300}, clock=lambda: self.t[0])

    def test_success_then_failure_keeps_values_and_backs_off(self):
        calls = {"n": 0}

        def codex():
            calls["n"] += 1
            if calls["n"] == 1:
                return {"5h": {"used_percent": 40.0, "resets_at": NOW + 100},
                        "7d": {"used_percent": 10.0, "resets_at": NOW + 5000}}
            raise SourceError("rate_limited", "slow down", retry_after=600)

        c = self.make(codex)
        c.poll("codex")
        svc = model.load_snapshot(self.path)["services"]["codex"]
        self.assertEqual(svc["windows"]["5h"]["used_percent"], 40.0)
        self.assertEqual(svc["last_success_at"], NOW)
        self.assertFalse(c.due("codex", NOW + 119))
        self.assertTrue(c.due("codex", NOW + 120))

        self.t[0] = NOW + 120
        c.poll("codex")
        svc = model.load_snapshot(self.path)["services"]["codex"]
        self.assertEqual(svc["windows"]["5h"]["used_percent"], 40.0)  # previous reading kept
        self.assertEqual(svc["error"]["kind"], "rate_limited")
        self.assertEqual(svc["retry_at"], NOW + 120 + 600)  # honours the provider's retry time
        self.assertFalse(c.due("codex", NOW + 700))
        self.assertTrue(c.due("codex", NOW + 720))
        self.assertEqual(model.load_snapshot(self.path)["seq"], 2)

    def test_backoff_grows_and_is_capped(self):
        def codex():
            raise SourceError("failed", "boom")

        c = self.make(codex)
        waits = []
        for _ in range(8):
            c.poll("codex")
            waits.append(c.snapshot["services"]["codex"]["retry_at"] - self.t[0])
            self.t[0] = c.snapshot["services"]["codex"]["retry_at"]
        self.assertEqual(waits[:3], [120, 240, 480])
        self.assertEqual(max(waits), 1800)

    def test_recovery_clears_error(self):
        state = {"fail": True}

        def codex():
            if state["fail"]:
                raise SourceError("auth", "nope")
            return {"5h": {"used_percent": 1.0, "resets_at": None}}

        c = self.make(codex)
        c.poll("codex")
        state["fail"] = False
        self.t[0] += 500
        c.poll("codex")
        svc = c.snapshot["services"]["codex"]
        self.assertIsNone(svc["error"])
        self.assertEqual((svc["failures"], svc["retry_at"]), (0, None))

    def test_window_dropped_by_provider_is_cleared(self):
        answers = [{"5h": {"used_percent": 5.0, "resets_at": None}, "7d": {"used_percent": 6.0, "resets_at": None}},
                   {"7d": {"used_percent": 7.0, "resets_at": None}}]
        c = self.make(lambda: answers.pop(0))
        c.poll("codex")
        c.poll("codex")
        w = c.snapshot["services"]["codex"]["windows"]
        self.assertIsNone(w["5h"]["used_percent"])
        self.assertEqual(w["7d"]["used_percent"], 7.0)

    def test_restart_keeps_last_good_values(self):
        c = self.make(lambda: {"5h": {"used_percent": 33.0, "resets_at": None}})
        c.poll("codex")
        c2 = self.make(lambda: (_ for _ in ()).throw(SourceError("failed", "x")))
        self.assertEqual(c2.snapshot["services"]["codex"]["windows"]["5h"]["used_percent"], 33.0)
        self.assertEqual(c2.snapshot["seq"], 1)

    def test_unexpected_exception_does_not_escape(self):
        c = self.make(lambda: 1 / 0)
        c.poll("codex")
        self.assertEqual(c.snapshot["services"]["codex"]["error"]["kind"], "failed")


class ServerTests(unittest.TestCase):
    KEY = "k" * 32

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.data = os.path.join(self.dir, "usage.json")
        self.keys = os.path.join(self.dir, "device_keys.txt")
        with open(self.keys, "w") as fh:
            fh.write("# keys\nesp32-test:%s\nspare:%s\n" % (self.KEY, "s" * 32))

    def serve(self, ctx=None):
        srv = Gateway(("127.0.0.1", 0), self.data, KeyStore(self.keys), ctx)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv

    def get(self, srv, path, key=None, tls=None):
        req = urllib.request.Request("%s://127.0.0.1:%d%s" % ("https" if tls else "http", srv.server_address[1], path))
        if key:
            req.add_header("Authorization", "Bearer " + key)
        try:
            with urllib.request.urlopen(req, timeout=5, context=tls) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_auth_and_payload_and_served_counter(self):
        model.write_snapshot(self.data, snap_with(codex={"5h": (93, NOW)}))
        srv = self.serve()
        self.assertEqual(self.get(srv, "/v1/usage")[0], 401)
        self.assertEqual(self.get(srv, "/v1/usage", key="wrong")[0], 401)
        self.assertEqual(self.get(srv, "/v1/usage", key=self.KEY[:-1])[0], 401)
        code, body = self.get(srv, "/v1/usage", key=self.KEY)
        self.assertEqual(code, 200)
        self.assertEqual((body["seq"], body["served"]), (7, 1))
        self.assertEqual(body["services"]["codex"]["windows"]["5h"]["percent"], 93)
        self.assertEqual(self.get(srv, "/v1/usage", key="s" * 32)[1]["served"], 2)

    def test_healthz_is_open_and_missing_snapshot_is_served_as_missing(self):
        srv = self.serve()
        code, body = self.get(srv, "/healthz")
        self.assertEqual((code, body["ok"]), (200, True))
        code, body = self.get(srv, "/v1/usage", key=self.KEY)
        self.assertEqual((code, body["services"]["codex"]["state"]), (200, "missing"))
        self.assertEqual(self.get(srv, "/nope")[0], 404)

    def test_key_file_reload(self):
        srv = self.serve()
        self.assertEqual(self.get(srv, "/v1/usage", key="newkey")[0], 401)
        with open(self.keys, "a") as fh:
            fh.write("added:newkey\n")
        os.utime(self.keys, (NOW, NOW))
        self.assertEqual(self.get(srv, "/v1/usage", key="newkey")[0], 200)

    @unittest.skipUnless(shutil.which("openssl"), "openssl not installed")
    def test_tls_with_private_ca_and_ip_san(self):
        pki = os.path.join(HERE, "..", "..", "deploy", "make_certs.sh")
        out = os.path.join(self.dir, "pki")
        subprocess.run(["bash", pki, out, "127.0.0.1"], check=True, stdout=subprocess.DEVNULL)
        srv = self.serve(make_ssl_context(os.path.join(out, "server.pem"), os.path.join(out, "server.key")))
        model.write_snapshot(self.data, snap_with(codex={"5h": (1, NOW)}))
        trusting = ssl.create_default_context(cafile=os.path.join(out, "ca.pem"))
        code, body = self.get(srv, "/v1/usage", key=self.KEY, tls=trusting)
        self.assertEqual((code, body["seq"]), (200, 7))
        with self.assertRaises(urllib.error.URLError):  # a client without our CA must refuse
            self.get(srv, "/healthz", tls=ssl.create_default_context())


if __name__ == "__main__":
    unittest.main()
