"""
Dashboard routes.
Provides overview stats, log retrieval, and configuration management.
"""

import os
import logging
from typing import List
from fastapi import APIRouter, Request

from models.schemas import DashboardStats, LogEntry, ServerConfig
from utils.powershell import run_powershell_json

router = APIRouter()
logger = logging.getLogger("smartdeploy.dashboard")


def _format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _get_dir_size(path: str) -> int:
    total = 0
    if os.path.exists(path):
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    return total


def _count_files(path: str, extensions: list) -> int:
    count = 0
    if os.path.exists(path):
        for f in os.listdir(path):
            if any(f.lower().endswith(ext) for ext in extensions):
                count += 1
    return count


def _count_dirs(path: str) -> int:
    if os.path.exists(path):
        return len([d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))])
    return 0


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(request: Request):
    """Get overview statistics for the dashboard."""
    config = request.app.state.config

    # Count resources
    total_images = _count_files(config.image_store, [".wim", ".esd", ".swm"])
    total_packs = _count_dirs(config.platform_pack_store)
    total_ts = _count_files(config.task_sequence_dir, [".json"])

    # Deployment stats from the in-memory tracker
    from routes.deployment import _active_deployments
    active = sum(1 for d in _active_deployments.values() if d.status.value == "in_progress")
    completed = sum(1 for d in _active_deployments.values() if d.status.value == "completed")
    failed = sum(1 for d in _active_deployments.values() if d.status.value == "failed")

    # Storage sizes
    image_size = _get_dir_size(config.image_store)
    driver_size = _get_dir_size(config.platform_pack_store)

    # Basic system info
    sys_info = {}
    si = await run_powershell_json(
        "Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, FreePhysicalMemory, TotalVisibleMemorySize"
    )
    if si:
        sys_info = {
            "os": si.get("Caption", ""),
            "version": si.get("Version", ""),
            "free_ram_mb": round(si.get("FreePhysicalMemory", 0) / 1024, 0),
            "total_ram_mb": round(si.get("TotalVisibleMemorySize", 0) / 1024, 0),
        }

    return DashboardStats(
        total_images=total_images,
        total_platform_packs=total_packs,
        total_task_sequences=total_ts,
        active_deployments=active,
        completed_deployments=completed,
        failed_deployments=failed,
        image_store_size=_format_size(image_size),
        driver_store_size=_format_size(driver_size),
        system_info=sys_info,
    )


@router.get("/logs", response_model=List[LogEntry])
async def get_recent_logs(lines: int = 100, level: str = None, request: Request = None):
    """Get recent log entries from the server log file."""
    config = request.app.state.config
    app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    log_file = os.path.join(app_data, "SmartDeployDesktop", "Logs", "server.log")

    entries = []
    if not os.path.exists(log_file):
        return entries

    try:
        with open(log_file, "r") as f:
            all_lines = f.readlines()

        # Take last N lines
        recent = all_lines[-lines:] if len(all_lines) > lines else all_lines

        for line in recent:
            line = line.strip()
            if not line:
                continue

            # Parse: "2024-01-15 10:30:00,123 | INFO     | smartdeploy.images | Message here"
            parts = line.split(" | ", 3)
            if len(parts) >= 4:
                entry = LogEntry(
                    timestamp=parts[0].strip(),
                    level=parts[1].strip(),
                    source=parts[2].strip(),
                    message=parts[3].strip(),
                )
                # Filter by level if specified
                if level and entry.level.upper() != level.upper():
                    continue
                entries.append(entry)

    except Exception as e:
        logger.warning(f"Failed to read log file: {e}")

    return entries


@router.get("/config", response_model=ServerConfig)
async def get_config(request: Request):
    """Get current server configuration."""
    config = request.app.state.config
    return ServerConfig(config=config.get_all())


@router.put("/config")
async def update_config(updates: dict, request: Request):
    """Update server configuration."""
    config = request.app.state.config
    config.update(updates)

    return {"success": True, "message": "Configuration updated", "config": config.get_all()}


@router.get("/disk-space")
async def get_disk_space():
    """Get disk space info for all volumes."""
    data = await run_powershell_json(
        "Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -eq 3 } | "
        "Select-Object DeviceID, VolumeName, Size, FreeSpace, FileSystem"
    )

    if not data:
        return {"volumes": []}

    items = data if isinstance(data, list) else [data]
    volumes = []
    for v in items:
        size = v.get("Size", 0) or 0
        free = v.get("FreeSpace", 0) or 0
        volumes.append({
            "drive": v.get("DeviceID", ""),
            "label": v.get("VolumeName", ""),
            "size": _format_size(size),
            "free": _format_size(free),
            "used_percent": round((1 - free / size) * 100, 1) if size > 0 else 0,
            "file_system": v.get("FileSystem", ""),
        })

    return {"volumes": volumes}
