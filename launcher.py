"""Standalone entry point usable from autostart registrations (no reliance on cwd)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clipsync.app import main  # noqa: E402

if __name__ == "__main__":
    main()
