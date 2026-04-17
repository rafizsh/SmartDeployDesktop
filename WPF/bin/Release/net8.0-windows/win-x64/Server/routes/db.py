"""
Database management API routes.
Handles PostgreSQL setup, health checks, and admin queries.
"""

import os
import json
import logging
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger("smartdeploy.db")

# Flag: is the database available?
_db_available = False


class DbSetupRequest(BaseModel):
    postgres_password: str = "postgres"
    db_name: str = "smartdeploy"
    db_user: str = "smartdeploy"
    db_password: str = "SmartDeploy2026!"
    model_config = {"extra": "allow"}


class DbConnectionConfig(BaseModel):
    """Connection settings written to %LOCALAPPDATA%\\SmartDeployDesktop\\db_config.json"""

    host: str = "localhost"
    port: int = 5432
    database: str = "smartdeploy"
    user: str = "smartdeploy"
    password: str = "SmartDeploy2026!"
    model_config = {"extra": "allow"}


async def try_init_db():
    """Try to initialize the database connection on startup. Non-fatal if it fails."""
    global _db_available

    async def _connect_and_schema():
        from database import get_pool, init_schema

        await get_pool()
        await init_schema()

    try:
        from database import DatabaseConfig, close_pool

        config = DatabaseConfig()
        if not os.path.exists(config.config_path):
            logger.info(
                "No db_config.json at %s — use Settings → Database → Save configuration, "
                "or run Setup PostgreSQL.",
                config.config_path,
            )
            return
        # Do not block API startup if PostgreSQL is slow or wedged (keeps WPF usable).
        try:
            await asyncio.wait_for(_connect_and_schema(), timeout=20.0)
        except asyncio.TimeoutError:
            logger.info(
                "Database init timed out after 20s — API will start without DB; "
                "fix PostgreSQL or db_config.json and use Test Connection in Settings."
            )
            try:
                await close_pool()
            except Exception:
                pass
            return
        _db_available = True
        logger.info("PostgreSQL database connected and schema ready")
    except ImportError:
        logger.info("asyncpg not installed — database features disabled")
    except Exception as e:
        logger.info(f"Database not available: {e} — file-backed stores will be used")


def is_db_available() -> bool:
    return _db_available


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/status")
async def db_status():
    """Check database connection status."""
    if not _db_available:
        # Check if config exists
        app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        config_path = os.path.join(app_data, "SmartDeployDesktop", "db_config.json")
        config_exists = os.path.exists(config_path)
        return {
            "connected": False,
            "configured": config_exists,
            "config_path": config_path,
            "message": (
                "Database not connected. Save configuration (creates db_config.json) or run Setup PostgreSQL."
                if not config_exists
                else "Database not connected. Check host, credentials, and that PostgreSQL is running."
            ),
        }

    try:
        from database import check_connection
        status = await check_connection()
        return status
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.post("/setup")
async def setup_database(req: DbSetupRequest):
    """
    Run the PostgreSQL setup process.
    Checks installation, creates user/database, initializes schema.
    """
    global _db_available

    from utils.powershell import run_powershell_script
    log = []

    # Find the setup script
    server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    setup_script = os.path.join(server_dir, "setup_postgres.ps1")

    if not os.path.exists(setup_script):
        # Try relative to the routes folder
        setup_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup_postgres.ps1")

    if not os.path.exists(setup_script):
        return {
            "success": False,
            "log": ["setup_postgres.ps1 not found"],
            "message": "Setup script missing"
        }

    log.append("Running PostgreSQL setup...")
    log.append(f"Script: {setup_script}")

    # Run the PowerShell setup script (-File + argv avoids -Command mangling paths like PostgreSQL\16)
    result = await run_powershell_script(
        setup_script,
        [
            "-PostgresPassword",
            req.postgres_password,
            "-DbName",
            req.db_name,
            "-DbUser",
            req.db_user,
            "-DbPassword",
            req.db_password,
        ],
        timeout=900,  # download + silent install can exceed 5 minutes
    )

    if result.stdout:
        for line in result.stdout.strip().splitlines():
            log.append(line)

    if result.stderr:
        for line in result.stderr.strip().splitlines():
            if line.strip():
                log.append(f"WARN: {line}")

    if not result.success:
        log.append("")
        log.append(
            f"PostgreSQL setup script exited with code {result.return_code}. "
            "If you are installing PostgreSQL for the first time, run SmartDeploy Desktop as Administrator "
            "and try again."
        )
        return {
            "success": False,
            "log": log,
            "message": "PostgreSQL setup script failed — see log for details",
        }

    # Try connecting
    log.append("")
    log.append("Testing database connection...")
    try:
        from database import DatabaseConfig, get_pool, init_schema, close_pool

        # Reload config
        config = DatabaseConfig()
        config.host = "localhost"
        config.port = 5432
        config.database = req.db_name
        config.user = req.db_user
        config.password = req.db_password
        config.save_config()

        # Reset pool to pick up new config
        await close_pool()
        pool = await get_pool()
        await init_schema()
        _db_available = True

        log.append("Database connection successful!")
        log.append("Schema initialized.")
        return {
            "success": True,
            "log": log,
            "message": "PostgreSQL setup complete"
        }
    except ImportError:
        log.append("asyncpg not installed. Run: pip install asyncpg")
        return {"success": False, "log": log, "message": "asyncpg not installed"}
    except Exception as e:
        log.append(f"Connection failed: {e}")
        return {
            "success": False,
            "log": log,
            "message": f"Setup ran but connection failed: {e}"
        }


