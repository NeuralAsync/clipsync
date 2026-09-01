"""Creates Desktop + Start Menu shortcuts for clipsync, with its own icon.

Run once on Windows: python make_windows_shortcut.py
"""

import sys
from pathlib import Path

from clipsync.tray import _make_icon

REPO_ROOT = Path(__file__).resolve().parent
LAUNCHER = REPO_ROOT / "launcher.py"


def build_ico():
    img = _make_icon("#3b82c4", "#2ecc71")
    ico_path = REPO_ROOT / "clipsync_icon.ico"
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ico_path, format="ICO", sizes=sizes)
    return ico_path


def pythonw_path() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else str(exe)


def create_shortcut(target_dir: Path, name: str, ico_path: Path):
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut_path = target_dir / f"{name}.lnk"
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = pythonw_path()
    shortcut.Arguments = f'"{LAUNCHER}"'
    shortcut.WorkingDirectory = str(REPO_ROOT)
    shortcut.IconLocation = str(ico_path)
    shortcut.Description = "ClipSync — encrypted clipboard sync"
    shortcut.save()
    print(f"created: {shortcut_path}")


def main():
    ico_path = build_ico()
    print(f"icon written to {ico_path}")

    desktop = Path.home() / "Desktop"
    start_menu = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    create_shortcut(desktop, "ClipSync", ico_path)
    create_shortcut(start_menu, "ClipSync", ico_path)
    print("done — ClipSync should now show up in the Start menu search, and on the Desktop.")


if __name__ == "__main__":
    main()
