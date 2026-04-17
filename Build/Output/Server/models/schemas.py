"""
Pydantic models for SmartDeploy Desktop API.
Defines request/response schemas for all endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime


# ============================================================================
# Enums
# ============================================================================

class DeployTarget(str, Enum):
    USB = "usb"
    NETWORK = "network"
    CLOUD = "cloud"
    PXE = "pxe"
    LOCAL = "local"


class DeploymentStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImageFormat(str, Enum):
    WIM = "wim"
    ESD = "esd"
    SWM = "swm"


class Architecture(str, Enum):
    X64 = "x64"
    X86 = "x86"
    ARM64 = "arm64"


class DismOperation(str, Enum):
    MOUNT = "mount"
    UNMOUNT = "unmount"
    APPLY = "apply"
    CAPTURE = "capture"
    SPLIT = "split"
    EXPORT = "export"
    INFO = "info"
    CLEANUP = "cleanup"


# ============================================================================
# Image Models
# ============================================================================

class WimImageInfo(BaseModel):
    """Information about a WIM image file."""
    name: str
    path: str
    size_bytes: int = 0
    size_display: str = ""
    image_count: int = 0
    format: ImageFormat = ImageFormat.WIM
    architecture: Architecture = Architecture.X64
    os_version: str = ""
    created: Optional[str] = None
    modified: Optional[str] = None


class WimIndexInfo(BaseModel):
    """Information about a specific index within a WIM file."""
    index: int
    name: str
    description: str = ""
    size_bytes: int = 0
    architecture: str = ""
    edition: str = ""
    version: str = ""
    build: str = ""
    language: str = ""
    hal: str = ""


class CaptureImageRequest(BaseModel):
    """Request to capture a new WIM image."""
    source_path: str = Field(..., description="Path to capture (e.g., C:\\ for a volume)")
    destination_path: str = Field(..., description="Output .wim file path")
    image_name: str = Field(..., description="Name for the image index")
    description: str = ""
    compress: str = Field(default="maximum", description="none, fast, maximum")
    boot_capture: bool = False
    verify: bool = True


class ImportImageRequest(BaseModel):
    """Request to import an existing WIM file into the image store."""
    source_path: str
    new_name: Optional[str] = None


# ============================================================================
# Platform Pack Models
# ============================================================================

class PlatformPack(BaseModel):
    """A Platform Pack (driver collection for a hardware model)."""
    id: str
    manufacturer: str
    model: str
    os_version: str
    architecture: Architecture = Architecture.X64
    path: str
    driver_count: int = 0
    size_bytes: int = 0
    size_display: str = ""
    version: str = ""
    created: Optional[str] = None


class InjectDriversRequest(BaseModel):
    """Request to inject drivers from a Platform Pack into a mounted image."""
    image_path: str = Field(..., description="Path to mounted WIM or offline image")
    mount_path: str = Field(..., description="Mount point path")
    platform_pack_id: str = Field(..., description="ID of the Platform Pack to inject")
    recurse: bool = True


# ============================================================================
# Deployment Models
# ============================================================================

class DeploymentRequest(BaseModel):
    """Request to deploy an image to a target."""
    image_path: str
    image_index: int = 1
    target: DeployTarget
    target_path: str = Field(..., description="USB drive letter, network share, or cloud URL")
    platform_pack_id: Optional[str] = None
    task_sequence_id: Optional[str] = None
    answer_file_path: Optional[str] = None
    format_target: bool = False
    boot_files: bool = True
    verify_after: bool = True


class DeploymentInfo(BaseModel):
    """Status info for an active or completed deployment."""
    id: str
    image_name: str
    target: DeployTarget
    target_path: str
    status: DeploymentStatus
    progress_percent: float = 0.0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    current_step: str = ""
    elapsed_seconds: int = 0


class USBDriveInfo(BaseModel):
    """Information about a connected USB drive."""
    device_id: str
    drive_letter: str
    label: str = ""
    size_bytes: int = 0
    size_display: str = ""
    free_bytes: int = 0
    file_system: str = ""
    is_removable: bool = True


# ============================================================================
# DISM Models
# ============================================================================

class DismMountRequest(BaseModel):
    """Request to mount a WIM image."""
    image_path: str
    index: int = 1
    mount_path: Optional[str] = None
    read_only: bool = False


class DismApplyRequest(BaseModel):
    """Request to apply a WIM image to a volume."""
    image_path: str
    index: int = 1
    apply_path: str = Field(..., description="Target volume (e.g., D:\\)")
    verify: bool = True
    compact: bool = False


class DismCaptureRequest(BaseModel):
    """Request to capture a volume to a WIM file."""
    capture_path: str
    destination_path: str
    image_name: str
    description: str = ""
    compress: str = "maximum"
    boot: bool = False
    verify: bool = True


class DismSplitRequest(BaseModel):
    """Request to split a WIM into SWM files."""
    image_path: str
    output_path: str
    max_size_mb: int = Field(default=4000, description="Max size per split file in MB")


class DismExportRequest(BaseModel):
    """Request to export a WIM index to a new WIM or ESD."""
    source_path: str
    source_index: int
    destination_path: str
    compress: str = "maximum"
    destination_format: ImageFormat = ImageFormat.WIM


class DismResult(BaseModel):
    """Result of a DISM operation."""
    success: bool
    operation: DismOperation
    message: str
    details: Optional[str] = None
    elapsed_seconds: float = 0


# ============================================================================
# Task Sequence Models
# ============================================================================

class StepCondition(BaseModel):
    """Structured condition evaluated against gathered variables at runtime.

    Example: variable='OSArchitecture', operator='equals', value='64-bit'
    """
    variable: str = ""            # Name of the variable (from gather step or sequence.variables)
    operator: str = "equals"      # equals, not_equals, contains, not_contains, starts_with,
                                  # ends_with, greater_than, less_than, greater_or_equal,
                                  # less_or_equal, is_empty, is_not_empty, matches_regex
    value: str = ""               # Comparison value (ignored for is_empty / is_not_empty)
    negate: bool = False          # Negate the final result


class TaskStep(BaseModel):
    """A single step in a task sequence."""
    id: str
    order: int
    name: str
    type: str
    enabled: bool = True
    continue_on_error: bool = False
    parameters: dict = {}
    condition: Optional[StepCondition] = None   # Structured condition (optional)


class TaskSequence(BaseModel):
    """A complete task sequence for automated deployment."""
    id: str
    name: str
    description: str = ""
    os_version: str = ""
    architecture: Architecture = Architecture.X64
    steps: List[TaskStep] = []
    variables: dict = {}          # Sequence-level variables: name -> default value
    created: Optional[str] = None
    modified: Optional[str] = None
    version: str = "1.0"


class CreateTaskSequenceRequest(BaseModel):
    """Request to create a new task sequence."""
    name: str
    description: str = ""
    os_version: str = "Windows 11 Pro"
    architecture: Architecture = Architecture.X64
    template: Optional[str] = None
    steps: List[TaskStep] = []


# ============================================================================
# Answer File Models
# ============================================================================

class AnswerFileSettings(BaseModel):
    """Settings for generating a Windows unattend.xml answer file."""
    computer_name: str = "*"
    organization: str = ""
    owner: str = ""
    timezone: str = "Pacific Standard Time"
    locale: str = "en-US"
    input_locale: str = "en-US"
    product_key: str = ""
    admin_password: str = ""
    auto_logon: bool = False
    auto_logon_count: int = 1
    skip_oobe: bool = True
    skip_eula: bool = True
    partition_scheme: str = "gpt_uefi"  # "gpt_uefi" or "mbr_bios"
    enable_remote_desktop: bool = False
    join_domain: str = ""
    domain_ou: str = ""
    domain_user: str = ""
    domain_password: str = ""
    run_synchronous_commands: List[str] = []
    first_logon_commands: List[str] = []


class AnswerFileInfo(BaseModel):
    """Metadata about a saved answer file."""
    id: str
    name: str
    path: str
    settings: AnswerFileSettings
    created: Optional[str] = None
    modified: Optional[str] = None


# ============================================================================
# Hardware Models
# ============================================================================

class HardwareInfo(BaseModel):
    """System hardware inventory."""
    computer_name: str = ""
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    bios_version: str = ""
    bios_mode: str = ""  # UEFI or Legacy
    secure_boot: bool = False
    tpm_version: str = ""
    tpm_present: bool = False
    cpu_name: str = ""
    cpu_cores: int = 0
    cpu_threads: int = 0
    ram_gb: float = 0
    ram_slots: List[dict] = []
    disks: List[dict] = []
    network_adapters: List[dict] = []
    gpu: str = ""
    os_name: str = ""
    os_version: str = ""
    os_build: str = ""
    os_architecture: str = ""
    domain: str = ""


class CompatibilityResult(BaseModel):
    """Windows 11 compatibility check result."""
    compatible: bool
    checks: List[dict] = []  # Each: {"name": "...", "passed": bool, "value": "...", "required": "..."}
    summary: str = ""


# ============================================================================
# Dashboard Models
# ============================================================================

class DashboardStats(BaseModel):
    """Overview statistics for the dashboard."""
    total_images: int = 0
    total_platform_packs: int = 0
    total_task_sequences: int = 0
    active_deployments: int = 0
    completed_deployments: int = 0
    failed_deployments: int = 0
    image_store_size: str = ""
    driver_store_size: str = ""
    system_info: dict = {}


class LogEntry(BaseModel):
    """A single log entry."""
    timestamp: str
    level: str
    source: str
    message: str


class ServerConfig(BaseModel):
    """Exposed server configuration."""
    config: dict = {}
