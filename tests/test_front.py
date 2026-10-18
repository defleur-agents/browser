"""Routing and handoff-auth rules of the MCP front (stdlib only, no containers)."""
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_front():
    src = (ROOT / "mcp" / "front.py").read_text() + "\n" + (ROOT / "mcp" / "tools.py").read_text()
    ns = {"__name__": "front_under_test"}
    exec(compile(src, "front+tools", "exec"), ns)
    ns["UP_HOST"] = "browser-engine"
    return ns


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.f = load_front()
        self.route = self.f["ROUTE"]
        h = self.f["HANDOFF"]
        h.clear()
        h.update(session_id="ho_test", token="A" * 32, ws_secret="B" * 32, purpose="captcha", note="",
                 tab_id="T1", started_at=time.time(), expires_at=time.time() + 600, base_url=None,
                 opened_at=None, seen_at=None)

    def test_devtools_passes_through_for_direct_callers(self):
        self.assertIsNone(self.route("GET", "/json/version", {"host": "127.0.0.1:8793"}))
        self.assertIsNone(self.route("GET", "/devtools/browser/x", {"host": "172.18.0.4:9222", "upgrade": "websocket"}))

    def test_devtools_refused_through_any_proxy(self):
        for header in ("x-forwarded-for", "tailscale-user-login", "forwarded", "x-forwarded-host"):
            r = self.route("GET", "/json/version", {"host": "127.0.0.1:8793", header: "x"})
            self.assertEqual((r[0], r[1]), ("respond", 403), header)

    def test_viewer_files_are_public_but_read_only(self):
        r = self.route("GET", "/handoff/client-1.3.0/vnc.html?x=1", {"x-forwarded-for": "100.64.0.2"})
        self.assertEqual(r[0], "proxy")
        self.assertEqual((r[2], r[3]), (self.f["CONTROL_PORT"], "/client-1.3.0/vnc.html"))
        self.assertIn("cookie", r[4])
        self.assertEqual(self.route("POST", "/handoff/index.html", {})[1], 405)
        self.assertEqual(self.route("GET", "/handoff", {})[1], 301)

    def test_stream_and_controls_need_the_capability_cookie(self):
        for path in ("/handoff/websockify", "/handoff/control/scroll?direction=down"):
            self.assertEqual(self.route("GET", path, {})[1], 401)
            self.assertEqual(self.route("GET", path, {"cookie": "browser_handoff=" + "C" * 32})[1], 401)
        ok = {"cookie": "other=1; browser_handoff=" + "A" * 32}
        ws = self.route("GET", "/handoff/websockify", ok)
        self.assertEqual((ws[0], ws[2], ws[3]), ("proxy", self.f["VNC_WS_PORT"], "/websockify"))
        self.assertTrue(ws[5][0].startswith("Authorization: Basic "))
        ctl = self.route("POST", "/handoff/control/scroll?direction=down", ok)
        self.assertEqual(ctl[3], "/control/scroll?direction=down")
        self.assertTrue(self.f["HANDOFF"]["opened_at"])

    def test_expired_handoff_refuses_and_reports_inactive(self):
        self.f["HANDOFF"]["expires_at"] = time.time() - 1
        ok = {"cookie": "browser_handoff=" + "A" * 32}
        self.assertEqual(self.route("GET", "/handoff/websockify", ok)[1], 401)
        self.assertEqual(self.route("GET", "/handoff/state", ok)[2], {"active": False, "authorized": False})

    def test_link_uses_base_url_and_fragment(self):
        h = self.f["HANDOFF"]
        url, path = self.f["_link"](h, "https://box.example.ts.net:8793/handoff/")
        self.assertEqual(path, "/handoff/#" + "A" * 32)
        self.assertEqual(url, "https://box.example.ts.net:8793/handoff/#" + "A" * 32)
        self.assertIsNone(self.f["_link"](h, None)[0])

    def test_existing_tools_still_listed(self):
        names = set(self.f["TOOLS"])
        self.assertTrue({"browser_status", "read_page", "screenshot"} <= names)
        self.assertTrue({"start_handoff", "handoff_status", "end_handoff"} <= names)


if __name__ == "__main__":
    unittest.main()
