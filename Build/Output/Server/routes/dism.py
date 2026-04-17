"""
DISM operations routes.
Direct access to DISM mount, unmount, apply, capture, split, export, and cleanup.
"""

import os
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request

from models.schemas import (
    DismMountRequest, DismApplyRequest, DismCaptureRequest,
    DismSplitRequest, DismExportRequest, DismResult, DismOperation
)
from utils.powershell import run_dism, run_powershell

router = APIRouter()
logger = logging.getLogger("smartdeploy.dism")


@router.post("/mount", response_model=DismResult)
async def mount_image(req: DismMountRequest, request: Request):
    """Mount a WIM image to a directory."""
    config = request.app.state.config
    start = datetime.now()

    # Use default mount dir if not specified
    mount_path = req.mount_path or os.path.join(config.mount_dir, f"mount_{req.index}")
    os.makedirs(mount_path, exist_ok=True)

    read_only = "/ReadOnly" if req.read_only else ""
    result = await run_dism(
        f'/Mount-Wim /WimFile:"{req.image_path}" /Index:{req.index} /MountDir:"{mount_path}" {read_only}',
        timeout=600
    )

    elapsed = (datetime.now() - start).total_seconds()

    return DismResult(
        success=result.success,
        operation=DismOperation.MOUNT,
        message=f"Image mounted at {mount_path}" if result.success else f"Mount failed: {result.stderr}",
        details=result.stdout if result.success else result.stderr,
        elapsed_seconds=elapsed,
    )


@router.post("/unmount")
async def unmount_image(mount_path: str, commit: bool = False):
    """Unmount a mounted WIM image."""
    start = datetime.now()
    action = "/Commit" if commit else "/Discard"

    result = await run_dism(
        f'/Unmount-Wim /MountDir:"{mount_path}" {action}',
        timeout=600
    )

    elapsed = (datetime.now() - start).total_seconds()

    return DismResult(
        success=result.success,
        operation=DismOperation.UNMOUNT,
        message=f"Image unmounted ({'committed' if commit else 'discarded'})" if result.success else f"Unmount failed: {result.stderr}",
        details=result.stdout if result.success else result.stderr,
        elapsed_seconds=elapsed,
    )


@router.post("/apply", response_model=DismResult)
async def apply_image(req: DismApplyRequest):
    """Apply a WIM image to a target volume."""
    start = datetime.now()

    cmd = f'/Apply-Image /ImageFile:"{req.image_path}" /Index:{req.index} /ApplyDir:"{req.apply_path}"'
    if req.verify:
        cmd += " /Verify"
    if req.compact:
        cmd += " /Compact"

    result = await run_dism(cmd, timeout=3600)
    elapsed = (datetime.now() - start).total_seconds()

    return DismResult(
        success=result.success,
        operation=DismOperation.APPLY,
        message=f"Image applied to {req.apply_path}" if result.success else f"Apply failed: {result.stderr}",
        details=result.stdout if result.success else result.stderr,
        elapsed_seconds=elapsed,
    )


@router.post("/capture", response_model=DismResult)
async def capture_image(req: DismCaptureRequest):
    """Capture a volume to a new WIM file."""
    start = datetime.now()

    compress_map = {"none": "none", "fast": "fast", "maximum": "max"}
    compress = compress_map.get(req.compress, "max")

    cmd = f'/Capture-Image /ImageFile:"{req.destination_path}" /CaptureDir:"{req.capture_path}" /Name:"{req.image_name}" /Compress:{compress}'
    if req.description:
        cmd += f' /Description:"{req.description}"'
    if req.boot:
        cmd += " /Bootable"
    if req.verify:
        cmd += " /Verify"

    result = await run_dism(cmd, timeout=3600)
    elapsed = (datetime.now() - start).total_seconds()

    return DismResult(
        success=result.success,
        operation=DismOperation.CAPTURE,
        message=f"Image captured to {req.destination_path}" if result.success else f"Capture failed: {result.stderr}",
        details=result.stdout if result.success else result.stderr,
        elapsed_seconds=elapsed,
    )


@router.post("/split", response_model=DismResult)
async def split_image(req: DismSplitRequest):
    """Split a WIM into multiple SWM files."""
    start = datetime.now()

    result = await run_dism(
        f'/Split-Image /ImageFile:"{req.image_path}" /SWMFile:"{req.output_path}" /FileSize:{req.max_size_mb}',
        timeout=3600
    )

    elapsed = (datetime.now() - start).total_seconds()

    return DismResult(
        success=result.success,
        operation=DismOperation.SPLIT,
        message=f"Image split to {req.output_path}" if result.success else f"Split failed: {result.stderr}",
        details=result.stdout if result.success else result.stderr,
        elapsed_seconds=elapsed,
    )


