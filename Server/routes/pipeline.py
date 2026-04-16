"""
SmartDeploy Deployment Pipeline
The actual 19-step Windows installation workflow.

Phase 1: WinPE Environment (Steps 1-10)
  - PXE boot → TFTP → WinPE
  - Disk prep, drivers, imaging, unattend

Phase 2: Reboot & First Boot (Steps 11-12)
  - State saved to disk, machine reboots
  - Windows OOBE runs unattend.xml

Phase 3: Post-Install (Steps 13-19)
  - Network reconnect, callback to server
  - Software, updates, domain join, final reboot
"""

import os
import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from utils.powershell import run_powershell, run_dism, run_powershell_json

router = APIRouter()
logger = logging.getLogger("smartdeploy.pipeline")


# ============================================================================
# Pipeline Step Definitions - The 19 Steps
# ============================================================================

PIPELINE_STEPS = [
    {
        "step": 1,
        "id": "pxe_boot",
        "name": "PXE Boot",
        "phase": "winpe",
        "description": "Client boots from network via PXE. DHCP provides IP, TFTP server address (Option 66), and boot file (Option 67).",
        "auto": True,  # Happens at network level, not scripted
        "parameters": {
            "dhcp_server": "",
            "tftp_server": "",
            "boot_file": "boot\\x64\\wdsnbp.com",
        },
    },
    {
        "step": 2,
        "id": "tftp_transfer_winpe",
        "name": "TFTP Transfers WinPE",
        "phase": "winpe",
        "description": "TFTP server sends the custom WinPE boot image (winpe.wim) to the client. Client loads WinPE into RAM.",
        "auto": True,
        "parameters": {
            "winpe_image": "",       # Path to custom winpe.wim on TFTP root
            "winpe_architecture": "x64",
            "scratch_space_mb": 512,
        },
    },
    {
        "step": 3,
        "id": "boot_winpe",
        "name": "Boot into WinPE",
        "phase": "winpe",
        "description": "WinPE environment loads. Network initialized, SmartDeploy client starts, connects back to API server.",
        "auto": True,
        "parameters": {
            "api_server_url": "http://{server_ip}:8000",
            "startup_script": "X:\\SmartDeploy\\start.cmd",
            "initialize_network": True,
            "map_deployment_share": True,
            "deployment_share": "",   # UNC path to deployment share
        },
    },
    {
        "step": 4,
        "id": "format_disk",
        "name": "Find Disk & Format",
        "phase": "winpe",
        "description": "Detect target disk, clean it, create GPT/UEFI partition layout (EFI + MSR + OS + Recovery).",
        "auto": False,
        "parameters": {
            "disk_number": 0,
            "auto_select_disk": True,    # Auto-pick largest non-USB disk
            "partition_scheme": "gpt_uefi",
            "efi_size_mb": 512,
            "msr_size_mb": 128,
            "recovery_size_mb": 1024,
            "os_label": "Windows",
            "os_drive_letter": "W",      # Temp letter during WinPE (not C:)
            "wipe_all_partitions": True,
            "file_system": "NTFS",
        },
    },
    {
        "step": 5,
        "id": "stage_drivers",
        "name": "Import & Stage Drivers",
        "phase": "winpe",
        "description": "Detect hardware model (manufacturer + model from SMBIOS). Match to Platform Pack. Copy matching drivers to temp staging folder on the target disk.",
        "auto": False,
        "parameters": {
            "auto_detect_model": True,
            "platform_pack_id": "",          # Manual override
            "driver_store_path": "",         # UNC or local path to driver store
            "staging_path": "W:\\$Drivers",  # Temp location on target disk
            "fallback_to_generic": True,     # Use generic drivers if no match
            "inject_method": "stage",        # "stage" (copy now, inject after image) vs "inject_offline" (DISM during WinPE)
        },
    },
    {
        "step": 6,
        "id": "rename_computer",
        "name": "Rename Computer",
        "phase": "winpe",
        "description": "Prompt technician to enter the computer name. Can auto-generate from template (prefix + serial, asset tag, etc.).",
        "auto": False,
        "requires_input": True,
        "parameters": {
            "prompt": True,                          # Show input dialog
            "auto_generate": False,                  # Auto-name if no prompt
            "naming_template": "{PREFIX}-{SERIAL:8}",
            "prefix": "WS",
            "use_serial": True,
            "use_asset_tag": False,
            "use_mac": False,
            "max_length": 15,                        # NetBIOS limit
            "computer_name": "",                     # Set by technician or auto
        },
    },
    {
        "step": 7,
        "id": "install_os",
        "name": "Install Windows from WIM",
        "phase": "winpe",
        "description": "Apply install.wim image to the OS partition using DISM /Apply-Image. This is the core imaging step.",
        "auto": False,
        "parameters": {
            "image_path": "",            # Path to install.wim (UNC or local)
            "image_index": 1,
            "apply_path": "W:\\",        # Target partition mount point in WinPE
            "verify": True,
            "compact": False,
            "wim_boot": False,
        },
    },
    {
        "step": 8,
        "id": "apply_drivers",
        "name": "Apply Drivers",
        "phase": "winpe",
        "description": "Inject staged drivers into the offline Windows image using DISM /Add-Driver from the staging folder.",
        "auto": False,
        "parameters": {
            "staging_path": "W:\\$Drivers",
            "target_image_path": "W:\\",
            "recurse": True,
            "force_unsigned": True,
            "cleanup_staging": True,     # Delete staging folder after injection
        },
    },
    {
        "step": 9,
        "id": "apply_custom_scripts",
        "name": "Apply Custom Scripts",
        "phase": "winpe",
        "description": "Copy and register custom scripts to run during or after first boot (SetupComplete.cmd, oobe scripts, etc.).",
        "auto": False,
        "parameters": {
            "scripts": [],  # [{source, destination, run_phase}]
            "setup_complete_script": "",        # Path to SetupComplete.cmd
            "oobe_scripts": [],
            "first_logon_scripts": [],
            "copy_tools": True,                 # Copy SmartDeploy client tools to target
            "tools_destination": "W:\\SmartDeploy",
        },
    },
    {
        "step": 10,
        "id": "apply_unattend",
        "name": "Apply unattend.xml",
        "phase": "winpe",
        "description": "Copy the unattend.xml answer file to the target OS. Sets computer name, locale, admin password, OOBE skip, domain join prep.",
        "auto": False,
        "parameters": {
            "unattend_source": "",                    # Path to unattend.xml template
            "unattend_destination": "W:\\Windows\\Panther\\unattend.xml",
            "inject_computer_name": True,             # Replace * with the name from step 6
            "inject_product_key": False,
            "product_key": "",
            "locale": "en-US",
            "timezone": "Pacific Standard Time",
            "admin_password": "",
            "skip_oobe": True,
            "auto_logon": True,
            "auto_logon_count": 3,
        },
    },
    {
        "step": 11,
        "id": "save_state_reboot",
        "name": "Save State & Reboot",
        "phase": "transition",
        "description": "Save the current pipeline state (step number, config, computer name) to the target disk so the process resumes after Windows boots. Configure boot files. Reboot.",
        "auto": False,
        "parameters": {
            "state_file_path": "W:\\SmartDeploy\\pipeline_state.json",
            "write_boot_files": True,
            "boot_mode": "UEFI",
            "bcdboot_source": "W:\\Windows",
            "bcdboot_target": "S:",          # EFI partition
            "reboot_delay_seconds": 5,
        },
    },
    {
        "step": 12,
        "id": "first_boot_oobe",
        "name": "Windows First Boot & OOBE",
        "phase": "first_boot",
        "description": "Windows boots for the first time. OOBE runs (skipped by unattend.xml). Specialize pass executes. Auto-logon to Administrator.",
        "auto": True,  # Handled by Windows + unattend.xml
        "parameters": {
            "expected_duration_minutes": 5,
            "oobe_skip_verified": True,
            "specialize_pass_runs": True,
        },
    },
    {
        "step": 13,
        "id": "network_connect",
        "name": "Find Network Connection",
        "phase": "post_install",
        "description": "Wait for a valid network connection via DHCP. Verify IP assignment, DNS resolution, and gateway connectivity.",
        "auto": False,
        "parameters": {
            "use_dhcp": True,
            "timeout_seconds": 120,
            "retry_interval_seconds": 5,
            "verify_dns": True,
            "verify_gateway": True,
            "dns_test_hostname": "",         # Test DNS resolution against this name
            "static_fallback": False,
            "static_ip": "",
            "static_mask": "",
            "static_gateway": "",
            "static_dns": [],
        },
    },
    {
        "step": 14,
        "id": "callback_server",
        "name": "Callback to Imaging Server",
        "phase": "post_install",
        "description": "Connect back to the SmartDeploy API server. Report status, resume pipeline state. Map the deployment share for software/updates.",
        "auto": False,
        "parameters": {
            "api_server_url": "http://{server_ip}:8000",
            "callback_endpoint": "/api/pipeline/callback",
            "deployment_share": "",          # UNC path: \\server\DeployShare$
            "share_username": "",
            "share_password": "",
            "map_drive_letter": "Z:",
            "software_path": "Z:\\Software",
            "updates_path": "Z:\\Updates",
            "retry_count": 10,
            "retry_delay_seconds": 10,
        },
    },
    {
        "step": 15,
        "id": "admin_first_logon",
        "name": "First Login to Administrator",
        "phase": "post_install",
        "description": "Auto-logon to local Administrator account (via unattend.xml). SetupComplete.cmd or scheduled task launches the SmartDeploy client agent.",
        "auto": True,
        "parameters": {
            "launch_agent": True,
            "agent_path": "C:\\SmartDeploy\\SmartDeployAgent.exe",
            "agent_args": "--resume-pipeline",
            "show_progress_window": True,
        },
    },
    {
        "step": 16,
        "id": "resume_task_sequence",
        "name": "Resume Task Sequence",
        "phase": "post_install",
        "description": "SmartDeploy client reads saved state, opens progress window showing current step and remaining work. Resumes from step 17.",
        "auto": False,
        "parameters": {
            "state_file_path": "C:\\SmartDeploy\\pipeline_state.json",
            "show_progress_window": True,
            "window_title": "SmartDeploy - Completing Setup",
            "allow_cancel": False,
            "lock_workstation": True,       # Prevent user interaction during install
        },
    },
    {
        "step": 17,
        "id": "install_software_updates",
        "name": "Install Software & Updates",
        "phase": "post_install",
        "description": "Silently install applications and Windows updates from the mapped deployment share. Show real-time progress in the status window.",
        "auto": False,
        "parameters": {
            "software_packages": [],   # [{name, path, args, type, success_codes}]
            "software_source": "Z:\\Software",
            "install_order": [],       # Ordered list of package names
            "windows_updates_source": "Z:\\Updates",
            "update_file_types": [".msu", ".cab"],
            "use_wsus": False,
            "wsus_server": "",
            "use_windows_update_online": False,
            "reboot_between_updates": False,
            "max_reboot_cycles": 3,
            "show_individual_progress": True,
            "timeout_per_package_minutes": 30,
        },
    },
    {
        "step": 18,
        "id": "join_domain",
        "name": "Join Domain",
        "phase": "post_install",
        "description": "Join the computer to the Active Directory domain in the specified OU. Apply computer name set in step 6.",
        "auto": False,
        "parameters": {
            "domain_name": "",
            "domain_ou": "",
            "domain_admin_user": "",
            "domain_admin_password": "",
            "computer_name": "",            # From step 6
            "retry_count": 3,
            "retry_delay_seconds": 15,
            "move_to_ou": True,
            "add_to_groups": [],
            "remove_from_default_computers": True,
        },
    },
    {
        "step": 19,
        "id": "final_reboot",
        "name": "Final Reboot",
        "phase": "post_install",
        "description": "Clean up temp files, remove auto-logon, disable SmartDeploy agent auto-start, and reboot into the completed system.",
        "auto": False,
        "parameters": {
            "cleanup_smartdeploy_files": True,
            "remove_auto_logon": True,
            "remove_agent_autostart": True,
            "cleanup_temp_drivers": True,
            "unmap_network_drives": True,
            "report_completion": True,          # Send final status to API server
            "reboot_delay_seconds": 10,
            "reboot_message": "SmartDeploy setup complete. Rebooting...",
            "final_status": "completed",
        },
    },
]


