# Browser

A shared Chromium for your Wizard server. Install it once; agents, DeFleur Video (motion-graphics capture) and any other app that needs a real browser use it instead of each bundling its own. Stopping the app in Runtipi is the off switch.

It runs headful on a virtual display, so your agent can hand it to you. When a page needs a person (CAPTCHA, one-time code, login, consent, payment) the agent sends you a private link; it opens the same live browser on your phone with **Keyboard**, **Paste**, **Up** and **Down** buttons. Finish the step, tell the agent done, and it carries on.

**From other Runtipi apps:** `http://browser:9222` (Chrome DevTools Protocol). With Puppeteer: `puppeteer.connect({browserURL: "http://<browser IP>:9222"})`.

**Settings**
- *Owner address of this app* (optional): the address your phone opens this app at, e.g. `https://box.your-tailnet.ts.net:8793`. Handoff links start with it. Without it the agent builds the link from the app's view address.

**Notes**
- Chrome only accepts DevTools requests whose `Host` is an IP address or `localhost`, so resolve the name `browser` to its IP first (`http://browser:9222` itself returns HTTP 500 to `/json/version`). DeFleur Video does this for you.
- DevTools has no password and can open any page the server can reach. The port is published on the server's loopback only (`127.0.0.1:8793`); other apps reach it over the private Runtipi network. Requests that arrive through a reverse proxy (Tailscale Serve, the Wizard gateway) are refused DevTools; only the handoff page `/handoff/` is meant for your devices.
- A handoff link expires after 15 minutes by default and the agent revokes it when you are done. The screen stream only runs while a handoff is open.
- Limits: 6 GB memory, 2 GB shared memory, 4096 processes. Each open page uses roughly 100-300 MB.
- Fonts: Liberation, DejaVu and Noto Color Emoji.

**License**
- Packaging, engine and handoff viewer patches: see the repository.
- Chromium: BSD-3-Clause (The Chromium Authors) plus its bundled third-party licenses; Debian package, unmodified.
- noVNC 1.3.0: MPL-2.0 (core) with its bundled licenses, served from a versioned path with the phone controls applied at build time. x11vnc: GPL-2.0, websockify: LGPL-3.0, Xvfb: MIT/X11; Debian packages, unmodified.
