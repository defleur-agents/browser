PAGE_TEXT_MAX = 100000


def _devtools(path, method="GET"):
    _, raw = http(method, path, timeout=30)
    return json.loads(raw) if raw else {}


class _WS:
    """Minimal WebSocket client for one Chrome DevTools target (text frames only)."""

    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((up_addr(), UP_PORT), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n") % (u.path, up_addr(), UP_PORT, key)
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("DevTools closed the connection")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("DevTools refused the WebSocket")
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.n = 0

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise ConnectionError("DevTools closed the connection")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, obj):
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                (bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n)))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            op = b1 & 0x0F
            if op == 8:
                raise ConnectionError("DevTools closed the WebSocket")
            if op in (0, 1):
                msg += payload
                if b1 & 0x80:
                    return json.loads(msg)

    def call(self, method, params=None):
        self.n += 1
        self.send({"id": self.n, "method": method, "params": params or {}})
        while True:
            m = self.recv()
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(m["error"].get("message"))
                return m.get("result") or {}

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _check_url(url):
    if urllib.parse.urlparse(str(url)).scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs")
    return str(url)


def _with_page(url, fn, width=1280, height=800, wait_ms=1500):
    target = _devtools("/json/new?" + urllib.parse.quote(_check_url(url), safe=""), "PUT")
    ws = _WS(target["webSocketDebuggerUrl"])
    try:
        ws.call("Emulation.setDeviceMetricsOverride", {"width": int(width), "height": int(height), "deviceScaleFactor": 1, "mobile": False})
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": url})
        deadline = time.time() + 30
        while time.time() < deadline:
            state = ws.call("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
            if state.get("result", {}).get("value") == "complete":
                break
            time.sleep(0.25)
        time.sleep(max(0, min(int(wait_ms), 10000)) / 1000)
        return fn(ws)
    finally:
        ws.close()
        try:
            _devtools("/json/close/" + target["id"])
        except Exception:
            pass


@tool("browser_status", "Check the shared Browser is up: Chromium version, open tabs, the DevTools address other apps use, and any open human handoff.")
def browser_status():
    v = _devtools("/json/version")
    tabs = [{"id": t.get("id"), "url": t.get("url"), "title": t.get("title")} for t in _devtools("/json/list") if t.get("type") == "page"]
    return {"ok": True, "browser": v.get("Browser"), "tabs": tabs,
            "devtools_for_apps": "http://browser:9222 (Puppeteer/Playwright connect over the Runtipi network)",
            "handoff": _handoff_public()}


@tool("read_page", "Open a URL in the shared headless browser (JavaScript runs) and return the page title and visible text.",
      {"url": {"type": "string"}, "wait_ms": {"type": "integer", "description": "Extra wait after load, max 10000 (default 1500)"}},
      ["url"])
def read_page(url, wait_ms=1500):
    def get(ws):
        r = ws.call("Runtime.evaluate", {"expression": "JSON.stringify({title: document.title, url: location.href, text: document.body ? document.body.innerText : ''})",
                                         "returnByValue": True})
        d = json.loads(r.get("result", {}).get("value") or "{}")
        d["text"] = (d.get("text") or "")[:PAGE_TEXT_MAX]
        return d
    return _with_page(url, get, wait_ms=wait_ms)


@tool("screenshot", "Open a URL in the shared headless browser and return a PNG screenshot.",
      {"url": {"type": "string"}, "width": {"type": "integer", "description": "Viewport width, default 1280"},
       "height": {"type": "integer", "description": "Viewport height, default 800"},
       "full_page": {"type": "boolean", "description": "Capture the whole page, not just the viewport"},
       "wait_ms": {"type": "integer", "description": "Extra wait after load, max 10000 (default 1500)"}},
      ["url"])
def screenshot(url, width=1280, height=800, full_page=False, wait_ms=1500):
    width, height = max(200, min(int(width), 3840)), max(200, min(int(height), 4000))

    def shot(ws):
        r = ws.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": bool(full_page)})
        return {"_content": [{"type": "image", "data": r["data"], "mimeType": "image/png"},
                             {"type": "text", "text": "Screenshot of %s (%dx%d%s)" % (url, width, height, ", full page" if full_page else "")}]}
    return _with_page(url, shot, width, height, wait_ms)



# ---- human handoff: the owner takes over this same live browser from a phone ----

import hmac
import secrets
import threading

CONTROL_PORT = int(os.environ.get("ENGINE_CONTROL_PORT", "6081"))
VNC_WS_PORT = int(os.environ.get("ENGINE_VNC_WS_PORT", "6080"))
PUBLIC_URL = os.environ.get("BROWSER_PUBLIC_URL", "").strip().rstrip("/")
HANDOFF_PREFIX = "/handoff"
COOKIE = "browser_handoff"
PURPOSES = ("captcha", "login", "otp", "consent", "payment", "verification", "other")
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "forwarded", "x-real-ip", "via",
                 "tailscale-user-login", "tailscale-user-name", "tailscale-headers-info")
