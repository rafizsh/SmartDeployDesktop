"""
WIM Image management routes.
Handles image listing, capture, import, delete, and info retrieval.
"""

import os
import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, Request

from models.schemas import (
    WimImageInfo, WimIndexInfo, CaptureImageRequest,
    ImportImageRequest, ImageFormat, Architecture
)
from utils.powershell import run_powershell, run_dism, run_powershell_json

router = APIRouter()
logger = logging.getLogger("smartdeploy.images")


def _format_size(size_bytes: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


@router.get("/", response_model=List[WimImageInfo])
async def list_images(request: Request):
    """List all WIM/ESD images in the image store."""
    config = request.app.state.config
    image_store = config.image_store
    images = []

    if not os.path.exists(image_store):
        return images

    for fname in os.listdir(image_store):
        fpath = os.path.join(image_store, fname)
        ext = os.path.splitext(fname)[1].lower()

        if ext not in (".wim", ".esd", ".swm"):
            continue

        stat = os.stat(fpath)
        fmt = ImageFormat.WIM if ext == ".wim" else (ImageFormat.ESD if ext == ".esd" else ImageFormat.SWM)

        images.append(WimImageInfo(
            name=fname,
            path=fpath,
            size_bytes=stat.st_size,
            size_display=_format_size(stat.st_size),
            format=fmt,
            created=datetime.fromtimestamp(stat.st_ctime).isoformat(),
            modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        ))

    logger.info(f"Listed {len(images)} images from {image_store}")
    return images


@router.get("/{image_name}/info", response_model=List[WimIndexInfo])
async def get_image_info(image_name: str, request: Request):
    """Get detailed info about all indexes in a WIM file using DISM."""
    config = request.app.state.config
    image_path = os.path.join(config.image_store, image_name)

    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail=f"Image not found: {image_name}")

    # Use DISM /Get-ImageInfo to enumerate indexes
    result = await run_dism(f"/Get-ImageInfo /ImageFile:\"{image_path}\"")

    if not result.success:
        raise HTTPException(status_code=500, detail=f"DISM failed: {result.stderr}")

    # Parse DISM output for index information
    indexes = _parse_image_info(result.stdout, image_path)
    return indexes


@router.get("/{image_name}/index/{index}/details", response_model=WimIndexInfo)
async def get_index_details(image_name: str, index: int, request: Request):
    """Get detailed info about a specific index in a WIM file."""
    config = request.app.state.config
    image_path = os.path.join(config.image_store, image_name)

    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail=f"Image not found: {image_name}")

    result = await run_dism(f"/Get-ImageInfo /ImageFile:\"{image_path}\" /Index:{index}")

    if not result.success:
        raise HTTPException(status_code=500, detail=f"DISM failed: {result.stderr}")

    info = _parse_single_index_info(result.stdout, index)
    return info


@router.post("/capture")
async def capture_image(req: CaptureImageRequest, request: Request):
    """Capture a new WIM image from a source path."""
    logger.info(f"Capturing image from {req.source_path} to {req.destination_path}")

    compress_map = {"none": "none", "fast": "fast", "maximum": "max"}
    compress_flag = compress_map.get(req.compress, "max")

    cmd = f'/Capture-Image /ImageFile:"{req.destination_path}" /CaptureDir:"{req.source_path}" /Name:"{req.image_name}"'
    if req.description:
        cmd += f' /Description:"{req.description}"'
    cmd += f" /Compress:{compress_flag}"
    if req.boot_capture:
        cmd += " /Bootable"
    if req.verify:
        cmd += " /Verify"

    result = await run_dism(cmd, timeout=3600)  # Allow up to 1 hour for capture

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Capture failed: {result.stderr}")

    return {"success": True, "message": f"Image captured to {req.destination_path}", "output": result.stdout}


@router.post("/import")
async def import_image(req: ImportImageRequest, request: Request):
    """Import an existing WIM file into the image store."""
    config = request.app.state.config

    if not os.path.exists(req.source_path):
        raise HTTPException(status_code=404, detail=f"Source file not found: {req.source_path}")

    dest_name = req.new_name or os.path.basename(req.source_path)
    dest_path = os.path.join(config.image_store, dest_name)

    # Copy file via PowerShell (handles large files and network paths)
    result = await run_powershell(
        f'Copy-Item -Path "{req.source_path}" -Destination "{dest_path}" -Force',
        timeout=3600
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=f"Import failed: {result.stderr}")

    return {"success": True, "message": f"Image imported as {dest_name}", "path": dest_path}


@router.delete("/{image_name}")
async def delete_image(image_name: str, request: Request):
    """Delete a WIM image from the store."""
    config = request.app.state.config
    image_path = os.path.join(config.image_store, image_name)

    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail=f"Image not found: {image_name}")

    try:
        os.remove(image_path)
        logger.info(f"Deleted image: {image_name}")
        return {"success": True, "message": f"Deleted {image_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


# ---------------------------------------------------------------------------
# DISM output parsing helpers
# ---------------------------------------------------------------------------

def _parse_image_info(dism_output: str, image_path: str) -> List[WimIndexInfo]:
    """Parse DISM /Get-ImageInfo output to extract index list."""
    indexes = []
    current = {}

    for line in dism_output.splitlines():
        line = line.strip()
        if line.startswith("Index :"):
            if current:
                indexes.append(WimIndexInfo(**current))
            current = {"index": int(line.split(":")[1].strip())}
        elif line.startswith("Name :"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description :"):
            current["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("Size :"):
            size_str = line.split(":", 1)[1].strip().replace(",", "").replace(" bytes", "")
            try:
                current["size_bytes"] = int(size_str)
            except ValueError:
                current["size_bytes"] = 0

    if current:
        indexes.append(WimIndexInfo(**current))

    return indexes


def _parse_single_index_info(dism_output: str, index: int) -> WimIndexInfo:
    """Parse DISM output for a single index with detailed info."""
    info = {"index": index, "name": "", "description": ""}

    field_map = {
        "Name": "name",
        "Description": "description",
        "Architecture": "architecture",
        "Edition": "edition",
        "Version": "version",
        "Build": "build",
        "Default Language": "language",
        "HAL": "hal",
    }

    for line in dism_output.splitlines():
        line = line.strip()
        for dism_key, model_key in field_map.items():
            if line.startswith(f"{dism_key} :"):
                info[model_key] = line.split(":", 1)[1].strip()

        if line.startswith("Size :"):
            size_str = line.split(":", 1)[1].strip().replace(",", "").replace(" bytes", "")
            try:
                info["size_bytes"] = int(size_str)
            except ValueError:
                pass

    return WimIndexInfo(**info)
