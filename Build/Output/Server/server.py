"""
SmartDeploy Desktop Server - FastAPI Backend
Provides REST API for Windows imaging, deployment, and management operations.
Runs on localhost:8000, launched by the WPF executable.
"""

import os
import sys
import json
import logging
import signal
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routes import images, platform_packs, deployment, dism, task_sequences, hardware, dashboard, settings, pipeline, files
from routes import db as db_routes
from services.config_service import ConfigService
from utils.logger import setup_logging

# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    setup_logging()
    logger = logging.getLogger("smartdeploy")
    logger.info("SmartDeploy Server starting on http://localhost:8000")

    # Load configuration
    config = ConfigService()
    config.load()
    app.state.config = config

    # Ensure working directories exist
    for d in [config.image_store, config.platform_pack_store, config.mount_dir,
              config.log_dir, config.task_sequence_dir, config.answer_file_dir,
              config.driver_store]:
        os.makedirs(d, exist_ok=True)
        logger.info(f"Directory ready: {d}")

    # Try to connect to PostgreSQL (non-fatal if not configured)
    await db_routes.try_init_db()

    yield

    # Shutdown: close database pool
    try:
        from database import close_pool
        await close_pool()
    except Exception:
        pass

    logger.info("SmartDeploy Server shutting down")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SmartDeploy Desktop API",
    description="Windows Imaging & Deployment Management API",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the WPF app to connect from localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register route modules
# ---------------------------------------------------------------------------

app.include_router(images.router,          prefix="/api/images",          tags=["Images"])
app.include_router(platform_packs.router,  prefix="/api/platform-packs",  tags=["Platform Packs"])
app.include_router(deployment.router,      prefix="/api/deploy",          tags=["Deployment"])
app.include_router(dism.router,            prefix="/api/dism",            tags=["DISM Operations"])
app.include_router(task_sequences.router,  prefix="/api/task-sequences",  tags=["Task Sequences"])
app.include_router(hardware.router,        prefix="/api/hardware",        tags=["Hardware"])
app.include_router(dashboard.router,       prefix="/api/dashboard",       tags=["Dashboard"])
app.include_router(settings.router,        prefix="/api/settings",        tags=["Infrastructure Settings"])
app.include_router(pipeline.router,        prefix="/api/pipeline",        tags=["Deployment Pipeline"])
app.include_router(db_routes.router,       prefix="/api/db",              tags=["Database"])
app.include_router(files.router,           prefix="/api",                 tags=["Files"])


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check():
    return {"status": "running", "version": "1.0.0", "service": "SmartDeploy Desktop Server"}


@app.get("/api/debug/paths")
async def debug_paths():
    """Show all configured paths and whether they exist/are writable."""
    config = app.state.config
    paths = {
        "image_store": config.image_store,
        "platform_pack_store": config.platform_pack_store,
        "mount_dir": config.mount_dir,
        "log_dir": config.log_dir,
        "task_sequence_dir": config.task_sequence_dir,
        "answer_file_dir": config.answer_file_dir,
        "driver_store": config.driver_store,
    }
    result = {}
    for name, path in paths.items():
        exists = os.path.exists(path)
        writable = False
        file_count = 0
        if exists:
            try:
                test_file = os.path.join(path, ".write_test")
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
                writable = True
            except Exception:
                pass
            try:
                file_count = len(os.listdir(path))
            except Exception:
                pass
        result[name] = {"path": path, "exists": exists, "writable": writable, "files": file_count}
    return result


@app.get("/")
async def root():
    return {"message": "SmartDeploy Desktop API", "docs": "/docs"}


# ---------------------------------------------------------------------------
# Graceful shutdown on SIGTERM from WPF parent process
# ---------------------------------------------------------------------------

def handle_sigterm(signum, frame):
    logging.getLogger("smartdeploy").info("Received SIGTERM, shutting down...")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import multiprocessing

    # Desktop (WPF-launched) on Windows: use a single worker by default. Multi-worker
    # Uvicorn + multiprocessing is flaky with redirected stdio and delays /api/health,
    # which makes the UI look frozen or "not functional". Override with:
    #   set SMARTDEPLOY_UVICORN_WORKERS=4
    if sys.platform == "win32":
        default_workers = 1
    else:
        default_workers = min(multiprocessing.cpu_count(), 4)
    workers = int(os.environ.get("SMARTDEPLOY_UVICORN_WORKERS", str(default_workers)))
    workers = max(1, min(workers, 32))

    uvicorn.run(
        "server:app",
        host="0.0.0.0",        # Listen on ALL interfaces (needed for WinPE clients on 10.10.10.x)
        port=8000,
        log_level="info",
        reload=False,
        workers=workers,
        limit_concurrency=100,  # Max simultaneous connections
        timeout_keep_alive=30,  # Keep connections alive for polling
    )
