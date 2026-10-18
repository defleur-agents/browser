#!/usr/bin/env python3
"""Browser engine: one headful Chromium on an Xvfb display, shared by agents and,
during a human handoff, by the owner through the noVNC viewer.

Processes (all inside this container, stdlib only):
- Xvfb :99 (screen BROWSER_SCREEN, default 500x900 portrait, the tested phone size)
- Chromium, headful on :99, DevTools on 127.0.0.1:9223 (restarted if it exits)
- a TCP forwarder 0.0.0.0:9222 -> 127.0.0.1:9223, so other apps keep using :9222
- the control server on :6081: viewer files, phone controls (scroll, focused-field
  probe) and the handoff session API used by the MCP front
- only while a handoff is open: x11vnc (localhost, password) + websockify on :6080

The control server answers only the MCP front (FRONT_HOST) and loopback.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DISPLAY = os.environ.get("BROWSER_DISPLAY", ":99")
SCREEN = os.environ.get("BROWSER_SCREEN", "500x900")
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
CHROME_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9223"))
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "6081"))
WS_PORT = int(os.environ.get("VNC_WS_PORT", "6080"))
VNC_PORT = int(os.environ.get("VNC_PORT", "5900"))
FRONT_HOST = os.environ.get("FRONT_HOST", "")
VIEWER_ROOT = Path(os.environ.get("VIEWER_ROOT", "/opt/viewer")).resolve()
RUNTIME = Path(os.environ.get("ENGINE_RUNTIME", "/tmp/engine"))
PROFILE = Path(os.environ.get("BROWSER_PROFILE", "/tmp/chromium-profile"))
CHROMIUM = os.environ.get("CHROMIUM", "/usr/bin/chromium")
START_URL = os.environ.get("BROWSER_START_URL", "about:blank")
EXTRA_FLAGS = os.environ.get("CHROMIUM_FLAGS", "").split()
CDP_HTTP = "http://127.0.0.1:%d" % CHROME_PORT
MAX_TTL = 3600


def log(*parts):
    print("[engine]", *parts, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- processes

class Proc:
    def __init__(self, name, argv, env=None):
        self.name, self.argv, self.env, self.p = name, argv, env, None

    def start(self):
        self.p = subprocess.Popen(self.argv, env=self.env, stdin=subprocess.DEVNULL, start_new_session=True)
        log("started", self.name, "pid", self.p.pid)
        return self

    def alive(self):
        return self.p is not None and self.p.poll() is None

    def stop(self, timeout=5):
        if not self.alive():
            return
        try:
            os.killpg(self.p.pid, signal.SIGTERM)
            self.p.wait(timeout=timeout)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log("stopped", self.name)


def x_env():
    env = dict(os.environ)
    env["DISPLAY"] = DISPLAY
    env.setdefault("HOME", "/tmp")
    return env


def wait_for(check, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("%s did not start" % what)


def tcp_open(port):
    with socket.create_connection(("127.0.0.1", port), timeout=1):
        return True


def start_xvfb():
    w, h = SCREEN.lower().split("x")
    p = Proc("xvfb", ["Xvfb", DISPLAY, "-screen", "0", "%sx%sx24" % (w, h), "-nolisten", "tcp", "-dpi", "96"]).start()
    sock = Path("/tmp/.X11-unix/X" + DISPLAY.lstrip(":"))
    wait_for(sock.exists, 15, "Xvfb")
    return p


def chromium_argv():
    w, h = SCREEN.lower().split("x")
    return [
        CHROMIUM,
        "--user-data-dir=%s" % PROFILE,
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=%d" % CHROME_PORT,
        "--no-sandbox",  # the container drops every capability; there is no sandbox to build
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-sync",
        "--disable-infobars",
        "--hide-crash-restore-bubble",
        "--disable-session-crashed-bubble",
        "--password-store=basic",
        "--disable-features=PasswordManagerOnboarding,AutofillServerCommunication,AutofillEnablePayments,Translate,MediaRouter",
        # Agents and renderers (DeFleur) drive tabs the screen may not show.
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--window-position=0,0",
        "--window-size=%s,%s" % (w, h),
        *EXTRA_FLAGS,
        START_URL,
    ]


def start_chromium():
    PROFILE.mkdir(parents=True, exist_ok=True)
    for lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (PROFILE / lock).unlink()
        except FileNotFoundError:
            pass
    p = Proc("chromium", chromium_argv(), x_env()).start()
    wait_for(lambda: urllib.request.urlopen(CDP_HTTP + "/json/version", timeout=1).status == 200, 45, "Chromium DevTools")
    return p


# ---------------------------------------------------------------- CDP forwarder

def _pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _forward_one(client):
    try:
        upstream = socket.create_connection(("127.0.0.1", CHROME_PORT), timeout=10)
        upstream.settimeout(None)
    except OSError:
        client.close()
        return
    t = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
    t.start()
    _pipe(client, upstream)
    t.join()
    client.close()
    upstream.close()


def serve_cdp_forwarder():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", CDP_PORT))
    srv.listen(128)
    log("DevTools forwarder on :%d -> 127.0.0.1:%d" % (CDP_PORT, CHROME_PORT))
    while True:
        client, _ = srv.accept()
        threading.Thread(target=_forward_one, args=(client,), daemon=True).start()


# ---------------------------------------------------------------- handoff session

class Handoff:
    """x11vnc + websockify exist only while a handoff is open."""

    def __init__(self):
        self.lock = threading.Lock()
        self.vnc = self.ws = None
        self.expires = 0.0

    def active(self):
        return bool(self.vnc and self.vnc.alive() and self.ws and self.ws.alive() and time.time() < self.expires)

    def start(self, password, ws_secret, ttl):
        if not (8 <= len(password) <= 128 and password.isalnum()):
            raise ValueError("password must be 8-128 letters or digits")
        if not (16 <= len(ws_secret) <= 128 and ws_secret.isalnum()):
            raise ValueError("ws_secret must be 16-128 letters or digits")
        ttl = max(60, min(int(ttl), MAX_TTL))
        with self.lock:
            self._stop()
            RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
            pw = RUNTIME / "vnc-passwd"
            r = subprocess.run(["x11vnc", "-storepasswd", password[:8], str(pw)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=x_env())
            if r.returncode != 0 or not pw.is_file():
                raise RuntimeError("x11vnc could not store the session password")
            pw.chmod(0o600)
            self.vnc = Proc("x11vnc", ["x11vnc", "-display", DISPLAY, "-localhost", "-rfbport", str(VNC_PORT),
                                       "-forever", "-shared", "-rfbauth", str(pw), "-noxdamage", "-repeat",
                                       "-quiet", "-noclipboard", "-nosetclipboard"], x_env()).start()
            wait_for(lambda: tcp_open(VNC_PORT), 15, "x11vnc")
            # The MCP front adds this Basic credential when it forwards an authorized viewer, so
            # nothing else on the network can open the VNC stream; the VNC password is a second lock.
            self.ws = Proc("websockify", [sys.executable, "-m", "websockify", "--auth-plugin", "BasicHTTPAuth",
                                          "--auth-source", "handoff:" + ws_secret, "0.0.0.0:%d" % WS_PORT,
                                          "127.0.0.1:%d" % VNC_PORT], x_env()).start()
            wait_for(lambda: tcp_open(WS_PORT), 15, "websockify")
            self.expires = time.time() + ttl
            return self.state()

    def _stop(self):
        for p in (self.ws, self.vnc):
            if p:
                p.stop()
        self.vnc = self.ws = None
        self.expires = 0.0
        try:
            (RUNTIME / "vnc-passwd").unlink()
        except FileNotFoundError:
            pass

    def stop(self):
        with self.lock:
            was = self.vnc is not None
            self._stop()
            return {"stopped": was}

    def state(self):
        return {"active": self.active(), "expires_in": max(0, int(self.expires - time.time())) if self.vnc else 0}

    def reap(self):
        with self.lock:
            if self.vnc and not self.active():
                log("handoff ended (expired or a VNC process exited)")
                self._stop()


HANDOFF = Handoff()


# ---------------------------------------------------------------- phone controls (from tailnet-browser)

def _recv_exact(sock, length):
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(length - len(chunks))
        if not chunk:
            raise ConnectionError("WebSocket closed unexpectedly")
        chunks.extend(chunk)
    return bytes(chunks)


def _send_ws_text(sock, text):
    payload = text.encode("utf-8")
    mask = os.urandom(4)
    n = len(payload)
    if n < 126:
        header = bytes((0x81, 0x80 | n))
    elif n < 65536:
        header = bytes((0x81, 0x80 | 126)) + struct.pack("!H", n)
    else:
        header = bytes((0x81, 0x80 | 127)) + struct.pack("!Q", n)
    sock.sendall(header + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload)))


def _recv_ws_text(sock):
    while True:
        first, second = _recv_exact(sock, 2)
        opcode, length = first & 0x0F, second & 0x7F
        masked = bool(second & 0x80)
        if length == 126:
            length = struct.unpack("!H", _recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
        mask = _recv_exact(sock, 4) if masked else b""
        payload = _recv_exact(sock, length)
        if masked:
            payload = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
        if opcode == 0x9:
            sock.sendall(bytes((0x8A, len(payload))) + payload)
            continue
        if opcode == 0x8:
            raise ConnectionError("Chrome closed the CDP WebSocket")
        if opcode in (0x1, 0x0):
            return payload.decode("utf-8")


def _cdp_to_page(page, command):
    url = urllib.parse.urlparse(page["webSocketDebuggerUrl"])
    sock = socket.create_connection(("127.0.0.1", CHROME_PORT), timeout=3)
    sock.settimeout(5)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        sock.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (url.path, CHROME_PORT, key)).encode())
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("Chrome closed the CDP WebSocket")
            response.extend(chunk)
        headers = bytes(response).split(b"\r\n\r\n", 1)[0]
        if b" 101 " not in headers.split(b"\r\n", 1)[0]:
            raise ConnectionError("Chrome rejected the CDP WebSocket upgrade")
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if expected.lower() not in headers.lower():
            raise ConnectionError("Chrome returned an invalid WebSocket accept key")
        _send_ws_text(sock, json.dumps(command, separators=(",", ":")))
        while True:
            message = json.loads(_recv_ws_text(sock))
            if message.get("id") == command.get("id"):
                return message
    finally:
        sock.close()


def _eval(page, expression):
    r = _cdp_to_page(page, {"id": 1, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}})
    if "error" in r:
        raise RuntimeError(r["error"].get("message", "CDP command failed"))
    return r.get("result", {}).get("result", {}).get("value")


def visible_page():
    """The tab the human sees: focused, else visible, else the first page."""
    with urllib.request.urlopen(CDP_HTTP + "/json/list", timeout=3) as r:
        pages = [p for p in json.load(r) if p.get("type") == "page"]
    if not pages:
        raise RuntimeError("No Chromium page is available")
    for expr in ("document.hasFocus()", "document.visibilityState === 'visible'"):
        for page in pages:
            try:
                if _eval(page, expr) is True:
                    return page
            except Exception:
                continue
    return pages[0]


SCROLL_JS = """(() => {
  const sign = %d;
  const root = document.scrollingElement;
  const scrollable = (el) => {
    if (!el || el.clientHeight <= 0 || el.scrollHeight <= el.clientHeight + 4) return false;
    if (el === root) return true;
    const overflow = getComputedStyle(el).overflowY;
    return overflow === 'auto' || overflow === 'scroll' || overflow === 'overlay';
  };
  let target = document.activeElement;
  while (target && target !== document.body && !scrollable(target)) target = target.parentElement;
  if (!scrollable(target)) {
    target = [root, ...document.querySelectorAll('*')]
      .filter(scrollable)
      .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
  }
  if (!target) return {scrolled:false, reason:'no-scrollable-element'};
  const before = target.scrollTop;
  const amount = Math.max(160, Math.round(target.clientHeight * 0.39));
  target.scrollTop += sign * amount;
  return {scrolled:target.scrollTop !== before, before, after:target.scrollTop, amount, tag:target.tagName};
})()"""

FOCUSED_EDITABLE_JS = """(() => {
  let element = document.activeElement;
  while (element) {
    try {
      if (element.shadowRoot && element.shadowRoot.activeElement) { element = element.shadowRoot.activeElement; continue; }
      if (element.tagName === 'IFRAME' && element.contentDocument && element.contentDocument.activeElement) {
        element = element.contentDocument.activeElement; continue;
      }
    } catch (_) {}
    break;
  }
  const tag = element ? element.tagName : '';
  const blocked = new Set(['button','checkbox','color','file','hidden','image','radio','range','reset','submit']);
  const editable = Boolean(element && !element.disabled && !element.readOnly && (
    tag === 'TEXTAREA' || (tag === 'INPUT' && !blocked.has((element.type || 'text').toLowerCase())) || element.isContentEditable));
  return {editable};
})()"""


# ---------------------------------------------------------------- control server

_PEERS = {"at": 0.0, "set": set()}


def allowed_peers():
    if time.monotonic() - _PEERS["at"] > 15:
        peers = {"127.0.0.1", "::1"}
        if FRONT_HOST:
            try:
                peers.update(str(i[4][0]) for i in socket.getaddrinfo(FRONT_HOST, None))
            except OSError:
                pass
        _PEERS.update(at=time.monotonic(), set=peers)
    return _PEERS["set"]


CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".ico": "image/x-icon", ".json": "application/json", ".txt": "text/plain; charset=utf-8",
                 ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".oga": "audio/ogg",
                 ".mp3": "audio/mpeg", ".wav": "audio/wav"}


class Control(BaseHTTPRequestHandler):
    server_version = "BrowserEngine/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _peer_ok(self):
        if self.client_address[0] in allowed_peers():
            return True
        self._send(403, {"ok": False, "error": "the browser engine answers only the Browser app"})
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(min(n, 65536)) or b"{}") if n else {}

    def do_GET(self):
        if not self._peer_ok():
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"ok": True, "handoff": HANDOFF.state()})
        if path == "/session":
            return self._send(200, HANDOFF.state())
        rel = path.lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        target = (VIEWER_ROOT / rel).resolve()
        if VIEWER_ROOT not in target.parents or not target.is_file():
            return self._send(404, {"ok": False, "error": "not-found"})
        self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

    do_HEAD = do_GET

    def do_DELETE(self):
        if not self._peer_ok():
            return
        if urllib.parse.urlparse(self.path).path != "/session":
            return self._send(404, {"ok": False, "error": "not-found"})
        self._send(200, {"ok": True, **HANDOFF.stop()})

    def do_POST(self):
        if not self._peer_ok():
            return
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/session":
                body = self._body()
                return self._send(200, {"ok": True, **HANDOFF.start(str(body.get("password", "")),
                                                                    str(body.get("ws_secret", "")),
                                                                    body.get("ttl", 900))})
            if not HANDOFF.active():
                return self._send(409, {"ok": False, "error": "no-active-handoff"})
            if parsed.path == "/control/scroll":
                direction = query.get("direction", [""])[0]
                if direction not in ("up", "down"):
                    return self._send(400, {"ok": False, "error": "direction-must-be-up-or-down"})
                result = _eval(visible_page(), SCROLL_JS % (-1 if direction == "up" else 1))
                return self._send(200, {"ok": True, "result": result if isinstance(result, dict) else {"scrolled": False}})
            if parsed.path == "/control/focused-editable":
                result = _eval(visible_page(), FOCUSED_EDITABLE_JS)
                return self._send(200, {"ok": True, "result": result if isinstance(result, dict) else {"editable": False}})
            self._send(404, {"ok": False, "error": "not-found"})
        except ValueError as exc:
            self._send(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send(502, {"ok": False, "error": str(exc)})


# ---------------------------------------------------------------- main

def main():
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    xvfb = start_xvfb()
    chrome = start_chromium()
    threading.Thread(target=serve_cdp_forwarder, daemon=True).start()
    control = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), Control)
    control.daemon_threads = True
    threading.Thread(target=control.serve_forever, daemon=True).start()
    log("control on :%d, screen %s, viewer %s" % (CONTROL_PORT, SCREEN, VIEWER_ROOT))

    stopping = threading.Event()

    def on_signal(*_):
        stopping.set()
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    while not stopping.wait(1):
        if not xvfb.alive():
            log("Xvfb exited; restarting the display and the browser")
            HANDOFF.stop()
            chrome.stop()
            xvfb = start_xvfb()
            chrome = start_chromium()
        elif not chrome.alive():
            log("Chromium exited (a client may have called Browser.close); restarting it")
            try:
                chrome = start_chromium()
            except RuntimeError as exc:
                log(exc)
        HANDOFF.reap()
    HANDOFF.stop()
    chrome.stop()
    xvfb.stop()


if __name__ == "__main__":
    main()
