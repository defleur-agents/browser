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


@tool("browser_status", "Check the shared Browser is up: Chromium version, open tabs, and the DevTools address other apps use.")
def browser_status():
    v = _devtools("/json/version")
    tabs = [{"id": t.get("id"), "url": t.get("url"), "title": t.get("title")} for t in _devtools("/json/list") if t.get("type") == "page"]
    return {"ok": True, "browser": v.get("Browser"), "tabs": tabs,
            "devtools_for_apps": "http://browser:9222 (Puppeteer/Playwright connect over the Runtipi network)"}


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
