"""
Configuration service for SmartDeploy Desktop Server.
Manages paths, settings, and persistent configuration.
"""

import os
import json
import logging
from pathlib import Path

logger = logging.getLogger("smartdeploy.config")


class ConfigService:
    """Manages application configuration and directory paths."""

    DEFAULT_CONFIG = {
        "image_store": r"C:\SmartDeploy\Images",
        "platform_pack_store": r"C:\SmartDeploy\PlatformPacks",
        "mount_dir": r"C:\SmartDeploy\Mount",
        "log_dir": r"C:\SmartDeploy\Logs",
        "task_sequence_dir": r"C:\SmartDeploy\TaskSequences",
        "answer_file_dir": r"C:\SmartDeploy\AnswerFiles",
        "driver_store": r"C:\SmartDeploy\Drivers",
        "usb_boot_template": r"C:\SmartDeploy\USBTemplate",
        "network_share": "",
        "cloud_storage_url": "",
        "default_os_edition": "Windows 11 Pro",
        "default_architecture": "x64",
        "pxe_server": "",
        "wds_server": "",
        "auto_cleanup_mount": True,
        "max_concurrent_deployments": 3,
        "deployment_timeout_minutes": 120,
        "enable_bitlocker_suspend": True,
        "log_level": "INFO",
    }

    def __init__(self):
        self._config = dict(self.DEFAULT_CONFIG)
        self._config_path = self._resolve_config_path()

    # ---- properties for commonly used paths ----

    @property
    def image_store(self) -> str:
        return self._config["image_store"]

    @property
    def platform_pack_store(self) -> str:
        return self._config["platform_pack_store"]

    @property
    def mount_dir(self) -> str:
        return self._config["mount_dir"]

    @property
    def log_dir(self) -> str:
        return self._config["log_dir"]

    @property
    def task_sequence_dir(self) -> str:
        return self._config["task_sequence_dir"]

    @property
    def answer_file_dir(self) -> str:
        return self._config["answer_file_dir"]

    @property
    def driver_store(self) -> str:
        return self._config["driver_store"]

    # ---- core methods ----

    def _resolve_config_path(self) -> str:
        app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        config_dir = os.path.join(app_data, "SmartDeployDesktop")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "config.json")

    def load(self):
        """Load configuration from disk, falling back to defaults."""
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r") as f:
                    saved = json.load(f)
                self._config.update(saved)
                logger.info(f"Configuration loaded from {self._config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config: {e}. Using defaults.")
        else:
            logger.info("No config file found. Using defaults.")
            self.save()

    def save(self):
        """Persist current configuration to disk."""
        try:
            with open(self._config_path, "w") as f:
                json.dump(self._config, f, indent=2)
            logger.info(f"Configuration saved to {self._config_path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def set(self, key: str, value):
        self._config[key] = value

    def get_all(self) -> dict:
        return dict(self._config)

    def update(self, updates: dict):
        self._config.update(updates)
        self.save()