# ============================================================================
# Pipeline State Model
# ============================================================================

class PipelineState(BaseModel):
    """Persisted state that survives reboots."""
    pipeline_id: str
    computer_name: str = ""
    current_step: int = 1
    phase: str = "winpe"                   # winpe, transition, first_boot, post_install
    status: str = "running"                # running, paused, completed, failed
    started_at: str = ""
    steps_completed: List[int] = []
    steps_failed: List[int] = []
    error_log: List[str] = []
    variables: dict = {}                   # Shared variables between steps
    # Config inherited from deployment settings
    server_ip: str = ""
    deployment_share: str = ""
    image_path: str = ""
    image_index: int = 1
    platform_pack_id: str = ""
    unattend_path: str = ""
    domain_name: str = ""
    domain_ou: str = ""
    domain_user: str = ""
    domain_password: str = ""
    software_packages: List[dict] = []
    custom_scripts: List[dict] = []


class StartPipelineRequest(BaseModel):
    """Request to start a new deployment pipeline."""
    image_path: str
    image_index: int = 1
    server_ip: str = ""
    deployment_share: str = ""
    platform_pack_id: str = ""
    unattend_path: str = ""
    computer_name: str = ""              # Pre-set or leave empty for prompt
    domain_name: str = ""
    domain_ou: str = ""
    domain_user: str = ""
    domain_password: str = ""
    software_packages: List[dict] = []   # [{name, path, args}]
    custom_scripts: List[dict] = []


