# Browser

Shared Chromium for agents and apps, with a phone viewer so the owner can take over the live browser for CAPTCHAs, one-time codes and logins.

A [Wizard app](https://www.aiwizards.com/wizard-apps): install it from the Wizard Apps screen, or with the Wizard App Manager on any box running stock [Runtipi](https://runtipi.io).

- `wizard.md`: what the app is and what it gives the agent (spec: wizard.md v0.2).
- `runtipi/`: stock Runtipi `config.json` and `docker-compose.yml`.
- `mcp/`: the app's MCP front (`front.py` + `tools.py`), inlined into the compose file by `python3 mcp/inline.py`. It serves `/mcp`, the handoff viewer at `/handoff/`, and passes DevTools through to the engine for direct (non-proxied) callers.
- `engine/`: the `browser-engine` image: headful Chromium on Xvfb with DevTools on `:9222`; x11vnc + websockify only while a handoff is open.
- `viewer/`: builds the mobile handoff viewer from stock noVNC 1.3.0 (keep 1.3.0 and the versioned `client-1.3.0/` path; a newer client dropped on Android).
- `tests/`: `test_front.py` (stdlib unit tests) and `qa_handoff.mjs` (end-to-end against a running app: CDP, MCP tools, 390x844 touch viewer).
- `SKILL.md`: the skill the agent loads when this app is installed.
- `.github/workflows/publish.yml`: checks and a multi-arch engine build on every PR; on `main` it pushes the engine image to GHCR and re-publishes to the index at apps.aiwizards.com.
