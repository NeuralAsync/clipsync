"""Discover peers using the local Tailscale daemon (no custom network discovery)."""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

_KNOWN_PATHS = (
    "/usr/local/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
)


@dataclass
class Peer:
    hostname: str
    ip: str
    online: bool


def find_tailscale_binary() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for candidate in _KNOWN_PATHS:
        if os.path.exists(candidate):
            return candidate
    return None


def list_peers() -> list[Peer]:
    """Return other devices in the user's tailnet, via `tailscale status --json`."""
    binary = find_tailscale_binary()
    if binary is None:
        raise RuntimeError("tailscale CLI not found — is Tailscale installed?")

    result = subprocess.run([binary, "status", "--json"], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"tailscale status failed: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    peers = []
    for peer in (data.get("Peer") or {}).values():
        ips = peer.get("TailscaleIPs") or []
        ipv4 = next((ip for ip in ips if "." in ip), None)
        if ipv4 is None:
            continue
        peers.append(Peer(
            hostname=peer.get("HostName", ipv4),
            ip=ipv4,
            online=bool(peer.get("Online")),
        ))
    return sorted(peers, key=lambda p: (not p.online, p.hostname.lower()))