class PipelineStepResult(BaseModel):
    """Result of executing a single pipeline step."""
    step: int
    step_id: str
    success: bool
    message: str
    duration_seconds: float = 0
    output: str = ""


class ClientCallbackRequest(BaseModel):
    """Callback from the client agent after reboot (step 14)."""
    pipeline_id: str
    computer_name: str = ""
    ip_address: str = ""
    mac_address: str = ""
    current_step: int = 13
    status: str = "online"


# ============================================================================
# File-backed stores (shared across workers)
# ============================================================================

import threading

_store_lock = threading.Lock()

def _get_store_dir() -> str:
    """Get the directory for persistent stores."""
    app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    store_dir = os.path.join(app_data, "SmartDeployDesktop", "stores")
    os.makedirs(store_dir, exist_ok=True)
    return store_dir

def _load_pipelines() -> dict:
    """Load active pipelines from disk."""
    path = os.path.join(_get_store_dir(), "pipelines.json")
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_pipelines(data: dict):
    """Save active pipelines to disk."""
    path = os.path.join(_get_store_dir(), "pipelines.json")
    with _store_lock:
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

def _load_clients() -> dict:
    """Load PXE clients from disk."""
    path = os.path.join(_get_store_dir(), "pxe_clients.json")
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_clients(data: dict):
    """Save PXE clients to disk."""
    path = os.path.join(_get_store_dir(), "pxe_clients.json")
    with _store_lock:
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


