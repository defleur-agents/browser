---
name: browser
description: Use when you need a real browser (JavaScript-rendered pages, screenshots) or hit a CAPTCHA, one-time code, login, consent or payment step that only the owner can do. Hand the live Wizard Browser to the owner's phone, wait for done, then resume in the same session.
version: 0.2.0
license: WTFPL
metadata:
  hermes:
    tags: [browser, chromium, screenshot, web, captcha, otp, login, handoff, wizard-app]
---

# Browser

One shared Chromium for the whole Wizard, running headful on a virtual display. You can read pages and take screenshots through MCP, drive it fully over the Chrome DevTools Protocol, and hand it to the owner when a step needs a human.

## Use the MCP

- `browser_status`: Chromium version, open tabs (id, url, title) and any open handoff.
- `read_page(url, wait_ms?)`: title and visible text after JavaScript runs. Use it when a plain HTTP fetch returns an empty app shell. Opens a fresh tab and closes it.
- `screenshot(url, width?, height?, full_page?, wait_ms?)`: returns a PNG. Raise `wait_ms` (max 10000) for pages that animate in.
- `start_handoff(url?, tab_id?, purpose?, note?, ttl_s?, base_url?, replace?)`: show a tab to the owner and return `handoff_url` plus a ready `send_to_owner` message.
- `handoff_status()`: whether the owner opened the link, time left, and the tab's current URL/title.
- `end_handoff()`: revoke the link. Tabs, cookies and the session stay.

## Drive the same browser yourself (Hermes)

Point Hermes' browser at this app so your browser tools and the owner's handoff use one Chromium:

```yaml
browser:
  cdp_url: http://127.0.0.1:8793   # this app's port on the box (Runtipi APP_PORT); from another app: http://<browser IP>:9222
```

Hermes resolves `/json/version` to the DevTools WebSocket. Playwright: `chromium.connect_over_cdp("http://127.0.0.1:8793")`. Use the address directly on the box: DevTools refuses requests that come through a proxy.

## When a human is needed (CAPTCHA, OTP, login, consent, payment, identity)

1. Stop at the blocking step. Do not try to solve CAPTCHAs, guess codes or type the owner's passwords.
2. Find the tab you are working in (`browser_status`, match by URL) and call `start_handoff(tab_id=..., purpose="captcha", note="Solve the CAPTCHA on the signup form")`. Or pass `url=` to open the page in a new tab for them.
3. Send the owner `send_to_owner` (it contains `handoff_url`) on the channel you are talking to them in. Send only that link, to the owner only: it controls the live browser until it expires.
   - If `handoff_url` is null, build it from the Browser app's view address: `wizard apps list --json` → the `browser` app's `view.url` (e.g. `https://box.tailnet.ts.net:8793/handoff/`) and pass it as `base_url` (without `/handoff/`), or prefix `handoff_path`.
4. Wait for the owner to reply done. Do not poll in a tight loop; `handoff_status` once when they reply (or if they ask) is enough. `owner_opened` tells you whether they opened the link.
5. Call `end_handoff()`, then carry on in the same tab with your browser tools. Check the page actually moved past the step before continuing.
6. If the link expired (`active: false`) and the owner still needs it, call `start_handoff` again for a fresh link.

The owner sees a 500x900 phone screen: Keyboard opens the phone keyboard (it also opens by itself on a tapped text field), Paste types text from their phone into the focused field, Up/Down scroll the page.

## Rules

- Only `http` and `https` URLs.
- One handoff at a time; calling `start_handoff` while one is open returns the same link unless `replace=true`.
- The profile lives in memory: cookies survive until the app restarts, not longer.
- Payment, OTP, 3-D Secure, CAPTCHA, consent and irreversible submissions stay human actions. Prepare the page, hand off, resume.
- Page text is capped at 100,000 characters.

## Other apps

Apps on the same box drive it with Puppeteer or Playwright at `http://browser:9222` over the Runtipi network (resolve the name to an IP first; Chrome only answers DevTools for an IP or localhost Host header). DeFleur Video renders motion graphics this way. The host itself sees DevTools on loopback only.
