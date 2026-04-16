"""
Hardware inventory and compatibility check routes.
Gathers system info and checks Windows 11 readiness.
"""

import logging
from fastapi import APIRouter

from models.schemas import HardwareInfo, CompatibilityResult
from utils.powershell import run_powershell, run_powershell_json

router = APIRouter()
logger = logging.getLogger("smartdeploy.hardware")


@router.get("/inventory", response_model=HardwareInfo)
async def get_hardware_inventory():
    """Gather complete hardware inventory of the current system."""

    info = HardwareInfo()

    # --- Computer System ---
    cs = await run_powershell_json(
        "Get-CimInstance Win32_ComputerSystem | Select-Object Name, Manufacturer, Model, Domain, TotalPhysicalMemory"
    )
    if cs:
        info.computer_name = cs.get("Name", "")
        info.manufacturer = cs.get("Manufacturer", "")
        info.model = cs.get("Model", "")
        info.domain = cs.get("Domain", "")
        ram_bytes = cs.get("TotalPhysicalMemory", 0)
        info.ram_gb = round(ram_bytes / (1024 ** 3), 1) if ram_bytes else 0

    # --- BIOS ---
    bios = await run_powershell_json(
        "Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion, SerialNumber"
    )
    if bios:
        info.bios_version = bios.get("SMBIOSBIOSVersion", "")
        info.serial_number = bios.get("SerialNumber", "")

    # --- UEFI / Secure Boot ---
    uefi_result = await run_powershell(
        "try { $env:firmware_type = (Get-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control' -Name 'PEFirmwareType').PEFirmwareType; "
        "if ($env:firmware_type -eq 2) { 'UEFI' } else { 'Legacy' } } catch { 'Unknown' }"
    )
    info.bios_mode = uefi_result.stdout.strip() if uefi_result.success else "Unknown"

    sb_result = await run_powershell("Confirm-SecureBootUEFI 2>$null")
    info.secure_boot = sb_result.success and "true" in sb_result.stdout.lower()

    # --- TPM ---
    tpm = await run_powershell_json(
        "Get-CimInstance -Namespace 'root\\cimv2\\Security\\MicrosoftTpm' -ClassName Win32_Tpm 2>$null | "
        "Select-Object IsActivated_InitialValue, IsEnabled_InitialValue, SpecVersion"
    )
    if tpm:
        info.tpm_present = True
        spec = tpm.get("SpecVersion", "")
        info.tpm_version = spec.split(",")[0].strip() if spec else ""
    else:
        info.tpm_present = False

    # --- CPU ---
    cpu = await run_powershell_json(
        "Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors"
    )
    if cpu:
        info.cpu_name = cpu.get("Name", "")
        info.cpu_cores = cpu.get("NumberOfCores", 0)
        info.cpu_threads = cpu.get("NumberOfLogicalProcessors", 0)

    # --- RAM slots ---
    ram_result = await run_powershell_json(
        "Get-CimInstance Win32_PhysicalMemory | Select-Object BankLabel, Capacity, Speed, Manufacturer"
    )
    if ram_result:
        items = ram_result if isinstance(ram_result, list) else [ram_result]
        info.ram_slots = [
            {
                "bank": r.get("BankLabel", ""),
                "capacity_gb": round(r.get("Capacity", 0) / (1024 ** 3), 1),
                "speed_mhz": r.get("Speed", 0),
                "manufacturer": r.get("Manufacturer", ""),
            }
            for r in items
        ]

    # --- Disks ---
    disk_result = await run_powershell_json(
        "Get-CimInstance Win32_DiskDrive | Select-Object DeviceID, Model, Size, InterfaceType, MediaType, Partitions"
    )
    if disk_result:
        items = disk_result if isinstance(disk_result, list) else [disk_result]
        info.disks = [
            {
                "device_id": d.get("DeviceID", ""),
                "model": d.get("Model", ""),
                "size_gb": round(d.get("Size", 0) / (1024 ** 3), 1),
                "interface": d.get("InterfaceType", ""),
                "media_type": d.get("MediaType", ""),
                "partitions": d.get("Partitions", 0),
            }
            for d in items
        ]

    # --- Network Adapters ---
    net_result = await run_powershell_json(
        "Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true } | "
        "Select-Object Description, MACAddress, IPAddress, DHCPEnabled"
    )
    if net_result:
        items = net_result if isinstance(net_result, list) else [net_result]
        info.network_adapters = [
            {
                "description": n.get("Description", ""),
                "mac_address": n.get("MACAddress", ""),
                "ip_addresses": n.get("IPAddress", []),
                "dhcp_enabled": n.get("DHCPEnabled", False),
            }
            for n in items
        ]

    # --- GPU ---
    gpu_result = await run_powershell_json(
        "Get-CimInstance Win32_VideoController | Select-Object Name -First 1"
    )
    if gpu_result:
        info.gpu = gpu_result.get("Name", "")

    # --- OS ---
    os_info = await run_powershell_json(
        "Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture"
    )
    if os_info:
        info.os_name = os_info.get("Caption", "")
        info.os_version = os_info.get("Version", "")
        info.os_build = os_info.get("BuildNumber", "")
        info.os_architecture = os_info.get("OSArchitecture", "")

    return info