# ============================================================================
# Pipeline Endpoints
# ============================================================================

@router.get("/steps")
async def get_pipeline_steps():
    """Return the full 19-step deployment pipeline definition."""
    return {
        "total_steps": len(PIPELINE_STEPS),
        "phases": {
            "winpe": "Steps 1-10: WinPE environment (pre-imaging)",
            "transition": "Step 11: Save state and reboot",
            "first_boot": "Step 12: Windows first boot and OOBE",
            "post_install": "Steps 13-19: Post-install (software, domain, cleanup)",
        },
        "steps": PIPELINE_STEPS,
    }


@router.get("/steps/{step_number}")
async def get_pipeline_step(step_number: int):
    """Get details for a specific pipeline step."""
    for step in PIPELINE_STEPS:
        if step["step"] == step_number:
            return step
    raise HTTPException(status_code=404, detail=f"Step {step_number} not found")


@router.post("/start")
async def start_pipeline(req: StartPipelineRequest):
    """Initialize a new deployment pipeline."""
    pipeline_id = str(uuid.uuid4())[:8]

    state = PipelineState(
        pipeline_id=pipeline_id,
        computer_name=req.computer_name,
        current_step=1,
        phase="winpe",
        status="running",
        started_at=datetime.now().isoformat(),
        server_ip=req.server_ip,
        deployment_share=req.deployment_share,
        image_path=req.image_path,
        image_index=req.image_index,
        platform_pack_id=req.platform_pack_id,
        unattend_path=req.unattend_path,
        domain_name=req.domain_name,
        domain_ou=req.domain_ou,
        domain_user=req.domain_user,
        domain_password=req.domain_password,
        software_packages=req.software_packages,
        custom_scripts=req.custom_scripts,
    )

    pipelines = _load_pipelines()
    pipelines[pipeline_id] = state.model_dump()
    _save_pipelines(pipelines)
    logger.info(f"Pipeline {pipeline_id} started: image={req.image_path}")

    return {
        "pipeline_id": pipeline_id,
        "status": "running",
        "current_step": 1,
        "total_steps": 19,
        "message": "Pipeline initialized. Waiting for PXE boot.",
    }