@router.post("/config")
async def save_db_config(req: DbConnectionConfig):
    """
    Write db_config.json from the request body (no PowerShell / install).
    Use this for an existing PostgreSQL server or after manual install.
    """
    global _db_available
    try:
        from database import DatabaseConfig, close_pool

        config = DatabaseConfig()
        config.host = req.host.strip() or "localhost"
        config.port = int(req.port)
        config.database = req.database.strip() or "smartdeploy"
        config.user = req.user.strip() or "smartdeploy"
        config.password = req.password
        config.save_config()
        await close_pool()
        _db_available = False
        logger.info("db_config.json saved to %s", config.config_path)
        return {
            "success": True,
            "path": config.config_path,
            "message": f"Saved database configuration to {config.config_path}",
        }
    except Exception as e:
        logger.warning("save_db_config failed: %s", e)
        return {"success": False, "message": str(e), "path": None}


@router.post("/test")
async def test_connection(req: DbConnectionConfig):
    """
    Test PostgreSQL using the request body (same fields as Save configuration).
    Avoids relying on db_config.json matching what is typed in the UI.
    """
    global _db_available
    try:
        from database import DatabaseConfig, init_schema, check_connection, close_pool, rebind_pool

        config = DatabaseConfig()
        config.host = (req.host or "").strip() or "localhost"
        config.port = int(req.port)
        config.database = (req.database or "").strip() or "smartdeploy"
        config.user = (req.user or "").strip() or "smartdeploy"
        config.password = req.password

        await close_pool()
        await rebind_pool(config)
        await init_schema()
        status = await check_connection()
        _db_available = status.get("connected", False)
        return status
    except ImportError:
        return {"connected": False, "error": "asyncpg not installed"}
    except Exception as e:
        logger.warning("db test failed: %s", e)
        return {"connected": False, "error": str(e)}


@router.get("/deployments")
async def get_deployments(limit: int = 50):
    """Get deployment history from database."""
    if not _db_available:
        raise HTTPException(503, "Database not available")
    try:
        from database import get_recent_deployments
        rows = await get_recent_deployments(limit)
        # Convert datetime objects to strings
        for row in rows:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()
        return {"deployments": rows}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/clients")
async def get_clients():
    """Get all PXE clients from database."""
    if not _db_available:
        raise HTTPException(503, "Database not available")
    try:
        from database import get_all_clients
        rows = await get_all_clients()
        for row in rows:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()
        return {"clients": rows}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/events/{mac}")
async def get_events(mac: str, limit: int = 50):
    """Get events for a specific PXE client."""
    if not _db_available:
        raise HTTPException(503, "Database not available")
    try:
        from database import get_client_events
        rows = await get_client_events(mac, limit)
        for row in rows:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()
        return {"events": rows}
    except Exception as e:
        raise HTTPException(500, str(e))
