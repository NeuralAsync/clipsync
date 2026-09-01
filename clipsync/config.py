"""Local config persistence: peer IP + shared passphrase."""

import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".clipsync"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class Config:
    peer_ip: str
    peer_hostname: str
    passphrase: str


def load() -> Config | None:
    if not CONFIG_PATH.exists():
        return None
    with open(CONFIG_PATH, "r") as f:
        data = json.load(f)
    return Config(**data)


def save(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(asdict(config), f, indent=2)
    # Restrict to owner read/write only — this file holds the shared secret.
    if os.name != "nt":
        os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)