@router.get("/status/{pipeline_id}")
async def get_pipeline_status(pipeline_id: str):
    """Get current status of a deployment pipeline."""
    pipelines = _load_pipelines()
    if pipeline_id not in pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    state_data = pipelines[pipeline_id]
    state = PipelineState(**state_data) if isinstance(state_data, dict) else state_data
    current = None
    for s in PIPELINE_STEPS:
        if s["step"] == state.current_step:
            current = s
            break

    return {
        "pipeline_id": pipeline_id,
        "status": state.status,
        "phase": state.phase,
        "current_step": state.current_step,
        "current_step_name": current["name"] if current else "",
        "current_step_description": current["description"] if current else "",
        "total_steps": 19,
        "progress_percent": round((state.current_step - 1) / 19 * 100, 1),
        "computer_name": state.computer_name,
        "steps_completed": state.steps_completed,
        "steps_failed": state.steps_failed,
        "error_log": state.error_log[-10:],
        "started_at": state.started_at,
    }


@router.get("/active")
async def list_active_pipelines():
    """List all active deployment pipelines."""
    results = []
    pipelines = _load_pipelines()
    for pid, state in pipelines.items():
        if isinstance(state, dict):
            step = state.get("current_step", 1)
            results.append({
                "pipeline_id": pid,
                "computer_name": state.get("computer_name", ""),
                "current_step": step,
                "status": state.get("status", "unknown"),
                "phase": state.get("phase", ""),
                "progress_percent": round(((step - 1) / 19) * 100, 1) if isinstance(step, (int, float)) else 0,
            })
    return {"pipelines": results}


@router.post("/advance/{pipeline_id}")
async def advance_pipeline(pipeline_id: str, step_result: PipelineStepResult):
    """Mark current step as complete and advance to next step."""
    pipelines = _load_pipelines()
    if pipeline_id not in pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    state_data = pipelines[pipeline_id]
    state = PipelineState(**state_data) if isinstance(state_data, dict) else state_data

    if step_result.success:
        state.steps_completed.append(step_result.step)
        logger.info(f"[{pipeline_id}] Step {step_result.step} ({step_result.step_id}) completed: {step_result.message}")
    else:
        state.steps_failed.append(step_result.step)
        state.error_log.append(f"Step {step_result.step}: {step_result.message}")
        logger.error(f"[{pipeline_id}] Step {step_result.step} failed: {step_result.message}")

    # Advance to next step
    if step_result.step < 19 and step_result.success:
        state.current_step = step_result.step + 1

        # Update phase
        if state.current_step <= 10:
            state.phase = "winpe"
        elif state.current_step == 11:
            state.phase = "transition"
        elif state.current_step == 12:
            state.phase = "first_boot"
        else:
            state.phase = "post_install"
    elif step_result.step >= 19:
        state.status = "completed"
        state.phase = "post_install"
    elif not step_result.success:
        state.status = "failed"

    return {
        "pipeline_id": pipeline_id,
        "current_step": state.current_step,
        "status": state.status,
        "phase": state.phase,
    }


@router.post("/callback")
async def client_callback(req: ClientCallbackRequest):
    """
    Step 14 callback: Client agent calls back after Windows first boot.
    Resumes the pipeline from step 14 onward.
    """
    pipelines = _load_pipelines()
    if req.pipeline_id not in pipelines:
        # Try to find by computer name
        found = None
        for pid, state_data in pipelines.items():
            state = PipelineState(**state_data) if isinstance(state_data, dict) else state_data
            if state.computer_name == req.computer_name:
                found = pid
                break
        if not found:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        req.pipeline_id = found

    state_data = pipelines[req.pipeline_id]
    state = PipelineState(**state_data) if isinstance(state_data, dict) else state_data
    state.current_step = 14
    state.phase = "post_install"
    state.status = "running"
    state.variables["client_ip"] = req.ip_address
    state.variables["client_mac"] = req.mac_address

    logger.info(f"[{req.pipeline_id}] Client callback from {req.computer_name} ({req.ip_address})")

    # Return the remaining pipeline config so the client knows what to do
    return {
        "pipeline_id": req.pipeline_id,
        "status": "resumed",
        "current_step": 14,
        "computer_name": state.computer_name,
        "deployment_share": state.deployment_share,
        "domain_name": state.domain_name,
        "domain_ou": state.domain_ou,
        "domain_user": state.domain_user,
        "software_packages": state.software_packages,
        "remaining_steps": [s for s in PIPELINE_STEPS if s["step"] >= 14],
    }