HANDOFF = {}
HANDOFF_LOCK = threading.Lock()
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _secret(n):
    return "".join(secrets.choice(_ALNUM) for _ in range(n))


def _engine(method, path, obj=None, timeout=30):
    url = "http://%s:%d%s" % (up_addr(), CONTROL_PORT, path)
    data = None if obj is None else json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}").get("error")
        except ValueError:
            detail = None
        raise RuntimeError("browser engine: %s" % (detail or e.code))


def _active():
    """The current handoff, or {} once it has expired or the engine has dropped it."""
    h = HANDOFF
    if not h or time.time() >= h["expires_at"]:
        return {}
    return h


def _link(h, base_url=None):
    base = (base_url or PUBLIC_URL).strip().rstrip("/")
    if base.endswith(HANDOFF_PREFIX):
        base = base[: -len(HANDOFF_PREFIX)]
    path = HANDOFF_PREFIX + "/#" + h["token"]
    return (base + path) if base else None, path


def _handoff_public(h=None, include_link=False):
    h = h if h is not None else _active()
    if not h:
        return {"active": False}
    out = {"active": True, "session_id": h["session_id"], "purpose": h["purpose"], "note": h["note"],
           "tab_id": h["tab_id"], "started_at": int(h["started_at"]), "expires_at": int(h["expires_at"]),
           "expires_in_s": max(0, int(h["expires_at"] - time.time())),
           "owner_opened": bool(h.get("opened_at")), "owner_last_seen_s_ago":
               int(time.time() - h["seen_at"]) if h.get("seen_at") else None}
    if include_link:
        url, path = _link(h, h.get("base_url"))
        out["handoff_url"] = url
        out["handoff_path"] = path
    return out


def _page_tabs():
    return [t for t in _devtools("/json/list") if t.get("type") == "page"]


def _tab_summary(tab_id):
    for t in _page_tabs():
        if t.get("id") == tab_id:
            return {"id": tab_id, "url": t.get("url"), "title": t.get("title")}
    return None


@tool("start_handoff",
      "Hand this live browser to the owner on their phone for a step only a human should do (CAPTCHA, one-time code, "
      "login, consent, payment, identity check). Optionally opens a URL first. Returns a private link to send the owner; "
      "the agent keeps the same tabs, cookies and session and resumes after the owner says done. Calling it again while a "
      "handoff is open returns the same link (pass replace=true for a fresh link).",
      {"url": {"type": "string", "description": "http(s) page to open in a new focused tab first (optional)"},
       "tab_id": {"type": "string", "description": "Existing tab to show the owner instead (from browser_status)"},
       "purpose": {"type": "string", "enum": list(PURPOSES), "description": "Why the human is needed (default other)"},
       "note": {"type": "string", "description": "One short line shown in status, e.g. 'Solve the CAPTCHA on the signup form'"},
       "ttl_s": {"type": "integer", "description": "Link lifetime in seconds, 60-3600 (default 900)"},
       "base_url": {"type": "string", "description": "Owner-reachable address of this Browser app (its view url, e.g. "
                                                     "https://box.tailnet.ts.net:8793); defaults to BROWSER_PUBLIC_URL"},
       "replace": {"type": "boolean", "description": "Revoke an open handoff and issue a new link"}})
def start_handoff(url=None, tab_id=None, purpose="other", note="", ttl_s=900, base_url=None, replace=False):
    purpose = purpose if purpose in PURPOSES else "other"
    ttl = max(60, min(int(ttl_s or 900), 3600))
    if base_url and urllib.parse.urlparse(str(base_url)).scheme not in ("http", "https"):
        raise ValueError("base_url must be an http(s) address")
    with HANDOFF_LOCK:
        h = _active()
        engine_state = _engine("GET", "/session")
        if h and engine_state.get("active") and not replace:
            if base_url:
                h["base_url"] = base_url
            return {"ok": True, "reused": True, **_handoff_public(h, include_link=True),
                    "tab": _tab_summary(h["tab_id"]), "send_to_owner": _owner_message(h)}
        if url:
            tab = _devtools("/json/new?" + urllib.parse.quote(_check_url(url), safe=""), "PUT")
            tab_id = tab["id"]
        elif tab_id:
            if not _tab_summary(tab_id):
                raise ValueError("no open tab with id %s" % tab_id)
        else:
            tabs = _page_tabs()
            if not tabs:
                tab_id = _devtools("/json/new?about:blank", "PUT")["id"]
            else:
                tab_id = tabs[0]["id"]
        _devtools("/json/activate/" + tab_id)
        token, ws_secret = _secret(32), _secret(32)
        _engine("POST", "/session", {"password": token[:8], "ws_secret": ws_secret, "ttl": ttl})
        now = time.time()
        HANDOFF.clear()
        HANDOFF.update(session_id="ho_" + _secret(10), token=token, ws_secret=ws_secret, purpose=purpose,
                       note=str(note or "")[:200], tab_id=tab_id, started_at=now, expires_at=now + ttl,
                       base_url=base_url, opened_at=None, seen_at=None)
        h = HANDOFF
        out = {"ok": True, "reused": False, **_handoff_public(h, include_link=True), "tab": _tab_summary(tab_id),
               "send_to_owner": _owner_message(h)}
        if not out["handoff_url"]:
            out["warning"] = ("No owner-reachable address is configured. Prefix handoff_path with the Browser app's "
                              "view address (wizard apps list --json: view.url, without /handoff/) or pass base_url.")
        return out


