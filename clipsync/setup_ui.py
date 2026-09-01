"""First-run / reconfigure dialog: pick a Tailscale peer, set the shared passphrase.

Runs as its own process (see __main__ below). On macOS, Tk and pystray both
want to own NSApplication; running the dialog in-process alongside a live
tray icon crashes with "unrecognized selector sent to NSApplication". Keeping
this dialog in a separate process sidesteps that entirely.
"""

import secrets
import string
import tkinter as tk
from dataclasses import asdict
from tkinter import messagebox, ttk

from . import config, discovery


def _generate_passphrase(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def run_setup_dialog(existing: config.Config | None = None) -> config.Config | None:
    """Blocking modal dialog. Returns the new Config, or None if the user cancelled."""
    result: dict = {}

    root = tk.Tk()
    root.title("clipsync — setup")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=16)
    frame.grid()

    ttk.Label(frame, text="Peer device (from your tailnet):").grid(column=0, row=0, sticky="w")
    peer_var = tk.StringVar()
    peer_combo = ttk.Combobox(frame, textvariable=peer_var, width=40, state="readonly")
    peer_combo.grid(column=0, row=1, columnspan=2, sticky="we", pady=(0, 8))

    status_var = tk.StringVar(value="Discovering peers via Tailscale...")
    ttk.Label(frame, textvariable=status_var, foreground="gray").grid(column=0, row=2, columnspan=2, sticky="w")

    peers_by_label: dict[str, discovery.Peer] = {}

    def refresh_peers():
        try:
            peers = discovery.list_peers()
        except Exception as e:
            status_var.set(f"Error: {e}")
            return
        peers_by_label.clear()
        labels = []
        for p in peers:
            label = f"{p.hostname}  ({p.ip})  {'●online' if p.online else '○offline'}"
            peers_by_label[label] = p
            labels.append(label)
        peer_combo["values"] = labels
        if existing is not None:
            for label, p in peers_by_label.items():
                if p.ip == existing.peer_ip:
                    peer_var.set(label)
                    break
        elif labels:
            peer_var.set(labels[0])
        status_var.set(f"Found {len(labels)} peer(s)." if labels else "No peers found — is Tailscale running on both machines?")

    ttk.Button(frame, text="Refresh", command=refresh_peers).grid(column=1, row=0, sticky="e")

    ttk.Label(frame, text="Shared passphrase (same on both machines):").grid(column=0, row=3, columnspan=2, sticky="w", pady=(12, 0))
    pass_var = tk.StringVar(value=existing.passphrase if existing else _generate_passphrase())
    pass_entry = ttk.Entry(frame, textvariable=pass_var, width=40, show="•")
    pass_entry.grid(column=0, row=4, sticky="we")

    show_var = tk.BooleanVar(value=False)

    def toggle_show():
        pass_entry.config(show="" if show_var.get() else "•")

    ttk.Checkbutton(frame, text="Show", variable=show_var, command=toggle_show).grid(column=1, row=4, sticky="w")
    ttk.Button(frame, text="Generate new", command=lambda: pass_var.set(_generate_passphrase())).grid(column=0, row=5, sticky="w", pady=(4, 0))

    button_row = ttk.Frame(frame)
    button_row.grid(column=0, row=6, columnspan=2, sticky="e", pady=(16, 0))

    def on_save():
        label = peer_var.get()
        peer = peers_by_label.get(label)
        if peer is None:
            messagebox.showerror("clipsync", "Pick a peer from the list.")
            return
        if not pass_var.get().strip():
            messagebox.showerror("clipsync", "Passphrase can't be empty.")
            return
        result["config"] = config.Config(peer_ip=peer.ip, peer_hostname=peer.hostname, passphrase=pass_var.get().strip())
        root.destroy()

    def on_cancel():
        root.destroy()

    ttk.Button(button_row, text="Cancel", command=on_cancel).grid(column=0, row=0, padx=(0, 8))
    ttk.Button(button_row, text="Save", command=on_save).grid(column=1, row=0)

    root.after(100, refresh_peers)
    root.eval("tk::PlaceWindow . center")
    root.mainloop()

    return result.get("config")


def _cli():
    """Standalone entry point: `python -m clipsync.setup_ui [--existing <json>]`.
    Prints the resulting config as JSON on stdout, exits nonzero if cancelled."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--existing", help="JSON-encoded existing Config, to pre-fill the dialog")
    args = parser.parse_args()

    existing = config.Config(**json.loads(args.existing)) if args.existing else None
    cfg = run_setup_dialog(existing=existing)
    if cfg is None:
        sys.exit(1)
    print(json.dumps(asdict(cfg)))


if __name__ == "__main__":
    _cli()
