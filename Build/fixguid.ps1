$bcd = "C:\RemoteInstall\Boot\BCD"

# Make sure the folder exists
New-Item -Path (Split-Path $bcd) -ItemType Directory -Force | Out-Null

# Nuke any existing BCD so we start clean
if (Test-Path $bcd) { Remove-Item $bcd -Force }

# 1. Create an empty BCD store
bcdedit /createstore $bcd

# 2. Create the {ramdiskoptions} entry - tells the boot manager where
#    to find boot.sdi (the RAM disk template)
bcdedit /store $bcd /create "{ramdiskoptions}" /d "Ramdisk options"
bcdedit /store $bcd /set "{ramdiskoptions}" ramdisksdidevice boot
bcdedit /store $bcd /set "{ramdiskoptions}" ramdisksdipath \Boot\boot.sdi

# 3. Create the WinPE OS loader entry and capture its auto-generated GUID
$output = bcdedit /store $bcd /create /d "SmartDeploy WinPE" /application osloader
$guid  = [regex]::Match($output, '\{[0-9a-fA-F\-]+\}').Value
Write-Host "WinPE loader GUID: $guid" -ForegroundColor Cyan

# 4. Configure the WinPE loader - point it at boot.wim via RAM disk
bcdedit /store $bcd /set $guid systemroot \Windows
bcdedit /store $bcd /set $guid detecthal Yes
bcdedit /store $bcd /set $guid winpe Yes
bcdedit /store $bcd /set $guid osdevice "ramdisk=[boot]\sources\boot.wim,{ramdiskoptions}"
bcdedit /store $bcd /set $guid device   "ramdisk=[boot]\sources\boot.wim,{ramdiskoptions}"

# 5. Create the {bootmgr} entry and make the WinPE loader its default
bcdedit /store $bcd /create "{bootmgr}" /d "Windows Boot Manager"
bcdedit /store $bcd /set "{bootmgr}" default      $guid
bcdedit /store $bcd /set "{bootmgr}" displayorder $guid
bcdedit /store $bcd /set "{bootmgr}" timeout 1

# 6. Verify - should list bootmgr + ramdiskoptions + your loader
Write-Host ""
Write-Host "=== BCD contents ===" -ForegroundColor Green
bcdedit /store $bcd /enum all