@router.post("/set-computer-name/{pipeline_id}")
async def set_computer_name(pipeline_id: str, computer_name: str):
    """Step 6: Set the computer name (from technician input or auto-generate)."""
    pipelines = _load_pipelines()
    if pipeline_id not in pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    state_data = pipelines[pipeline_id]
    state = PipelineState(**state_data) if isinstance(state_data, dict) else state_data
    state.computer_name = computer_name
    state.variables["computer_name"] = computer_name

    logger.info(f"[{pipeline_id}] Computer name set: {computer_name}")
    return {"success": True, "computer_name": computer_name}


@router.post("/generate-computer-name/{pipeline_id}")
async def generate_computer_name(pipeline_id: str, request: Request):
    """Auto-generate computer name from template + hardware info."""
    pipelines = _load_pipelines()
    if pipeline_id not in pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    state_data = pipelines[pipeline_id]
    state = PipelineState(**state_data) if isinstance(state_data, dict) else state_data
    step6 = PIPELINE_STEPS[5]  # Step 6 config
    params = step6["parameters"]

    template = params.get("naming_template", "{PREFIX}-{SERIAL:8}")
    prefix = params.get("prefix", "WS")

    # Get serial number from hardware
    serial_result = await run_powershell(
        "Get-CimInstance Win32_BIOS | Select-Object -ExpandProperty SerialNumber"
    )
    serial = serial_result.stdout.strip() if serial_result.success else "UNKNOWN"

    # Get asset tag
    asset_result = await run_powershell(
        "Get-CimInstance Win32_SystemEnclosure | Select-Object -ExpandProperty SMBIOSAssetTag"
    )
    asset = asset_result.stdout.strip() if asset_result.success else ""

    # Get MAC address
    mac_result = await run_powershell(
        "Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled } | Select-Object -First 1 -ExpandProperty MACAddress"
    )
    mac = mac_result.stdout.strip().replace(":", "").replace("-", "") if mac_result.success else ""

    # Build name from template
    name = template
    name = name.replace("{PREFIX}", prefix)
    name = name.replace("{SERIAL}", serial[:15])
    name = name.replace("{SERIAL:8}", serial[:8])
    name = name.replace("{SERIAL:6}", serial[:6])
    name = name.replace("{ASSET}", asset[:15])
    name = name.replace("{MAC}", mac[-6:])
    name = name.replace("{MAC:6}", mac[-6:])

    # Truncate to NetBIOS limit
    name = name[:15].strip("-").strip("_")

    state.computer_name = name
    state.variables["computer_name"] = name

    return {"success": True, "computer_name": name, "serial": serial}


@router.get("/state-file/{pipeline_id}")
async def get_state_file(pipeline_id: str):
    """
    Generate the state file content for step 11 (save to target disk).
    The client agent reads this after first boot to resume the pipeline.
    """
    pipelines = _load_pipelines()
    if pipeline_id not in pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    state_data = pipelines[pipeline_id]
    state = PipelineState(**state_data) if isinstance(state_data, dict) else state_data

    state_data = {
        "pipeline_id": pipeline_id,
        "computer_name": state.computer_name,
        "resume_step": 13,      # After reboot + OOBE, resume at step 13
        "server_ip": state.server_ip,
        "api_url": f"http://{state.server_ip}:8000",
        "callback_url": f"http://{state.server_ip}:8000/api/pipeline/callback",
        "deployment_share": state.deployment_share,
        "domain_name": state.domain_name,
        "domain_ou": state.domain_ou,
        "domain_user": state.domain_user,
        "software_packages": state.software_packages,
        "custom_scripts": state.custom_scripts,
        "saved_at": datetime.now().isoformat(),
        "variables": state.variables,
    }

    return state_data