@router.post("/export", response_model=DismResult)
async def export_image(req: DismExportRequest):
    """Export a WIM index to a new WIM or ESD file."""
    start = datetime.now()

    compress_map = {"none": "none", "fast": "fast", "maximum": "max", "recovery": "recovery"}
    compress = compress_map.get(req.compress, "max")

    result = await run_dism(
        f'/Export-Image /SourceImageFile:"{req.source_path}" /SourceIndex:{req.source_index} '
        f'/DestinationImageFile:"{req.destination_path}" /Compress:{compress}',
        timeout=3600
    )

    elapsed = (datetime.now() - start).total_seconds()

    return DismResult(
        success=result.success,
        operation=DismOperation.EXPORT,
        message=f"Index exported to {req.destination_path}" if result.success else f"Export failed: {result.stderr}",
        details=result.stdout if result.success else result.stderr,
        elapsed_seconds=elapsed,
    )


@router.get("/mounted")
async def list_mounted_images():
    """List currently mounted WIM images."""
    result = await run_dism("/Get-MountedWimInfo")

    if not result.success:
        return {"mounted_images": [], "raw_output": result.stderr}

    # Parse mounted image info
    mounts = []
    current = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Mount Dir :"):
            if current:
                mounts.append(current)
            current = {"mount_dir": line.split(":", 1)[1].strip()}
        elif line.startswith("Image File :"):
            current["image_file"] = line.split(":", 1)[1].strip()
        elif line.startswith("Image Index :"):
            current["image_index"] = line.split(":", 1)[1].strip()
        elif line.startswith("Mounted Read/Write :"):
            current["read_write"] = "yes" in line.lower()
        elif line.startswith("Status :"):
            current["status"] = line.split(":", 1)[1].strip()

    if current:
        mounts.append(current)

    return {"mounted_images": mounts}


@router.post("/cleanup")
async def cleanup_wim():
    """Clean up orphaned WIM mount points and resources."""
    result = await run_dism("/Cleanup-Wim")

    return DismResult(
        success=result.success,
        operation=DismOperation.CLEANUP,
        message="WIM cleanup completed" if result.success else f"Cleanup failed: {result.stderr}",
        details=result.stdout if result.success else result.stderr,
    )


@router.post("/cleanup-mountpoints")
async def cleanup_mountpoints(request: Request):
    """Force cleanup of all mount points."""
    config = request.app.state.config

    # First, try DISM cleanup
    await run_dism("/Cleanup-Mountpoints")

    # Then clean the mount directory
    mount_dir = config.mount_dir
    if os.path.exists(mount_dir):
        result = await run_powershell(
            f'Get-ChildItem -Path "{mount_dir}" -Directory | ForEach-Object {{ '
            f'DISM.exe /Unmount-Wim /MountDir:"$($_.FullName)" /Discard 2>$null; '
            f'Remove-Item -Path "$($_.FullName)" -Recurse -Force 2>$null }}'
        )

    return {"success": True, "message": "Mount points cleaned up"}


# ============================================================================
# Driver Injection into WIM
# ============================================================================

from pydantic import BaseModel
from typing import List, Optional

class DriverInjectRequest(BaseModel):
    """Request to inject drivers into a WIM image."""
    wim_path: str                    # Full path to the .wim file
    image_index: int = 1             # Which index in the WIM to modify
    driver_paths: List[str] = []     # List of paths to driver folders or .inf files
    recurse: bool = True             # Search subfolders for .inf files
    model_config = {"extra": "allow"}


class DriverInjectResult(BaseModel):
    """Result of driver injection."""
    success: bool
    message: str
    drivers_added: int = 0
    drivers_found: int = 0
    log: List[str] = []
    model_config = {"extra": "allow"}


