# clipsync

Encrypted, peer-to-peer clipboard sync between two machines over Tailscale (or plain LAN). No third-party server — traffic goes directly between the two IPs you configure.

Syncs text and images (screenshots, copied images) in both directions. Runs as a system tray app on macOS and Windows.

## Why

Built as a self-auditable, minimal alternative to closed-source clipboard sync tools — small enough to read end to end in one sitting.

## How it works

- Each machine runs the same app: a small TCP server (`core.py`) that listens on port `45123`, plus an outbound connection to the configured peer.
- Content is encrypted with [PyNaCl](https://pynacl.readthedocs.io/) (`SecretBox`, XChaCha20-Poly1305) using a shared passphrase — never sent in plaintext, never touches a third-party server.
- Peer discovery uses the local Tailscale daemon (`tailscale status --json`) to list devices in your tailnet, so you pick a peer from a list instead of typing IPs.
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
   - **Start at login** — registers autostart (LaunchAgent on macOS, Task Scheduler on Windows)
   - **Quit**

## Desktop shortcuts

- macOS: `/Applications/ClipSync.app` (built via the icon-generation code in `clipsync/tray.py` + `iconutil`)
- Windows: run `python make_windows_shortcut.py` once — creates a Desktop + Start Menu shortcut with its own icon.

Both just launch `launcher.py`, which checks if an instance is already running (port already bound) and exits quietly instead of starting a duplicate.

## Limitations

- **Two machines only.** `core.py` connects to a single configured peer IP and rejects connections from anyone else. Extending to 3+ machines would mean a peer list + full-mesh connections instead of a single link — not implemented.
- **No file transfer** (beyond clipboard text/images) yet.
- Image round-trips through the OS clipboard aren't always byte-identical (e.g. Windows re-encodes through BMP/DIB) — handled by hashing the post-write read-back, not the original bytes, to avoid re-sync loops.

## Project layout

```
clipsync/
  core.py          sync engine: encryption, framing, connect/listen, clipboard polling
  clipboard_image.py  cross-platform image read/write (Pillow ImageGrab + AppKit/win32clipboard)
  discovery.py     lists Tailscale peers
  config.py        local config persistence (~/.clipsync/config.json)
  setup_ui.py      Tk setup dialog (runs as its own subprocess — see note below)
  tray.py          system tray icon, menu, autostart toggle
  autostart.py     per-OS autostart registration (LaunchAgent / schtasks)
  app.py           entry point wiring it all together
launcher.py        standalone entry point (used by shortcuts/autostart, not cwd-dependent)
```

**Why `setup_ui.py` runs as a subprocess:** on macOS, Tk and the tray icon (pystray/AppKit) both want to own `NSApplication`. Running the setup dialog in-process while the tray icon is alive crashes with `unrecognized selector sent to NSApplication`. Running it as a separate process sidesteps this.

**Why Windows autostart uses `schtasks.exe` instead of the registry `Run` key:** some Python distributions (notably the Microsoft Store package) run with registry writes silently virtualized to a per-package view — the write "succeeds" from the process's own point of view, but no other process (including PowerShell) ever sees it. `schtasks.exe`, an ordinary unsandboxed system binary, avoids that failure mode.