@router.delete("/{pipeline_id}")
async def cancel_pipeline(pipeline_id: str):
    """Cancel an active pipeline."""
    pipelines = _load_pipelines()
    if pipeline_id not in pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    state_data = pipelines[pipeline_id]
    state = PipelineState(**state_data) if isinstance(state_data, dict) else state_data
    state.status = "cancelled"

    return {"success": True, "message": f"Pipeline {pipeline_id} cancelled"}


# ============================================================================
# PXE Client Registry - tracks ALL machines that contact the server
# ============================================================================




class PxeClientEvent(BaseModel):
    """An event from a PXE-booting client."""
    mac: str = ""
    ip: str = ""
    hostname: str = ""
    event: str = ""          # dhcp_discover, dhcp_offer, tftp_request, winpe_start, pipeline_start, pipeline_step, pipeline_complete, pipeline_failed
    detail: str = ""
    timestamp: str = ""


@router.post("/client-event")
async def register_client_event(evt: PxeClientEvent):
    """Register a PXE client event (called by DHCP server, TFTP server, or WinPE agent)."""
    mac = evt.mac.upper().replace("-", ":") if evt.mac else "UNKNOWN"
    now = datetime.now().isoformat()

    clients = _load_clients()
    if mac not in clients:
        clients[mac] = {
            "mac": mac,
            "ip": evt.ip,
            "hostname": evt.hostname or "",
            "first_seen": now,
            "last_seen": now,
            "status": evt.event,
            "current_step": "",
            "progress": 0,
            "pipeline_id": "",
            "events": [],
        }

    client = clients[mac]
    client["last_seen"] = now
    client["status"] = evt.event
    if evt.ip:
        client["ip"] = evt.ip
    if evt.hostname:
        client["hostname"] = evt.hostname

    # Track pipeline progress
    if evt.event == "pipeline_start":
        client["current_step"] = "Step 1: PXE Boot"
        client["progress"] = 0
    elif evt.event == "pipeline_step":
        try:
            step_num = int(evt.detail.split(":")[0]) if ":" in evt.detail else int(evt.detail)
            client["current_step"] = evt.detail
            client["progress"] = round((step_num / 19) * 100)
        except ValueError:
            client["current_step"] = evt.detail
    elif evt.event == "pipeline_complete":
        client["status"] = "completed"
        client["progress"] = 100
        client["current_step"] = "Complete"
    elif evt.event == "pipeline_failed":
        client["status"] = "failed"
        client["current_step"] = f"FAILED: {evt.detail}"

    # Keep last 50 events per client
    client["events"].append({
        "time": now,
        "event": evt.event,
        "detail": evt.detail,
    })
    if len(client["events"]) > 50:
        client["events"] = client["events"][-50:]

    # Save updated client data (file-backed store — always works)
    _save_clients(clients)

    # Also persist to PostgreSQL if available
    try:
        from routes.db import is_db_available
        if is_db_available():
            from database import upsert_pxe_client, insert_client_event
            await upsert_pxe_client(
                mac=mac, ip=evt.ip or None, hostname=evt.hostname or None,
                status=evt.event, step=client.get("current_step"),
                progress=client.get("progress", 0)
            )
            await insert_client_event(mac, evt.ip or "", evt.event, evt.detail)
    except Exception as e:
        logger.debug(f"DB write skipped: {e}")

    logger.info(f"PXE client {mac} ({evt.ip}): {evt.event} - {evt.detail}")
    return {"success": True, "mac": mac}


@router.get("/clients")
async def list_pxe_clients():
    """List all PXE clients that have contacted the server."""
    clients = sorted(
        _load_clients().values(),
        key=lambda c: c["last_seen"],
        reverse=True,
    )
    return {"clients": clients, "total": len(clients)}


@router.get("/clients/{mac}")
async def get_pxe_client(mac: str):
    """Get details for a specific PXE client."""
    mac = mac.upper().replace("-", ":")
    clients = _load_clients()
    if mac not in clients:
        raise HTTPException(status_code=404, detail="Client not found")
    return clients[mac]


@router.delete("/clients")
async def clear_pxe_clients():
    """Clear the PXE client registry."""
    _save_clients({})
    return {"success": True, "message": "Client registry cleared"}
