"""
Infrastructure Settings routes.
Manages Active Directory, DHCP, TFTP/PXE, UNC shares, WDS, and MDT configuration.
Provides validation endpoints for testing connectivity to each service.
"""

import os
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from utils.powershell import run_powershell, run_powershell_json

router = APIRouter()
logger = logging.getLogger("smartdeploy.settings")


# ============================================================================
# Settings Models
# ============================================================================

class _LenientModel(BaseModel):
    """Base model that accepts extra fields and populates by field name."""
    model_config = {"extra": "allow", "populate_by_name": True}


class ActiveDirectorySettings(_LenientModel):
    """Active Directory / Domain join configuration."""
    enabled: bool = False
    domain_name: str = ""
    domain_controller: str = ""
    default_ou: str = ""
    ou_targets: List[dict] = []
    join_account_username: str = ""
    join_account_password: str = ""
    machine_naming_template: str = "%PREFIX%-%SERIAL:8%"
    machine_name_prefix: str = "WS"
    ldap_port: int = 389
    ldaps_port: int = 636
    use_ldaps: bool = False
    search_base: str = ""
    computer_group: str = ""


class DHCPSettings(_LenientModel):
    """DHCP server and scope configuration."""
    enabled: bool = False
    dhcp_server: str = ""
    scopes: List[dict] = []
    pxe_boot_options: dict = Field(default_factory=lambda: {
        "option_66": "",
        "option_67": "",
        "option_60": "PXEClient",
    })
    reservations: List[dict] = []
    dns_servers: List[str] = []
    default_gateway: str = ""
    domain_suffix: str = ""


class TFTPPXESettings(_LenientModel):
    """TFTP and PXE Boot Server configuration."""
    enabled: bool = False
    tftp_server: str = ""
    tftp_root_path: str = ""
    boot_image_path: str = ""
    boot_file_x64: str = "boot\\x64\\wdsnbp.com"
    boot_file_bios: str = "boot\\x86\\wdsnbp.com"
    boot_file_uefi_http: str = ""
    architecture: str = "Both"
    pxe_prompt_policy: str = "OptIn"
    pxe_prompt_timeout: int = 5
    multicast_enabled: bool = False
    multicast_range_start: str = ""
    multicast_range_end: str = ""
    bandwidth_throttle_kbps: int = 0


class UNCMountSettings(_LenientModel):
    """UNC Network Share mount point configuration."""
    shares: List[dict] = []
    default_credentials_username: str = ""
    default_credentials_password: str = ""
    default_credentials_domain: str = ""
    share_images: str = ""
    share_drivers: str = ""
    share_deployment: str = ""
    share_capture: str = ""
    share_logs: str = ""


class WDSSettings(_LenientModel):
    """Windows Deployment Services configuration."""
    enabled: bool = False
    wds_server: str = ""
    remote_install_path: str = ""
    respond_to_all_clients: bool = False
    respond_only_known: bool = True
    require_admin_approval: bool = False
    default_boot_image: str = ""
    install_images: List[dict] = []
    boot_images: List[dict] = []
    image_group: str = "Windows 11"
    multicast_namespace: str = ""
    auto_add_policy: str = "AdminApproval"
    prestaged_devices: List[dict] = []
    unattend_file_path: str = ""


class MDTSettings(_LenientModel):
    """Microsoft Deployment Toolkit configuration."""
    enabled: bool = False
    deployment_share_path: str = ""
    deployment_share_local: str = ""
    toolkit_path: str = ""
    monitoring_enabled: bool = False
    monitoring_host: str = ""
    monitoring_port: int = 9800
    database_enabled: bool = False
    database_server: str = ""
    database_name: str = "MDT"
    database_instance: str = ""
    rules_file_path: str = ""
    bootstrap_file_path: str = ""
    selection_profiles: List[str] = []
    linked_deployment_shares: List[dict] = []


class AllInfrastructureSettings(_LenientModel):
    """Complete infrastructure settings bundle."""
    active_directory: ActiveDirectorySettings = ActiveDirectorySettings()
    dhcp: DHCPSettings = DHCPSettings()
    tftp_pxe: TFTPPXESettings = TFTPPXESettings()
    unc_mounts: UNCMountSettings = UNCMountSettings()
    wds: WDSSettings = WDSSettings()
    mdt: MDTSettings = MDTSettings()


# ============================================================================
# Persistence helpers
# ============================================================================

