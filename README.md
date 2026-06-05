# GhostGauge

A tiny macOS **menubar app** that shows your Claude Code usage (session + weekly rate limits) at a glance — without needing an active Claude Code session.

![menubar](https://img.shields.io/badge/macOS-menubar-D7875F)

## What it shows

- **Menubar title:** current 5‑hour session usage as a bar + percent, e.g. `█░░░░░░░░░░░ 9%`.
- **Dropdown panel** (Claude Desktop style):
  - **Current session** (5‑hour window) — % used + relative reset (`resets in 4h 31m`)
  - **All models** (7‑day window) — % used + absolute reset (`resets Mon 2:00 PM`)
  - **Sonnet only** (7‑day window, when present)

Auto‑refreshes every 60 seconds.

## How it works

GhostGauge reads your Claude Code OAuth access token from the macOS **Keychain**
(service `Claude Code-credentials`) and calls the same usage endpoint Claude Code
itself uses:

```
GET https://api.anthropic.com/api/oauth/usage
```

The token never leaves your machine and is never logged or displayed — only the
returned usage percentages and reset times are shown.

## Install (recommended — free, no Gatekeeper prompt)

Because the app is **built locally**, it is never quarantined, so macOS
Gatekeeper does **not** block it (no Apple Developer account or signing needed).

Requires [uv](https://docs.astral.sh/uv/).

**Option A — double‑click button:** in Finder, double‑click **`install.command`**.
A Terminal window builds the app and installs it to `/Applications`, then launches it.

**Option B — terminal:**

```bash
./install.sh
```

Both build a fresh `dist/GhostGauge.app`, copy it to `/Applications/GhostGauge.app`,
and register it as a **Login Item** so it starts automatically at login. (The first
run may ask Terminal for Automation permission to add the login item — a one-time
macOS prompt. Toggle it any time in **System Settings → General → Login Items**.)

## Run (development)

Dependencies are declared inline (PEP 723), so no setup is needed:

```bash
uv run app.py            # run the menubar app
uv run app.py --once     # headless: print usage to stdout, no GUI
```

## Build only (no install)

```bash
./build.sh               # produces dist/GhostGauge.app (menubar-only, no Dock icon)
```

`build.sh` creates an isolated build venv via py2app and is reproducible.

## Notes

- The `.app` is **not code‑signed / notarized** (notarization needs a paid Apple
  Developer account). The local install above sidesteps Gatekeeper for free.
- Requires that you are logged into Claude Code (`claude`) so the Keychain token
  exists. If the token expires, the menubar shows a re‑auth hint; run `claude`.

## License

MIT
