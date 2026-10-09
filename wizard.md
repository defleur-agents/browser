---
wizard: 0.2
id: browser
name: Browser
type: service
version: 155.0.8059.40
summary: Shared headless Chromium with a DevTools/Puppeteer endpoint for other apps.
license: WTFPL
source: https://github.com/oscarhenrycollins/browser
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
mcp:
  path: /mcp
  port: 9222
  transport: streamable-http
skill: SKILL.md
provides:
- browser
---

# Browser

Shared headless Chromium with a DevTools/Puppeteer endpoint for other apps.