def _get_settings_path() -> str:
    # Try multiple locations in order
    # 1. LOCALAPPDATA (standard Windows)
    app_data = os.environ.get("LOCALAPPDATA", "")
    if not app_data:
        # 2. APPDATA fallback
        app_data = os.environ.get("APPDATA", "")
    if not app_data:
        # 3. User home
        app_data = os.path.expanduser("~")

    settings_dir = os.path.join(app_data, "SmartDeployDesktop")
    os.makedirs(settings_dir, exist_ok=True)
    return os.path.join(settings_dir, "infrastructure.json")


def _load_settings() -> AllInfrastructureSettings:
    path = _get_settings_path()
    logger.info(f"Loading settings from: {path}")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            logger.info(f"Settings loaded successfully ({len(data)} keys)")
            return AllInfrastructureSettings(**data)
        except Exception as e:
            logger.warning(f"Failed to load infrastructure settings: {e}")
    else:
        logger.info(f"No settings file found at {path}")
    return AllInfrastructureSettings()


def _save_settings(settings: AllInfrastructureSettings):
    path = _get_settings_path()
    try:
        with open(path, "w") as f:
            json.dump(settings.model_dump(), f, indent=2)
        logger.info(f"Infrastructure settings saved to {path}")
    except Exception as e:
        logger.error(f"Failed to save settings to {path}: {e}")


@router.get("/debug/path")
async def get_settings_path():
    """Debug: show where settings are stored."""
    path = _get_settings_path()
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    return {
        "settings_path": path,
        "exists": exists,
        "size_bytes": size,
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", "NOT SET"),
        "APPDATA": os.environ.get("APPDATA", "NOT SET"),
        "user_home": os.path.expanduser("~"),
    }


# ============================================================================
# CRUD endpoints - Get / Update all settings
# ============================================================================

@router.get("/", response_model=AllInfrastructureSettings)
async def get_all_settings():
    """Get all infrastructure settings."""
    return _load_settings()


@router.put("/", response_model=AllInfrastructureSettings)
async def update_all_settings(settings: AllInfrastructureSettings):
    """Save all infrastructure settings at once."""
    _save_settings(settings)
    return settings


# ============================================================================
# Individual section endpoints
# ============================================================================

@router.get("/active-directory", response_model=ActiveDirectorySettings)
async def get_ad_settings():
    return _load_settings().active_directory

@router.put("/active-directory")
async def update_ad_settings(ad: ActiveDirectorySettings):
    settings = _load_settings()
    settings.active_directory = ad
    _save_settings(settings)
    return {"success": True, "message": "Active Directory settings updated"}


@router.get("/dhcp", response_model=DHCPSettings)
async def get_dhcp_settings():
    return _load_settings().dhcp

@router.put("/dhcp")
async def update_dhcp_settings(dhcp: DHCPSettings):
    settings = _load_settings()
    settings.dhcp = dhcp
    _save_settings(settings)
    return {"success": True, "message": "DHCP settings updated"}


@router.get("/tftp-pxe", response_model=TFTPPXESettings)
async def get_tftp_settings():
    return _load_settings().tftp_pxe

@router.put("/tftp-pxe")
async def update_tftp_settings(tftp: TFTPPXESettings):
    settings = _load_settings()
    settings.tftp_pxe = tftp
    _save_settings(settings)
    return {"success": True, "message": "TFTP/PXE settings updated"}


@router.get("/unc-mounts", response_model=UNCMountSettings)
async def get_unc_settings():
    return _load_settings().unc_mounts

@router.put("/unc-mounts")
async def update_unc_settings(unc: UNCMountSettings):
    settings = _load_settings()
    settings.unc_mounts = unc
    _save_settings(settings)
    return {"success": True, "message": "UNC mount settings updated"}


@router.get("/wds", response_model=WDSSettings)
async def get_wds_settings():
    return _load_settings().wds

@router.put("/wds")
async def update_wds_settings(wds: WDSSettings):
    settings = _load_settings()
    settings.wds = wds
    _save_settings(settings)
    return {"success": True, "message": "WDS settings updated"}


@router.get("/mdt", response_model=MDTSettings)
async def get_mdt_settings():
    return _load_settings().mdt

@router.put("/mdt")
async def update_mdt_settings(mdt: MDTSettings):
    settings = _load_settings()
    settings.mdt = mdt
    _save_settings(settings)
    return {"success": True, "message": "MDT settings updated"}


