"""
Deployment routes.
Handles deploying images to USB, network shares, cloud, and PXE targets.
Tracks deployment status and progress.
"""

import os
import uuid
import logging
import asyncio
from datetime import datetime
from typing import List, Dict
from fastapi import APIRouter, HTTPException, Request

from models.schemas import (
    DeploymentRequest, DeploymentInfo, DeploymentStatus,
    DeployTarget, USBDriveInfo
)
from utils.powershell import run_powershell, run_dism, run_diskpart, run_powershell_json

router = APIRouter()
logger = logging.getLogger("smartdeploy.deployment")

# In-memory deployment tracker
_active_deployments: Dict[str, DeploymentInfo] = {}


@router.get("/status", response_model=List[DeploymentInfo])
async def list_deployments():
    """List all active and recent deployments."""
    return list(_active_deployments.values())


@router.get("/status/{deploy_id}", response_model=DeploymentInfo)
async def get_deployment_status(deploy_id: str):
    """Get status of a specific deployment."""
    if deploy_id not in _active_deployments:
        raise HTTPException(status_code=404, detail=f"Deployment not found: {deploy_id}")
    return _active_deployments[deploy_id]


@router.post("/start", response_model=DeploymentInfo)
async def start_deployment(req: DeploymentRequest, request: Request):
    """Start a new deployment."""
    config = request.app.state.config

    if not os.path.exists(req.image_path):
        raise HTTPException(status_code=404, detail=f"Image not found: {req.image_path}")

    deploy_id = str(uuid.uuid4())[:8]
    deployment = DeploymentInfo(
        id=deploy_id,
        image_name=os.path.basename(req.image_path),
        target=req.target,
        target_path=req.target_path,
        status=DeploymentStatus.PENDING,
        started_at=datetime.now().isoformat(),
        current_step="Initializing",
    )
    _active_deployments[deploy_id] = deployment

    # Launch deployment in background
    asyncio.create_task(_run_deployment(deploy_id, req, config))

    logger.info(f"Deployment {deploy_id} started: {req.target} -> {req.target_path}")
    return deployment


@router.post("/cancel/{deploy_id}")
async def cancel_deployment(deploy_id: str):
    """Cancel an active deployment."""
    if deploy_id not in _active_deployments:
        raise HTTPException(status_code=404, detail=f"Deployment not found: {deploy_id}")

    dep = _active_deployments[deploy_id]
    if dep.status not in (DeploymentStatus.PENDING, DeploymentStatus.IN_PROGRESS):
        raise HTTPException(status_code=400, detail="Deployment is not active")

    dep.status = DeploymentStatus.CANCELLED
    dep.completed_at = datetime.now().isoformat()
    dep.current_step = "Cancelled by user"

    return {"success": True, "message": f"Deployment {deploy_id} cancelled"}


@router.get("/usb-drives", response_model=List[USBDriveInfo])
async def list_usb_drives():
    """List connected USB removable drives."""
    ps_cmd = """
    Get-WmiObject Win32_DiskDrive | Where-Object { $_.InterfaceType -eq 'USB' } | ForEach-Object {
        $disk = $_
        $partitions = Get-WmiObject -Query "ASSOCIATORS OF {Win32_DiskDrive.DeviceID='$($disk.DeviceID)'} WHERE AssocClass=Win32_DiskDriveToDiskPartition"
        foreach ($part in $partitions) {
            $logicals = Get-WmiObject -Query "ASSOCIATORS OF {Win32_DiskPartition.DeviceID='$($part.DeviceID)'} WHERE AssocClass=Win32_LogicalDiskToPartition"
            foreach ($logical in $logicals) {
                [PSCustomObject]@{
                    DeviceID = $disk.DeviceID
                    DriveLetter = $logical.DeviceID
                    Label = $logical.VolumeName
                    SizeBytes = [long]$logical.Size
                    FreeBytes = [long]$logical.FreeSpace
                    FileSystem = $logical.FileSystem
                }
            }
        }
    }
    """

    data = await run_powershell_json(ps_cmd)
    drives = []

    if data:
        # Handle single result (dict) vs multiple (list)
        items = data if isinstance(data, list) else [data]
        for d in items:
            drives.append(USBDriveInfo(
                device_id=d.get("DeviceID", ""),
                drive_letter=d.get("DriveLetter", ""),
                label=d.get("Label", ""),
                size_bytes=d.get("SizeBytes", 0),
                size_display=_format_size(d.get("SizeBytes", 0)),
                free_bytes=d.get("FreeBytes", 0),
                file_system=d.get("FileSystem", ""),
            ))

    return drives


