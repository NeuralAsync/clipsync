# clipsync

Encrypted, peer-to-peer clipboard sync between two machines over [Tailscale](https://tailscale.com) (or plain LAN). No third-party server, no account, no cloud relay — content goes directly between the two IPs you configure, encrypted end to end.

Syncs text and images (screenshots, copied images) in both directions. Runs as a system tray app on macOS and Windows.

## Why this exists

I was using a closed-source clipboard-sync tool and got nervous about it — it's the kind of app that, by design, needs to read everything you copy. I asked an AI (Claude) to audit its source (it turned out to be open source too) and it came back clean, but I still didn't love depending on someone else's binary for something that touches everything I copy/paste, including passwords and other sensitive text.

So the actual goal here wasn't "build a clipboard sync tool" — it was **build one small enough that I, or anyone else, can read the entire thing and know exactly what it does**. That constraint shaped every decision below: no dependencies pulled in just for convenience, no code paths I can't explain, nothing that phones home.

This was built almost entirely through conversation with Claude (Anthropic's AI), including the debugging sessions — a lot of the commit history and the "known quirks" section below exists because we hit a real bug, root-caused it together (sometimes by writing a minimal reproduction script), and fixed it. That process is part of why I trust this codebase: nothing in here is a black box to me.

## What it does — and deliberately doesn't

- ✅ Syncs clipboard **text** and **images** between exactly two machines.
- ✅ Everything is encrypted with a passphrase only you know — see [Security model](#security-model).
- ✅ Works over Tailscale (so the two machines don't need to be on the same LAN).
- ❌ Does **not** sync arbitrary files, only clipboard content.
- ❌ Does **not** support more than two machines (see [Limitations](#known-limitations--quirks)).
- ❌ Does **not** talk to any server other than the peer you configure. No analytics, no telemetry, no update-checker.

## Security model

- **Encryption**: [PyNaCl](https://pynacl.readthedocs.io/)'s `SecretBox` — XSalsa20-Poly1305 authenticated encryption (the same primitive libsodium uses). The key is `SHA-256(passphrase)`. See `core.py::derive_key`.
- **Transport**: a plain TCP socket between the two configured IPs (`core.py::PORT = 45123`). No TLS layer needed on top since the payload itself is already encrypted and authenticated per-message.
- **Peer pinning**: each side only accepts connections from the one IP you configured (`core.py::serve` — rejects anything else outright). This isn't a broadcast/discovery protocol at the network level; discovery only helps you *pick* an IP during setup (see below), it doesn't change who can connect.
- **What this protects against**: anyone on your network, or on the wire between the two machines, reading your clipboard content — including the operators of Tailscale, your ISP, or someone on the same Wi-Fi.
- **What this does *not* protect against**: the other machine itself being compromised (it holds the same passphrase and sees plaintext), or someone with the passphrase. There's no forward secrecy — one static key is used for the life of the config. This is a personal-use tool between two machines you trust, not a hardened secure-messaging protocol.
- **Local storage**: the passphrase is stored in `~/.clipsync/config.json`, `chmod 600` (owner read/write only) on macOS/Linux. On Windows there's no equivalent restriction applied — anyone with access to your Windows user account can read it, same as most local app configs.

## How to audit this yourself

This is the whole point of the project, so here's a concrete path through it. The core sync logic is **under 300 lines** across two files; you can read the security-relevant part in about 15 minutes:

1. **`clipsync/core.py`** — the entire sync engine. Encryption (`encrypt`/`decrypt`), the wire protocol (`send_frame`/`recv_frame`, a 4-byte length prefix + encrypted payload), connection handling (`serve`, `maintain_outbound_connection`), and what happens to clipboard content in each direction (`_check_text`, `_check_image`, `_apply_received`). This is the file that matters most — everything else is UI and plumbing around it.
2. **`clipsync/clipboard_image.py`** — how images are read from and written to the OS clipboard. Short, platform-specific, no networking.
3. **`clipsync/config.py`** — confirms the passphrase only ever gets written to `~/.clipsync/config.json`, nowhere else.
4. **`clipsync/discovery.py`** — confirms "discovery" is just shelling out to `tailscale status --json` (a read-only, local-only call) to list your own tailnet devices for the setup UI. It has no effect on who can actually connect (see [Security model](#security-model)).
5. Grep for anything that leaves the machine: `grep -rn "requests\|urllib\|http" clipsync/` — you'll find nothing, because there's no HTTP client anywhere in this codebase. The only network code is the raw TCP socket usage in `core.py`.

Everything else (`tray.py`, `setup_ui.py`, `autostart.py`, `app.py`) is UI, autostart registration, and process wiring — worth a skim, but none of it touches the network or your clipboard content directly.

## How it works

- Each machine runs the same app: a small TCP server (`core.py`) that listens on port `45123`, plus an outbound connection to the configured peer.
- Content is encrypted with PyNaCl before being sent — never sent in plaintext, never touches a third-party server.
- Peer discovery uses the local Tailscale daemon (`tailscale status --json`) to list devices in your tailnet, so you pick a peer from a list during setup instead of typing IPs.
- The clipboard is polled every 0.5s; a content-type tag (`text` / `image`) in the encrypted payload tells the receiver how to apply it.

## Setup

1. Install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
   On macOS, if `tkinter` import fails: `brew install python-tk@<your-python-version>`.

2. Run it on both machines:
   ```bash
   python -m clipsync          # macOS / Windows (console)
   pythonw -m clipsync         # Windows, no console window
   ```
   First run opens a setup dialog: pick the other machine from your Tailscale peers, set a shared passphrase (same on both sides).

3. From the tray icon menu:
   - **Change peer / passphrase...** — reconfigure without restarting
   - **Sync images** — off by default; toggle on to also sync copied images/screenshots, not just text
   - **Start at login** — registers autostart (LaunchAgent on macOS, Scheduled Task on Windows)
   - **Quit**

## Desktop launchers

- **macOS**: run `./build_mac_launcher.sh` once — builds `/Applications/Start ClipSync.app`. This doesn't run clipsync itself; it asks `launchd` to (re)start the real background service, then quits (see [Known quirks](#known-limitations--quirks) for why). Alternatively, `./start_clipsync.sh` does the same thing from a terminal.
- **Windows**: run `python make_windows_shortcut.py` once — creates a Desktop + Start Menu shortcut with its own icon.

Both platforms' launchers go through `launcher.py`, which checks if an instance is already running (port already bound) and exits quietly instead of starting a duplicate.

## Known limitations & quirks

- **Two machines only.** `core.py` connects to a single configured peer IP and rejects connections from anyone else. Extending to 3+ machines would mean a peer list + full-mesh connections instead of a single link — not implemented.
- **No file transfer** beyond clipboard text/images.
- **Image round-trips aren't always byte-identical** — e.g. Windows re-encodes clipboard images through BMP/DIB, so what you read back after writing isn't the exact bytes you sent. Handled by hashing the post-write read-back rather than the original bytes, to avoid a resend-forever loop (see `core.py::_apply_received`).
- **macOS: a `.app` bundle launched via double-click/Launchpad can't show the tray icon.** This turned out to be a real macOS bug, not ours: `ControlCenter` refuses the `NSStatusItem` "scene" request over XPC (`BSServiceConnectionErrorDomain` code 3) for GUI processes launched through LaunchServices (`open`, double-click, Launchpad) unless the app is signed with a paid Apple Developer ID and notarized. Confirmed by reproducing it with a *minimal* test app (just a colored circle, no other code) and by checking `log show` for the exact XPC failure. A Terminal-launched or `launchd`-launched process never hits this — which is why `build_mac_launcher.sh` builds a launcher that doesn't create a tray icon itself; it just asks `launchd` to start the real process.
- **macOS: the tray status dot can appear stuck** after many rapid restarts during development — this was chased extensively and turned out to be leftover "ghost" status items from repeatedly killing and relaunching the process in quick succession (a real, if annoying, characteristic of macOS's menu bar), not a code bug. A normal single start/stop doesn't cause it.
- **Windows: the tray status dot doesn't reliably reflect connected/disconnected.** Confirmed cosmetic — sync itself works correctly regardless. Not yet root-caused.

## Project layout

```
clipsync/
  core.py              sync engine: encryption, framing, connect/listen, clipboard polling
  clipboard_image.py   cross-platform image read/write (Pillow ImageGrab + AppKit/win32clipboard)
  discovery.py         lists Tailscale peers (read-only, local `tailscale status` call)
  config.py            local config persistence (~/.clipsync/config.json)
  setup_ui.py          Tk setup dialog (runs as its own subprocess — see note below)
  tray.py              system tray icon, menu, autostart toggle
  autostart.py         per-OS autostart registration (LaunchAgent / Scheduled Task)
  app.py               entry point wiring it all together
launcher.py             standalone entry point (used by shortcuts/autostart, not cwd-dependent)
start_clipsync.sh        manually (re)starts the macOS LaunchAgent
build_mac_launcher.sh    builds the macOS "Start ClipSync.app" launcher, with icon
make_windows_shortcut.py builds the Windows Desktop/Start Menu shortcut, with icon
```

**Why `setup_ui.py` runs as a subprocess:** on macOS, Tk and the tray icon (pystray/AppKit) both want to own `NSApplication`. Running the setup dialog in-process while the tray icon is alive crashes with `unrecognized selector sent to NSApplication`. Running it as a separate process sidesteps this.

**Why Windows autostart uses `schtasks.exe` instead of the registry `Run` key:** some Python distributions (notably the Microsoft Store package) run with registry writes silently virtualized to a per-package view — the write "succeeds" from the process's own point of view, but no other process (including PowerShell) ever sees it. `schtasks.exe`, an ordinary unsandboxed system binary, avoids that failure mode.

## Disclaimer

This is a personal tool, built and audited by one person (with AI assistance) — not professionally security-reviewed, not penetration-tested, no bug bounty. It's built to be *readable*, which is a different (and more inspectable) property than *proven secure*, but it isn't a substitute for one. Read the code — that's the whole point — before trusting it with anything sensitive. No license file is included yet; treat it as all-rights-reserved until one is added.