# ============================================================================
# Validation / Test Connection endpoints
# ============================================================================

@router.post("/test/active-directory")
async def test_ad_connection():
    """Test Active Directory connectivity and domain join capability."""
    settings = _load_settings().active_directory

    if not settings.domain_name:
        return {"success": False, "message": "No domain configured"}

    results = []
    target = settings.domain_controller or settings.domain_name

    # Test DNS resolution of domain
    dns_result = await run_powershell(
        f'Resolve-DnsName -Name "{settings.domain_name}" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty IPAddress'
    )
    results.append({
        "test": "DNS Resolution",
        "passed": dns_result.success and dns_result.stdout.strip() != "",
        "detail": dns_result.stdout.strip() if dns_result.success else dns_result.stderr[:100],
    })

    # Test DC connectivity
    if settings.domain_controller:
        dc_result = await run_powershell(
            f'Test-Connection -ComputerName "{settings.domain_controller}" -Count 1 -Quiet'
        )
        results.append({
            "test": "Domain Controller Ping",
            "passed": "true" in dc_result.stdout.lower(),
            "detail": settings.domain_controller,
        })

    # Test LDAP port
    port = settings.ldaps_port if settings.use_ldaps else settings.ldap_port
    ldap_result = await run_powershell(
        f'(New-Object System.Net.Sockets.TcpClient).Connect("{target}", {port}); "OK"'
    )
    results.append({
        "test": f"LDAP{'S' if settings.use_ldaps else ''} Port ({port})",
        "passed": "OK" in ldap_result.stdout,
        "detail": f"{target}:{port}",
    })

    # Build credential block for subsequent tests (escape special chars in password)
    cred_block = ""
    has_creds = settings.join_account_username and settings.join_account_password
    if has_creds:
        # Escape single quotes in password for PowerShell
        escaped_pw = settings.join_account_password.replace("'", "''")
        cred_block = (
            f"$secpw = ConvertTo-SecureString '{escaped_pw}' -AsPlainText -Force; "
            f"$cred = New-Object System.Management.Automation.PSCredential('{settings.join_account_username}', $secpw); "
        )

    # Test credentials if provided
    if has_creds:
        cred_result = await run_powershell(
            f'{cred_block}'
            f'Get-ADDomain -Server "{target}" -Credential $cred -ErrorAction Stop | Select-Object -ExpandProperty DNSRoot'
        )
        passed = cred_result.success and cred_result.stdout.strip() != ""
        results.append({
            "test": "Credential Validation",
            "passed": passed,
            "detail": "Authenticated successfully" if passed else cred_result.stderr[:200].strip(),
        })

    # Test OU path (use credentials if available)
    if settings.default_ou:
        if has_creds:
            ou_cmd = (
                f'{cred_block}'
                f'try {{ '
                f'  $ou = Get-ADOrganizationalUnit -Identity "{settings.default_ou}" -Server "{target}" -Credential $cred -ErrorAction Stop; '
                f'  $ou.Name '
                f'}} catch {{ '
                f'  try {{ '
                f'    $obj = Get-ADObject -Identity "{settings.default_ou}" -Server "{target}" -Credential $cred -ErrorAction Stop; '
                f'    $obj.Name '
                f'  }} catch {{ '
                f'    "NOT_FOUND:$($_.Exception.Message)" '
                f'  }} '
                f'}}'
            )
        else:
            ou_cmd = (
                f'try {{ '
                f'  $ou = Get-ADOrganizationalUnit -Identity "{settings.default_ou}" -Server "{target}" -ErrorAction Stop; '
                f'  $ou.Name '
                f'}} catch {{ '
                f'  try {{ '
                f'    $obj = Get-ADObject -Identity "{settings.default_ou}" -Server "{target}" -ErrorAction Stop; '
                f'    $obj.Name '
                f'  }} catch {{ '
                f'    "NOT_FOUND:$($_.Exception.Message)" '
                f'  }} '
                f'}}'
            )

        ou_result = await run_powershell(ou_cmd)
        found = ou_result.success and ou_result.stdout.strip() != "" and "NOT_FOUND" not in ou_result.stdout
        detail = settings.default_ou if found else ou_result.stdout.replace("NOT_FOUND:", "").strip()[:200]
        if not detail:
            detail = ou_result.stderr[:200].strip() if ou_result.stderr else "OU not found"
        results.append({
            "test": "Default OU Exists",
            "passed": found,
            "detail": detail,
        })

    all_passed = all(r["passed"] for r in results)
    return {"success": all_passed, "results": results}