@router.get("/network-shares")
async def validate_network_share(path: str):
    """Validate a network share path is accessible."""
    result = await run_powershell(f'Test-Path -Path "{path}"')

    accessible = result.success and result.stdout.strip().lower() == "true"
    return {
        "path": path,
        "accessible": accessible,
        "message": "Share is accessible" if accessible else "Share is not accessible or does not exist"
    }


# ---------------------------------------------------------------------------
# Background deployment logic
# ---------------------------------------------------------------------------

async def _run_deployment(deploy_id: str, req: DeploymentRequest, config):
    """Execute deployment steps in the background."""
    dep = _active_deployments[deploy_id]
    dep.status = DeploymentStatus.IN_PROGRESS
    start_time = datetime.now()

    try:
        if req.target == DeployTarget.USB:
            await _deploy_to_usb(dep, req, config)
        elif req.target == DeployTarget.NETWORK:
            await _deploy_to_network(dep, req, config)
        elif req.target == DeployTarget.CLOUD:
            await _deploy_to_cloud(dep, req, config)
        elif req.target == DeployTarget.LOCAL:
            await _deploy_local(dep, req, config)
        else:
            raise ValueError(f"Unsupported target: {req.target}")

        dep.status = DeploymentStatus.COMPLETED
        dep.progress_percent = 100.0
        dep.current_step = "Deployment complete"

    except Exception as e:
        dep.status = DeploymentStatus.FAILED
        dep.error_message = str(e)
        dep.current_step = f"Failed: {str(e)[:100]}"
        logger.error(f"Deployment {deploy_id} failed: {e}")

    finally:
        dep.completed_at = datetime.now().isoformat()
        dep.elapsed_seconds = int((datetime.now() - start_time).total_seconds())


async def _deploy_to_usb(dep: DeploymentInfo, req: DeploymentRequest, config):
    """Deploy image to a USB drive."""
    drive = req.target_path  # e.g., "E:"

    # Step 1: Format if requested
    if req.format_target:
        dep.current_step = "Formatting USB drive"
        dep.progress_percent = 5.0

        # Get disk number for the drive letter
        result = await run_powershell(
            f'(Get-Partition -DriveLetter "{drive[0]}").DiskNumber'
        )
        if not result.success:
            raise RuntimeError(f"Cannot identify disk for {drive}: {result.stderr}")

        disk_num = result.stdout.strip()
        await run_diskpart([
            f"select disk {disk_num}",
            "clean",
            "convert gpt",
            "create partition efi size=512",
            "format fs=fat32 quick label=BOOT",
            "assign",
            "create partition primary",
            "format fs=ntfs quick label=DEPLOY",
            "assign",
        ])

    # Step 2: Apply image
    dep.current_step = "Applying WIM image to USB"
    dep.progress_percent = 20.0

    result = await run_dism(
        f'/Apply-Image /ImageFile:"{req.image_path}" /Index:{req.image_index} /ApplyDir:"{drive}\\"',
        timeout=3600
    )
    if not result.success:
        raise RuntimeError(f"Image apply failed: {result.stderr}")

    dep.progress_percent = 70.0

    # Step 3: Make bootable
    if req.boot_files:
        dep.current_step = "Writing boot files"
        dep.progress_percent = 80.0

        result = await run_powershell(
            f'bcdboot "{drive}\\Windows" /s {drive} /f UEFI',
            run_as_admin=True
        )
        if not result.success:
            logger.warning(f"Boot file creation warning: {result.stderr}")

    # Step 4: Inject drivers if platform pack specified
    if req.platform_pack_id:
        dep.current_step = "Injecting Platform Pack drivers"
        dep.progress_percent = 85.0

        pack_path = os.path.join(config.platform_pack_store, req.platform_pack_id)
        if os.path.exists(pack_path):
            await run_dism(
                f'/Image:"{drive}\\" /Add-Driver /Driver:"{pack_path}" /Recurse /ForceUnsigned',
                timeout=600
            )

    # Step 5: Verify
    if req.verify_after:
        dep.current_step = "Verifying deployment"
        dep.progress_percent = 95.0
        # Basic verification: check Windows directory exists
        result = await run_powershell(f'Test-Path -Path "{drive}\\Windows"')
        if "True" not in result.stdout:
            raise RuntimeError("Verification failed: Windows directory not found on target")


