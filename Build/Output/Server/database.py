"""
SmartDeploy PostgreSQL Database Setup and Schema.
Handles automated PostgreSQL installation, database creation, and schema migration.
"""

import os
import sys
import json
import logging
import subprocess
import asyncio
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger("smartdeploy.database")

# ============================================================================
# Schema Definition
# ============================================================================

SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- SmartDeploy Database Schema v1

-- Deployment history
CREATE TABLE IF NOT EXISTS deployments (
    id SERIAL PRIMARY KEY,
    pipeline_id VARCHAR(64) UNIQUE NOT NULL,
    mac_address VARCHAR(20) NOT NULL,
    ip_address VARCHAR(45),
    hostname VARCHAR(255),
    computer_name VARCHAR(255),
    image_path TEXT,
    image_index INTEGER DEFAULT 1,
    task_sequence_id VARCHAR(64),
    unattend_path TEXT,
    status VARCHAR(32) DEFAULT 'pending',
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 7,
    phase VARCHAR(32) DEFAULT 'init',
    progress INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_deployments_mac ON deployments(mac_address);
CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status);
CREATE INDEX IF NOT EXISTS idx_deployments_started ON deployments(started_at DESC);

-- PXE client registry
CREATE TABLE IF NOT EXISTS pxe_clients (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(20) UNIQUE NOT NULL,
    ip_address VARCHAR(45),
    hostname VARCHAR(255),
    status VARCHAR(32) DEFAULT 'discovered',
    current_step VARCHAR(255),
    progress INTEGER DEFAULT 0,
    pipeline_id VARCHAR(64),
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_pxe_clients_mac ON pxe_clients(mac_address);
CREATE INDEX IF NOT EXISTS idx_pxe_clients_last_seen ON pxe_clients(last_seen DESC);

-- PXE client events
CREATE TABLE IF NOT EXISTS client_events (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(20) NOT NULL,
    ip_address VARCHAR(45),
    event_type VARCHAR(64) NOT NULL,
    detail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_client_events_mac ON client_events(mac_address);
CREATE INDEX IF NOT EXISTS idx_client_events_time ON client_events(created_at DESC);

-- Task sequences
CREATE TABLE IF NOT EXISTS task_sequences (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    os_version VARCHAR(128) DEFAULT 'Windows 11 Pro',
    architecture VARCHAR(16) DEFAULT 'x64',
    template VARCHAR(64),
    steps JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Answer files
CREATE TABLE IF NOT EXISTS answer_files (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    content TEXT,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Infrastructure settings
CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(128) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- WIM images metadata
CREATE TABLE IF NOT EXISTS images (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    path TEXT NOT NULL,
    size_bytes BIGINT DEFAULT 0,
    format VARCHAR(16) DEFAULT 'wim',
    architecture VARCHAR(16) DEFAULT 'x64',
    os_version VARCHAR(128),
    image_count INTEGER DEFAULT 0,
    indexes JSONB DEFAULT '[]',
    hash_sha256 VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_images_name ON images(name);

-- Server logs
CREATE TABLE IF NOT EXISTS server_logs (
    id SERIAL PRIMARY KEY,
    level VARCHAR(16) NOT NULL,
    source VARCHAR(128),
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_time ON server_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_level ON server_logs(level);

-- DHCP leases
CREATE TABLE IF NOT EXISTS dhcp_leases (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(20) NOT NULL,
    ip_address VARCHAR(45) NOT NULL,
    hostname VARCHAR(255),
    scope_name VARCHAR(128),
    lease_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    lease_end TIMESTAMP,
    active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_dhcp_leases_mac ON dhcp_leases(mac_address);
CREATE INDEX IF NOT EXISTS idx_dhcp_leases_active ON dhcp_leases(active);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO schema_version (version) VALUES (1) ON CONFLICT (version) DO NOTHING;
"""


# ============================================================================
# Database Connection
# ============================================================================

class DatabaseConfig:
    """PostgreSQL connection configuration."""
    def __init__(self):
        self.host = os.environ.get("SMARTDEPLOY_DB_HOST", "localhost")
        self.port = int(os.environ.get("SMARTDEPLOY_DB_PORT", "5432"))
        self.database = os.environ.get("SMARTDEPLOY_DB_NAME", "smartdeploy")
        self.user = os.environ.get("SMARTDEPLOY_DB_USER", "smartdeploy")
        self.password = os.environ.get("SMARTDEPLOY_DB_PASSWORD", "SmartDeploy2026!")
        self.config_path = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "SmartDeployDesktop", "db_config.json"
        )
        self._load_config()

    def _load_config(self):
        """Load config from file if it exists."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    cfg = json.load(f)
                self.host = cfg.get("host", self.host)
                self.port = cfg.get("port", self.port)
                self.database = cfg.get("database", self.database)
                self.user = cfg.get("user", self.user)
                self.password = cfg.get("password", self.password)
            except Exception:
                pass

    def save_config(self):
        """Save current config to file."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump({
                "host": self.host,
                "port": self.port,
                "database": self.database,
                "user": self.user,
                "password": self.password,
            }, f, indent=2)

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def dsn_no_db(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/postgres"


# ============================================================================
# Database Manager
# ============================================================================

_db_pool = None


async def _create_pool_for_config(config: DatabaseConfig):
    """Open a new asyncpg pool for the given configuration (does not assign globals)."""
    import asyncpg

    return await asyncpg.create_pool(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        min_size=1,
        max_size=20,
        command_timeout=60,
        timeout=15.0,
    )


async def get_pool():
    """Get or create the connection pool."""
    global _db_pool
    if _db_pool is None:
        try:
            config = DatabaseConfig()
            _db_pool = await _create_pool_for_config(config)
            logger.info(f"Database pool created: {config.host}:{config.port}/{config.database}")
        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise
    return _db_pool


async def rebind_pool(config: DatabaseConfig):
    """Close the global pool and open a new one using explicit settings (e.g. from the UI)."""
    global _db_pool
    await close_pool()
    try:
        _db_pool = await _create_pool_for_config(config)
        logger.info(f"Database pool rebound: {config.host}:{config.port}/{config.database}")
    except Exception as e:
        logger.error(f"Failed to rebind database pool: {e}")
        raise


async def close_pool():
    """Close the connection pool."""
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None


async def init_schema():
    """Initialize the database schema."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Database schema initialized")


async def check_connection() -> dict:
    """Check database connectivity and return status."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            tables = await conn.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
            )
            deployments = await conn.fetchval("SELECT count(*) FROM deployments")
            clients = await conn.fetchval("SELECT count(*) FROM pxe_clients")
        return {
            "connected": True,
            "version": version.split(",")[0] if version else "unknown",
            "tables": tables,
            "deployments": deployments,
            "clients": clients,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ============================================================================
# PostgreSQL Installer (Windows)
# ============================================================================

POSTGRES_VERSION = "16"
POSTGRES_INSTALLER_URL = f"https://get.enterprisedb.com/postgresql/postgresql-{POSTGRES_VERSION}.2-1-windows-x64.exe"
POSTGRES_DEFAULT_DIR = r"C:\Program Files\PostgreSQL\16"


def is_postgres_installed() -> bool:
    """Check if PostgreSQL is installed."""
    # Check default install location
    if os.path.exists(os.path.join(POSTGRES_DEFAULT_DIR, "bin", "psql.exe")):
        return True
    # Check PATH
    try:
        result = subprocess.run(["psql", "--version"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def is_postgres_running() -> bool:
    """Check if PostgreSQL service is running."""
    try:
        result = subprocess.run(
            ["sc", "query", f"postgresql-x64-{POSTGRES_VERSION}"],
            capture_output=True, text=True, timeout=5
        )
        return "RUNNING" in result.stdout
    except Exception:
        return False


def get_psql_path() -> str:
    """Get path to psql.exe."""
    default = os.path.join(POSTGRES_DEFAULT_DIR, "bin", "psql.exe")
    if os.path.exists(default):
        return default
    # Try PATH
    try:
        result = subprocess.run(["where", "psql"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return "psql"


def setup_database(config: DatabaseConfig = None) -> dict:
    """
    Full automated PostgreSQL setup:
    1. Check if PostgreSQL is installed
    2. Install if needed (silent install)
    3. Create database and user
    4. Initialize schema
    Returns status dict with steps completed.
    """
    if config is None:
        config = DatabaseConfig()

    log = []

    # Step 1: Check installation
    log.append("Checking PostgreSQL installation...")
    if is_postgres_installed():
        log.append(f"  PostgreSQL found at {POSTGRES_DEFAULT_DIR}")
    else:
        log.append("  PostgreSQL NOT installed")
        log.append("  Please install PostgreSQL 16 from: https://www.postgresql.org/download/windows/")
        log.append(f"  Or download directly: {POSTGRES_INSTALLER_URL}")
        log.append("")
        log.append("  After installing, run this setup again.")
        return {"success": False, "log": log, "step": "install"}

    # Step 2: Check service
    log.append("Checking PostgreSQL service...")
    if is_postgres_running():
        log.append(f"  Service postgresql-x64-{POSTGRES_VERSION} is RUNNING")
    else:
        log.append(f"  Service not running. Starting...")
        try:
            subprocess.run(
                ["net", "start", f"postgresql-x64-{POSTGRES_VERSION}"],
                capture_output=True, timeout=30
            )
            if is_postgres_running():
                log.append("  Service started successfully")
            else:
                log.append("  Failed to start service. Start it manually:")
                log.append(f"    net start postgresql-x64-{POSTGRES_VERSION}")
                return {"success": False, "log": log, "step": "service"}
        except Exception as e:
            log.append(f"  Error: {e}")
            return {"success": False, "log": log, "step": "service"}

    # Step 3: Create user and database
    psql = get_psql_path()
    log.append("Creating database user and database...")

    # Create user
    create_user_sql = (
        f"DO $$ BEGIN "
        f"  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{config.user}') THEN "
        f"    CREATE ROLE {config.user} WITH LOGIN PASSWORD '{config.password}'; "
        f"  END IF; "
        f"END $$;"
    )
    try:
        result = subprocess.run(
            [psql, "-U", "postgres", "-h", config.host, "-p", str(config.port), "-c", create_user_sql],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PGPASSWORD": "postgres"}  # Default postgres superuser password
        )
        if result.returncode == 0:
            log.append(f"  User '{config.user}' ready")
        else:
            log.append(f"  User creation: {result.stderr.strip()}")
    except Exception as e:
        log.append(f"  Error creating user: {e}")
        log.append("  You may need to set the postgres superuser password first:")
        log.append(f'    "{psql}" -U postgres -c "ALTER USER postgres PASSWORD \'postgres\';"')

    # Create database
    try:
        result = subprocess.run(
            [psql, "-U", "postgres", "-h", config.host, "-p", str(config.port),
             "-c", f"SELECT 1 FROM pg_database WHERE datname = '{config.database}'"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PGPASSWORD": "postgres"}
        )
        if config.database not in result.stdout:
            subprocess.run(
                [psql, "-U", "postgres", "-h", config.host, "-p", str(config.port),
                 "-c", f"CREATE DATABASE {config.database} OWNER {config.user}"],
                capture_output=True, text=True, timeout=10,
                env={**os.environ, "PGPASSWORD": "postgres"}
            )
            log.append(f"  Database '{config.database}' created")
        else:
            log.append(f"  Database '{config.database}' already exists")
    except Exception as e:
        log.append(f"  Error creating database: {e}")

    # Grant privileges
    try:
        subprocess.run(
            [psql, "-U", "postgres", "-h", config.host, "-p", str(config.port),
             "-c", f"GRANT ALL PRIVILEGES ON DATABASE {config.database} TO {config.user}"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PGPASSWORD": "postgres"}
        )
    except Exception:
        pass

    # Step 4: Initialize schema
    log.append("Initializing database schema...")
    try:
        result = subprocess.run(
            [psql, "-U", config.user, "-h", config.host, "-p", str(config.port),
             "-d", config.database, "-c", SCHEMA_SQL],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PGPASSWORD": config.password}
        )
        if result.returncode == 0:
            log.append("  Schema initialized successfully")
        else:
            log.append(f"  Schema error: {result.stderr.strip()[:200]}")
    except Exception as e:
        log.append(f"  Error: {e}")

    # Save config
    config.save_config()
    log.append(f"Config saved to {config.config_path}")

    log.append("")
    log.append("PostgreSQL setup complete!")
    return {"success": True, "log": log}


# ============================================================================
# Convenience query functions
# ============================================================================

async def insert_deployment(data: dict) -> int:
    """Insert a new deployment record."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO deployments (pipeline_id, mac_address, ip_address, hostname, image_path, 
                                     image_index, task_sequence_id, status, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, data.get("pipeline_id"), data.get("mac_address"), data.get("ip_address"),
            data.get("hostname"), data.get("image_path"), data.get("image_index", 1),
            data.get("task_sequence_id"), data.get("status", "pending"),
            json.dumps(data.get("metadata", {})))


async def update_deployment_status(pipeline_id: str, status: str, step: int = None,
                                    progress: int = None, error: str = None):
    """Update deployment status."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        sets = ["status = $2", "updated_at = CURRENT_TIMESTAMP"]
        params = [pipeline_id, status]
        idx = 3
        if step is not None:
            sets.append(f"current_step = ${idx}")
            params.append(step)
            idx += 1
        if progress is not None:
            sets.append(f"progress = ${idx}")
            params.append(progress)
            idx += 1
        if error:
            sets.append(f"error_message = ${idx}")
            params.append(error)
            idx += 1
        if status == "completed":
            sets.append("completed_at = CURRENT_TIMESTAMP")

        await conn.execute(
            f"UPDATE deployments SET {', '.join(sets)} WHERE pipeline_id = $1",
            *params
        )


async def upsert_pxe_client(mac: str, ip: str = None, hostname: str = None,
                             status: str = None, step: str = None, progress: int = None):
    """Insert or update a PXE client."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO pxe_clients (mac_address, ip_address, hostname, status, current_step, progress)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (mac_address) DO UPDATE SET
                ip_address = COALESCE($2, pxe_clients.ip_address),
                hostname = COALESCE($3, pxe_clients.hostname),
                status = COALESCE($4, pxe_clients.status),
                current_step = COALESCE($5, pxe_clients.current_step),
                progress = COALESCE($6, pxe_clients.progress),
                last_seen = CURRENT_TIMESTAMP
        """, mac, ip, hostname, status, step, progress)


async def insert_client_event(mac: str, ip: str, event_type: str, detail: str):
    """Log a client event."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO client_events (mac_address, ip_address, event_type, detail)
            VALUES ($1, $2, $3, $4)
        """, mac, ip, event_type, detail)


async def get_recent_deployments(limit: int = 50) -> list:
    """Get recent deployments."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM deployments ORDER BY started_at DESC LIMIT $1", limit
        )
        return [dict(r) for r in rows]


async def get_all_clients() -> list:
    """Get all PXE clients."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM pxe_clients ORDER BY last_seen DESC"
        )
        return [dict(r) for r in rows]


async def get_client_events(mac: str, limit: int = 50) -> list:
    """Get events for a specific client."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM client_events WHERE mac_address = $1 ORDER BY created_at DESC LIMIT $2",
            mac, limit
        )
        return [dict(r) for r in rows]


async def insert_log(level: str, source: str, message: str, metadata: dict = None):
    """Insert a server log entry."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO server_logs (level, source, message, metadata)
            VALUES ($1, $2, $3, $4)
        """, level, source, message, json.dumps(metadata or {}))