@router.post("/test/dhcp")
async def test_dhcp_connection():
    """Test DHCP server connectivity."""
    settings = _load_settings().dhcp
    results = []

    # 1. Check SmartDeploy's own DHCP server (port 8001)
    import urllib.request
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8001/status", timeout=3)
        data = json.loads(req.read().decode())
        scopes = data.get("scopes", 0)
        leases = data.get("active_leases", 0)
        results.append({
            "test": "SmartDeploy DHCP Server",
            "passed": True,
            "detail": f"Running — {scopes} scope(s), {leases} active lease(s)",
        })

        # Check if proxy DHCP is enabled
        stats = data.get("stats", {})
        if isinstance(stats, dict):
            ports = stats.get("listening_ports", [])
            has_proxy = 4011 in ports if isinstance(ports, list) else "4011" in str(ports)
            results.append({
                "test": "Proxy DHCP (Port 4011)",
                "passed": has_proxy,
                "detail": "Enabled — responds to PXE boot requests" if has_proxy else "Not enabled. Start with --enable-proxy",
            })
    except Exception:
        results.append({
            "test": "SmartDeploy DHCP Server",
            "passed": False,
            "detail": "Not running. Start it from the Services page.",
        })

    # 2. Check configured external DHCP server (if set)
    if settings.dhcp_server:
        ping = await run_powershell(
            f'Test-Connection -ComputerName "{settings.dhcp_server}" -Count 1 -Quiet'
        )
        results.append({
            "test": f"External DHCP Server ({settings.dhcp_server})",
            "passed": "true" in ping.stdout.lower(),
            "detail": "Reachable" if "true" in ping.stdout.lower() else "Cannot reach server",
        })

        # Try RSAT query if available (optional — won't fail if RSAT not installed)
        svc = await run_powershell(
            f'Get-DhcpServerv4Scope -ComputerName "{settings.dhcp_server}" -ErrorAction Stop | Measure-Object | Select-Object -ExpandProperty Count'
        )
        if svc.success and svc.stdout.strip().isdigit():
            results.append({
                "test": "External DHCP Scopes (RSAT)",
                "passed": int(svc.stdout.strip()) > 0,
                "detail": f"{svc.stdout.strip()} scope(s) configured",
            })

    all_passed = all(r["passed"] for r in results)
    return {"success": all_passed, "results": results}


@router.post("/test/tftp-pxe")
async def test_tftp_connection():
    """Test TFTP/PXE server connectivity."""
    settings = _load_settings().tftp_pxe

    if not settings.tftp_server:
        return {"success": False, "message": "No TFTP server configured"}

    results = []

    # Ping
    ping = await run_powershell(
        f'Test-Connection -ComputerName "{settings.tftp_server}" -Count 1 -Quiet'
    )
    results.append({
        "test": "TFTP Server Ping",
        "passed": "true" in ping.stdout.lower(),
        "detail": settings.tftp_server,
    })

    # Test TFTP port (69/UDP is hard to test, check TCP fallback or service)
    tftp_port = await run_powershell(
        f'$udp = New-Object System.Net.Sockets.UdpClient; '
        f'try {{ $udp.Connect("{settings.tftp_server}", 69); "OK" }} '
        f'catch {{ "FAIL" }} finally {{ $udp.Close() }}'
    )
    results.append({
        "test": "TFTP Port 69 (UDP)",
        "passed": "OK" in tftp_port.stdout,
        "detail": f"{settings.tftp_server}:69",
    })

    # Test boot file path
    if settings.tftp_root_path:
        path_test = await run_powershell(f'Test-Path -Path "{settings.tftp_root_path}"')
        results.append({
            "test": "TFTP Root Path",
            "passed": "true" in path_test.stdout.lower(),
            "detail": settings.tftp_root_path,
        })

    all_passed = all(r["passed"] for r in results)
    return {"success": all_passed, "results": results}