def _owner_message(h):
    url, path = _link(h, h.get("base_url"))
    what = {"captcha": "solve a CAPTCHA", "login": "sign in", "otp": "enter a one-time code", "consent": "approve a consent step",
            "payment": "confirm a payment", "verification": "verify your identity"}.get(h["purpose"], "finish a step")
    return "I need you to %s in my browser%s: %s  Reply done when finished." % (
        what, (" (" + h["note"] + ")") if h["note"] else "", url or path)


@tool("handoff_status",
      "Is a human handoff open, has the owner opened the link, how long until it expires, and which page the shared tab is on now.")
def handoff_status():
    h = _active()
    engine_state = _engine("GET", "/session")
    out = _handoff_public(h)
    out["engine_active"] = bool(engine_state.get("active"))
    if h:
        out["tab"] = _tab_summary(h["tab_id"])
        if not engine_state.get("active"):
            out["active"] = False
            out["detail"] = "the viewer stopped (expired or the engine restarted); start a new handoff if still needed"
    return out


@tool("end_handoff",
      "End the human handoff: revoke the link and stop the viewer. The browser, its tabs and the session stay as they are, so the agent resumes where the owner left off.")
def end_handoff():
    with HANDOFF_LOCK:
        had = bool(HANDOFF)
        tab = HANDOFF.get("tab_id")
        HANDOFF.clear()
        r = _engine("DELETE", "/session")
    return {"ok": True, "ended": had or bool(r.get("stopped")), "tab": _tab_summary(tab) if tab else None}


def _cookie_token(headers):
    for part in headers.get("cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return ""


def _authorized(headers):
    h = _active()
    return bool(h) and hmac.compare_digest(_cookie_token(headers).encode(), h["token"].encode())


def route(method, target, headers):
    """Handoff viewer under /handoff/, DevTools for direct callers only, everything else unchanged."""
    path, _, query = target.partition("?")
    if path == HANDOFF_PREFIX:
        return ("respond", 301, None, "Location: handoff/\r\n")
    if path.startswith(HANDOFF_PREFIX + "/"):
        rest = path[len(HANDOFF_PREFIX):]
        if rest == "/state":
            h = _active()
            ok = _authorized(headers)
            if ok:
                h["seen_at"] = time.time()
            return ("respond", 200, {"active": bool(h), "authorized": ok}, "")
        if rest == "/websockify" or rest.startswith("/control/"):
            if not _authorized(headers):
                return ("respond", 401, {"error": "this handoff link has ended or is not valid"}, "")
            h = HANDOFF
            h["seen_at"] = time.time()
            if rest == "/websockify":
                h["opened_at"] = h.get("opened_at") or time.time()
                auth = base64.b64encode(("handoff:" + h["ws_secret"]).encode()).decode()
                return ("proxy", UP_HOST, VNC_WS_PORT, "/websockify", ("cookie", "authorization"),
                        ["Authorization: Basic " + auth])
            return ("proxy", UP_HOST, CONTROL_PORT, rest + ("?" + query if query else ""), ("cookie", "authorization"), [])
        if method not in ("GET", "HEAD"):
            return ("respond", 405, {"error": "the viewer is read-only"}, "Allow: GET, HEAD\r\n")
        return ("proxy", UP_HOST, CONTROL_PORT, rest, ("cookie", "authorization"), [])
    # DevTools has no password. Other apps and the host call it directly; anything arriving through a
    # reverse proxy (Tailscale Serve, the Wizard gateway) is a remote client and gets no DevTools.
    if any(k in headers for k in PROXY_HEADERS):
        return ("respond", 403, {"error": "DevTools is only for apps on this box; the owner's page is /handoff/"}, "")
    return None


ROUTE = route
