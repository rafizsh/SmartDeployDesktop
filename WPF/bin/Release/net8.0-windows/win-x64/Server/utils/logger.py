"""
Logging setup for SmartDeploy Desktop Server.
"""

import os
import logging
from logging.handlers import RotatingFileHandler


def setup_logging(log_dir: str = None, level: str = "INFO"):
    """Configure logging to console and rotating file."""

    if log_dir is None:
        app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        log_dir = os.path.join(app_data, "SmartDeployDesktop", "Logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "server.log")
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger("smartdeploy")
    root_logger.setLevel(numeric_level)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console_fmt = logging.Formatter("[%(asctime)s] %(levelname)-8s %(name)s: %(message)s", datefmt="%H:%M:%S")
    console.setFormatter(console_fmt)

    # File handler (10 MB rotating, keep 5 backups)
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setLevel(numeric_level)
    file_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    file_handler.setFormatter(file_fmt)

    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)

    root_logger.info(f"Logging initialized. Level={level}, File={log_file}")