@router.post("/test/unc-mount")
async def test_unc_shares():
    """Test all configured UNC share paths for accessibility."""
    settings = _load_settings().unc_mounts
    results = []

    # Collect all configured share paths from the model fields
    shares_to_test = []
    if settings.share_images:
        shares_to_test.append(("Image Store", settings.share_images))
    if settings.share_drivers:
        shares_to_test.append(("Driver Store", settings.share_drivers))
    if settings.share_deployment:
        shares_to_test.append(("Deployment Share", settings.share_deployment))
    if settings.share_capture:
        shares_to_test.append(("Capture Share", settings.share_capture))
    if settings.share_logs:
        shares_to_test.append(("Log Share", settings.share_logs))

    # Also check the shares list
    for share in settings.shares:
        if share.get("unc_path"):
            shares_to_test.append((share.get("name", "Share"), share["unc_path"]))

    if not shares_to_test:
        return {"success": False, "message": "No UNC shares configured", "results": [
            {"test": "Configuration", "passed": False, "detail": "Enter at least one UNC share path in the fields above, then Save before testing"}
        ]}

    for name, unc_path in shares_to_test:
        # Test accessibility
        result = await run_powershell(f'Test-Path -Path "{unc_path}"')
        accessible = "true" in result.stdout.lower()

        results.append({
            "test": name,
            "passed": accessible,
            "detail": f"{unc_path} — {'Accessible' if accessible else 'Not found or access denied'}",
        })

        # If accessible, check write permission
        if accessible:
            write_test = await run_powershell(
                f'$testFile = Join-Path "{unc_path}" ".smartdeploy_test"; '
                f'try {{ [System.IO.File]::WriteAllText($testFile, "test"); Remove-Item $testFile -Force; "WRITABLE" }} '
                f'catch {{ "READONLY" }}'
            )
            results.append({
                "test": f"{name} — Write Permission",
                "passed": "WRITABLE" in write_test.stdout,
                "detail": "Read/Write" if "WRITABLE" in write_test.stdout else "Read Only",
            })

    all_passed = all(r["passed"] for r in results)
    return {"success": all_passed, "results": results}


