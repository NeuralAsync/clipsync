"""System tray icon: shows connection status, lets the user reconfigure or quit."""

import logging
import sys
import threading

import pystray
from PIL import Image, ImageDraw

from . import autostart

log = logging.getLogger("clipsync.tray")


def _run_on_ui_thread(func):
    """Runs func() on the thread AppKit actually accepts UI mutations from.

    pystray's macOS backend (_darwin.py) mutates AppKit objects directly with
    no thread marshaling of its own. Calling it from a background thread —
    e.g. core.py's connection-maintenance thread reporting a status change —
    is undefined in Cocoa: the change is silently dropped more often than
    not, which is why the tray dot could stay gray after actually
    reconnecting. PyObjCTools.AppHelper.callAfter hands the call to the main
    run loop, which is the standard fix for this class of bug.
    """
    if sys.platform == "darwin":
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(func)
            return
        except Exception as e:
            log.warning("failed to marshal UI update to main thread: %s", e)
    func()


def _hide_dock_icon_on_macos():
    """Menu-bar-only app: no Dock icon, no Cmd-Tab entry."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception as e:
        log.warning("failed to hide Dock icon: %s", e)


def _make_icon(board_color: str, dot_color: str) -> Image.Image:
    """Draw a small clipboard glyph: body + clip + two lines, with a status dot."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Clipboard body
    body = (12, 10, 52, 58)
    draw.rounded_rectangle(body, radius=6, fill=board_color, outline="#1c1c1c", width=2)

    # Clip at the top
    clip = (24, 4, 40, 16)
    draw.rounded_rectangle(clip, radius=4, fill="#1c1c1c")

    # Two "text lines" on the board
    draw.rounded_rectangle((19, 26, 45, 31), radius=2, fill="#ffffff", outline=None)
    draw.rounded_rectangle((19, 36, 39, 41), radius=2, fill="#ffffff", outline=None)

    # Status dot, bottom-right
    draw.ellipse((40, 42, 58, 60), fill=dot_color, outline="#1c1c1c", width=2)

    return img


ICON_CONNECTED = _make_icon("#3b82c4", "#2ecc71")
ICON_DISCONNECTED = _make_icon("#3b82c4", "#95a5a6")


class TrayApp:
    def __init__(self, peer_hostname: str, on_reconfigure, on_quit, sync_images: bool = False, on_toggle_images=None):
        _hide_dock_icon_on_macos()
        self.peer_hostname = peer_hostname
        self.on_reconfigure = on_reconfigure
        self.on_quit = on_quit
        self.on_toggle_images = on_toggle_images or (lambda enabled: None)
        self.connected = False
        self._sync_images = sync_images
        # Cached, not queried live: pystray re-evaluates `checked=` on every
        # WM_MENUSELECT (i.e. every time the mouse passes over the item, not
        # just on click). A live autostart.is_enabled() there means a
        # schtasks.exe subprocess launches on every hover on Windows.
        self._autostart_enabled = autostart.is_supported() and autostart.is_enabled()
        self.icon = pystray.Icon(
            "clipsync",
            icon=ICON_DISCONNECTED,
            title=self._title(),
            menu=self._build_menu(),
        )

    def _title(self) -> str:
        state = "connected" if self.connected else "connecting..."
        return f"clipsync — {self.peer_hostname} ({state})"

    def _build_menu(self) -> pystray.Menu:
        items = [
            pystray.MenuItem(self._title(), None, enabled=False),
            pystray.MenuItem("Change peer / passphrase...", lambda: self.on_reconfigure()),
            pystray.MenuItem(
                "Sync images",
                self._toggle_images,
                checked=lambda item: self._sync_images,
            ),
        ]
        if autostart.is_supported():
            items.append(
                pystray.MenuItem(
                    "Start at login",
                    self._toggle_autostart,
                    checked=lambda item: self._autostart_enabled,
                )
            )
        items.append(pystray.MenuItem("Quit", lambda: self.on_quit()))
        return pystray.Menu(*items)

    def _toggle_images(self, icon, item):
        self._sync_images = not self._sync_images
        self.on_toggle_images(self._sync_images)
        self.icon.menu = self._build_menu()

    def _toggle_autostart(self, icon, item):
        try:
            if self._autostart_enabled:
                autostart.disable()
            else:
                autostart.enable()
            self._autostart_enabled = not self._autostart_enabled
        except Exception as e:
            log.warning("failed to toggle autostart: %s", e)
        self.icon.menu = self._build_menu()

    def set_status(self, connected: bool):
        self.connected = connected

        def _apply():
            self.icon.icon = ICON_CONNECTED if connected else ICON_DISCONNECTED
            self.icon.title = self._title()
            self.icon.menu = self._build_menu()

        _run_on_ui_thread(_apply)

    def set_peer(self, peer_hostname: str):
        self.peer_hostname = peer_hostname

        def _apply():
            self.icon.title = self._title()
            self.icon.menu = self._build_menu()

        _run_on_ui_thread(_apply)

    def run(self):
        self.icon.run()

    def stop(self):
        self.icon.stop()
