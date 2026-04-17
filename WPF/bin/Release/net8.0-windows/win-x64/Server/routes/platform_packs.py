"""
Platform Pack management routes.
Handles driver pack listing, importing, driver injection into images.
"""

import os
import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, Request

from models.schemas import PlatformPack, InjectDriversRequest, Architecture
from utils.powershell import run_powershell, run_dism

router = APIRouter()
logger = logging.getLogger("smartdeploy.platform_packs")


def _format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _get_dir_size(path: str) -> int:
    """Calculate total size of directory recursively."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def _count_drivers(path: str) -> int:
    """Count .inf files in a directory tree (each represents a driver)."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            if f.lower().endswith(".inf"):
                count += 1
    return count


@router.get("/", response_model=List[PlatformPack])
async def list_platform_packs(request: Request):
    """List all available Platform Packs."""
    config = request.app.state.config
    store = config.platform_pack_store
    packs = []

    if not os.path.exists(store):
        return packs

    for item in os.listdir(store):
        item_path = os.path.join(store, item)
        if not os.path.isdir(item_path):
            continue

        # Expect directory structure: Manufacturer_Model_OS/
        parts = item.split("_", 2)
        manufacturer = parts[0] if len(parts) > 0 else "Unknown"
        model = parts[1] if len(parts) > 1 else "Unknown"
        os_ver = parts[2] if len(parts) > 2 else ""

        size = _get_dir_size(item_path)
        driver_count = _count_drivers(item_path)
        stat = os.stat(item_path)

        packs.append(PlatformPack(
            id=item,
            manufacturer=manufacturer,
            model=model,
            os_version=os_ver.replace("_", " "),
            path=item_path,
            driver_count=driver_count,
            size_bytes=size,
            size_display=_format_size(size),
            created=datetime.fromtimestamp(stat.st_ctime).isoformat(),
        ))

    logger.info(f"Listed {len(packs)} platform packs")
    return packs


@router.get("/{pack_id}", response_model=PlatformPack)
async def get_platform_pack(pack_id: str, request: Request):
    """Get details for a specific Platform Pack."""
    config = request.app.state.config
    pack_path = os.path.join(config.platform_pack_store, pack_id)

    if not os.path.exists(pack_path):
        raise HTTPException(status_code=404, detail=f"Platform Pack not found: {pack_id}")

    parts = pack_id.split("_", 2)
    size = _get_dir_size(pack_path)
    driver_count = _count_drivers(pack_path)
    stat = os.stat(pack_path)

    return PlatformPack(
        id=pack_id,
        manufacturer=parts[0] if len(parts) > 0 else "Unknown",
        model=parts[1] if len(parts) > 1 else "Unknown",
        os_version=parts[2].replace("_", " ") if len(parts) > 2 else "",
        path=pack_path,
        driver_count=driver_count,
        size_bytes=size,
        size_display=_format_size(size),
        created=datetime.fromtimestamp(stat.st_ctime).isoformat(),
    )


@router.post("/inject")
async def inject_drivers(req: InjectDriversRequest, request: Request):
    """Inject drivers from a Platform Pack into a mounted WIM image."""
    config = request.app.state.config
    pack_path = os.path.join(config.platform_pack_store, req.platform_pack_id)

    if not os.path.exists(pack_path):
        raise HTTPException(status_code=404, detail=f"Platform Pack not found: {req.platform_pack_id}")

    if not os.path.exists(req.mount_path):
        raise HTTPException(status_code=400, detail=f"Mount path does not exist: {req.mount_path}")

    logger.info(f"Injecting drivers from {req.platform_pack_id} into {req.mount_path}")

    recurse_flag = "/Recurse" if req.recurse else ""
    result = await run_dism(
        f'/Image:"{req.mount_path}" /Add-Driver /Driver:"{pack_path}" {recurse_flag} /ForceUnsigned',
        timeout=600
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Driver injection failed: {result.stderr}")

    # Count injected drivers from output
    injected = result.stdout.lower().count("successfully")

    return {
        "success": True,
        "message": f"Drivers injected from {req.platform_pack_id}",
        "drivers_processed": injected,
        "output": result.stdout
    }


@router.post("/import")
async def import_platform_pack(
    source_path: str,
    pack_name: str,
    request: Request
):
    """Import a driver folder as a new Platform Pack."""
    config = request.app.state.config

    if not os.path.exists(source_path):
        raise HTTPException(status_code=404, detail=f"Source path not found: {source_path}")

    dest_path = os.path.join(config.platform_pack_store, pack_name)

    result = await run_powershell(
        f'Copy-Item -Path "{source_path}" -Destination "{dest_path}" -Recurse -Force',
        timeout=1800
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Import failed: {result.stderr}")

    driver_count = _count_drivers(dest_path)

    return {
        "success": True,
        "message": f"Platform Pack imported as {pack_name}",
        "driver_count": driver_count,
        "path": dest_path
    }


@router.delete("/{pack_id}")
async def delete_platform_pack(pack_id: str, request: Request):
    """Delete a Platform Pack."""
    config = request.app.state.config
    pack_path = os.path.join(config.platform_pack_store, pack_id)

    if not os.path.exists(pack_path):
        raise HTTPException(status_code=404, detail=f"Platform Pack not found: {pack_id}")

    result = await run_powershell(
        f'Remove-Item -Path "{pack_path}" -Recurse -Force',
        timeout=120
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Delete failed: {result.stderr}")

    return {"success": True, "message": f"Deleted Platform Pack: {pack_id}"}