@router.post("/test/wds")
async def test_wds_connection():
    """Test Windows Deployment Services connectivity."""
    settings = _load_settings().wds
    unc_settings = _load_settings().unc_mounts

    if not settings.wds_server:
        return {"success": False, "message": "No WDS server configured"}

    results = []

    # Build credential block from UNC settings if available
    cred_block = ""
    has_creds = unc_settings.default_credentials_username and unc_settings.default_credentials_domain
    if has_creds:
        escaped_pw = (unc_settings.default_credentials_password or "").replace("'", "''")
        domain = unc_settings.default_credentials_domain
        user = unc_settings.default_credentials_username
        cred_block = (
            f"$secpw = ConvertTo-SecureString '{escaped_pw}' -AsPlainText -Force; "
            f"$cred = New-Object System.Management.Automation.PSCredential('{domain}\\{user}', $secpw); "
        )

    # Ping
    ping = await run_powershell(
        f'Test-Connection -ComputerName "{settings.wds_server}" -Count 1 -Quiet'
    )
    results.append({
        "test": "WDS Server Ping",
        "passed": "true" in ping.stdout.lower(),
        "detail": settings.wds_server,
    })

    # Check WDS service status on remote server
    if has_creds:
        svc = await run_powershell(
            f'{cred_block}'
            f'Invoke-Command -ComputerName "{settings.wds_server}" -Credential $cred -ScriptBlock {{ '
            f'Get-Service -Name WDSServer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status '
            f'}} -ErrorAction SilentlyContinue'
        )
    else:
        svc = await run_powershell(
            f'Invoke-Command -ComputerName "{settings.wds_server}" -ScriptBlock {{ '
            f'Get-Service -Name WDSServer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status '
            f'}} -ErrorAction SilentlyContinue'
        )

    if svc.success and svc.stdout.strip():
        results.append({
            "test": "WDS Service Status",
            "passed": "running" in svc.stdout.lower(),
            "detail": svc.stdout.strip(),
        })
    else:
        results.append({
            "test": "WDS Service Status",
            "passed": False,
            "detail": svc.stderr[:150].strip() if svc.stderr else "Cannot query (enable WinRM or check credentials)",
        })

    # Check RemoteInstall path with credentials
    ri_path = settings.remote_install_path
    if ri_path:
        if has_creds and ri_path.startswith("\\\\"):
            # Map the share with credentials first
            ri_test = await run_powershell(
                f'{cred_block}'
                f'New-PSDrive -Name "WDSTest" -PSProvider FileSystem -Root "{ri_path}" -Credential $cred -ErrorAction SilentlyContinue | Out-Null; '
                f'$exists = Test-Path -Path "{ri_path}"; '
                f'Remove-PSDrive -Name "WDSTest" -Force -ErrorAction SilentlyContinue; '
                f'$exists'
            )
        else:
            ri_test = await run_powershell(f'Test-Path -Path "{ri_path}"')

        results.append({
            "test": "RemoteInstall Path",
            "passed": "true" in ri_test.stdout.lower(),
            "detail": f"{ri_path}" if "true" in ri_test.stdout.lower() else f"{ri_path} — Access denied or not found. Check UNC credentials.",
        })
    else:
        # Try standard share names with credentials
        found = False
        for share_path in [f"\\\\{settings.wds_server}\\RemoteInstall", f"\\\\{settings.wds_server}\\REMINST"]:
            if has_creds:
                ri_test = await run_powershell(
                    f'{cred_block}'
                    f'New-PSDrive -Name "WDSTest" -PSProvider FileSystem -Root "{share_path}" -Credential $cred -ErrorAction SilentlyContinue | Out-Null; '
                    f'$exists = Test-Path -Path "{share_path}"; '
                    f'Remove-PSDrive -Name "WDSTest" -Force -ErrorAction SilentlyContinue; '
                    f'$exists'
                )
            else:
                ri_test = await run_powershell(f'Test-Path -Path "{share_path}"')

            if "true" in ri_test.stdout.lower():
                results.append({"test": "RemoteInstall Share", "passed": True, "detail": share_path})
                found = True
                break

        if not found:
            results.append({
                "test": "RemoteInstall Share",
                "passed": False,
                "detail": "Not found. Enter the full UNC path (e.g., \\\\SCCM\\d\\RemoteInstall) and check UNC credentials.",
            })

    # Check boot images
    boot_path = settings.default_boot_image
    if boot_path:
        if has_creds and boot_path.startswith("\\\\"):
            boot_test = await run_powershell(
                f'{cred_block}'
                f'New-PSDrive -Name "WDSTest" -PSProvider FileSystem -Root (Split-Path "{boot_path}") -Credential $cred -ErrorAction SilentlyContinue | Out-Null; '
                f'$exists = Test-Path -Path "{boot_path}"; '
                f'Remove-PSDrive -Name "WDSTest" -Force -ErrorAction SilentlyContinue; '
                f'$exists'
            )
        else:
            boot_test = await run_powershell(f'Test-Path -Path "{boot_path}"')
        results.append({
            "test": "Boot Image File",
            "passed": "true" in boot_test.stdout.lower(),
            "detail": boot_path if "true" in boot_test.stdout.lower() else f"{boot_path} — Not found",
        })

    # Try remote WDS query via Invoke-Command
    if has_creds:
        wds_remote = await run_powershell(
            f'{cred_block}'
            f'Invoke-Command -ComputerName "{settings.wds_server}" -Credential $cred -ScriptBlock {{ '
            f'Import-Module WdsServer -ErrorAction SilentlyContinue; '
            f'$images = Get-WdsBootImage -ErrorAction SilentlyContinue; '
            f'if ($images) {{ $images.Count }} else {{ "0" }} '
            f'}} -ErrorAction SilentlyContinue'
        )
    else:
        wds_remote = await run_powershell(
            f'Invoke-Command -ComputerName "{settings.wds_server}" -ScriptBlock {{ '
            f'Import-Module WdsServer -ErrorAction SilentlyContinue; '
            f'$images = Get-WdsBootImage -ErrorAction SilentlyContinue; '
            f'if ($images) {{ $images.Count }} else {{ "0" }} '
            f'}} -ErrorAction SilentlyContinue'
        )

    if wds_remote.success and wds_remote.stdout.strip():
        count = wds_remote.stdout.strip()
        results.append({
            "test": "WDS Boot Images (Remote)",
            "passed": count != "0",
            "detail": f"{count} boot images registered in WDS",
        })

    all_passed = all(r["passed"] for r in results)
    return {"success": all_passed, "results": results}