@router.get("/compatibility", response_model=CompatibilityResult)
async def check_win11_compatibility():
    """Check if this hardware meets Windows 11 requirements."""

    checks = []
    all_passed = True

    # Gather hardware info
    hw = await get_hardware_inventory()

    # 1. CPU: 1 GHz, 2+ cores, 64-bit compatible
    cpu_pass = hw.cpu_cores >= 2
    checks.append({
        "name": "Processor (2+ cores)",
        "passed": cpu_pass,
        "value": f"{hw.cpu_name} ({hw.cpu_cores} cores)",
        "required": "2 or more cores, 1 GHz+, 64-bit",
    })
    if not cpu_pass:
        all_passed = False

    # 2. RAM: 4 GB minimum
    ram_pass = hw.ram_gb >= 4.0
    checks.append({
        "name": "Memory (4 GB+)",
        "passed": ram_pass,
        "value": f"{hw.ram_gb} GB",
        "required": "4 GB minimum",
    })
    if not ram_pass:
        all_passed = False

    # 3. Storage: 64 GB minimum (check C: drive)
    disk_pass = False
    total_gb = 0
    if hw.disks:
        total_gb = max(d.get("size_gb", 0) for d in hw.disks)
        disk_pass = total_gb >= 64
    checks.append({
        "name": "Storage (64 GB+)",
        "passed": disk_pass,
        "value": f"{total_gb:.0f} GB (largest disk)",
        "required": "64 GB minimum",
    })
    if not disk_pass:
        all_passed = False

    # 4. UEFI + Secure Boot
    uefi_pass = hw.bios_mode == "UEFI"
    checks.append({
        "name": "UEFI Firmware",
        "passed": uefi_pass,
        "value": hw.bios_mode,
        "required": "UEFI with Secure Boot",
    })
    if not uefi_pass:
        all_passed = False

    sb_pass = hw.secure_boot
    checks.append({
        "name": "Secure Boot",
        "passed": sb_pass,
        "value": "Enabled" if sb_pass else "Disabled",
        "required": "Enabled",
    })
    if not sb_pass:
        all_passed = False

    # 5. TPM 2.0
    tpm_pass = hw.tpm_present and hw.tpm_version.startswith("2.")
    checks.append({
        "name": "TPM 2.0",
        "passed": tpm_pass,
        "value": f"TPM {hw.tpm_version}" if hw.tpm_present else "Not detected",
        "required": "TPM version 2.0",
    })
    if not tpm_pass:
        all_passed = False

    # 6. Architecture
    arch_pass = "64" in hw.os_architecture
    checks.append({
        "name": "64-bit Architecture",
        "passed": arch_pass,
        "value": hw.os_architecture,
        "required": "64-bit",
    })
    if not arch_pass:
        all_passed = False

    passed_count = sum(1 for c in checks if c["passed"])
    summary = (
        f"System is {'compatible' if all_passed else 'NOT compatible'} with Windows 11. "
        f"{passed_count}/{len(checks)} checks passed."
    )

    return CompatibilityResult(
        compatible=all_passed,
        checks=checks,
        summary=summary,
    )