@router.post("/inject-drivers", response_model=DriverInjectResult)
async def inject_drivers(req: DriverInjectRequest, request: Request):
    """
    Inject drivers into a WIM image.
    1. Mount the WIM
    2. Add drivers via DISM
    3. Unmount and commit
    """
    config = request.app.state.config
    log = []

    if not os.path.exists(req.wim_path):
        return DriverInjectResult(
            success=False, message=f"WIM file not found: {req.wim_path}", log=log)

    # Determine driver paths
    driver_paths = req.driver_paths
    if not driver_paths:
        # Use the default driver store
        driver_store = config.driver_store
        if os.path.exists(driver_store):
            driver_paths = [driver_store]
        else:
            return DriverInjectResult(
                success=False, message=f"No driver paths specified and driver store is empty: {driver_store}", log=log)

    # Count available .inf files
    inf_count = 0
    for dp in driver_paths:
        if os.path.isfile(dp) and dp.lower().endswith(".inf"):
            inf_count += 1
        elif os.path.isdir(dp):
            for root, dirs, files in os.walk(dp):
                inf_count += sum(1 for f in files if f.lower().endswith(".inf"))
                if not req.recurse:
                    break

    log.append(f"Found {inf_count} .inf driver files across {len(driver_paths)} path(s)")

    if inf_count == 0:
        return DriverInjectResult(
            success=False, message="No .inf driver files found in the specified paths",
            drivers_found=0, log=log)

    # Step 1: Mount the WIM
    mount_path = os.path.join(config.mount_dir, f"inject_{req.image_index}")
    os.makedirs(mount_path, exist_ok=True)

    log.append(f"Mounting {os.path.basename(req.wim_path)} index {req.image_index} to {mount_path}...")

    mount_result = await run_dism(
        f'/Mount-Wim /WimFile:"{req.wim_path}" /Index:{req.image_index} /MountDir:"{mount_path}"'
    )

    if not mount_result.success:
        log.append(f"Mount FAILED: {mount_result.stderr[:300]}")
        return DriverInjectResult(
            success=False, message="Failed to mount WIM image",
            drivers_found=inf_count, log=log)

    log.append("WIM mounted successfully")

    # Step 2: Add drivers
    drivers_added = 0
    for dp in driver_paths:
        if os.path.isfile(dp) and dp.lower().endswith(".inf"):
            # Single .inf file
            log.append(f"Adding driver: {dp}")
            add_result = await run_dism(
                f'/Image:"{mount_path}" /Add-Driver /Driver:"{dp}"'
            )
            if add_result.success:
                drivers_added += 1
                log.append(f"  ✓ Added {os.path.basename(dp)}")
            else:
                log.append(f"  ✗ Failed: {add_result.stderr[:200]}")
        elif os.path.isdir(dp):
            # Folder of drivers
            recurse_flag = "/Recurse" if req.recurse else ""
            log.append(f"Adding drivers from folder: {dp} {recurse_flag}")
            add_result = await run_dism(
                f'/Image:"{mount_path}" /Add-Driver /Driver:"{dp}" {recurse_flag} /ForceUnsigned'
            )
            if add_result.success:
                # Count how many were added from the output
                added_lines = [l for l in add_result.stdout.splitlines() if "installed" in l.lower() or "added" in l.lower()]
                count = len(added_lines) if added_lines else inf_count
                drivers_added += count
                log.append(f"  ✓ Added drivers from {dp}")
                if add_result.stdout.strip():
                    for line in add_result.stdout.strip().splitlines()[-5:]:
                        log.append(f"    {line.strip()}")
            else:
                log.append(f"  ✗ Failed: {add_result.stderr[:200]}")

    # Step 3: Unmount and commit
    log.append("Unmounting and committing changes...")
    unmount_result = await run_dism(
        f'/Unmount-Wim /MountDir:"{mount_path}" /Commit'
    )

    if unmount_result.success:
        log.append("✓ WIM saved with drivers injected")
    else:
        log.append(f"✗ Unmount failed: {unmount_result.stderr[:300]}")
        # Try to discard and cleanup
        await run_dism(f'/Unmount-Wim /MountDir:"{mount_path}" /Discard')
        return DriverInjectResult(
            success=False, message="Failed to commit changes to WIM",
            drivers_added=drivers_added, drivers_found=inf_count, log=log)

    # Cleanup mount directory
    try:
        os.rmdir(mount_path)
    except Exception:
        pass

    logger.info(f"Driver injection complete: {drivers_added} drivers added to {os.path.basename(req.wim_path)}")

    return DriverInjectResult(
        success=True,
        message=f"Successfully injected {drivers_added} driver(s) into {os.path.basename(req.wim_path)}",
        drivers_added=drivers_added,
        drivers_found=inf_count,
        log=log)


@router.get("/drivers/{wim_path:path}")
async def list_drivers_in_wim(wim_path: str, index: int = 1, request: Request = None):
    """List drivers already in a WIM image (without mounting permanently)."""
    config = request.app.state.config

    full_path = wim_path
    if not os.path.isabs(wim_path):
        full_path = os.path.join(config.image_store, wim_path)

    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"WIM not found: {full_path}")

    # Mount temporarily, list drivers, unmount
    mount_path = os.path.join(config.mount_dir, "driver_list_temp")
    os.makedirs(mount_path, exist_ok=True)

    await run_dism(f'/Mount-Wim /WimFile:"{full_path}" /Index:{index} /MountDir:"{mount_path}" /ReadOnly')

    result = await run_dism(f'/Image:"{mount_path}" /Get-Drivers /Format:Table')

    await run_dism(f'/Unmount-Wim /MountDir:"{mount_path}" /Discard')

    try:
        os.rmdir(mount_path)
    except Exception:
        pass

    drivers = []
    if result.success:
        for line in result.stdout.splitlines():
            if ".inf" in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    drivers.append({
                        "name": parts[0],
                        "original_name": parts[1] if len(parts) > 1 else "",
                        "provider": parts[2] if len(parts) > 2 else "",
                        "version": parts[3] if len(parts) > 3 else "",
                    })

    return {"wim": os.path.basename(full_path), "index": index, "driver_count": len(drivers), "drivers": drivers}