@router.post("/test/mdt")
async def test_mdt_connection():
    """Test MDT deployment share connectivity."""
    settings = _load_settings().mdt

    results = []

    # Test deployment share path
    share_path = settings.deployment_share_path or settings.deployment_share_local
    if not share_path:
        return {"success": False, "message": "No deployment share configured"}

    path_test = await run_powershell(f'Test-Path -Path "{share_path}"')
    results.append({
        "test": "Deployment Share Path",
        "passed": "true" in path_test.stdout.lower(),
        "detail": share_path,
    })

    # Check for Control directory (indicates valid MDT share)
    control_test = await run_powershell(f'Test-Path -Path "{share_path}\\Control"')
    results.append({
        "test": "MDT Control Folder",
        "passed": "true" in control_test.stdout.lower(),
        "detail": f"{share_path}\\Control",
    })

    # Check for CustomSettings.ini
    cs_path = settings.rules_file_path or f"{share_path}\\Control\\CustomSettings.ini"
    cs_test = await run_powershell(f'Test-Path -Path "{cs_path}"')
    results.append({
        "test": "CustomSettings.ini",
        "passed": "true" in cs_test.stdout.lower(),
        "detail": cs_path,
    })

    # Check MDT toolkit installation
    if settings.toolkit_path:
        mdt_test = await run_powershell(f'Test-Path -Path "{settings.toolkit_path}\\Bin\\Microsoft.BDD.Utility.dll"')
        results.append({
            "test": "MDT Toolkit Installed",
            "passed": "true" in mdt_test.stdout.lower(),
            "detail": settings.toolkit_path,
        })

    # Check monitoring service
    if settings.monitoring_enabled and settings.monitoring_host:
        mon = await run_powershell(
            f'(New-Object System.Net.Sockets.TcpClient).Connect("{settings.monitoring_host}", {settings.monitoring_port}); "OK"'
        )
        results.append({
            "test": "MDT Monitoring Port",
            "passed": "OK" in mon.stdout,
            "detail": f"{settings.monitoring_host}:{settings.monitoring_port}",
        })

    all_passed = all(r["passed"] for r in results)
    return {"success": all_passed, "results": results}


# ============================================================================
# Utility endpoints
# ============================================================================

@router.post("/unc-mounts/mount")
async def mount_unc_share(unc_path: str, drive_letter: str, username: str = "", password: str = ""):
    """Mount a UNC share to a drive letter."""
    if username and password:
        cmd = (
            f'$secpw = ConvertTo-SecureString "{password}" -AsPlainText -Force; '
            f'$cred = New-Object System.Management.Automation.PSCredential("{username}", $secpw); '
            f'New-PSDrive -Name "{drive_letter[0]}" -PSProvider FileSystem -Root "{unc_path}" -Credential $cred -Persist -Scope Global'
        )
    else:
        cmd = f'net use {drive_letter} "{unc_path}" /persistent:yes'

    result = await run_powershell(cmd)
    return {
        "success": result.success,
        "message": f"Mounted {unc_path} as {drive_letter}" if result.success else f"Mount failed: {result.stderr}",
    }


@router.post("/unc-mounts/unmount")
async def unmount_unc_share(drive_letter: str):
    """Unmount a mapped drive."""
    result = await run_powershell(f'net use {drive_letter} /delete /yes')
    return {
        "success": result.success,
        "message": f"Unmounted {drive_letter}" if result.success else f"Unmount failed: {result.stderr}",
    }


@router.get("/unc-mounts/mapped")
async def list_mapped_drives():
    """List currently mapped network drives."""
    data = await run_powershell_json(
        'Get-PSDrive -PSProvider FileSystem | Where-Object { $_.DisplayRoot -ne $null } | '
        'Select-Object Name, @{N="DriveLetter";E={"$($_.Name):"}}, DisplayRoot, '
        '@{N="FreeGB";E={[math]::Round($_.Free / 1GB, 1)}}, '
        '@{N="UsedGB";E={[math]::Round($_.Used / 1GB, 1)}}'
    )

    if not data:
        return {"drives": []}

    items = data if isinstance(data, list) else [data]
    return {"drives": items}


@router.get("/active-directory/ou-tree")
async def get_ad_ou_tree():
    """Retrieve the OU tree from Active Directory for OU targeting."""
    settings = _load_settings().active_directory

    if not settings.domain_name:
        return {"ous": [], "message": "No domain configured"}

    search_base = settings.search_base or f"DC={settings.domain_name.replace('.', ',DC=')}"

    result = await run_powershell_json(
        f'Get-ADOrganizationalUnit -Filter * -SearchBase "{search_base}" -Properties CanonicalName | '
        f'Select-Object Name, DistinguishedName, CanonicalName | Sort-Object CanonicalName'
    )

    if not result:
        return {"ous": [], "message": "Failed to query AD. Ensure RSAT-AD-PowerShell is installed."}

    items = result if isinstance(result, list) else [result]
    return {"ous": items}
