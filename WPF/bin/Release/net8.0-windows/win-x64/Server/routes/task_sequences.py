"""
Task Sequence and Answer File routes.
Create, manage, execute task sequences and generate unattend.xml answer files.
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, Request, Body
from fastapi.responses import JSONResponse

from models.schemas import (
    TaskSequence, TaskStep, CreateTaskSequenceRequest,
    AnswerFileSettings, AnswerFileInfo, Architecture
)

router = APIRouter()
logger = logging.getLogger("smartdeploy.task_sequences")


# ============================================================================
# Task Sequence Endpoints
# ============================================================================

@router.get("/", response_model=List[TaskSequence])
async def list_task_sequences(request: Request):
    """List all saved task sequences."""
    config = request.app.state.config
    ts_dir = config.task_sequence_dir
    sequences = []

    if not os.path.exists(ts_dir):
        return sequences

    for fname in os.listdir(ts_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(ts_dir, fname)
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            sequences.append(TaskSequence(**data))
        except Exception as e:
            logger.warning(f"Failed to load task sequence {fname}: {e}")

    return sequences


@router.get("/{ts_id}", response_model=TaskSequence)
async def get_task_sequence(ts_id: str, request: Request):
    """Get a specific task sequence by ID."""
    config = request.app.state.config
    ts_path = os.path.join(config.task_sequence_dir, f"{ts_id}.json")

    if not os.path.exists(ts_path):
        raise HTTPException(status_code=404, detail=f"Task sequence not found: {ts_id}")

    with open(ts_path, "r") as f:
        data = json.load(f)

    return TaskSequence(**data)


@router.post("/", response_model=TaskSequence)
async def create_task_sequence(req: CreateTaskSequenceRequest, request: Request):
    """Create a new task sequence (optionally from a template).

    On create, each step's parameters get pre-populated from the user's saved
    infrastructure settings (AD / DHCP / TFTP / UNC shares) so the sequence is
    usable immediately without re-typing values. User edits in the editor
    always win - the auto-fill only touches empty parameters.
    """
    config = request.app.state.config
    os.makedirs(config.task_sequence_dir, exist_ok=True)

    ts_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Apply template steps if requested
    steps = req.steps if req.steps else _get_template_steps(req.template)

    # Pull infrastructure settings once and apply to every step
    infra = _load_infrastructure_settings()
    if infra:
        for step in steps:
            _apply_settings_to_step(step, infra, overwrite=False)
        logger.info(f"Auto-filled step parameters from infrastructure settings for new sequence")

    ts = TaskSequence(
        id=ts_id,
        name=req.name,
        description=req.description,
        os_version=req.os_version,
        architecture=req.architecture,
        steps=steps,
        created=now,
        modified=now,
    )

    ts_path = os.path.join(config.task_sequence_dir, f"{ts_id}.json")
    with open(ts_path, "w") as f:
        json.dump(ts.model_dump(), f, indent=2)

    logger.info(f"Created task sequence: {ts.name} ({ts_id})")
    return ts


@router.put("/{ts_id}", response_model=TaskSequence)
async def update_task_sequence(ts_id: str, ts: TaskSequence, request: Request):
    """Update an existing task sequence."""
    config = request.app.state.config
    ts_path = os.path.join(config.task_sequence_dir, f"{ts_id}.json")

    if not os.path.exists(ts_path):
        raise HTTPException(status_code=404, detail=f"Task sequence not found: {ts_id}")

    ts.id = ts_id
    ts.modified = datetime.now().isoformat()

    with open(ts_path, "w") as f:
        json.dump(ts.model_dump(), f, indent=2)

    return ts


@router.delete("/{ts_id}")
async def delete_task_sequence(ts_id: str, request: Request):
    """Delete a task sequence."""
    config = request.app.state.config
    ts_path = os.path.join(config.task_sequence_dir, f"{ts_id}.json")

    if not os.path.exists(ts_path):
        raise HTTPException(status_code=404, detail=f"Task sequence not found: {ts_id}")

    os.remove(ts_path)
    return {"success": True, "message": f"Deleted task sequence: {ts_id}"}


@router.get("/templates/list")
async def list_templates():
    """List available task sequence templates."""
    return {
        "templates": [
            {"id": "bare_metal", "name": "Bare Metal Deployment", "description": "Fresh OS install: format, image, drivers, domain join, BitLocker"},
            {"id": "refresh", "name": "PC Refresh", "description": "Backup user state, wipe, reinstall, restore, domain rejoin"},
            {"id": "upgrade", "name": "In-Place Upgrade", "description": "Win10 → Win11 upgrade: suspend BitLocker, setup, drivers, resume"},
            {"id": "capture", "name": "Reference Image Capture", "description": "Sysprep, generalize, boot WinPE, capture to WIM"},
            {"id": "network_deploy", "name": "Network Deployment Server", "description": "Configure DHCP, DNS, ADDS, PXE for network-based imaging"},
            {"id": "custom", "name": "Custom (Empty)", "description": "Blank task sequence — add steps from the catalog"},
        ]
    }


# ============================================================================
# Answer File Endpoints
# ============================================================================

@router.get("/answer-files", response_model=List[AnswerFileInfo])
async def list_answer_files(request: Request):
    """List all saved answer files."""
    config = request.app.state.config
    af_dir = config.answer_file_dir
    files = []

    if not os.path.exists(af_dir):
        return files

    for fname in os.listdir(af_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(af_dir, fname)
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            files.append(AnswerFileInfo(**data))
        except Exception as e:
            logger.warning(f"Failed to load answer file {fname}: {e}")

    return files


@router.post("/answer-files/generate")
async def generate_answer_file(settings: AnswerFileSettings, name: str, request: Request):
    """Generate an unattend.xml answer file from settings."""
    config = request.app.state.config
    os.makedirs(config.answer_file_dir, exist_ok=True)

    af_id = str(uuid.uuid4())[:8]
    xml_content = _build_unattend_xml(settings)

    # Save the XML file
    xml_path = os.path.join(config.answer_file_dir, f"{af_id}_autounattend.xml")
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    # Save settings metadata
    meta = AnswerFileInfo(
        id=af_id,
        name=name,
        path=xml_path,
        settings=settings,
        created=datetime.now().isoformat(),
    )
    meta_path = os.path.join(config.answer_file_dir, f"{af_id}.json")
    with open(meta_path, "w") as f:
        json.dump(meta.model_dump(), f, indent=2)

    return {
        "success": True,
        "id": af_id,
        "xml_path": xml_path,
        "xml_preview": xml_content[:500] + "..." if len(xml_content) > 500 else xml_content,
    }


@router.delete("/answer-files/{af_id}")
async def delete_answer_file(af_id: str, request: Request):
    """Delete an answer file and its metadata."""
    config = request.app.state.config

    meta_path = os.path.join(config.answer_file_dir, f"{af_id}.json")
    xml_path = os.path.join(config.answer_file_dir, f"{af_id}_autounattend.xml")

    deleted = False
    for p in [meta_path, xml_path]:
        if os.path.exists(p):
            os.remove(p)
            deleted = True

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Answer file not found: {af_id}")

    return {"success": True, "message": f"Deleted answer file: {af_id}"}


# ============================================================================
# Duplicate / Export / Import / Reorder
# ============================================================================

@router.post("/{ts_id}/duplicate", response_model=TaskSequence)
async def duplicate_task_sequence(ts_id: str, request: Request):
    """Clone an existing task sequence into a new one with a fresh ID."""
    config = request.app.state.config
    src_path = os.path.join(config.task_sequence_dir, f"{ts_id}.json")

    if not os.path.exists(src_path):
        raise HTTPException(status_code=404, detail=f"Task sequence not found: {ts_id}")

    with open(src_path, "r") as f:
        data = json.load(f)

    new_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    data["id"] = new_id
    data["name"] = f"{data.get('name', 'Unnamed')} (Copy)"
    data["created"] = now
    data["modified"] = now

    dst_path = os.path.join(config.task_sequence_dir, f"{new_id}.json")
    with open(dst_path, "w") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Duplicated task sequence {ts_id} -> {new_id}")
    return TaskSequence(**data)


@router.get("/{ts_id}/export")
async def export_task_sequence(ts_id: str, request: Request):
    """Return the raw JSON of a task sequence for client-side download."""
    config = request.app.state.config
    ts_path = os.path.join(config.task_sequence_dir, f"{ts_id}.json")

    if not os.path.exists(ts_path):
        raise HTTPException(status_code=404, detail=f"Task sequence not found: {ts_id}")

    with open(ts_path, "r") as f:
        data = json.load(f)

    filename = f"{data.get('name', 'sequence').replace(' ', '_')}_{ts_id}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=TaskSequence)
async def import_task_sequence(payload: dict = Body(...), request: Request = None):
    """Import a task sequence from JSON payload. Assigns a fresh ID."""
    config = request.app.state.config
    os.makedirs(config.task_sequence_dir, exist_ok=True)

    # Strip server-managed fields and assign new ones
    payload.pop("id", None)
    payload.pop("created", None)
    payload.pop("modified", None)

    # Validate via Pydantic by giving a temp id that we'll overwrite
    try:
        ts_temp = TaskSequence(id="temp", **payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid task sequence JSON: {e}")

    new_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    data = ts_temp.model_dump()
    data["id"] = new_id
    data["created"] = now
    data["modified"] = now
    if not data.get("name"):
        data["name"] = f"Imported Sequence {new_id}"

    dst_path = os.path.join(config.task_sequence_dir, f"{new_id}.json")
    with open(dst_path, "w") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Imported task sequence as {new_id}: {data.get('name')}")
    return TaskSequence(**data)


@router.post("/{ts_id}/steps/reorder", response_model=TaskSequence)
async def reorder_steps(ts_id: str, payload: dict = Body(...), request: Request = None):
    """Reorder steps by supplying an ordered list of step IDs.

    Body: { "order": ["s1", "s3", "s2", ...] }
    """
    config = request.app.state.config
    ts_path = os.path.join(config.task_sequence_dir, f"{ts_id}.json")

    if not os.path.exists(ts_path):
        raise HTTPException(status_code=404, detail=f"Task sequence not found: {ts_id}")

    new_order = payload.get("order", [])
    if not isinstance(new_order, list):
        raise HTTPException(status_code=400, detail="'order' must be a list of step IDs")

    with open(ts_path, "r") as f:
        data = json.load(f)

    step_map = {s["id"]: s for s in data.get("steps", [])}
    reordered = []
    for i, sid in enumerate(new_order, 1):
        if sid in step_map:
            step = step_map.pop(sid)
            step["order"] = i
            reordered.append(step)
    # Append any leftovers (steps not mentioned in the reorder) at the end
    for leftover in step_map.values():
        leftover["order"] = len(reordered) + 1
        reordered.append(leftover)

    data["steps"] = reordered
    data["modified"] = datetime.now().isoformat()

    with open(ts_path, "w") as f:
        json.dump(data, f, indent=2)

    return TaskSequence(**data)


# ============================================================================
# Condition Support - variables and operators for the structured condition UI
# ============================================================================

@router.get("/condition-helpers")
async def get_condition_helpers():
    """Return standard gather variables and available operators for the condition builder."""
    return {
        "gather_variables": [
            # From the gather step
            {"name": "OSArchitecture", "description": "OS architecture: '64-bit' or '32-bit'"},
            {"name": "OSVersion", "description": "Windows version, e.g., '10.0.22631'"},
            {"name": "OSCurrentBuildNumber", "description": "Build number, e.g., '22631'"},
            {"name": "OSEdition", "description": "Edition, e.g., 'Professional', 'Enterprise'"},
            {"name": "IsLaptop", "description": "'True' if chassis is laptop/notebook"},
            {"name": "IsDesktop", "description": "'True' if chassis is desktop/tower"},
            {"name": "IsVM", "description": "'True' if running in a virtual machine"},
            {"name": "IsUEFI", "description": "'True' if booted in UEFI mode"},
            {"name": "IsSecureBoot", "description": "'True' if Secure Boot enabled"},
            {"name": "Manufacturer", "description": "System manufacturer, e.g., 'Dell Inc.'"},
            {"name": "Model", "description": "System model, e.g., 'Latitude 7420'"},
            {"name": "SerialNumber", "description": "System serial number"},
            {"name": "AssetTag", "description": "BIOS asset tag"},
            {"name": "ChassisType", "description": "Chassis type string"},
            {"name": "Memory", "description": "Total RAM in MB"},
            {"name": "CPUArchitecture", "description": "CPU architecture: 'AMD64', 'x86', 'ARM64'"},
            {"name": "CPUSpeed", "description": "CPU speed in MHz"},
            {"name": "NumberOfProcessors", "description": "Logical processor count"},
            {"name": "TPMVersion", "description": "TPM version, e.g., '2.0'"},
            {"name": "TPMPresent", "description": "'True' if TPM chip detected"},
            {"name": "DiskCount", "description": "Number of physical disks"},
            {"name": "DiskSize", "description": "Primary disk size in GB"},
            {"name": "IPAddress", "description": "Primary adapter IPv4 address"},
            {"name": "MACAddress", "description": "Primary adapter MAC address"},
            {"name": "ComputerName", "description": "Current hostname"},
            {"name": "DomainJoined", "description": "'True' if currently domain-joined"},
            {"name": "Domain", "description": "Current domain name (if joined)"},
        ],
        "operators": [
            {"id": "equals",           "display": "equals",            "takes_value": True},
            {"id": "not_equals",       "display": "does not equal",    "takes_value": True},
            {"id": "contains",         "display": "contains",          "takes_value": True},
            {"id": "not_contains",     "display": "does not contain",  "takes_value": True},
            {"id": "starts_with",      "display": "starts with",       "takes_value": True},
            {"id": "ends_with",        "display": "ends with",         "takes_value": True},
            {"id": "greater_than",     "display": "greater than",      "takes_value": True},
            {"id": "less_than",        "display": "less than",         "takes_value": True},
            {"id": "greater_or_equal", "display": "greater or equal",  "takes_value": True},
            {"id": "less_or_equal",    "display": "less or equal",     "takes_value": True},
            {"id": "is_empty",         "display": "is empty",          "takes_value": False},
            {"id": "is_not_empty",     "display": "is not empty",      "takes_value": False},
            {"id": "matches_regex",    "display": "matches regex",     "takes_value": True},
        ],
    }


# ============================================================================
# Helpers
# ============================================================================

def _get_template_steps(template: str = None) -> List[TaskStep]:
    """Generate default steps for a task sequence template using the step catalog."""
    if template == "bare_metal":
        return [
            _make_step(1, "gather"),
            _make_step(2, "validate"),
            _make_step(3, "format_and_partition_disk"),
            _make_step(4, "install_operating_system"),
            _make_step(5, "inject_drivers"),
            _make_step(6, "apply_network_settings"),
            _make_step(7, "configure_adds"),
            _make_step(8, "install_roles_and_features", enabled=False),
            _make_step(9, "install_application", enabled=False),
            _make_step(10, "install_updates_offline"),
            _make_step(11, "enable_disable_bitlocker"),
            _make_step(12, "restart_computer"),
        ]
    elif template == "refresh":
        return [
            _make_step(1, "gather"),
            _make_step(2, "validate"),
            _make_step(3, "capture_network_settings"),
            _make_step(4, "run_command_line", params={"command": "scanstate.exe /o /c /ue:*\\* /ui:DOMAIN\\*", "description": "Backup User State (USMT)"}),
            _make_step(5, "format_and_partition_disk"),
            _make_step(6, "install_operating_system"),
            _make_step(7, "inject_drivers"),
            _make_step(8, "apply_network_settings"),
            _make_step(9, "configure_adds"),
            _make_step(10, "recover_from_domain_join_failure", enabled=False),
            _make_step(11, "run_command_line", params={"command": "loadstate.exe /c /lac", "description": "Restore User State (USMT)"}),
            _make_step(12, "install_updates_offline"),
            _make_step(13, "restart_computer"),
        ]
    elif template == "upgrade":
        return [
            _make_step(1, "gather"),
            _make_step(2, "validate"),
            _make_step(3, "capture_network_settings"),
            _make_step(4, "enable_disable_bitlocker", params={"action": "suspend", "reboot_count": 2}),
            _make_step(5, "run_command_line", params={"command": "setup.exe /auto upgrade /quiet /noreboot /compat ignorewarning", "description": "In-Place Upgrade Setup"}),
            _make_step(6, "inject_drivers", enabled=False),
            _make_step(7, "install_updates_offline"),
            _make_step(8, "enable_disable_bitlocker", params={"action": "resume"}),
            _make_step(9, "restart_computer"),
        ]
    elif template == "capture":
        return [
            _make_step(1, "gather"),
            _make_step(2, "run_command_line", params={"command": r"C:\Windows\System32\Sysprep\sysprep.exe /generalize /oobe /shutdown", "description": "Sysprep Generalize"}),
            _make_step(3, "restart_computer", params={"target": "winpe"}),
            _make_step(4, "run_command_line", params={"command": "DISM.exe /Capture-Image /ImageFile:D:\\Capture\\image.wim /CaptureDir:C:\\ /Name:RefImage /Compress:max /Verify", "description": "Capture to WIM"}),
        ]
    elif template == "network_deploy":
        return [
            _make_step(1, "gather"),
            _make_step(2, "validate"),
            _make_step(3, "configure_dhcp"),
            _make_step(4, "authorize_dhcp"),
            _make_step(5, "configure_dns"),
            _make_step(6, "configure_adds"),
            _make_step(7, "format_and_partition_disk"),
            _make_step(8, "install_operating_system"),
            _make_step(9, "inject_drivers"),
            _make_step(10, "apply_network_settings"),
            _make_step(11, "install_roles_and_features"),
            _make_step(12, "install_application", enabled=False),
            _make_step(13, "restart_computer"),
        ]
    else:
        return []


def _make_step(order: int, step_type: str, enabled: bool = True, params: dict = None) -> TaskStep:
    """Create a TaskStep from the step catalog."""
    catalog_entry = STEP_CATALOG.get(step_type, {})
    merged_params = dict(catalog_entry.get("default_parameters", {}))
    if params:
        merged_params.update(params)

    return TaskStep(
        id=f"s{order}",
        order=order,
        name=catalog_entry.get("display_name", step_type),
        type=step_type,
        enabled=enabled,
        continue_on_error=catalog_entry.get("continue_on_error", False),
        parameters=merged_params,
    )


# ============================================================================
# Settings-based auto-fill
# ----------------------------------------------------------------------------
# Maps step types + parameter names to infrastructure settings values so users
# don't have to type the same domain/credentials/paths into every step.
#
# Returns a dict of {param_name: computed_value}. Only includes params we know
# how to resolve AND that have meaningful values in settings. Empty/missing
# settings are skipped so we don't overwrite user data with blanks.
# ============================================================================

def _compute_settings_fill(step_type: str, infra: dict) -> dict:
    """Return a dict of parameter overrides derived from infrastructure settings."""
    ad    = infra.get("active_directory", {}) or {}
    dhcp  = infra.get("dhcp", {})             or {}
    tftp  = infra.get("tftp_pxe", {})         or {}
    unc   = infra.get("unc_mounts", {})       or {}
    wds   = infra.get("wds", {})              or {}

    out: dict = {}

    if step_type == "configure_adds":
        if ad.get("domain_name"):           out["domain_name"]           = ad["domain_name"]
        if ad.get("default_ou"):            out["domain_ou"]             = ad["default_ou"]
        if ad.get("join_account_username"): out["domain_admin_user"]     = ad["join_account_username"]
        if ad.get("join_account_password"): out["domain_admin_password"] = ad["join_account_password"]

    elif step_type == "configure_dhcp":
        if dhcp.get("default_gateway"): out["default_gateway"] = dhcp["default_gateway"]
        if dhcp.get("dns_servers"):     out["dns_servers"]     = list(dhcp["dns_servers"])
        scopes = dhcp.get("scopes") or []
        if scopes:
            s0 = scopes[0]
            if s0.get("name"):          out["scope_name"]   = s0["name"]
            if s0.get("start_ip"):      out["start_ip"]     = s0["start_ip"]
            if s0.get("end_ip"):        out["end_ip"]       = s0["end_ip"]
            if s0.get("subnet_mask"):   out["subnet_mask"]  = s0["subnet_mask"]
        pxe = dhcp.get("pxe_boot_options") or {}
        if pxe.get("option_66"): out["pxe_option_66"] = pxe["option_66"]
        if pxe.get("option_67"): out["pxe_option_67"] = pxe["option_67"]

    elif step_type == "configure_dns":
        # Nothing obvious to pull - dns step currently has zone_name etc.
        # that aren't in settings. Leave empty so user fills them in.
        pass

    elif step_type == "apply_network_settings":
        if dhcp.get("dns_servers"):     out["dns_servers"]     = list(dhcp["dns_servers"])
        if dhcp.get("default_gateway"): out["default_gateway"] = dhcp["default_gateway"]
        if dhcp.get("domain_suffix"):   out["dns_suffix"]      = dhcp["domain_suffix"]

    elif step_type == "authorize_dhcp":
        if dhcp.get("dhcp_server"): out["dhcp_server"] = dhcp["dhcp_server"]

    elif step_type == "install_operating_system":
        # Prefer share_images. image_path is commonly <share>\install.wim by convention
        if unc.get("share_images"):
            out["image_path"] = unc["share_images"].rstrip("\\/") + "\\install.wim"

    elif step_type == "inject_drivers":
        if unc.get("share_drivers"):
            out["driver_path"] = unc["share_drivers"]

    elif step_type == "install_updates_offline":
        if unc.get("share_deployment"):
            out["update_source"] = unc["share_deployment"].rstrip("\\/") + "\\Updates"

    elif step_type == "validate":
        # No direct settings mapping - validate thresholds are user-specific
        pass

    elif step_type == "gather":
        # Rules file could live on the deployment share
        if unc.get("share_deployment"):
            out["rules_file"] = unc["share_deployment"].rstrip("\\/") + "\\CustomSettings.ini"

    return out


def _apply_settings_to_step(step: TaskStep, infra: dict, overwrite: bool = False) -> TaskStep:
    """Merge settings-derived params into a step.

    If overwrite=False (default, used on create), only fills params that are
    currently empty/falsy so we never clobber user edits.
    If overwrite=True (used by the editor's Pull From Settings button), forces
    the settings value into the step.
    """
    fill = _compute_settings_fill(step.type, infra)
    if not fill:
        return step

    current = dict(step.parameters or {})
    for key, value in fill.items():
        existing = current.get(key)
        is_empty = (
            existing is None
            or existing == ""
            or existing == []
            or existing == {}
        )
        if overwrite or is_empty:
            current[key] = value

    step.parameters = current
    return step


def _load_infrastructure_settings() -> dict:
    """Read the infrastructure.json settings file. Returns empty dict on any failure."""
    try:
        # Import lazily to avoid circular import at module load time
        from routes.settings import _load_settings
        return _load_settings().model_dump()
    except Exception as e:
        logger.warning(f"Could not load infrastructure settings for auto-fill: {e}")
        return {}


# ============================================================================
# Endpoints for the editor to query "what would settings fill in for this step?"
# ============================================================================

@router.get("/fill-preview/{step_type}")
async def preview_step_fill(step_type: str):
    """Return the parameter values that would be auto-filled for a given step type.

    Used by the editor's per-parameter '🔄 Pull from settings' button to know
    which parameters are eligible and what value each would receive.
    """
    infra = _load_infrastructure_settings()
    fill = _compute_settings_fill(step_type, infra)
    return {"step_type": step_type, "fill": fill}


# ============================================================================
# Step Type Catalog - all 18 available step types
# ============================================================================

STEP_CATALOG = {
    "apply_network_settings": {
        "display_name": "Apply Network Settings",
        "description": "Configure IP address, DNS, WINS, and domain membership on the target machine",
        "category": "Network",
        "default_parameters": {
            "use_dhcp": True,
            "static_ip": "",
            "subnet_mask": "",
            "default_gateway": "",
            "dns_servers": [],
            "wins_servers": [],
            "dns_suffix": "",
            "adapter_name": "",
        },
    },
    "authorize_dhcp": {
        "display_name": "Authorize DHCP",
        "description": "Authorize the DHCP server in Active Directory so it can issue leases",
        "category": "Network",
        "default_parameters": {
            "dhcp_server": "",
            "dns_name": "",
            "ip_address": "",
        },
    },
    "capture_network_settings": {
        "display_name": "Capture Network Settings",
        "description": "Save current network configuration (IP, DNS, domain) for reapplication after imaging",
        "category": "Network",
        "default_parameters": {
            "capture_adapters": True,
            "capture_domain": True,
            "capture_workgroup": True,
            "output_variable": "OSDNetworkSettings",
        },
    },
    "configure_adds": {
        "display_name": "Configure ADDS",
        "description": "Join a domain, create a computer account in the specified OU, or configure AD DS role",
        "category": "Domain",
        "default_parameters": {
            "action": "join",  # "join", "promote_dc", "create_account"
            "domain_name": "",
            "domain_ou": "",
            "domain_admin_user": "",
            "domain_admin_password": "",
            "machine_name": "",
            "skip_if_already_joined": True,
        },
    },
    "configure_dhcp": {
        "display_name": "Configure DHCP",
        "description": "Install and configure DHCP server role with scopes, reservations, and options",
        "category": "Network",
        "default_parameters": {
            "scope_name": "",
            "start_ip": "",
            "end_ip": "",
            "subnet_mask": "255.255.255.0",
            "default_gateway": "",
            "dns_servers": [],
            "lease_duration_hours": 8,
            "pxe_option_66": "",
            "pxe_option_67": "",
            "exclusion_ranges": [],
        },
    },
    "configure_dns": {
        "display_name": "Configure DNS",
        "description": "Install and configure DNS server role with zones and records",
        "category": "Network",
        "default_parameters": {
            "zone_name": "",
            "zone_type": "primary",  # "primary", "secondary", "stub", "forwarder"
            "forwarders": [],
            "reverse_zone": "",
            "dynamic_update": "secure",
        },
    },
    "enable_disable_bitlocker": {
        "display_name": "Enable/Disable BitLocker",
        "description": "Enable, disable, suspend, or resume BitLocker drive encryption",
        "category": "Security",
        "default_parameters": {
            "action": "enable",  # "enable", "disable", "suspend", "resume"
            "drive": "C:",
            "encryption_method": "XtsAes256",
            "protector_type": "tpm",  # "tpm", "tpm_pin", "password", "recovery_key"
            "pin": "",
            "recovery_key_path": "",
            "reboot_count": 1,  # For suspend: how many reboots to suspend for
            "skip_hardware_test": False,
        },
    },
    "format_and_partition_disk": {
        "display_name": "Format and Partition Disk",
        "description": "Partition and format disk with GPT/UEFI or MBR/BIOS layout",
        "category": "Disk",
        "default_parameters": {
            "disk_number": 0,
            "partition_scheme": "gpt_uefi",  # "gpt_uefi" or "mbr_bios"
            "efi_size_mb": 512,
            "msr_size_mb": 128,
            "recovery_size_mb": 1024,
            "os_partition_label": "Windows",
            "quick_format": True,
            "file_system": "NTFS",
            "wipe_disk": True,
        },
    },
    "gather": {
        "display_name": "Gather",
        "description": "Collect system information: hardware, OS, network, disk, TPM, BIOS mode for use in conditions",
        "category": "Information",
        "continue_on_error": True,
        "default_parameters": {
            "gather_hardware": True,
            "gather_network": True,
            "gather_os": True,
            "gather_disk": True,
            "gather_bios": True,
            "gather_tpm": True,
            "custom_properties": [],
            "rules_file": "",  # Path to CustomSettings.ini or rules file
        },
    },
    "group": {
        "display_name": "Group",
        "description": "Logical grouping container for organizing task sequence steps (does not execute, just groups)",
        "category": "Logic",
        "default_parameters": {
            "group_name": "",
            "condition": "",  # Conditional expression to evaluate
            "description": "",
        },
    },
    "inject_drivers": {
        "display_name": "Inject Drivers",
        "description": "Inject device drivers from a Platform Pack or driver store into the OS image",
        "category": "Drivers",
        "default_parameters": {
            "platform_pack_id": "",
            "driver_path": "",
            "recurse": True,
            "force_unsigned": True,
            "target_os_path": "",  # Offline OS root (e.g., mounted WIM or volume)
            "auto_detect_model": True,
        },
    },
    "install_application": {
        "display_name": "Install Application",
        "description": "Install one or more applications silently using MSI, EXE, MSIX, or script",
        "category": "Software",
        "default_parameters": {
            "application_name": "",
            "installer_path": "",
            "installer_type": "msi",  # "msi", "exe", "msix", "script", "winget", "choco"
            "silent_args": "/qn /norestart",
            "success_codes": [0, 3010],
            "reboot_if_needed": False,
            "winget_id": "",
            "choco_package": "",
            "applications": [],  # List of multiple apps: [{name, path, args}]
        },
    },
    "install_operating_system": {
        "display_name": "Install Operating System",
        "description": "Apply a WIM/ESD image to the target partition using DISM",
        "category": "OS",
        "default_parameters": {
            "image_path": "",
            "image_index": 1,
            "target_partition": "C:",
            "verify": True,
            "compact": False,
            "answer_file": "",
            "product_key": "",
            "edition": "",
        },
    },
    "install_roles_and_features": {
        "display_name": "Install Roles and Features",
        "description": "Install Windows Server roles or optional features (e.g., .NET, Hyper-V, IIS, RSAT)",
        "category": "Software",
        "default_parameters": {
            "roles": [],      # e.g., ["Web-Server", "DNS", "DHCP"]
            "features": [],   # e.g., ["NET-Framework-45-Core", "RSAT-AD-Tools"]
            "source_path": "",  # Optional SxS source for offline installs
            "include_management_tools": True,
            "restart_if_needed": False,
        },
    },
    "install_updates_offline": {
        "display_name": "Install Updates Offline",
        "description": "Apply Windows updates (.msu/.cab) to an offline or online OS image",
        "category": "Updates",
        "default_parameters": {
            "update_source": "",       # Path to folder with .msu/.cab files
            "target_path": "",         # Offline OS mount path (empty = online)
            "package_paths": [],       # Specific update file paths
            "reboot_if_needed": True,
            "use_wsus": False,
            "wsus_server": "",
        },
    },
    "recover_from_domain_join_failure": {
        "display_name": "Recover From Domain Join Failure",
        "description": "Retry domain join with alternate credentials or fall back to workgroup if join fails",
        "category": "Domain",
        "continue_on_error": True,
        "default_parameters": {
            "retry_count": 3,
            "retry_delay_seconds": 30,
            "alternate_domain_user": "",
            "alternate_domain_password": "",
            "fallback_to_workgroup": False,
            "workgroup_name": "WORKGROUP",
            "remove_stale_computer_account": True,
        },
    },
    "restart_computer": {
        "display_name": "Restart Computer",
        "description": "Restart the computer, optionally booting to WinPE, full OS, or PXE",
        "category": "System",
        "default_parameters": {
            "target": "current_os",  # "current_os", "winpe", "pxe", "bios"
            "delay_seconds": 0,
            "message": "",
            "timeout_seconds": 120,  # Max wait for restart to complete
        },
    },
    "run_command_line": {
        "display_name": "Run Command Line",
        "description": "Execute a command, script, or PowerShell command with optional working directory and timeout",
        "category": "General",
        "default_parameters": {
            "command": "",
            "description": "",
            "working_directory": "",
            "run_as_admin": True,
            "timeout_seconds": 600,
            "success_codes": [0, 3010],
            "powershell": False,  # If true, wraps in powershell.exe -Command
            "script_path": "",    # Path to .ps1 / .bat / .cmd script
        },
    },
    "validate": {
        "display_name": "Validate",
        "description": "Validate system readiness: check minimum RAM, disk space, OS version, UEFI, TPM, network",
        "category": "Information",
        "default_parameters": {
            "min_ram_mb": 4096,
            "min_disk_gb": 64,
            "require_uefi": True,
            "require_tpm": True,
            "require_tpm_version": "2.0",
            "require_secure_boot": False,
            "require_network": True,
            "require_ac_power": False,
            "min_cpu_cores": 2,
            "min_cpu_speed_ghz": 1.0,
            "allowed_os_versions": [],   # Empty = any
            "blocked_models": [],        # Block specific hardware models
        },
    },
}


@router.get("/step-catalog")
async def get_step_catalog():
    """Return the full catalog of available task sequence step types."""
    catalog = []
    for type_id, info in STEP_CATALOG.items():
        catalog.append({
            "type": type_id,
            "display_name": info["display_name"],
            "description": info["description"],
            "category": info["category"],
            "default_parameters": info["default_parameters"],
        })

    # Group by category
    categories = {}
    for item in catalog:
        cat = item["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)

    return {"step_types": catalog, "categories": categories}


def _build_unattend_xml(s: AnswerFileSettings) -> str:
    """Generate a Windows unattend.xml from settings."""
    # Partition configuration based on scheme
    if s.partition_scheme == "gpt_uefi":
        disk_config = """
            <DiskConfiguration>
              <Disk wcm:action="add">
                <DiskID>0</DiskID>
                <WillWipeDisk>true</WillWipeDisk>
                <CreatePartitions>
                  <CreatePartition wcm:action="add">
                    <Order>1</Order>
                    <Size>512</Size>
                    <Type>EFI</Type>
                  </CreatePartition>
                  <CreatePartition wcm:action="add">
                    <Order>2</Order>
                    <Size>128</Size>
                    <Type>MSR</Type>
                  </CreatePartition>
                  <CreatePartition wcm:action="add">
                    <Order>3</Order>
                    <Extend>true</Extend>
                    <Type>Primary</Type>
                  </CreatePartition>
                  <CreatePartition wcm:action="add">
                    <Order>4</Order>
                    <Size>1024</Size>
                    <Type>Primary</Type>
                  </CreatePartition>
                </CreatePartitions>
                <ModifyPartitions>
                  <ModifyPartition wcm:action="add">
                    <Order>1</Order>
                    <PartitionID>1</PartitionID>
                    <Format>FAT32</Format>
                    <Label>System</Label>
                  </ModifyPartition>
                  <ModifyPartition wcm:action="add">
                    <Order>2</Order>
                    <PartitionID>3</PartitionID>
                    <Format>NTFS</Format>
                    <Label>Windows</Label>
                    <Letter>C</Letter>
                  </ModifyPartition>
                  <ModifyPartition wcm:action="add">
                    <Order>3</Order>
                    <PartitionID>4</PartitionID>
                    <Format>NTFS</Format>
                    <Label>Recovery</Label>
                    <TypeID>de94bba4-06d1-4d40-a16a-bfd50179d6ac</TypeID>
                  </ModifyPartition>
                </ModifyPartitions>
              </Disk>
            </DiskConfiguration>"""
    else:
        disk_config = """
            <DiskConfiguration>
              <Disk wcm:action="add">
                <DiskID>0</DiskID>
                <WillWipeDisk>true</WillWipeDisk>
                <CreatePartitions>
                  <CreatePartition wcm:action="add">
                    <Order>1</Order>
                    <Size>512</Size>
                    <Type>Primary</Type>
                    <Active>true</Active>
                  </CreatePartition>
                  <CreatePartition wcm:action="add">
                    <Order>2</Order>
                    <Extend>true</Extend>
                    <Type>Primary</Type>
                  </CreatePartition>
                </CreatePartitions>
                <ModifyPartitions>
                  <ModifyPartition wcm:action="add">
                    <Order>1</Order>
                    <PartitionID>1</PartitionID>
                    <Format>NTFS</Format>
                    <Label>System Reserved</Label>
                    <Active>true</Active>
                  </ModifyPartition>
                  <ModifyPartition wcm:action="add">
                    <Order>2</Order>
                    <PartitionID>2</PartitionID>
                    <Format>NTFS</Format>
                    <Label>Windows</Label>
                    <Letter>C</Letter>
                  </ModifyPartition>
                </ModifyPartitions>
              </Disk>
            </DiskConfiguration>"""

    # Domain join section
    domain_section = ""
    if s.join_domain:
        domain_section = f"""
          <Component name="Microsoft-Windows-UnattendedJoin" processorArchitecture="amd64" language="neutral" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
            <Identification>
              <JoinDomain>{s.join_domain}</JoinDomain>
              {'<MachineObjectOU>' + s.domain_ou + '</MachineObjectOU>' if s.domain_ou else ''}
              <Credentials>
                <Domain>{s.join_domain}</Domain>
                <Username>{s.domain_user}</Username>
                <Password>{s.domain_password}</Password>
              </Credentials>
            </Identification>
          </Component>"""

    # Auto-logon section
    autologon_section = ""
    if s.auto_logon:
        autologon_section = f"""
              <AutoLogon>
                <Enabled>true</Enabled>
                <LogonCount>{s.auto_logon_count}</LogonCount>
                <Username>Administrator</Username>
                <Password>
                  <Value>{s.admin_password}</Value>
                  <PlainText>true</PlainText>
                </Password>
              </AutoLogon>"""

    # First logon commands
    first_logon = ""
    if s.first_logon_commands:
        cmds = ""
        for i, cmd in enumerate(s.first_logon_commands, 1):
            cmds += f"""
                <SynchronousCommand wcm:action="add">
                  <Order>{i}</Order>
                  <CommandLine>{cmd}</CommandLine>
                  <RequiresUserInput>false</RequiresUserInput>
                </SynchronousCommand>"""
        first_logon = f"""
              <FirstLogonCommands>{cmds}
              </FirstLogonCommands>"""

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend"
          xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">

  <!-- ==================== windowsPE Pass ==================== -->
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" language="neutral" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <SetupUILanguage>
        <UILanguage>{s.locale}</UILanguage>
      </SetupUILanguage>
      <InputLocale>{s.input_locale}</InputLocale>
      <SystemLocale>{s.locale}</SystemLocale>
      <UILanguage>{s.locale}</UILanguage>
      <UserLocale>{s.locale}</UserLocale>
    </component>

    <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" language="neutral" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      {disk_config}
      <ImageInstall>
        <OSImage>
          <InstallTo>
            <DiskID>0</DiskID>
            <PartitionID>{'3' if s.partition_scheme == 'gpt_uefi' else '2'}</PartitionID>
          </InstallTo>
        </OSImage>
      </ImageInstall>
      {'<UserData><ProductKey><Key>' + s.product_key + '</Key></ProductKey><AcceptEula>true</AcceptEula><Organization>' + s.organization + '</Organization><FullName>' + s.owner + '</FullName></UserData>' if s.product_key else '<UserData><AcceptEula>true</AcceptEula></UserData>'}
    </component>
  </settings>

  <!-- ==================== specialize Pass ==================== -->
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" language="neutral" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <ComputerName>{s.computer_name}</ComputerName>
      <TimeZone>{s.timezone}</TimeZone>
      {'<RegisteredOrganization>' + s.organization + '</RegisteredOrganization>' if s.organization else ''}
      {'<RegisteredOwner>' + s.owner + '</RegisteredOwner>' if s.owner else ''}
    </component>
    {domain_section}
    {'<component name="Microsoft-Windows-TerminalServices-LocalSessionManager" processorArchitecture="amd64" language="neutral"><fDenyTSConnections>false</fDenyTSConnections></component>' if s.enable_remote_desktop else ''}
  </settings>

  <!-- ==================== oobeSystem Pass ==================== -->
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" language="neutral" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <OOBE>
        <HideEULAPage>{str(s.skip_eula).lower()}</HideEULAPage>
        <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <ProtectYourPC>3</ProtectYourPC>
        <SkipMachineOOBE>{str(s.skip_oobe).lower()}</SkipMachineOOBE>
        <SkipUserOOBE>{str(s.skip_oobe).lower()}</SkipUserOOBE>
      </OOBE>
      <UserAccounts>
        <AdministratorPassword>
          <Value>{s.admin_password}</Value>
          <PlainText>true</PlainText>
        </AdministratorPassword>
      </UserAccounts>
      {autologon_section}
      {first_logon}
    </component>
  </settings>

</unattend>"""

    return xml
