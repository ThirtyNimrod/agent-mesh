import logging
import sys
from datetime import datetime
from pathlib import Path

_configured = False

def setup_logging(source: str, level: int = logging.INFO) -> None:
    """Configure root logger with a per-run timestamped log file and a stderr console handler.

    Creates logs/<YYYY-MM-DD_HH-MM-SS>_<source>.log on each invocation.
    Subsequent calls within the same process are no-ops.
    """
    global _configured
    if _configured:
        return
    _configured = True

    project_root = Path(__file__).resolve().parent.parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = logs_dir / f"{timestamp}_{source}.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)
