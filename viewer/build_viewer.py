#!/usr/bin/env python3
"""Build the Browser app's mobile human-handoff viewer from stock noVNC 1.3.0.

Usage: python3 viewer/build_viewer.py <noVNC-1.3.0 source dir> <output dir>

The phone controls (fixed bottom bar: Keyboard, Paste, Up, Down; automatic
keyboard for focused remote fields; keyboard-safe viewport; 39% page scroll)
and the paced native tap patch are ported unchanged from Humanity Labs'
tailnet-browser / hermes-human-handoff viewer, which is tested on Android
and iOS phones. Keep noVNC at 1.3.0 and keep the versioned client-1.3.0/
asset path: an adapted noVNC 1.7 client hung and dropped on Android.

Every replacement is exact: the build fails if noVNC's markup is not the
1.3.0 markup the patches were written against.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_rfb_taps import patch_rfb_taps  # noqa: E402

if len(sys.argv) != 3:
    sys.exit(__doc__)
source, root = Path(sys.argv[1]), Path(sys.argv[2])
if '"version": "1.3.0"' not in (source / "package.json").read_text():
    sys.exit("noVNC source is not version 1.3.0")
client = root / "client-1.3.0"
if root.exists():
    shutil.rmtree(root)
client.mkdir(parents=True)
for name in ("app", "core", "vendor"):
    shutil.copytree(source / name, client / name)
for name in ("vnc.html", "LICENSE.txt", "AUTHORS"):
    shutil.copy2(source / name, client / name)
shutil.copy2(Path(__file__).resolve().parent / "index.html", root / "index.html")

p = client / "vnc.html"
s = p.read_text(encoding="utf-8")
s = s.replace("<title>noVNC</title>", "<title>Browser handoff</title>")
s = s.replace(
    'content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"',
    'content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, interactive-widget=resizes-content"',
)
s = s.replace("</head>", '  <meta name="theme-color" content="#0B0B0D" />\n  <meta name="robots" content="noindex,nofollow" />\n</head>', 1)
p.write_text(s, encoding="utf-8")

# Keep the stock noVNC transport while replacing its side drawer with a
# phone-native bottom toolbar. The paste field is masked by default because
# this path is primarily used for credentials and clears after sending.
html_path = client / 'vnc.html'
html = html_path.read_text(encoding='utf-8')
build_id = '20260822-19'
html = html.replace('href="app/styles/base.css"', f'href="app/styles/base.css?v={build_id}"')
html = html.replace('src="app/error-handler.js"', f'src="app/error-handler.js?v={build_id}"')
html = html.replace('src="app/ui.js"', f'src="app/ui.js?v={build_id}"')
handoff_bootstrap = '''    <script>
      (() => {
        // Browser app: the capability arrives in the URL fragment, never in a
        // query string or server log. Keep it in a path-scoped session cookie
        // (the MCP front checks it on the WebSocket and control requests), use
        // its first 8 characters as the VNC password, then drop it from history.
        const root = window.location.pathname.replace(/client-1\\.3\\.0\\/[^/]*$/, '');
        const name = 'browser_handoff';
        let raw = window.location.hash.slice(1);
        if (/^[A-Za-z0-9]{16,128}$/.test(raw)) {
          document.cookie = name + '=' + raw + '; path=' + root + '; SameSite=Strict' +
            (window.location.protocol === 'https:' ? '; Secure' : '');
          history.replaceState(null, '', window.location.pathname + window.location.search);
        } else {
          const match = document.cookie.match(/(?:^|; )browser_handoff=([A-Za-z0-9]{16,128})/);
          raw = match ? match[1] : '';
        }
        if (raw) window.__HANDOFF_CAPABILITY__ = raw.slice(0, 8);
        const control = new URLSearchParams(window.location.search).get('control');
        window.__HANDOFF_CONTROL_BASE__ = (control || (root + 'control')).replace(/\\/$/, '');
      })();
    </script>
'''
html = html.replace(
    '    <script type="module" crossorigin="anonymous" src="app/ui.js?v=20260822-19"></script>',
    handoff_bootstrap + '    <script type="module" crossorigin="anonymous" src="app/ui.js?v=20260822-19"></script>',
    1,
)
old_clipboard = '''                <textarea id="noVNC_clipboard_text" rows=5></textarea>
                <br>
                <input id="noVNC_clipboard_clear_button" type="button"
                    value="Clear" class="noVNC_submit">'''
new_clipboard = '''                <label class="noVNC_clipboard_label" for="noVNC_clipboard_text">Paste from this device</label>
                <input id="noVNC_clipboard_text" type="password" maxlength="4096"
                    autocomplete="off" autocapitalize="none" autocorrect="off"
                    spellcheck="false" placeholder="Paste text or password">
                <label class="noVNC_clipboard_reveal">
                    <input id="noVNC_clipboard_show_text" type="checkbox"> Show text
                </label>
                <p class="noVNC_clipboard_help">Tap the remote field first, paste here, then send it.</p>
                <div class="noVNC_clipboard_actions">
                    <input id="noVNC_clipboard_clear_button" type="button"
                        value="Clear" class="noVNC_submit">
                    <input id="noVNC_clipboard_paste_button" type="button"
                        value="Paste into focused field" class="noVNC_submit">
                </div>'''
if old_clipboard not in html:
    raise SystemExit('Expected noVNC 1.3.0 clipboard markup was not found')
html = html.replace(old_clipboard, new_clipboard, 1)

dock_anchor = '''    <!-- Status Dialog -->'''
dock_markup = '''    <!-- Tailnet Browser phone controls -->
    <div id="tailnet_paste_sheet" role="dialog" aria-modal="false" aria-labelledby="tailnet_paste_title" aria-hidden="true">
        <div class="tailnet_sheet_header">
            <strong id="tailnet_paste_title">Paste into remote field</strong>
            <button id="tailnet_paste_close" type="button" title="Close paste panel" aria-label="Close paste panel">×</button>
        </div>
        <input id="tailnet_paste_text" class="tailnet_masked" type="text" maxlength="4096"
            autocomplete="off" autocapitalize="none" autocorrect="off"
            spellcheck="false" placeholder="Paste text or password">
        <div class="tailnet_sheet_meta">
            <button id="tailnet_paste_show" class="tailnet_visibility_toggle" type="button" aria-pressed="false">
                <span class="tailnet_visibility_mark" aria-hidden="true"></span> Show text
            </button>
            <span>Tap the remote field first</span>
        </div>
        <div class="tailnet_sheet_actions">
            <button id="tailnet_paste_clear" type="button">Clear</button>
            <button id="tailnet_paste_send" class="tailnet_primary" type="button">Paste into field</button>
        </div>
    </div>

    <nav id="tailnet_mobile_bar" aria-label="Remote browser controls">
        <button id="tailnet_keyboard" type="button" title="Open phone keyboard" aria-label="Open phone keyboard">
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M6 9h1m3 0h1m3 0h1m3 0h0M6 12h1m3 0h1m3 0h1m3 0h0M7 15h10"/></svg>
            <span>Keyboard</span>
        </button>
        <button id="tailnet_paste" type="button" title="Paste into remote field" aria-label="Paste into remote field" aria-expanded="false">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5h6l1 2h3v13H5V7h3z"/><path d="M9 4h6v4H9zM8 12h8m-8 4h6"/></svg>
            <span>Paste</span>
        </button>
        <button id="tailnet_scroll_up" type="button" title="Scroll page up" aria-label="Scroll page up">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 14 6-6 6 6"/></svg>
            <span>Up</span>
        </button>
        <button id="tailnet_scroll_down" type="button" title="Scroll page down" aria-label="Scroll page down">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 10 6 6 6-6"/></svg>
            <span>Down</span>
        </button>
    </nav>

    <div id="tailnet_live_announcement" class="tailnet_sr_only" aria-live="polite"></div>

'''
if dock_anchor not in html:
    raise SystemExit('Expected noVNC status dialog anchor was not found')
html = html.replace(dock_anchor, dock_markup + dock_anchor, 1)
html_path.write_text(html, encoding='utf-8')

ui_path = client / 'app' / 'ui.js'
ui = ui_path.read_text(encoding='utf-8')
old_handlers = '''        document.getElementById("noVNC_clipboard_clear_button")
            .addEventListener('click', UI.clipboardClear);'''
new_handlers = '''        const on = (id, event, handler) => {
            const element = document.getElementById(id);
            if (element) element.addEventListener(event, handler);
            return element;
        };
        on("noVNC_clipboard_clear_button", 'click', UI.clipboardClear);
        on("noVNC_clipboard_paste_button", 'click', UI.clipboardPasteIntoFocusedField);
        on("noVNC_clipboard_show_text", 'change', UI.clipboardToggleVisibility);
        const scrollUp = document.getElementById("tailnet_scroll_up");
        const scrollDown = document.getElementById("tailnet_scroll_down");
        if (scrollUp && scrollDown) {
            UI.bindMobileScrollButton(scrollUp, -1);
            UI.bindMobileScrollButton(scrollDown, 1);
        }
        on("tailnet_keyboard", 'click', UI.toggleTailnetKeyboard);
        on("tailnet_paste", 'click', UI.toggleTailnetPasteSheet);
        on("tailnet_paste_close", 'click', UI.closeTailnetPasteSheet);
        on("tailnet_paste_clear", 'click', UI.clearTailnetPaste);
        on("tailnet_paste_send", 'click', UI.clipboardPasteIntoFocusedField);
        on("tailnet_paste_show", 'pointerdown', UI.preserveTailnetPasteFocus);
        on("tailnet_paste_show", 'click', UI.toggleTailnetPasteVisibility);
        on("noVNC_keyboardinput", 'focus', UI.syncTailnetKeyboardButton);
        on("noVNC_keyboardinput", 'blur', UI.syncTailnetKeyboardButton);
        UI.initTailnetViewport();
        UI.initTailnetRemoteEditableFocus();
'''
if old_handlers not in ui:
    raise SystemExit('Expected noVNC clipboard handlers were not found')
ui = ui.replace(old_handlers, new_handlers, 1)
old_functions = '''    clipboardReceive(e) {
        Log.Debug(">> UI.clipboardReceive: " + e.detail.text.substr(0, 40) + "...");
        document.getElementById('noVNC_clipboard_text').value = e.detail.text;
        Log.Debug("<< UI.clipboardReceive");
    },

    clipboardClear() {
        document.getElementById('noVNC_clipboard_text').value = "";
        UI.rfb.clipboardPasteFrom("");
    },

    clipboardSend() {
        const text = document.getElementById('noVNC_clipboard_text').value;
        Log.Debug(">> UI.clipboardSend: " + text.substr(0, 40) + "...");
        UI.rfb.clipboardPasteFrom(text);
        Log.Debug("<< UI.clipboardSend");
    },'''
new_functions = '''    announceTailnetControl(message) {
        const live = document.getElementById("tailnet_live_announcement");
        live.textContent = "";
        setTimeout(() => { live.textContent = message; }, 10);
    },

    initTailnetViewport() {
        let frame = null;
        const schedule = () => {
            if (frame !== null) cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => {
                frame = null;
                UI.syncTailnetViewport();
            });
        };
        window.addEventListener('resize', schedule, {passive: true});
        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', schedule, {passive: true});
            window.visualViewport.addEventListener('scroll', schedule, {passive: true});
        }
        schedule();
    },

    syncTailnetViewport() {
        const viewport = window.visualViewport;
        const root = document.documentElement;
        const visibleHeight = Math.max(240, Math.round(viewport ? viewport.height : window.innerHeight));
        const layoutHeight = Math.max(visibleHeight, root.clientHeight || window.innerHeight);
        const offsetTop = Math.max(0, Math.round(viewport ? viewport.offsetTop : 0));
        const coveredBottom = Math.max(0, Math.round(layoutHeight - visibleHeight - offsetTop));
        root.style.setProperty('--tailnet-visible-height', `${visibleHeight}px`);
        root.style.setProperty('--tailnet-keyboard-inset', `${coveredBottom}px`);
    },

    tailnetKeyboardIsActive() {
        const input = document.getElementById("noVNC_keyboardinput");
        const button = document.getElementById("tailnet_keyboard");
        const upstream = document.getElementById("noVNC_keyboard_button");
        return document.activeElement === input ||
            Boolean(button && button.classList.contains("tailnet_active")) ||
            Boolean(upstream && upstream.classList.contains("noVNC_selected"));
    },

    dismissTailnetKeyboard() {
        // Use the Paste panel's proven close path directly: blur the local
        // keyboard target, then return focus to the remote canvas. The previous
        // synthetic focus transfer caused the visible Android keyboard flicker.
        UI.hideVirtualKeyboard();
        const input = document.getElementById("noVNC_keyboardinput");
        if (input) input.blur();
        if (UI.rfb) UI.rfb.focus();
        UI.syncTailnetKeyboardButton();
        UI.syncTailnetViewport();
    },

    toggleTailnetKeyboard(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        const keyboardWasActive = UI.tailnetKeyboardIsActive();
        UI.closeTailnetPasteSheet();
        if (keyboardWasActive) {
            UI.dismissTailnetKeyboard();
            UI.announceTailnetControl(_("Keyboard hidden"));
        } else {
            UI.showVirtualKeyboard();
            UI.announceTailnetControl(_("Keyboard shown"));
        }
        setTimeout(() => {
            UI.syncTailnetKeyboardButton();
            UI.syncTailnetViewport();
        }, 0);
    },

    initTailnetRemoteEditableFocus() {
        const container = document.getElementById("noVNC_container");
        if (!container) return;
        container.addEventListener('pointerup', UI.probeTailnetRemoteEditable, {passive: true});
    },

    tailnetControlEndpoint(action) {
        const configured = window.__HANDOFF_CONTROL_BASE__;
        if (configured) return `${configured}/${action}`;
        return `${window.location.pathname.replace(/client-1\\.3\\.0\\/[^/]*$/, '')}control/${action}`;
    },

    probeTailnetRemoteEditable(event) {
        if (!UI.connected || event.isPrimary === false) return;
        const canvas = event.target && event.target.closest ? event.target.closest("canvas") : null;
        if (!canvas) return;
        const probeId = (UI.tailnetEditableProbeId || 0) + 1;
        UI.tailnetEditableProbeId = probeId;
        setTimeout(() => {
            if (UI.tailnetEditableProbeId !== probeId) return;
            const sheet = document.getElementById("tailnet_paste_sheet");
            if (sheet && sheet.classList.contains("tailnet_open")) return;
            fetch(UI.tailnetControlEndpoint("focused-editable"), {
                method: "POST",
                cache: "no-store",
                credentials: "same-origin",
            }).then((response) => {
                if (!response.ok) throw new Error(`Browser control returned ${response.status}`);
                return response.json();
            }).then((payload) => {
                if (UI.tailnetEditableProbeId !== probeId) return;
                const editable = Boolean(payload && payload.result && payload.result.editable);
                if (!editable) return;
                UI.showVirtualKeyboard();
                UI.syncTailnetKeyboardButton();
                UI.syncTailnetViewport();
            }).catch(() => {});
        }, 220);
    },

    syncTailnetKeyboardButton() {
        const active = document.activeElement === document.getElementById("noVNC_keyboardinput");
        const button = document.getElementById("tailnet_keyboard");
        button.classList.toggle("tailnet_active", active);
        button.setAttribute("aria-pressed", String(active));
    },

    syncTailnetFullscreenButton() {
        const button = document.getElementById("tailnet_fullscreen");
        if (!button) return;
        const active = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
        button.classList.toggle("tailnet_active", active);
        button.setAttribute("aria-pressed", String(active));
    },

    toggleTailnetPasteSheet() {
        const sheet = document.getElementById("tailnet_paste_sheet");
        if (sheet.classList.contains("tailnet_open")) {
            UI.closeTailnetPasteSheet();
        } else {
            UI.hideVirtualKeyboard();
            sheet.classList.add("tailnet_open");
            sheet.setAttribute("aria-hidden", "false");
            document.getElementById("tailnet_paste").setAttribute("aria-expanded", "true");
            setTimeout(() => document.getElementById("tailnet_paste_text").focus(), 40);
        }
    },

    closeTailnetPasteSheet() {
        const sheet = document.getElementById("tailnet_paste_sheet");
        sheet.classList.remove("tailnet_open");
        sheet.setAttribute("aria-hidden", "true");
        document.getElementById("tailnet_paste").setAttribute("aria-expanded", "false");
        document.getElementById("tailnet_paste_text").blur();
        if (UI.rfb) UI.rfb.focus();
    },

    clearTailnetPaste() {
        const field = document.getElementById("tailnet_paste_text");
        field.value = "";
        document.getElementById("tailnet_paste_show").setAttribute("aria-pressed", "false");
        field.classList.add("tailnet_masked");
        field.focus();
    },

    preserveTailnetPasteFocus(event) {
        if (event) event.preventDefault();
    },

    toggleTailnetPasteVisibility() {
        const button = document.getElementById("tailnet_paste_show");
        const next = button.getAttribute("aria-pressed") !== "true";
        button.setAttribute("aria-pressed", next ? "true" : "false");
        UI.syncTailnetPasteVisibility();
    },

    syncTailnetPasteVisibility() {
        const field = document.getElementById("tailnet_paste_text");
        const show = document.getElementById("tailnet_paste_show").getAttribute("aria-pressed") === "true";
        field.classList.toggle("tailnet_masked", !show);
        field.focus({preventScroll: true});
    },

    bindMobileScrollButton(button, direction) {
        // One native button click equals one predictable page step. Long-press
        // repeat is intentionally omitted because noVNC can capture the release
        // event and leave a mobile repeat timer running to the page boundary.
        button.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            UI.remoteScroll(direction);
        });
    },

    remoteScroll(direction) {
        if (!UI.rfb || !UI.connected) {
            UI.showStatus(_("The remote browser is not connected"), "warning");
            return;
        }

        const directionName = direction < 0 ? "up" : "down";
        const endpoint = UI.tailnetControlEndpoint("scroll");
        fetch(`${endpoint}?direction=${directionName}`, {
            method: "POST",
            cache: "no-store",
            credentials: "same-origin",
        }).then((response) => {
            if (!response.ok) throw new Error(`Browser control returned ${response.status}`);
        }).catch(() => {
            // Fallback for installs without the local control bridge.
            const keysym = direction < 0 ? 0xff55 : 0xff56;
            const code = direction < 0 ? "PageUp" : "PageDown";
            UI.rfb.sendKey(keysym, code);
        });
        UI.rfb.focus();
    },

    clipboardReceive(e) {
        Log.Debug(">> UI.clipboardReceive");
        document.getElementById('noVNC_clipboard_text').value = e.detail.text;
        Log.Debug("<< UI.clipboardReceive");
    },

    clipboardToggleVisibility() {
        const field = document.getElementById('noVNC_clipboard_text');
        const show = document.getElementById('noVNC_clipboard_show_text').checked;
        field.type = show ? "text" : "password";
    },

    clipboardClear() {
        const field = document.getElementById('noVNC_clipboard_text');
        field.value = "";
        field.type = "password";
        document.getElementById('noVNC_clipboard_show_text').checked = false;
        UI.rfb.clipboardPasteFrom("");
    },

    clipboardSend() {
        const text = document.getElementById('noVNC_clipboard_text').value;
        Log.Debug(">> UI.clipboardSend");
        UI.rfb.clipboardPasteFrom(text);
        Log.Debug("<< UI.clipboardSend");
    },

    clipboardPasteIntoFocusedField() {
        const field = document.getElementById('tailnet_paste_text');
        const text = field.value;

        if (!UI.rfb || !UI.connected) {
            UI.showStatus(_("The remote browser is not connected"), "warning");
            return;
        }
        if (!text) {
            UI.showStatus(_("Paste field is empty"), "warning");
            return;
        }

        const characters = Array.from(text);
        if (characters.length > 4096) {
            UI.showStatus(_("Paste is too long"), "warning");
            return;
        }

        // Use the same RFB key path as noVNC's Android keyboard support. This
        // avoids browser clipboard-permission differences and preserves the
        // remote field that the user tapped before opening this panel.
        for (const character of characters) {
            if (character === "\\n" || character === "\\r") {
                UI.rfb.sendKey(KeyTable.XK_Return, "Enter");
            } else if (character === "\\t") {
                UI.rfb.sendKey(KeyTable.XK_Tab, "Tab");
            } else {
                UI.rfb.sendKey(keysyms.lookup(character.codePointAt(0)));
            }
        }

        field.value = "";
        document.getElementById('tailnet_paste_show').setAttribute("aria-pressed", "false");
        field.classList.add("tailnet_masked");
        UI.closeTailnetPasteSheet();
        UI.rfb.focus();
        UI.announceTailnetControl(_("Pasted into focused field"));
        UI.showStatus(_("Pasted into focused field"), "normal");
    },'''
if old_functions not in ui:
    raise SystemExit('Expected noVNC clipboard functions were not found')
ui = ui.replace(old_functions, new_functions, 1)
password_lookup = '''        if (typeof password === 'undefined') {
            password = WebUtil.getConfigVar('password');
            UI.reconnectPassword = password;
        }'''
handoff_password_lookup = '''        if (typeof password === 'undefined') {
            password = window.__HANDOFF_CAPABILITY__ || WebUtil.getConfigVar('password');
            UI.reconnectPassword = password;
            window.__HANDOFF_CAPABILITY__ = null;
        }'''
if password_lookup not in ui:
    raise SystemExit('Expected noVNC password lookup was not found')
ui_path.write_text(ui.replace(password_lookup, handoff_password_lookup, 1), encoding='utf-8')

css_path = client / 'app' / 'styles' / 'base.css'
css = css_path.read_text(encoding='utf-8')
paste_css = '''

/* Tailnet Browser: compact, phone-friendly direct paste control. */
.noVNC_clipboard_label {
  display: block;
  margin: 0 0 6px;
  font-weight: 600;
}
#noVNC_clipboard_text {
  box-sizing: border-box;
  min-height: 44px;
  padding: 10px 12px;
  font-size: 16px;
}
.noVNC_clipboard_reveal {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  font-size: 14px;
}
.noVNC_clipboard_help {
  margin: 4px 0 10px;
  max-width: 500px;
  color: rgb(80, 80, 80);
  font-size: 13px;
  line-height: 1.35;
}
.noVNC_clipboard_actions {
  display: flex;
  gap: 8px;
}
.noVNC_clipboard_actions .noVNC_submit {
  float: none;
  min-height: 44px;
  flex: 1 1 auto;
}
#noVNC_clipboard_paste_button {
  font-weight: 600;
}
:root {
  --tailnet-bar-height: 76px;
  --tailnet-accent: #8ab4f8;
  --tailnet-accent-soft: rgba(138,180,248,.12);
  --tailnet-panel: #12151a;
}
#noVNC_control_bar_anchor {
  display: none !important;
}
:root.noVNC_connected #noVNC_container {
  height: calc(var(--tailnet-visible-height, 100vh) - var(--tailnet-bar-height) - env(safe-area-inset-bottom));
  border-radius: 0;
}
#noVNC_keyboardinput {
  position: fixed;
  top: 0;
  left: 0;
  opacity: 0;
}
#tailnet_mobile_bar {
  box-sizing: border-box;
  position: fixed;
  z-index: 40;
  left: 0;
  right: 0;
  bottom: var(--tailnet-keyboard-inset, 0px);
  height: calc(var(--tailnet-bar-height) + env(safe-area-inset-bottom));
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: stretch;
  gap: 2px;
  padding: 6px 6px calc(6px + env(safe-area-inset-bottom));
  border-top: 1px solid rgba(255,255,255,.12);
  background: rgba(14,17,22,.97);
  box-shadow: 0 -8px 28px rgba(0,0,0,.36);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}
#tailnet_mobile_bar button {
  min-width: 0;
  min-height: 60px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  margin: 0;
  padding: 4px 1px 3px;
  border: 0;
  border-radius: 12px;
  color: rgba(255,255,255,.74);
  background: transparent;
  font: 650 10.5px/1 system-ui, -apple-system, sans-serif;
  letter-spacing: .01em;
  touch-action: manipulation;
  user-select: none;
  -webkit-user-select: none;
}
#tailnet_mobile_bar svg {
  width: 25px;
  height: 25px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
#tailnet_mobile_bar button.tailnet_active,
#tailnet_mobile_bar button.tailnet_pressed,
#tailnet_mobile_bar button:active {
  color: var(--tailnet-accent);
  background: var(--tailnet-accent-soft);
}
#tailnet_mobile_bar button.tailnet_pressed,
#tailnet_mobile_bar button:active {
  transform: scale(.95);
}
:root:not(.noVNC_connected) #tailnet_mobile_bar {
  opacity: .42;
}
#tailnet_paste_sheet {
  box-sizing: border-box;
  position: fixed;
  z-index: 45;
  left: 8px;
  right: 8px;
  bottom: calc(var(--tailnet-keyboard-inset, 0px) + var(--tailnet-bar-height) + env(safe-area-inset-bottom) + 8px);
  width: auto;
  max-width: 480px;
  margin: 0 auto;
  padding: 14px;
  border: 1px solid rgba(255,255,255,.14);
  border-radius: 18px;
  color: #f1f4f8;
  background: rgba(18,21,26,.98);
  box-shadow: 0 16px 48px rgba(0,0,0,.58);
  opacity: 0;
  pointer-events: none;
  transform: translateY(18px) scale(.98);
  transition: opacity .16s ease, transform .16s ease;
}
#tailnet_paste_sheet.tailnet_open {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0) scale(1);
}
.tailnet_sheet_header,
.tailnet_sheet_meta,
.tailnet_sheet_actions {
  display: flex;
  align-items: center;
}
.tailnet_sheet_header {
  justify-content: space-between;
  margin-bottom: 11px;
}
.tailnet_sheet_header strong {
  font: 700 16px/1.2 system-ui, -apple-system, sans-serif;
}
#tailnet_paste_close {
  width: 36px;
  height: 36px;
  margin: -7px -5px -7px 8px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: rgba(255,255,255,.75);
  background: rgba(255,255,255,.08);
  font: 300 27px/1 system-ui, sans-serif;
}
#tailnet_paste_text {
  box-sizing: border-box;
  width: 100%;
  min-height: 48px;
  margin: 0;
  padding: 11px 13px;
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 12px;
  color: #fff;
  background: #20252d;
  font: 16px/1.3 system-ui, -apple-system, sans-serif;
}
#tailnet_paste_text.tailnet_masked {
  -webkit-text-security: disc;
}
#tailnet_paste_text:focus {
  border-color: var(--tailnet-accent);
  box-shadow: 0 0 0 3px var(--tailnet-accent-soft);
}
.tailnet_sheet_meta {
  justify-content: space-between;
  gap: 12px;
  min-height: 38px;
  color: rgba(255,255,255,.58);
  font: 12px/1.2 system-ui, -apple-system, sans-serif;
}
.tailnet_visibility_toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0;
  border: 0;
  color: inherit;
  background: transparent;
  font: inherit;
  white-space: nowrap;
}
.tailnet_visibility_mark {
  box-sizing: border-box;
  width: 15px;
  height: 15px;
  border: 1px solid rgba(255,255,255,.42);
  border-radius: 4px;
}
.tailnet_visibility_toggle[aria-pressed="true"] .tailnet_visibility_mark {
  border-color: var(--tailnet-accent);
  background: var(--tailnet-accent);
  box-shadow: inset 0 0 0 3px #20252d;
}
.tailnet_sheet_actions {
  gap: 8px;
}
.tailnet_sheet_actions button {
  min-height: 46px;
  flex: 1 1 0;
  margin: 0;
  padding: 8px 12px;
  border: 1px solid rgba(255,255,255,.15);
  border-radius: 12px;
  color: #f5f5f6;
  background: #252b34;
  font: 700 14px/1 system-ui, -apple-system, sans-serif;
}
.tailnet_sheet_actions button.tailnet_primary {
  color: #0b1220;
  border-color: var(--tailnet-accent);
  background: var(--tailnet-accent);
}
.tailnet_sr_only {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  padding: 0 !important;
  margin: -1px !important;
  overflow: hidden !important;
  clip: rect(0,0,0,0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}
@media (max-width: 360px) {
  #tailnet_mobile_bar button {
    font-size: 9.5px;
  }
  #tailnet_mobile_bar svg {
    width: 23px;
    height: 23px;
  }
}
'''
if 'Tailnet Browser: compact, phone-friendly direct paste control.' not in css:
    css_path.write_text(css + paste_css, encoding='utf-8')

# Keep touch input on the real noVNC -> RFB -> X11 path (paced native taps).
patch_rfb_taps(client / "core" / "rfb.js")
print("built", root)
