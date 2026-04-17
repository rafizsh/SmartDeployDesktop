"""File serving endpoints for WinPE wizard fallback (when SMB is unavailable)."""
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter(prefix="/files", tags=["files"])

# Base directory for file serving (matches SmartDeploy share)
BASE_DIR = r"C:\SmartDeploy"


def _safe_path(subpath: str) -> str:
    """Prevent path traversal - only allow files within BASE_DIR."""
    full = os.path.normpath(os.path.join(BASE_DIR, subpath))
    if not full.startswith(os.path.normpath(BASE_DIR)):
        raise HTTPException(403, "Path traversal not allowed")
    return full


@router.get("/{path:path}")
async def serve_file(path: str):
    """Serve a file from C:\\SmartDeploy\\ over HTTP.
    Used by the WinPE wizard when SMB share access fails.

    Examples:
      GET /api/files/images/install.wim
      GET /api/files/Drivers/some.inf
      GET /api/files/TaskSequences/post_install.cmd
    """
    full_path = _safe_path(path)

    if not os.path.exists(full_path):
        raise HTTPException(404, f"File not found: {path}")

    if os.path.isdir(full_path):
        # Return directory listing as JSON
        items = []
        for entry in os.scandir(full_path):
            items.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None,
            })
        return {"path": path, "items": items}

    # Stream the file (important for large WIMs)
    return FileResponse(
        full_path,
        filename=os.path.basename(full_path),
        media_type="application/octet-stream",
    )