async def _deploy_to_network(dep: DeploymentInfo, req: DeploymentRequest, config):
    """Deploy image to a network share."""
    share = req.target_path

    dep.current_step = "Validating network share"
    dep.progress_percent = 5.0

    result = await run_powershell(f'Test-Path -Path "{share}"')
    if "True" not in result.stdout:
        raise RuntimeError(f"Network share not accessible: {share}")

    dep.current_step = "Copying WIM image to network share"
    dep.progress_percent = 10.0

    dest_file = os.path.join(share, os.path.basename(req.image_path))
    result = await run_powershell(
        f'Copy-Item -Path "{req.image_path}" -Destination "{dest_file}" -Force',
        timeout=7200
    )
    if not result.success:
        raise RuntimeError(f"Copy failed: {result.stderr}")

    dep.progress_percent = 80.0

    # Copy answer file if specified
    if req.answer_file_path and os.path.exists(req.answer_file_path):
        dep.current_step = "Copying answer file"
        dep.progress_percent = 85.0
        dest_af = os.path.join(share, "autounattend.xml")
        await run_powershell(f'Copy-Item -Path "{req.answer_file_path}" -Destination "{dest_af}" -Force')

    # Copy task sequence if specified
    if req.task_sequence_id:
        dep.current_step = "Copying task sequence"
        dep.progress_percent = 90.0
        ts_path = os.path.join(config.task_sequence_dir, f"{req.task_sequence_id}.json")
        if os.path.exists(ts_path):
            dest_ts = os.path.join(share, "task_sequence.json")
            await run_powershell(f'Copy-Item -Path "{ts_path}" -Destination "{dest_ts}" -Force')


async def _deploy_to_cloud(dep: DeploymentInfo, req: DeploymentRequest, config):
    """Deploy image to cloud storage (Azure Blob, S3, etc.)."""
    dep.current_step = "Preparing cloud upload"
    dep.progress_percent = 5.0

    # Use azcopy or AWS CLI depending on URL scheme
    url = req.target_path

    if "blob.core.windows.net" in url or "azure" in url.lower():
        dep.current_step = "Uploading to Azure Blob Storage"
        dep.progress_percent = 10.0
        result = await run_powershell(
            f'azcopy copy "{req.image_path}" "{url}" --overwrite true',
            timeout=7200
        )
    elif "s3://" in url or "amazonaws.com" in url:
        dep.current_step = "Uploading to AWS S3"
        dep.progress_percent = 10.0
        result = await run_powershell(
            f'aws s3 cp "{req.image_path}" "{url}"',
            timeout=7200
        )
    else:
        # Generic HTTP upload via PowerShell
        dep.current_step = "Uploading to cloud endpoint"
        dep.progress_percent = 10.0
        result = await run_powershell(
            f'Invoke-WebRequest -Uri "{url}" -Method PUT -InFile "{req.image_path}"',
            timeout=7200
        )

    if not result.success:
        raise RuntimeError(f"Cloud upload failed: {result.stderr}")


async def _deploy_local(dep: DeploymentInfo, req: DeploymentRequest, config):
    """Apply image to a local volume (for in-place operations)."""
    dep.current_step = "Applying image to local volume"
    dep.progress_percent = 10.0

    result = await run_dism(
        f'/Apply-Image /ImageFile:"{req.image_path}" /Index:{req.image_index} /ApplyDir:"{req.target_path}"',
        timeout=3600
    )
    if not result.success:
        raise RuntimeError(f"Local apply failed: {result.stderr}")


def _format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"
