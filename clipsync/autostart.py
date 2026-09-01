"""Register/unregister clipsync to start automatically at login, per-OS."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "launcher.py"

# --- macOS: LaunchAgent ---
_MAC_LABEL = "com.clipsync.app"
_MAC_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_MAC_LABEL}.plist"

_MAC_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{launcher}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_dir}/launchagent.out.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/launchagent.err.log</string>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
"""


def _mac_is_enabled() -> bool:
    return _MAC_PLIST_PATH.exists()


def _mac_enable() -> None:
    log_dir = Path.home() / ".clipsync"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist = _MAC_PLIST_TEMPLATE.format(
        label=_MAC_LABEL,
        python=sys.executable,
        launcher=str(LAUNCHER),
        log_dir=str(log_dir),
    )
    _MAC_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MAC_PLIST_PATH.write_text(plist)
    uid = subprocess.check_output(["id", "-u"], text=True).strip()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{_MAC_LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(_MAC_PLIST_PATH)], check=True)


def _mac_disable() -> None:
    if _MAC_PLIST_PATH.exists():
        uid = subprocess.check_output(["id", "-u"], text=True).strip()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{_MAC_LABEL}"], capture_output=True)
        _MAC_PLIST_PATH.unlink()


# --- Windows: Task Scheduler ---


def _win_pythonw() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else str(exe)


# Uses schtasks.exe (an ordinary, unsandboxed system binary) instead of writing
# to HKCU\...\Run directly. Some Python distributions (notably the Microsoft
# Store package) run with registry writes silently virtualized to a
# per-package view — the write "succeeds" but no other process, including
# PowerShell, ever sees it. schtasks sidesteps that entirely.
_WIN_TASK_NAME = "ClipSync"


# Without these, every subprocess.run() below briefly flashes a console
# window — visible even from a windowless (pythonw) process — because
# schtasks.exe is a console app and gets a fresh console by default.
# CREATE_NO_WINDOW alone isn't always enough (seen under the Microsoft Store
# Python packaging), so it's paired with an explicit SW_HIDE STARTUPINFO.
if sys.platform == "win32":
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUPINFO.wShowWindow = subprocess.SW_HIDE
else:
    _NO_WINDOW = 0
    _STARTUPINFO = None


def _win_is_enabled() -> bool:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", _WIN_TASK_NAME],
        capture_output=True, text=True, creationflags=_NO_WINDOW, startupinfo=_STARTUPINFO,
    )
    return result.returncode == 0


def _win_enable() -> None:
    tr = f'"{_win_pythonw()}" "{LAUNCHER}"'
    subprocess.run(
        ["schtasks", "/create", "/tn", _WIN_TASK_NAME, "/tr", tr, "/sc", "onlogon", "/rl", "limited", "/f"],
        check=True, capture_output=True, text=True, creationflags=_NO_WINDOW, startupinfo=_STARTUPINFO,
    )


def _win_disable() -> None:
    subprocess.run(
        ["schtasks", "/delete", "/tn", _WIN_TASK_NAME, "/f"],
        capture_output=True, text=True, creationflags=_NO_WINDOW, startupinfo=_STARTUPINFO,
    )


# --- public API ---

def is_supported() -> bool:
    return sys.platform in ("darwin", "win32")


def is_enabled() -> bool:
    if sys.platform == "darwin":
        return _mac_is_enabled()
    if sys.platform == "win32":
        return _win_is_enabled()
    return False


def enable() -> None:
    if sys.platform == "darwin":
        _mac_enable()
    elif sys.platform == "win32":
        _win_enable()
    else:
        raise RuntimeError(f"autostart not supported on {sys.platform}")


def disable() -> None:
    if sys.platform == "darwin":
        _mac_disable()
    elif sys.platform == "win32":
        _win_disable()
    else:
        raise RuntimeError(f"autostart not supported on {sys.platform}")
