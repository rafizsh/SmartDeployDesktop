"""
PowerShell execution utility.
Wraps subprocess calls to PowerShell for DISM, diskpart, and other Windows tools.
"""

import asyncio
import subprocess
import logging
import json
from typing import Optional

logger = logging.getLogger("smartdeploy.powershell")


class PowerShellResult:
    """Result of a PowerShell command execution."""

    def __init__(self, return_code: int, stdout: str, stderr: str, command: str):
        self.return_code = return_code
        self.stdout = stdout.strip()
        self.stderr = stderr.strip()
        self.command = command
        self.success = return_code == 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "command": self.command,
        }


async def run_powershell(command: str, timeout: int = 300, run_as_admin: bool = False) -> PowerShellResult:
    """
    Execute a PowerShell command asynchronously.

    Args:
        command: PowerShell command string to execute.
        timeout: Timeout in seconds (default 5 minutes).
        run_as_admin: Whether the command needs elevation (logged, not enforced here).

    Returns:
        PowerShellResult with output and status.
    """
    if run_as_admin:
        logger.info(f"[ADMIN] Executing: {command[:120]}...")
    else:
        logger.info(f"Executing: {command[:120]}...")

    try:
        process = await asyncio.create_subprocess_exec(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-Command", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        result = PowerShellResult(
            return_code=process.returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            command=command,
        )

        if not result.success:
            logger.warning(f"Command failed (rc={result.return_code}): {result.stderr[:200]}")
        else:
            logger.debug(f"Command succeeded: {result.stdout[:200]}")

        return result

    except asyncio.TimeoutError:
        logger.error(f"Command timed out after {timeout}s: {command[:80]}")
        return PowerShellResult(return_code=-1, stdout="", stderr=f"Timeout after {timeout} seconds", command=command)
    except FileNotFoundError:
        logger.error("powershell.exe not found on this system")
        return PowerShellResult(return_code=-2, stdout="", stderr="PowerShell not found", command=command)
    except Exception as e:
        logger.error(f"Unexpected error executing PowerShell: {e}")
        return PowerShellResult(return_code=-3, stdout="", stderr=str(e), command=command)


async def run_powershell_script(
    script_path: str,
    script_args: list[str],
    timeout: int = 300,
) -> PowerShellResult:
    """
    Run a .ps1 script via powershell -File with argv-style arguments.

    Prefer this over run_powershell(-Command ...) when passing paths or secrets:
    -Command can mangle backslashes (e.g. PostgreSQL\\16 -> wrong tokens) and
    break on quotes inside passwords.
    """
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script_path,
        *script_args,
    ]
    display = f"-File {script_path} ({len(script_args)} args)"
    logger.info(f"Executing: {display[:160]}...")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        rc = process.returncode
        if rc is None:
            rc = -1
        result = PowerShellResult(
            return_code=rc,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            command=display,
        )
        if not result.success:
            logger.warning(f"Script failed (rc={result.return_code}): {result.stderr[:300]}")
        return result
    except asyncio.TimeoutError:
        logger.error(f"Script timed out after {timeout}s: {script_path}")
        return PowerShellResult(
            return_code=-1, stdout="", stderr=f"Timeout after {timeout} seconds", command=display
        )
    except FileNotFoundError:
        return PowerShellResult(return_code=-2, stdout="", stderr="PowerShell not found", command=display)
    except Exception as e:
        logger.error(f"Unexpected error running script: {e}")
        return PowerShellResult(return_code=-3, stdout="", stderr=str(e), command=display)


async def run_powershell_json(command: str, timeout: int = 300) -> Optional[dict]:
    """
    Execute a PowerShell command that returns JSON (via ConvertTo-Json).
    Parses and returns the JSON object, or None on failure.
    """
    json_command = f"{command} | ConvertTo-Json -Depth 5"
    result = await run_powershell(json_command, timeout=timeout)

    if result.success and result.stdout:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON output: {e}")
            return None
    return None


async def run_dism(args: str, timeout: int = 600) -> PowerShellResult:
    """
    Execute a DISM command.
    Wraps the DISM.exe call with common parameters.
    """
    command = f"DISM.exe {args}"
    return await run_powershell(command, timeout=timeout, run_as_admin=True)


async def run_diskpart(script_lines: list[str], timeout: int = 120) -> PowerShellResult:
    """
    Execute a diskpart script.
    Creates a temporary script file, runs diskpart against it.
    """
    import tempfile
    script_content = "\n".join(script_lines)

    command = f"""
$scriptFile = [System.IO.Path]::GetTempFileName()
Set-Content -Path $scriptFile -Value @'
{script_content}
'@
$result = diskpart /s $scriptFile 2>&1
Remove-Item $scriptFile -Force
$result
"""
    return await run_powershell(command, timeout=timeout, run_as_admin=True)
