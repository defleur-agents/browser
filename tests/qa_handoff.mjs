// End-to-end QA for the Browser app: DevTools compatibility, handoff MCP tools and the phone viewer.
// Usage: BASE=http://127.0.0.1:18793 OUT=./evidence node tests/qa_handoff.mjs
// Needs playwright-core and a local Chromium (CHROME=/path or Playwright's cached browser).
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const BASE = (process.env.BASE || 'http://127.0.0.1:18793').replace(/\/$/, '');
const OUT = process.env.OUT || './qa-out';
const CHROME = process.env.CHROME || undefined;
fs.mkdirSync(OUT, { recursive: true });
const report = { base: BASE, checks: {} };
const check = (name, ok, detail) => {
  report.checks[name] = { ok: Boolean(ok), detail };
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail !== undefined ? '  ' + JSON.stringify(detail) : ''}`);
  if (!ok) { fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2)); fetch(`${BASE}/mcp`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 0, method: 'tools/call', params: { name: 'end_handoff', arguments: {} } }) }).finally(() => process.exit(1)); }
};
// Raw WebSocket-upgrade probe (fetch cannot send Connection/Upgrade): returns the HTTP status.
const wsProbe = (cookie) => Number(execFileSync('curl', ['-s', '-o', '/dev/null', '-m', '5', '-w', '%{http_code}',
  '-H', 'Connection: Upgrade', '-H', 'Upgrade: websocket', '-H', 'Sec-WebSocket-Version: 13', '-H', 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
  ...(cookie ? ['-H', 'Cookie: browser_handoff=' + cookie] : []), `${BASE}/handoff/websockify`]).toString());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 5000, step = 100) {
  const end = Date.now() + ms;
  for (;;) { const v = await fn(); if (v) return v; if (Date.now() > end) return v; await sleep(step); }
}

let rpcId = 0;
async function mcp(method, params = {}) {
  const r = await fetch(`${BASE}/mcp`, { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream' },
    body: JSON.stringify({ jsonrpc: '2.0', id: ++rpcId, method, params }) });
  return r.json();
}
async function tool(name, args = {}) {
  const r = await mcp('tools/call', { name, arguments: args });
  if (r.error || r.result.isError) throw new Error(`${name}: ${JSON.stringify(r.error || r.result.content)}`);
  const c = r.result.content[0];
  return c.type === 'text' ? JSON.parse(c.text) : r.result.content;
}

const FIXTURE = `<!doctype html><html><head><meta name="viewport" content="width=device-width">
<title>Handoff fixture</title><style>body{margin:0;font:18px system-ui;background:#fff}
#hero{height:120px;background:#1565c0;color:#fff;display:flex;align-items:center;justify-content:center;font-size:28px}
input{display:block;box-sizing:border-box;width:90%;margin:20px 5%;height:56px;font-size:20px}
button{display:block;width:90%;margin:20px 5%;height:64px;font-size:20px}.spacer{height:1600px;background:linear-gradient(#fff,#e33)}</style></head>
<body><div id="hero">AGENT PAGE</div><input id="email" placeholder="email"><input id="code" placeholder="code">
<button id="complete" onclick="document.getElementById('result').textContent='passed'">I am human</button>
<p id="result">waiting</p><div class="spacer"></div></body></html>`;

// ---- (a) DevTools compatibility on the app port ----------------------------------------------------
const getVersion = async () => { try { const r = await fetch(`${BASE}/json/version`); return r.ok ? await r.json() : null; } catch { return null; } };
const version = await until(getVersion, 60000, 500);
check('cdp /json/version answers', version.Browser && version.webSocketDebuggerUrl, { Browser: version.Browser });
const wsHost = new URL(version.webSocketDebuggerUrl).host;
check('webSocketDebuggerUrl points back at the app port (Hermes browser.cdp_url resolution)', wsHost === new URL(BASE).host, version.webSocketDebuggerUrl);
const proxied = await fetch(`${BASE}/json/version`, { headers: { 'X-Forwarded-For': '100.64.0.9', 'Tailscale-User-Login': 'someone@example.com' } });
check('cdp refused through a reverse proxy', proxied.status === 403, proxied.status);

const agent = await chromium.connectOverCDP(BASE);
const ctx = agent.contexts()[0];
const remote = await ctx.newPage();
await remote.setContent(FIXTURE);
await remote.bringToFront();
const driven = await remote.evaluate(() => ({ title: document.title, ua: navigator.userAgent, w: innerWidth, h: innerHeight }));
check('playwright drives a page over CDP', driven.title === 'Handoff fixture', driven);
check('browser is headful (no HeadlessChrome UA)', !/HeadlessChrome/.test(driven.ua), driven.ua);

// ---- (c) MCP tools ------------------------------------------------------------------------------------
const init = await mcp('initialize', { protocolVersion: '2025-06-18' });
const list = await mcp('tools/list');
const names = list.result.tools.map((t) => t.name);
check('mcp lists old and new tools', ['browser_status', 'read_page', 'screenshot', 'start_handoff', 'handoff_status', 'end_handoff'].every((n) => names.includes(n)), names);
const status0 = await tool('browser_status');
const tab = status0.tabs.find((t) => t.title === 'Handoff fixture');
check('browser_status sees the agent tab', tab, { tabs: status0.tabs.length, handoff: status0.handoff });
const before = await tool('handoff_status');
check('no handoff before start', before.active === false && before.engine_active === false, before);
const ws0 = wsProbe('');
check('vnc websocket refused without a handoff', ws0 === 401, ws0);

const started = await tool('start_handoff', { tab_id: tab.id, purpose: 'captcha', note: 'QA: tap I am human', ttl_s: 600 });
check('start_handoff returns a capability link', started.ok && /\/handoff\/#[A-Za-z0-9]{32}$/.test(started.handoff_url || ''), { ...started, handoff_url: started.handoff_url && started.handoff_url.replace(/#.*/, '#<redacted>') , send_to_owner: '<redacted>' });
const again = await tool('start_handoff', { tab_id: tab.id });
check('start_handoff is idempotent while open', again.reused === true && again.handoff_url === started.handoff_url, { reused: again.reused });
const st1 = await tool('handoff_status');
check('handoff_status: open, not yet opened by owner', st1.active && st1.engine_active && st1.owner_opened === false && st1.tab.id === tab.id, st1);
const wsBad = wsProbe('x'.repeat(32));
check('vnc websocket refused with a wrong capability', wsBad === 401, wsBad);

// ---- (b) phone viewer ---------------------------------------------------------------------------------
const phone = await chromium.launch({ headless: true, executablePath: CHROME });
const pctx = await phone.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2,
  userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36' });
const viewer = await pctx.newPage();
const editableProbes = [];
viewer.on('request', (r) => { if (r.url().endsWith('/control/focused-editable')) editableProbes.push(r.url()); });
await viewer.goto(started.handoff_url, { waitUntil: 'domcontentloaded' });
await viewer.waitForFunction(() => document.documentElement.classList.contains('noVNC_connected'), null, { timeout: 25000 });
await viewer.waitForFunction(() => [...document.querySelectorAll('#noVNC_container canvas')].some((c) => c.width >= 500), null, { timeout: 10000 });
await viewer.waitForTimeout(1200);
const loc = await viewer.evaluate(() => ({ href: location.href, path: location.pathname }));
check('viewer is the versioned noVNC 1.3.0 client and the capability left the address bar', loc.path.endsWith('/handoff/client-1.3.0/vnc.html') && !loc.href.includes('#'), loc);
const px = await viewer.evaluate(() => {
  const c = [...document.querySelectorAll('#noVNC_container canvas')].find((x) => x.width >= 500);
  const g = c.getContext('2d');
  const counts = { blue: 0, total: 0 };
  const d = g.getImageData(0, 0, c.width, c.height).data;
  for (let i = 0; i < d.length; i += 16) { counts.total++; if (d[i] < 60 && d[i + 1] > 70 && d[i + 1] < 140 && d[i + 2] > 160) counts.blue++; }
  return { w: c.width, h: c.height, blueShare: counts.blue / counts.total };
});
check('viewer shows the remote page (blue AGENT PAGE banner pixels on the VNC canvas)', px.w === 500 && px.h === 900 && px.blueShare > 0.03, px);
await viewer.screenshot({ path: path.join(OUT, 'viewer-connected.png') });
const st2 = await until(async () => { const s = await tool('handoff_status'); return s.owner_opened ? s : null; });
check('handoff_status reports the owner opened it', st2 && st2.owner_opened, st2);

const tapEl = async (sel) => { const b = await viewer.locator(sel).boundingBox(); await viewer.touchscreen.tap(b.x + b.width / 2, b.y + b.height / 2); };

// Down / Up
await remote.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; scrollTo(0, 0); });
await tapEl('#tailnet_scroll_down');
const down = await until(async () => { const y = await remote.evaluate(() => scrollY); return y > 0 ? y : 0; });
const expected = await remote.evaluate(() => Math.max(160, Math.round(innerHeight * 0.39)));
check('Down scrolls the remote page 39%', Math.abs(down - expected) <= 2, { scrollY: down, expected });
await tapEl('#tailnet_scroll_up');
const up = await until(async () => (await remote.evaluate(() => scrollY)) === 0);
check('Up scrolls back', up === true);

// Tap a remote field -> it focuses, and the phone keyboard opens by itself
const m = await remote.evaluate(() => ({ screenX, screenY, outerWidth, outerHeight, innerWidth, innerHeight }));
const canvasBox = await viewer.locator('#noVNC_container canvas').first().boundingBox();
const chromeX = Math.max(0, Math.round((m.outerWidth - m.innerWidth) / 2));
const chromeY = Math.max(0, Math.round(m.outerHeight - m.innerHeight));
const toViewer = (b) => [canvasBox.x + (m.screenX + chromeX + b.x + b.width / 2) * canvasBox.width / 500,
  canvasBox.y + (m.screenY + chromeY + b.y + b.height / 2) * canvasBox.height / 900];
const [ex, ey] = toViewer(await remote.locator('#email').boundingBox());
await viewer.touchscreen.tap(ex, ey);
const focused = await until(() => remote.evaluate(() => document.activeElement && document.activeElement.id === 'email'));
check('a tap on the phone focuses the remote field', focused === true);
const autoKb = await until(() => viewer.evaluate(() => document.activeElement && document.activeElement.id === 'noVNC_keyboardinput'));
check('Keyboard opens by itself on an editable remote field', autoKb === true, { focusedEditableProbes: editableProbes.length });
await viewer.keyboard.type('owner@example.com', { delay: Number(process.env.TYPE_DELAY_MS || 60) });
await until(async () => (await remote.evaluate(() => document.getElementById('email').value)) === 'owner@example.com', 8000);
const typed = await remote.evaluate(() => ({ value: document.getElementById('email').value, focused: document.activeElement && document.activeElement.id }));
check('typing on the phone keyboard reaches the remote field', typed.value === 'owner@example.com', typed);
await viewer.screenshot({ path: path.join(OUT, 'viewer-keyboard.png') });

// Keyboard button toggles the keyboard closed and open again
await tapEl('#tailnet_keyboard');
const closed = await until(() => viewer.evaluate(() => document.activeElement && document.activeElement.id !== 'noVNC_keyboardinput'));
const kbState = await viewer.evaluate(() => document.getElementById('tailnet_keyboard').getAttribute('aria-pressed'));
check('Keyboard button closes the keyboard', closed === true && kbState === 'false', kbState);
await remote.locator('#code').focus();
await tapEl('#tailnet_keyboard');
const reopened = await until(() => viewer.evaluate(() => document.activeElement && document.activeElement.id === 'noVNC_keyboardinput'));
check('Keyboard button opens the keyboard', reopened === true);

// Paste: masked field, then typed into the focused remote field
await tapEl('#tailnet_paste');
const sheet = await until(() => viewer.evaluate(() => document.activeElement && document.activeElement.id === 'tailnet_paste_text'));
check('Paste opens the paste sheet', sheet === true);
await viewer.fill('#tailnet_paste_text', '493817');
const masked = await viewer.evaluate(() => document.getElementById('tailnet_paste_text').classList.contains('tailnet_masked'));
await viewer.screenshot({ path: path.join(OUT, 'viewer-paste.png') });
await tapEl('#tailnet_paste_send');
const pasted = await until(async () => { const v = await remote.evaluate(() => document.getElementById('code').value); return v === '493817' ? v : null; }, 8000);
check('Paste types into the focused remote field (masked by default)', pasted === '493817' && masked, { pasted, masked });

// Tap the human-only button through the viewer
const [bx, by] = toViewer(await remote.locator('#complete').boundingBox());
await viewer.touchscreen.tap(bx, by);
const passed = await until(() => remote.evaluate(() => document.getElementById('result').textContent === 'passed'));
check('a phone tap presses the remote button', passed === true);

// ---- end the handoff; the agent resumes in the same tab -----------------------------------------------
const ended = await tool('end_handoff');
check('end_handoff', ended.ok && ended.ended && ended.tab.id === tab.id, ended);
const dropped = await until(() => viewer.evaluate(() => !document.documentElement.classList.contains('noVNC_connected')), 8000);
check('viewer disconnects after end_handoff', dropped === true);
const after = await tool('handoff_status');
check('handoff_status inactive after end', after.active === false && after.engine_active === false, after);
const wsAfter = wsProbe(started.handoff_url.split('#')[1]);
check('old link refused after end', wsAfter === 401, wsAfter);
const resumed = await remote.evaluate(() => ({ email: document.getElementById('email').value, result: document.getElementById('result').textContent }));
check('agent resumes in the same tab with the owner\'s input', resumed.email === 'owner@example.com' && resumed.result === 'passed', resumed);
const read = await tool('read_page', { url: 'https://example.com/', wait_ms: 500 }).catch((e) => ({ error: String(e) }));
check('existing read_page tool still works', typeof read.title === 'string' && read.title.length > 0, { title: read.title, error: read.error });

await phone.close();
await remote.close();

// A client that closes the whole browser (puppeteer browser.close()) must not take the app down.
const cdp = await agent.newBrowserCDPSession();
await cdp.send('Browser.close').catch(() => {});
const back = await until(async () => { const v = await getVersion(); return v && v.webSocketDebuggerUrl !== version.webSocketDebuggerUrl ? v : null; }, 60000, 500);
await sleep(1500);
const stable = await getVersion();
check('Chromium restarts after a client calls Browser.close', back && stable && stable.webSocketDebuggerUrl === back.webSocketDebuggerUrl,
  { before: version.webSocketDebuggerUrl, after: back && back.webSocketDebuggerUrl });
report.status = 'PASS';
fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
console.log('ALL PASS');
process.exit(0);
