"""Entry point: ties config, discovery, sync engine and tray UI together."""

import json
import logging
import socket
import subprocess
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from . import config, core, tray

LOG_PATH = Path.home() / ".clipsync" / "clipsync.log"
REPO_ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger("clipsync.app")


def _setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
    )


def _run_setup_dialog(existing: config.Config | None) -> config.Config | None:
    """Runs the Tk setup dialog in its own process.

    On macOS, Tk and the pystray tray icon both want to own NSApplication;
    running the dialog in-process while the tray icon is alive crashes with
    "unrecognized selector sent to NSApplication". A subprocess sidesteps it.
    """
    cmd = [sys.executable, "-m", "clipsync.setup_ui"]
    if existing is not None:
        cmd += ["--existing", json.dumps(asdict(existing))]
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        if result.stderr.strip():
            log.warning("setup dialog exited with error: %s", result.stderr.strip())
        return None
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if not line:
        return None
    return config.Config(**json.loads(line))


def _already_running() -> bool:
    """True if another clipsync instance already holds our port.

    Lets a desktop-icon double-click be a no-op instead of spawning a
    duplicate instance (and a duplicate tray icon) when autostart already
    has one running.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("0.0.0.0", core.PORT))
    except OSError:
        return True
    finally:
        probe.close()
    return False


def main():
    _setup_logging()

    if _already_running():
        log.info("clipsync is already running (port %d in use) — not starting a second instance", core.PORT)
        return

    cfg = config.load()
    while True:
        if cfg is None:
            cfg = _run_setup_dialog(existing=None)
            if cfg is None:
                return  # user cancelled on first run, nothing to do
            config.save(cfg)

        tray_app = tray.TrayApp(cfg.peer_hostname, on_reconfigure=None, on_quit=None)
        reconfigure_requested = threading.Event()
        quit_requested = threading.Event()
        tray_app.on_reconfigure = lambda: (reconfigure_requested.set(), tray_app.stop())
        tray_app.on_quit = lambda: (quit_requested.set(), tray_app.stop())

        sync = core.ClipSync(cfg.peer_ip, cfg.passphrase, on_status_change=tray_app.set_status)
        sync.start()

        tray_app.run()  # blocks until tray_app.stop() is called
        sync.stop()

        if quit_requested.is_set():
            return

        if not reconfigure_requested.is_set():
            log.warning("tray icon exited without quit or reconfigure — restarting sync loop")

        if reconfigure_requested.is_set():
            new_cfg = _run_setup_dialog(existing=cfg)
            if new_cfg is not None:
                config.save(new_cfg)
                cfg = new_cfg
            # loop back and restart sync + tray with (possibly unchanged) cfg


if __name__ == "__main__":
    main()
