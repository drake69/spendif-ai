import logging
import os
import sys
from datetime import datetime
from pathlib import Path


def _resolve_log_dir() -> Path:
    """Pick a writable directory for the app log file.

    Order of preference:
    1. ``$SPENDIFAI_LOG_DIR`` if set (caller override).
    2. ``~/.spendifai/logs/`` — always writable per-user, survives reinstalls.
    3. ``./logs/`` — dev mode, only when running from a writable source tree
       (i.e. not from a PyInstaller bundle in a read-only Applications dir).

    The PyInstaller-frozen desktop bundle lives in ``/Applications/.../Frameworks``
    which is read-only — option 3 would crash there.
    """
    override = os.environ.get("SPENDIFAI_LOG_DIR")
    if override:
        return Path(override).expanduser()

    # Frozen → always use the per-user dotdir.
    if getattr(sys, "frozen", False):
        return Path.home() / ".spendifai" / "logs"

    # Source mode → keep the historical `./logs` if the cwd is writable.
    try:
        Path("logs").mkdir(exist_ok=True)
        # touch to confirm write access
        probe = Path("logs") / ".write_probe"
        probe.touch()
        probe.unlink()
        return Path("logs")
    except (OSError, PermissionError):
        # Fall through to the per-user dotdir.
        pass

    return Path.home() / ".spendifai" / "logs"


def setup_logging():
    log_dir = _resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        handlers=[
            logging.FileHandler(str(log_file)),
            logging.StreamHandler(),
        ],
    )

    return logging.getLogger("SPENDIFY")
