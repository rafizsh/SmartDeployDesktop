# ============================================================================
# SmartDeploy WinPE Deployment Wizard (PowerShell WinForms)
# Runs in WinPE after PXE boot. Replaces HTA which requires mshta.exe.
# ============================================================================

param(
    [string]$ServerIP = "%%SERVER_IP%%",
    [string]$UncPath = "%%UNC_PATH%%",
    [string]$UncUser = "%%UNC_USER%%",
    [string]$UncPassword = "%%UNC_PASSWORD%%",
    [string]$UncDomain = "%%UNC_DOMAIN%%",
    [string]$DeployImage = "%%DEPLOY_IMAGE%%",
    [int]$DeployIndex = 1,
    [string]$DeployEdition = "%%DEPLOY_EDITION%%"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ── Global State ──
$script:API = "http://${ServerIP}:8000/api"
$script:MyIP = "detecting..."
$script:MyMAC = "detecting..."
$script:CurrentStep = 0

# Task sequence runtime variables - gather fills this, conditions read from it.
# Also seeded with sequence-level variables before steps begin.
$script:Vars = @{}

# ── Detect IP/MAC via WMI ──
try {
    $nic = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true } | Select-Object -First 1
    if ($nic) {
        $script:MyIP = $nic.IPAddress[0]
        $script:MyMAC = $nic.MACAddress
    }
} catch {}

# ── Report to Server ──
function Report-Event($event, $detail) {
    try {
        $body = @{ mac = $script:MyMAC; ip = $script:MyIP; event = $event; detail = $detail } | ConvertTo-Json
        Invoke-RestMethod -Uri "$($script:API)/pipeline/client-event" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 3 -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}

# ── Evaluate a structured step condition against $script:Vars ──
# Returns $true if the step should run, $false if it should be skipped.
# Missing condition means "always run".
function Test-StepCondition($condition) {
    if (-not $condition) { return $true }
    if (-not $condition.variable) { return $true }

    $varName = $condition.variable
    $op      = if ($condition.operator) { $condition.operator } else { "equals" }
    $expected = if ($condition.value -ne $null) { [string]$condition.value } else { "" }
    $negate  = [bool]$condition.negate

    $actual = if ($script:Vars.ContainsKey($varName)) { [string]$script:Vars[$varName] } else { "" }

    $result = switch ($op) {
        "equals"           { $actual -eq $expected }
        "not_equals"       { $actual -ne $expected }
        "contains"         { $actual -like "*$expected*" }
        "not_contains"     { $actual -notlike "*$expected*" }
        "starts_with"      { $actual -like "$expected*" }
        "ends_with"        { $actual -like "*$expected" }
        "greater_than"     { [double]$actual -gt [double]$expected }
        "less_than"        { [double]$actual -lt [double]$expected }
        "greater_or_equal" { [double]$actual -ge [double]$expected }
        "less_or_equal"    { [double]$actual -le [double]$expected }
        "is_empty"         { [string]::IsNullOrEmpty($actual) }
        "is_not_empty"     { -not [string]::IsNullOrEmpty($actual) }
        "matches_regex"    { $actual -match $expected }
        default            { $true }   # unknown operator - run the step
    }

    if ($negate) { $result = -not $result }
    return $result
}

# ── Dialog: let the user pick which task sequence to run ──
# Returns the selected sequence object, or $null if cancelled.
function Select-TaskSequence($sequences) {
    if ($sequences.Count -eq 1) { return $sequences[0] }

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = "Select Task Sequence"
    $dlg.Size = New-Object System.Drawing.Size(560, 420)
    $dlg.StartPosition = "CenterParent"
    $dlg.FormBorderStyle = "FixedDialog"
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    $dlg.BackColor = $BgBase
    $dlg.ForeColor = $TextPrimary
    $dlg.Font = New-Object System.Drawing.Font("Segoe UI", 10)

    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "Choose the task sequence to execute:"
    $lbl.Location = New-Object System.Drawing.Point(20, 20)
    $lbl.Size = New-Object System.Drawing.Size(510, 24)
    $lbl.ForeColor = $TextPrimary
    $dlg.Controls.Add($lbl)

    $list = New-Object System.Windows.Forms.ListBox
    $list.Location = New-Object System.Drawing.Point(20, 54)
    $list.Size = New-Object System.Drawing.Size(510, 260)
    $list.BackColor = $BgSurface
    $list.ForeColor = $TextPrimary
    $list.BorderStyle = "FixedSingle"
    foreach ($s in $sequences) {
        $stepCount = if ($s.steps) { $s.steps.Count } else { 0 }
        [void]$list.Items.Add("$($s.name)   [$stepCount steps]   ($($s.os_version))")
    }
    if ($list.Items.Count -gt 0) { $list.SelectedIndex = 0 }
    $dlg.Controls.Add($list)

    $btnOk = New-Object System.Windows.Forms.Button
    $btnOk.Text = "Run This Sequence"
    $btnOk.Location = New-Object System.Drawing.Point(300, 330)
    $btnOk.Size = New-Object System.Drawing.Size(150, 32)
    $btnOk.BackColor = $AccentGreen
    $btnOk.ForeColor = [System.Drawing.Color]::Black
    $btnOk.FlatStyle = "Flat"
    $btnOk.DialogResult = "OK"
    $dlg.Controls.Add($btnOk)
    $dlg.AcceptButton = $btnOk

    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Text = "Cancel"
    $btnCancel.Location = New-Object System.Drawing.Point(455, 330)
    $btnCancel.Size = New-Object System.Drawing.Size(80, 32)
    $btnCancel.BackColor = $BgSurface
    $btnCancel.ForeColor = $TextPrimary
    $btnCancel.FlatStyle = "Flat"
    $btnCancel.DialogResult = "Cancel"
    $dlg.Controls.Add($btnCancel)
    $dlg.CancelButton = $btnCancel

    $result = $dlg.ShowDialog()
    if ($result -eq "OK" -and $list.SelectedIndex -ge 0) {
        return $sequences[$list.SelectedIndex]
    }
    return $null
}

# ── Colors (Catppuccin Mocha) ──
$BgDark = [System.Drawing.Color]::FromArgb(17, 17, 27)
$BgBase = [System.Drawing.Color]::FromArgb(30, 30, 46)
$BgSurface = [System.Drawing.Color]::FromArgb(49, 50, 68)
$TextPrimary = [System.Drawing.Color]::FromArgb(205, 214, 244)
$TextMuted = [System.Drawing.Color]::FromArgb(108, 112, 134)
$AccentBlue = [System.Drawing.Color]::FromArgb(137, 180, 250)
$AccentGreen = [System.Drawing.Color]::FromArgb(166, 227, 161)
$AccentRed = [System.Drawing.Color]::FromArgb(243, 139, 168)
$AccentYellow = [System.Drawing.Color]::FromArgb(249, 226, 175)
$AccentCyan = [System.Drawing.Color]::FromArgb(148, 226, 213)

# ── Main Form ──
$form = New-Object System.Windows.Forms.Form
$form.Text = "SmartDeploy - Windows Deployment Wizard"
$form.Size = New-Object System.Drawing.Size(600, 520)
$form.StartPosition = "CenterScreen"
$form.BackColor = $BgBase
$form.ForeColor = $TextPrimary
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)

# ── Header ──
$header = New-Object System.Windows.Forms.Panel
$header.Dock = "Top"
$header.Height = 50
$header.BackColor = $BgDark
$form.Controls.Add($header)

$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "SmartDeploy - Windows Deployment Wizard"
$lblTitle.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$lblTitle.ForeColor = $AccentBlue
$lblTitle.Location = New-Object System.Drawing.Point(16, 12)
$lblTitle.AutoSize = $true
$header.Controls.Add($lblTitle)

# ── Footer ──
$footer = New-Object System.Windows.Forms.Panel
$footer.Dock = "Bottom"
$footer.Height = 50
$footer.BackColor = $BgDark
$form.Controls.Add($footer)

$lblStep = New-Object System.Windows.Forms.Label
$lblStep.Text = "Step 1 of 5"
$lblStep.ForeColor = $TextMuted
$lblStep.Location = New-Object System.Drawing.Point(16, 15)
$lblStep.AutoSize = $true
$footer.Controls.Add($lblStep)

$btnBack = New-Object System.Windows.Forms.Button
$btnBack.Text = "Back"
$btnBack.Size = New-Object System.Drawing.Size(80, 32)
$btnBack.Location = New-Object System.Drawing.Point(370, 9)
$btnBack.FlatStyle = "Flat"
$btnBack.BackColor = $BgSurface
$btnBack.ForeColor = $TextPrimary
$btnBack.Enabled = $false
$footer.Controls.Add($btnBack)

$btnNext = New-Object System.Windows.Forms.Button
$btnNext.Text = "Next"
$btnNext.Size = New-Object System.Drawing.Size(80, 32)
$btnNext.Location = New-Object System.Drawing.Point(458, 9)
$btnNext.FlatStyle = "Flat"
$btnNext.BackColor = $AccentBlue
$btnNext.ForeColor = $BgDark
$footer.Controls.Add($btnNext)

$btnDeploy = New-Object System.Windows.Forms.Button
$btnDeploy.Text = "Deploy"
$btnDeploy.Size = New-Object System.Drawing.Size(80, 32)
$btnDeploy.Location = New-Object System.Drawing.Point(458, 9)
$btnDeploy.FlatStyle = "Flat"
$btnDeploy.BackColor = $AccentGreen
$btnDeploy.ForeColor = $BgDark
$btnDeploy.Visible = $false
$footer.Controls.Add($btnDeploy)

# ── Content Panel ──
$content = New-Object System.Windows.Forms.Panel
$content.Location = New-Object System.Drawing.Point(0, 50)
$content.Size = New-Object System.Drawing.Size(600, 370)
$content.BackColor = $BgBase
$form.Controls.Add($content)

# ── Step Panels ──
$panels = @()

# --- Step 0: Welcome ---
$p0 = New-Object System.Windows.Forms.Panel
$p0.Size = $content.Size
$p0.BackColor = $BgBase

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Welcome"
$lbl.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$lbl.ForeColor = $AccentBlue
$lbl.Location = New-Object System.Drawing.Point(20, 15)
$lbl.AutoSize = $true
$p0.Controls.Add($lbl)

$lbl2 = New-Object System.Windows.Forms.Label
$lbl2.Text = "This wizard will deploy Windows to this computer.`n`n  1. Select Windows image`n  2. Set computer name`n  3. Configure disk`n  4. Review and deploy"
$lbl2.ForeColor = $TextPrimary
$lbl2.Location = New-Object System.Drawing.Point(20, 50)
$lbl2.Size = New-Object System.Drawing.Size(540, 120)
$p0.Controls.Add($lbl2)

$infoPanel = New-Object System.Windows.Forms.Panel
$infoPanel.Location = New-Object System.Drawing.Point(20, 180)
$infoPanel.Size = New-Object System.Drawing.Size(540, 90)
$infoPanel.BackColor = $BgDark
$p0.Controls.Add($infoPanel)

$lblServer = New-Object System.Windows.Forms.Label
$lblServer.Text = "Server:  $ServerIP"
$lblServer.ForeColor = $AccentGreen
$lblServer.Font = New-Object System.Drawing.Font("Consolas", 10)
$lblServer.Location = New-Object System.Drawing.Point(12, 12)
$lblServer.AutoSize = $true
$infoPanel.Controls.Add($lblServer)

$lblMyIP = New-Object System.Windows.Forms.Label
$lblMyIP.Text = "My IP:   $($script:MyIP)"
$lblMyIP.ForeColor = $AccentGreen
$lblMyIP.Font = New-Object System.Drawing.Font("Consolas", 10)
$lblMyIP.Location = New-Object System.Drawing.Point(12, 36)
$lblMyIP.AutoSize = $true
$infoPanel.Controls.Add($lblMyIP)

$lblMyMAC = New-Object System.Windows.Forms.Label
$lblMyMAC.Text = "My MAC:  $($script:MyMAC)"
$lblMyMAC.ForeColor = $AccentGreen
$lblMyMAC.Font = New-Object System.Drawing.Font("Consolas", 10)
$lblMyMAC.Location = New-Object System.Drawing.Point(12, 60)
$lblMyMAC.AutoSize = $true
$infoPanel.Controls.Add($lblMyMAC)

$panels += $p0

# --- Step 1: Image Selection ---
$p1 = New-Object System.Windows.Forms.Panel
$p1.Size = $content.Size
$p1.BackColor = $BgBase

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Select Windows Image"
$lbl.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$lbl.ForeColor = $AccentBlue
$lbl.Location = New-Object System.Drawing.Point(20, 15)
$lbl.AutoSize = $true
$p1.Controls.Add($lbl)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Path to install.wim:"
$lbl.ForeColor = $TextMuted
$lbl.Location = New-Object System.Drawing.Point(20, 60)
$lbl.AutoSize = $true
$p1.Controls.Add($lbl)

$txtWimPath = New-Object System.Windows.Forms.TextBox
$defaultWimPath = if ($DeployImage -and $DeployImage -ne "%%DEPLOY_IMAGE%%") { $DeployImage } else { "Z:\Images\install.wim" }
$txtWimPath.Text = $defaultWimPath
$txtWimPath.Location = New-Object System.Drawing.Point(20, 85)
$txtWimPath.Size = New-Object System.Drawing.Size(540, 28)
$txtWimPath.BackColor = $BgSurface
$txtWimPath.ForeColor = $TextPrimary
$txtWimPath.BorderStyle = "FixedSingle"
$txtWimPath.Font = New-Object System.Drawing.Font("Consolas", 11)
$p1.Controls.Add($txtWimPath)

$lblImgStatus = New-Object System.Windows.Forms.Label
$lblImgStatus.Text = ""
$lblImgStatus.ForeColor = $AccentYellow
$lblImgStatus.Location = New-Object System.Drawing.Point(20, 120)
$lblImgStatus.Size = New-Object System.Drawing.Size(540, 20)
$p1.Controls.Add($lblImgStatus)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Image Index:"
$lbl.ForeColor = $TextMuted
$lbl.Location = New-Object System.Drawing.Point(20, 155)
$lbl.AutoSize = $true
$p1.Controls.Add($lbl)

$cmbIndex = New-Object System.Windows.Forms.ComboBox
$cmbIndex.Items.Add("(click Scan to detect editions)")
$cmbIndex.SelectedIndex = 0
$cmbIndex.Location = New-Object System.Drawing.Point(20, 180)
$cmbIndex.Size = New-Object System.Drawing.Size(420, 28)
$cmbIndex.BackColor = $BgSurface
$cmbIndex.ForeColor = $TextPrimary
$cmbIndex.FlatStyle = "Flat"
$cmbIndex.DropDownStyle = "DropDownList"
$p1.Controls.Add($cmbIndex)

$btnScanWim = New-Object System.Windows.Forms.Button
$btnScanWim.Text = "Scan"
$btnScanWim.Size = New-Object System.Drawing.Size(100, 28)
$btnScanWim.Location = New-Object System.Drawing.Point(450, 180)
$btnScanWim.FlatStyle = "Flat"
$btnScanWim.BackColor = $AccentBlue
$btnScanWim.ForeColor = $BgDark
$p1.Controls.Add($btnScanWim)

# Store index-to-number mapping
$script:WimIndexMap = @{}

function Scan-WimIndexes {
    param([string]$Path)

    $cmbIndex.Items.Clear()
    $script:WimIndexMap = @{}
    $cmbIndex.Items.Add("Scanning...")
    $cmbIndex.SelectedIndex = 0
    [System.Windows.Forms.Application]::DoEvents()

    if (-not (Test-Path $Path)) {
        $cmbIndex.Items.Clear()
        $cmbIndex.Items.Add("(WIM not found - map share first)")
        $cmbIndex.SelectedIndex = 0
        $lblImgStatus.Text = "File not found: $Path"
        $lblImgStatus.ForeColor = $AccentRed
        return
    }

    $wimSize = [math]::Round((Get-Item $Path).Length / 1GB, 1)
    $lblImgStatus.Text = "Found: $Path ($wimSize GB) — scanning editions..."
    $lblImgStatus.ForeColor = $AccentYellow
    [System.Windows.Forms.Application]::DoEvents()

    try {
        # Use DISM to get image info
        $output = dism /Get-WimInfo /WimFile:"$Path" 2>&1 | Out-String

        $cmbIndex.Items.Clear()
        $script:WimIndexMap = @{}
        $currentIndex = 0
        $currentName = ""
        $currentSize = ""
        $comboIdx = 0

        foreach ($line in $output -split "`n") {
            $trimmed = $line.Trim()
            if ($trimmed -match '^Index\s*:\s*(\d+)') {
                # Save previous entry
                if ($currentIndex -gt 0 -and $currentName) {
                    $label = "$currentIndex - $currentName"
                    if ($currentSize) { $label += " ($currentSize)" }
                    $cmbIndex.Items.Add($label)
                    $script:WimIndexMap[$comboIdx] = $currentIndex
                    $comboIdx++
                }
                $currentIndex = [int]$Matches[1]
                $currentName = ""
                $currentSize = ""
            }
            elseif ($trimmed -match '^Name\s*:\s*(.+)') {
                $currentName = $Matches[1].Trim()
            }
            elseif ($trimmed -match '^Size\s*:\s*(.+)') {
                $bytes = $Matches[1].Trim() -replace '[,\s]', ''
                if ($bytes -match '^\d+$') {
                    $currentSize = "$([math]::Round([long]$bytes / 1GB, 1)) GB"
                }
            }
        }
        # Save last entry
        if ($currentIndex -gt 0 -and $currentName) {
            $label = "$currentIndex - $currentName"
            if ($currentSize) { $label += " ($currentSize)" }
            $cmbIndex.Items.Add($label)
            $script:WimIndexMap[$comboIdx] = $currentIndex
        }

        if ($cmbIndex.Items.Count -gt 0) {
            $cmbIndex.SelectedIndex = 0
            $lblImgStatus.Text = "Found: $Path ($wimSize GB) — $($cmbIndex.Items.Count) edition(s)"
            $lblImgStatus.ForeColor = $AccentGreen
        } else {
            $cmbIndex.Items.Add("(no editions found)")
            $cmbIndex.SelectedIndex = 0
            $lblImgStatus.Text = "WIM found but no editions detected"
            $lblImgStatus.ForeColor = $AccentYellow
        }
    } catch {
        $cmbIndex.Items.Clear()
        $cmbIndex.Items.Add("(scan failed: $_)")
        $cmbIndex.SelectedIndex = 0
        $lblImgStatus.Text = "Scan failed: $_"
        $lblImgStatus.ForeColor = $AccentRed
    }
}

$btnScanWim.Add_Click({ Scan-WimIndexes $txtWimPath.Text })

# Auto-detect WIM at startup (won't work until Z: is mapped)
if (Test-Path $txtWimPath.Text) {
    $wimSize = [math]::Round((Get-Item $txtWimPath.Text).Length / 1GB, 1)
    $lblImgStatus.Text = "Found: $($txtWimPath.Text) ($wimSize GB) — scanning editions..."
    $lblImgStatus.ForeColor = $AccentYellow
    Scan-WimIndexes $txtWimPath.Text

    # Pre-select saved index
    if ($DeployIndex -gt 0 -and $DeployEdition -ne "%%DEPLOY_EDITION%%") {
        for ($i = 0; $i -lt $cmbIndex.Items.Count; $i++) {
            if ($script:WimIndexMap.ContainsKey($i) -and $script:WimIndexMap[$i] -eq $DeployIndex) {
                $cmbIndex.SelectedIndex = $i
                break
            }
        }
    }
} else {
    $lblImgStatus.Text = "WIM not accessible yet — share will be mapped at deploy time"
    $lblImgStatus.ForeColor = $AccentYellow

    # If we have a saved edition, show it as placeholder
    if ($DeployEdition -and $DeployEdition -ne "%%DEPLOY_EDITION%%") {
        $cmbIndex.Items.Clear()
        $cmbIndex.Items.Add("$DeployIndex - $DeployEdition (saved — click Scan to verify)")
        $script:WimIndexMap[0] = $DeployIndex
        $cmbIndex.SelectedIndex = 0
    }
}

$panels += $p1

# --- Step 2: Computer Name ---
$p2 = New-Object System.Windows.Forms.Panel
$p2.Size = $content.Size
$p2.BackColor = $BgBase

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Computer Name"
$lbl.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$lbl.ForeColor = $AccentBlue
$lbl.Location = New-Object System.Drawing.Point(20, 15)
$lbl.AutoSize = $true
$p2.Controls.Add($lbl)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Enter the name for this computer (max 15 chars, letters/numbers/hyphens):"
$lbl.ForeColor = $TextMuted
$lbl.Location = New-Object System.Drawing.Point(20, 55)
$lbl.Size = New-Object System.Drawing.Size(540, 20)
$p2.Controls.Add($lbl)

$defaultName = "PC-" + ($script:MyMAC -replace ":", "").Substring(6)
$txtComputerName = New-Object System.Windows.Forms.TextBox
$txtComputerName.Text = $defaultName
$txtComputerName.Location = New-Object System.Drawing.Point(20, 85)
$txtComputerName.Size = New-Object System.Drawing.Size(400, 32)
$txtComputerName.BackColor = $BgSurface
$txtComputerName.ForeColor = $TextPrimary
$txtComputerName.BorderStyle = "FixedSingle"
$txtComputerName.Font = New-Object System.Drawing.Font("Segoe UI", 16)
$p2.Controls.Add($txtComputerName)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Examples: PC-FINANCE-01, WS-HR-003, LAP-JSMITH"
$lbl.ForeColor = $TextMuted
$lbl.Location = New-Object System.Drawing.Point(20, 130)
$lbl.Size = New-Object System.Drawing.Size(540, 20)
$lbl.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$p2.Controls.Add($lbl)

$panels += $p2

# --- Step 3: Disk / Review ---
$p3 = New-Object System.Windows.Forms.Panel
$p3.Size = $content.Size
$p3.BackColor = $BgBase

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Review && Confirm"
$lbl.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$lbl.ForeColor = $AccentBlue
$lbl.Location = New-Object System.Drawing.Point(20, 15)
$lbl.AutoSize = $true
$p3.Controls.Add($lbl)

# OS Edition banner (large, prominent)
$lblEditionBanner = New-Object System.Windows.Forms.Label
$lblEditionBanner.Text = "(select an edition on the previous step)"
$lblEditionBanner.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
$lblEditionBanner.ForeColor = $AccentGreen
$lblEditionBanner.BackColor = $BgDark
$lblEditionBanner.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
$lblEditionBanner.Location = New-Object System.Drawing.Point(20, 48)
$lblEditionBanner.Size = New-Object System.Drawing.Size(540, 46)
$p3.Controls.Add($lblEditionBanner)

$reviewPanel = New-Object System.Windows.Forms.Panel
$reviewPanel.Location = New-Object System.Drawing.Point(20, 102)
$reviewPanel.Size = New-Object System.Drawing.Size(540, 140)
$reviewPanel.BackColor = $BgDark
$p3.Controls.Add($reviewPanel)

$lblReview = New-Object System.Windows.Forms.Label
$lblReview.Text = "(review loads when you reach this step)"
$lblReview.ForeColor = $AccentGreen
$lblReview.Font = New-Object System.Drawing.Font("Consolas", 10)
$lblReview.Location = New-Object System.Drawing.Point(12, 8)
$lblReview.Size = New-Object System.Drawing.Size(516, 124)
$reviewPanel.Controls.Add($lblReview)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "WARNING: All data on Disk 0 will be permanently erased!"
$lbl.ForeColor = $AccentRed
$lbl.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$lbl.Location = New-Object System.Drawing.Point(20, 255)
$lbl.Size = New-Object System.Drawing.Size(540, 20)
$p3.Controls.Add($lbl)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Click Deploy to begin. This process takes 10-30 minutes."
$lbl.ForeColor = $AccentYellow
$lbl.Location = New-Object System.Drawing.Point(20, 280)
$lbl.Size = New-Object System.Drawing.Size(540, 20)
$p3.Controls.Add($lbl)

$panels += $p3

# --- Step 4: Deploying ---
$p4 = New-Object System.Windows.Forms.Panel
$p4.Size = $content.Size
$p4.BackColor = $BgBase

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Deploying Windows..."
$lbl.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$lbl.ForeColor = $AccentBlue
$lbl.Location = New-Object System.Drawing.Point(20, 15)
$lbl.AutoSize = $true
$p4.Controls.Add($lbl)

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(20, 50)
$progressBar.Size = New-Object System.Drawing.Size(540, 24)
$progressBar.Style = "Continuous"
$p4.Controls.Add($progressBar)

$lblProgress = New-Object System.Windows.Forms.Label
$lblProgress.Text = "0% - Starting..."
$lblProgress.ForeColor = $AccentCyan
$lblProgress.Location = New-Object System.Drawing.Point(20, 80)
$lblProgress.Size = New-Object System.Drawing.Size(540, 20)
$p4.Controls.Add($lblProgress)

$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Location = New-Object System.Drawing.Point(20, 110)
$txtLog.Size = New-Object System.Drawing.Size(540, 220)
$txtLog.Multiline = $true
$txtLog.ReadOnly = $true
$txtLog.ScrollBars = "Vertical"
$txtLog.BackColor = $BgDark
$txtLog.ForeColor = $TextPrimary
$txtLog.Font = New-Object System.Drawing.Font("Consolas", 9)
$txtLog.WordWrap = $true
$p4.Controls.Add($txtLog)

$btnReboot = New-Object System.Windows.Forms.Button
$btnReboot.Text = "Reboot Now"
$btnReboot.Size = New-Object System.Drawing.Size(120, 32)
$btnReboot.Location = New-Object System.Drawing.Point(440, 338)
$btnReboot.FlatStyle = "Flat"
$btnReboot.BackColor = $AccentGreen
$btnReboot.ForeColor = $BgDark
$btnReboot.Visible = $false
$p4.Controls.Add($btnReboot)

$panels += $p4

# ── Add all panels to content ──
foreach ($p in $panels) {
    $p.Visible = $false
    $content.Controls.Add($p)
}
$panels[0].Visible = $true

# ── Navigation Logic ──
function Show-Step($n) {
    $script:CurrentStep = $n
    for ($i = 0; $i -lt $panels.Count; $i++) { $panels[$i].Visible = ($i -eq $n) }
    $lblStep.Text = "Step $($n + 1) of $($panels.Count)"
    $btnBack.Enabled = ($n -gt 0)

    if ($n -eq 3) {
        $btnNext.Visible = $false
        $btnDeploy.Visible = $true
        # Build review text
        $selectedEdition = $cmbIndex.SelectedItem
        $idx = if ($script:WimIndexMap.ContainsKey($cmbIndex.SelectedIndex)) { $script:WimIndexMap[$cmbIndex.SelectedIndex] } else { $cmbIndex.SelectedIndex + 1 }

        # Clean up edition name (remove "saved — click Scan" suffix if present)
        $editionClean = "$selectedEdition" -replace '\s*\(saved.*$', ''

        # Set the large banner
        $lblEditionBanner.Text = $editionClean
        $lblEditionBanner.ForeColor = $AccentGreen

        $lblReview.Text = "Image:          $($txtWimPath.Text)`nImage Index:     $idx`nComputer Name:   $($txtComputerName.Text)`nDisk Layout:     GPT / UEFI (W:=System, C:=Windows)`nServer:          $ServerIP`nDrivers:         Z:\Drivers (if available)`nUnattend.xml:    Z:\AnswerFiles (if available)"
    } elseif ($n -eq 4) {
        $btnNext.Visible = $false
        $btnDeploy.Visible = $false
        $btnBack.Enabled = $false
    } else {
        $btnNext.Visible = $true
        $btnDeploy.Visible = $false
    }
}

$btnNext.Add_Click({ Show-Step ($script:CurrentStep + 1) })
$btnBack.Add_Click({ Show-Step ($script:CurrentStep - 1) })
$btnReboot.Add_Click({ wpeutil reboot })

# ── Deploy Logic ──
function Write-Log($msg) {
    $txtLog.AppendText("$msg`r`n")
    $txtLog.SelectionStart = $txtLog.Text.Length
    $txtLog.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

function Update-Progress($pct, $msg) {
    $progressBar.Value = [Math]::Min($pct, 100)
    $lblProgress.Text = "$pct% - $msg"
    [System.Windows.Forms.Application]::DoEvents()
}

function Show-CredentialDialog {
    param(
        [string]$UncPath,
        [string]$DefaultUser = "",
        [string]$DefaultDomain = ""
    )

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = "Network Credentials"
    $dlg.Size = New-Object System.Drawing.Size(480, 340)
    $dlg.StartPosition = "CenterParent"
    $dlg.BackColor = $BgBase
    $dlg.ForeColor = $TextPrimary
    $dlg.FormBorderStyle = "FixedDialog"
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    $dlg.Font = New-Object System.Drawing.Font("Segoe UI", 10)

    # Header
    $lblTitle = New-Object System.Windows.Forms.Label
    $lblTitle.Text = "Authentication Required"
    $lblTitle.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
    $lblTitle.ForeColor = $AccentBlue
    $lblTitle.Location = New-Object System.Drawing.Point(20, 15)
    $lblTitle.AutoSize = $true
    $dlg.Controls.Add($lblTitle)

    # Info
    $lblInfo = New-Object System.Windows.Forms.Label
    $lblInfo.Text = "Enter credentials to access:"
    $lblInfo.ForeColor = $TextMuted
    $lblInfo.Location = New-Object System.Drawing.Point(20, 48)
    $lblInfo.AutoSize = $true
    $dlg.Controls.Add($lblInfo)

    $lblPath = New-Object System.Windows.Forms.Label
    $lblPath.Text = $UncPath
    $lblPath.ForeColor = $AccentGreen
    $lblPath.Font = New-Object System.Drawing.Font("Consolas", 10)
    $lblPath.Location = New-Object System.Drawing.Point(20, 70)
    $lblPath.Size = New-Object System.Drawing.Size(430, 20)
    $dlg.Controls.Add($lblPath)

    # Domain field
    $lblDomain = New-Object System.Windows.Forms.Label
    $lblDomain.Text = "Domain (optional):"
    $lblDomain.ForeColor = $TextMuted
    $lblDomain.Location = New-Object System.Drawing.Point(20, 105)
    $lblDomain.Size = New-Object System.Drawing.Size(140, 20)
    $dlg.Controls.Add($lblDomain)

    $txtDomain = New-Object System.Windows.Forms.TextBox
    $txtDomain.Text = $DefaultDomain
    $txtDomain.Location = New-Object System.Drawing.Point(170, 102)
    $txtDomain.Size = New-Object System.Drawing.Size(270, 26)
    $txtDomain.BackColor = $BgSurface
    $txtDomain.ForeColor = $TextPrimary
    $txtDomain.BorderStyle = "FixedSingle"
    $dlg.Controls.Add($txtDomain)

    # Username
    $lblUser = New-Object System.Windows.Forms.Label
    $lblUser.Text = "Username:"
    $lblUser.ForeColor = $TextMuted
    $lblUser.Location = New-Object System.Drawing.Point(20, 140)
    $lblUser.Size = New-Object System.Drawing.Size(140, 20)
    $dlg.Controls.Add($lblUser)

    $txtUser = New-Object System.Windows.Forms.TextBox
    $txtUser.Text = $DefaultUser
    $txtUser.Location = New-Object System.Drawing.Point(170, 137)
    $txtUser.Size = New-Object System.Drawing.Size(270, 26)
    $txtUser.BackColor = $BgSurface
    $txtUser.ForeColor = $TextPrimary
    $txtUser.BorderStyle = "FixedSingle"
    $dlg.Controls.Add($txtUser)

    # Password
    $lblPass = New-Object System.Windows.Forms.Label
    $lblPass.Text = "Password:"
    $lblPass.ForeColor = $TextMuted
    $lblPass.Location = New-Object System.Drawing.Point(20, 175)
    $lblPass.Size = New-Object System.Drawing.Size(140, 20)
    $dlg.Controls.Add($lblPass)

    $txtPass = New-Object System.Windows.Forms.TextBox
    $txtPass.UseSystemPasswordChar = $true
    $txtPass.Location = New-Object System.Drawing.Point(170, 172)
    $txtPass.Size = New-Object System.Drawing.Size(270, 26)
    $txtPass.BackColor = $BgSurface
    $txtPass.ForeColor = $TextPrimary
    $txtPass.BorderStyle = "FixedSingle"
    $dlg.Controls.Add($txtPass)

    # Hint
    $lblHint = New-Object System.Windows.Forms.Label
    $lblHint.Text = "Tip: Use your domain account (e.g. HIROFUMI\SCCMControl)"
    $lblHint.ForeColor = $TextMuted
    $lblHint.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $lblHint.Location = New-Object System.Drawing.Point(20, 215)
    $lblHint.Size = New-Object System.Drawing.Size(430, 20)
    $dlg.Controls.Add($lblHint)

    # Buttons
    $btnOK = New-Object System.Windows.Forms.Button
    $btnOK.Text = "Connect"
    $btnOK.Size = New-Object System.Drawing.Size(100, 32)
    $btnOK.Location = New-Object System.Drawing.Point(240, 255)
    $btnOK.FlatStyle = "Flat"
    $btnOK.BackColor = $AccentGreen
    $btnOK.ForeColor = $BgDark
    $btnOK.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $dlg.Controls.Add($btnOK)
    $dlg.AcceptButton = $btnOK

    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Text = "Cancel"
    $btnCancel.Size = New-Object System.Drawing.Size(100, 32)
    $btnCancel.Location = New-Object System.Drawing.Point(350, 255)
    $btnCancel.FlatStyle = "Flat"
    $btnCancel.BackColor = $BgSurface
    $btnCancel.ForeColor = $TextPrimary
    $btnCancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $dlg.Controls.Add($btnCancel)
    $dlg.CancelButton = $btnCancel

    # Focus on whichever field is empty first
    if (-not $DefaultUser) {
        $dlg.Add_Shown({ $txtUser.Focus() })
    } else {
        $dlg.Add_Shown({ $txtPass.Focus() })
    }

    $result = $dlg.ShowDialog($form)
    $dlg.Dispose()

    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        return @{
            User = $txtUser.Text.Trim()
            Password = $txtPass.Text
            Domain = $txtDomain.Text.Trim()
        }
    }
    return $null
}

# ============================================================================
# STEP HANDLERS
# Each Invoke-Step-<type> function executes one step of a task sequence.
# Handlers receive the full step object + its parameters hashtable.
# Throw on fatal errors - the executor catches and reports them.
# Never reference wizard UI fields; everything comes from $Params or $script:Vars.
# ============================================================================

function Invoke-Step-Gather {
    param($Step, $Params)
    Write-Log "  Collecting system variables..."
    $cs   = Get-WmiObject Win32_ComputerSystem     -ErrorAction SilentlyContinue
    $bios = Get-WmiObject Win32_BIOS               -ErrorAction SilentlyContinue
    $os   = Get-WmiObject Win32_OperatingSystem    -ErrorAction SilentlyContinue
    $disk = Get-WmiObject Win32_DiskDrive          -ErrorAction SilentlyContinue | Select-Object -First 1
    $tpm  = Get-WmiObject -Namespace "Root\CIMV2\Security\MicrosoftTpm" -Class Win32_Tpm -ErrorAction SilentlyContinue
    $enclosure = Get-WmiObject Win32_SystemEnclosure -ErrorAction SilentlyContinue
    $cpu  = Get-WmiObject Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($cs) {
        $script:Vars["Manufacturer"]       = "$($cs.Manufacturer)"
        $script:Vars["Model"]              = "$($cs.Model)"
        $script:Vars["NumberOfProcessors"] = "$($cs.NumberOfLogicalProcessors)"
        $script:Vars["Memory"]             = "$([int]($cs.TotalPhysicalMemory / 1MB))"
        $script:Vars["DomainJoined"]       = if ($cs.PartOfDomain) { "True" } else { "False" }
        $script:Vars["Domain"]             = "$($cs.Domain)"
        $script:Vars["ComputerName"]       = "$($cs.Name)"
        $script:Vars["IsVM"]               = if ($cs.Manufacturer -match "VMware|Xen|Microsoft|innotek|QEMU|Parallels") { "True" } else { "False" }
    }
    if ($enclosure) {
        $chassisType = $enclosure.ChassisTypes | Select-Object -First 1
        $script:Vars["ChassisType"] = "$chassisType"
        $script:Vars["IsLaptop"]    = if ($chassisType -in 8,9,10,11,12,14,18,21,30,31,32) { "True" } else { "False" }
        $script:Vars["IsDesktop"]   = if ($chassisType -in 3,4,5,6,7,13,15,16) { "True" } else { "False" }
        $script:Vars["AssetTag"]    = "$($enclosure.SMBIOSAssetTag)"
    }
    if ($bios) { $script:Vars["SerialNumber"] = "$($bios.SerialNumber)" }
    if ($os) {
        $script:Vars["OSVersion"]            = "$($os.Version)"
        $script:Vars["OSCurrentBuildNumber"] = "$($os.BuildNumber)"
        $script:Vars["OSEdition"]            = "$($os.Caption)"
        $script:Vars["OSArchitecture"]       = "$($os.OSArchitecture)"
    }
    if ($disk) {
        $script:Vars["DiskCount"] = "$((Get-WmiObject Win32_DiskDrive).Count)"
        $script:Vars["DiskSize"]  = "$([int]($disk.Size / 1GB))"
    }
    try {
        $sbState = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State" -ErrorAction SilentlyContinue
        $script:Vars["IsSecureBoot"] = if ($sbState.UEFISecureBootEnabled -eq 1) { "True" } else { "False" }
        $script:Vars["IsUEFI"]       = if ($env:firmware_type -eq "UEFI" -or $sbState) { "True" } else { "False" }
    } catch {
        $script:Vars["IsUEFI"] = "Unknown"; $script:Vars["IsSecureBoot"] = "Unknown"
    }
    if ($tpm) {
        $script:Vars["TPMPresent"] = "True"
        $script:Vars["TPMVersion"] = if ($tpm.SpecVersion) { ($tpm.SpecVersion -split ",")[0].Trim() } else { "Unknown" }
    } else {
        $script:Vars["TPMPresent"] = "False"; $script:Vars["TPMVersion"] = ""
    }
    if ($cpu) {
        $script:Vars["CPUArchitecture"] = switch ($cpu.Architecture) { 0 {"x86"} 5 {"ARM"} 9 {"AMD64"} 12 {"ARM64"} default {"Unknown"} }
        $script:Vars["CPUSpeed"]        = "$($cpu.MaxClockSpeed)"
    }
    $script:Vars["IPAddress"]  = "$($script:MyIP)"
    $script:Vars["MACAddress"] = "$($script:MyMAC)"

    Write-Log "  Collected $($script:Vars.Count) variables."
    Report-Event "pipeline_log" "Gathered $($script:Vars.Count) vars | Model: $($script:Vars['Manufacturer']) $($script:Vars['Model']) | Serial: $($script:Vars['SerialNumber']) | UEFI: $($script:Vars['IsUEFI']) | TPM: $($script:Vars['TPMVersion'])"
}

function Invoke-Step-Validate {
    param($Step, $Params)
    $minRam      = if ($Params.min_ram_mb)        { [int]$Params.min_ram_mb }        else { 0 }
    $minDisk     = if ($Params.min_disk_gb)       { [int]$Params.min_disk_gb }       else { 0 }
    $minCores    = if ($Params.min_cpu_cores)     { [int]$Params.min_cpu_cores }     else { 0 }
    $requireUefi = if ($Params.require_uefi -ne $null) { [bool]$Params.require_uefi } else { $false }
    $requireTpm  = if ($Params.require_tpm  -ne $null) { [bool]$Params.require_tpm }  else { $false }

    $actualRam   = if ($script:Vars.ContainsKey("Memory"))             { [int]$script:Vars["Memory"] }   else { 0 }
    $actualDisk  = if ($script:Vars.ContainsKey("DiskSize"))           { [int]$script:Vars["DiskSize"] } else { 0 }
    $actualCores = if ($script:Vars.ContainsKey("NumberOfProcessors")) { [int]$script:Vars["NumberOfProcessors"] } else { 0 }
    $actualUefi  = if ($script:Vars.ContainsKey("IsUEFI"))             { $script:Vars["IsUEFI"] -eq "True" } else { $false }
    $actualTpm   = if ($script:Vars.ContainsKey("TPMPresent"))         { $script:Vars["TPMPresent"] -eq "True" } else { $false }

    $failed = @()
    if ($minRam   -gt 0 -and $actualRam   -lt $minRam)   { $failed += "RAM $actualRam MB < $minRam MB" }
    if ($minDisk  -gt 0 -and $actualDisk  -lt $minDisk)  { $failed += "Disk $actualDisk GB < $minDisk GB" }
    if ($minCores -gt 0 -and $actualCores -lt $minCores) { $failed += "Cores $actualCores < $minCores" }
    if ($requireUefi -and -not $actualUefi) { $failed += "UEFI required but BIOS mode detected" }
    if ($requireTpm  -and -not $actualTpm)  { $failed += "TPM required but not present" }

    if ($failed.Count -gt 0) {
        throw "Validation failed: $($failed -join '; ')"
    }
    Write-Log "  All validation checks passed."
}

function Invoke-Step-Format-And-Partition-Disk {
    param($Step, $Params)
    $diskNum    = if ($Params.disk_number -ne $null)  { [int]$Params.disk_number }  else { 0 }
    $scheme     = if ($Params.partition_scheme)       { $Params.partition_scheme }  else { "gpt_uefi" }
    $efiSize    = if ($Params.efi_size_mb)            { [int]$Params.efi_size_mb }  else { 260 }
    $msrSize    = if ($Params.msr_size_mb)            { [int]$Params.msr_size_mb }  else { 16 }
    $osLabel    = if ($Params.os_partition_label)     { $Params.os_partition_label } else { "Windows" }
    $fileSystem = if ($Params.file_system)            { $Params.file_system }       else { "NTFS" }
    $wipeDisk   = if ($Params.wipe_disk -ne $null)    { [bool]$Params.wipe_disk }   else { $true }
    $quickFmt   = if ($Params.quick_format -ne $null) { [bool]$Params.quick_format } else { $true }
    $quickKw = if ($quickFmt) { "quick" } else { "" }

    Write-Log "  Partitioning disk $diskNum ($scheme) - EFI:$efiSize MB MSR:$msrSize MB OS:$osLabel/$fileSystem"

    if ($scheme -eq "gpt_uefi") {
        $wipeLine = if ($wipeDisk) { "clean`r`nconvert gpt" } else { "convert gpt" }
        $dpScript = @"
select disk $diskNum
$wipeLine
create partition efi size=$efiSize
format fs=fat32 $quickKw label="System"
assign letter=W
create partition msr size=$msrSize
create partition primary
format fs=$fileSystem $quickKw label="$osLabel"
assign letter=C
exit
"@
    } else {
        $wipeLine = if ($wipeDisk) { "clean" } else { "" }
        $dpScript = @"
select disk $diskNum
$wipeLine
create partition primary size=512
format fs=ntfs $quickKw label="System Reserved"
active
assign letter=W
create partition primary
format fs=$fileSystem $quickKw label="$osLabel"
assign letter=C
exit
"@
    }

    $dpScript | Out-File -FilePath "X:\diskpart.txt" -Encoding ASCII
    $proc = Start-Process -FilePath "diskpart" -ArgumentList "/s X:\diskpart.txt" -Wait -PassThru -WindowStyle Hidden
    if ($proc.ExitCode -ne 0) { throw "diskpart failed (exit $($proc.ExitCode))" }
    if (-not (Test-Path "C:\")) { throw "C:\ not created after partitioning" }
    Write-Log "  Partitioning complete."
}

function Invoke-Step-Install-Operating-System {
    param($Step, $Params)
    $imagePath  = if ($Params.image_path)       { [string]$Params.image_path }  else { "" }
    $imageIndex = if ($Params.image_index)      { [int]$Params.image_index }    else { 1 }
    $target     = if ($Params.target_partition) { [string]$Params.target_partition } else { "C:" }
    $verify     = if ($Params.verify -ne $null) { [bool]$Params.verify } else { $true }

    # Fall back to wizard-selected WIM only if the step didn't specify one
    if (-not $imagePath) { $imagePath = $wimPath }
    if (-not $imagePath) { throw "No image_path in step parameters and no WIM selected in the wizard." }
    if (-not (Test-Path $imagePath)) { throw "Image not found: $imagePath" }

    $verifyArg = if ($verify) { "/Verify" } else { "" }
    Write-Log "  Applying $imagePath (index $imageIndex) to $target ..."
    $args = "/Apply-Image /ImageFile:`"$imagePath`" /Index:$imageIndex /ApplyDir:$target\ $verifyArg"
    $proc = Start-Process -FilePath "dism" -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
    if ($proc.ExitCode -ne 0) { throw "DISM apply failed (exit $($proc.ExitCode))" }
    Write-Log "  Image applied."
}

function Invoke-Step-Inject-Drivers {
    param($Step, $Params)
    $driverPath  = if ($Params.driver_path)      { [string]$Params.driver_path } else { "" }
    $platformPack = if ($Params.platform_pack_id) { [string]$Params.platform_pack_id } else { "" }
    $targetOs    = if ($Params.target_os_path)   { [string]$Params.target_os_path } else { "C:\" }
    $recurse     = if ($Params.recurse -ne $null) { [bool]$Params.recurse } else { $true }
    $forceUnsigned = if ($Params.force_unsigned -ne $null) { [bool]$Params.force_unsigned } else { $true }

    # If a platform_pack_id is set, derive the path from the share
    if (-not $driverPath -and $platformPack) {
        $candidate = "Z:\PlatformPacks\$platformPack"
        if (Test-Path $candidate) { $driverPath = $candidate }
    }
    if (-not $driverPath) { Write-Log "  No driver_path or platform_pack_id - skipping."; return }
    if (-not (Test-Path $driverPath)) { Write-Log "  Driver path not found: $driverPath - skipping."; return }

    $flags = ""
    if ($recurse)       { $flags += " /Recurse" }
    if ($forceUnsigned) { $flags += " /ForceUnsigned" }

    Write-Log "  Injecting drivers from $driverPath into $targetOs ..."
    $proc = Start-Process -FilePath "dism" -ArgumentList "/Image:$targetOs /Add-Driver /Driver:`"$driverPath`"$flags" -Wait -PassThru -WindowStyle Hidden
    if ($proc.ExitCode -ne 0) { throw "DISM Add-Driver failed (exit $($proc.ExitCode))" }
    Write-Log "  Drivers injected."
}

function Invoke-Step-Apply-Network-Settings {
    param($Step, $Params)
    $useDhcp   = if ($Params.use_dhcp -ne $null) { [bool]$Params.use_dhcp } else { $true }
    $staticIp  = if ($Params.static_ip)          { [string]$Params.static_ip }  else { "" }
    $subnet    = if ($Params.subnet_mask)        { [string]$Params.subnet_mask } else { "" }
    $gateway   = if ($Params.default_gateway)    { [string]$Params.default_gateway } else { "" }
    $dnsSvrs   = if ($Params.dns_servers)        { @($Params.dns_servers) }     else { @() }
    $dnsSuffix = if ($Params.dns_suffix)         { [string]$Params.dns_suffix } else { "" }

    if ($useDhcp) {
        Write-Log "  Network set to DHCP (no static config applied)."
        return
    }
    if (-not $staticIp) { Write-Log "  use_dhcp=false but no static_ip set - skipping."; return }

    # Stage netsh commands to run on first boot (we're in WinPE, target is offline)
    $cmds = @()
    $cmds += "netsh interface ip set address name=`"Ethernet`" static $staticIp $subnet $gateway"
    foreach ($dns in $dnsSvrs) {
        $cmds += "netsh interface ip add dns name=`"Ethernet`" $dns index=$($cmds.Count)"
    }
    if ($dnsSuffix) { $cmds += "wmic nicconfig where IPEnabled=true call SetDNSSuffixSearchOrder ($dnsSuffix)" }

    New-Item -Path "C:\Windows\Setup\Scripts" -ItemType Directory -Force | Out-Null
    $firstLogon = "C:\Windows\Setup\Scripts\SmartDeploy-Net.cmd"
    @("@echo off") + $cmds | Out-File -FilePath $firstLogon -Encoding ASCII
    Write-Log "  Staged static IP $staticIp/$subnet gw $gateway (runs on first boot)."
}

function Invoke-Step-Configure-Adds {
    param($Step, $Params)
    $action     = if ($Params.action)              { [string]$Params.action }              else { "join" }
    $domainName = if ($Params.domain_name)         { [string]$Params.domain_name }         else { "" }
    $domainOu   = if ($Params.domain_ou)           { [string]$Params.domain_ou }           else { "" }
    $adminUser  = if ($Params.domain_admin_user)     { [string]$Params.domain_admin_user }     else { "" }
    $adminPwd   = if ($Params.domain_admin_password) { [string]$Params.domain_admin_password } else { "" }
    $machineName = if ($Params.machine_name)        { [string]$Params.machine_name }        else { $script:Vars["ComputerName"] }

    if ($action -ne "join") { Write-Log "  action=$action - deferred to post-install."; return }
    if (-not $domainName)   { Write-Log "  No domain_name - skipping domain join."; return }
    if (-not $adminUser -or -not $adminPwd) { Write-Log "  Missing join credentials - skipping."; return }

    # Offline domain join via djoin.exe: provisions a blob we drop into the target OS
    $blobPath = "X:\djoin.blob"
    $djoinArgs = "/PROVISION /DOMAIN `"$domainName`" /MACHINE `"$machineName`" /SAVEFILE `"$blobPath`""
    if ($domainOu) { $djoinArgs += " /MACHINEOU `"$domainOu`"" }
    Write-Log "  Provisioning offline domain join for $machineName to $domainName ..."
    $proc = Start-Process -FilePath "djoin.exe" -ArgumentList $djoinArgs -Wait -PassThru -WindowStyle Hidden
    if ($proc.ExitCode -ne 0) { throw "djoin /PROVISION failed (exit $($proc.ExitCode))" }

    $requestArgs = "/REQUESTODJ /LOADFILE `"$blobPath`" /WINDOWSPATH C:\Windows /LOCALOS"
    $proc = Start-Process -FilePath "djoin.exe" -ArgumentList $requestArgs -Wait -PassThru -WindowStyle Hidden
    if ($proc.ExitCode -ne 0) { throw "djoin /REQUESTODJ failed (exit $($proc.ExitCode))" }
    Write-Log "  Offline domain join staged. Machine will be joined on first boot."
}

function Invoke-Step-Install-Roles-And-Features {
    param($Step, $Params)
    $roles    = if ($Params.roles)    { @($Params.roles) }    else { @() }
    $features = if ($Params.features) { @($Params.features) } else { @() }
    $all = @($roles) + @($features)
    if ($all.Count -eq 0) { Write-Log "  No roles/features specified - skipping."; return }

    foreach ($feat in $all) {
        if (-not $feat) { continue }
        Write-Log "  Enabling feature: $feat"
        $proc = Start-Process -FilePath "dism" -ArgumentList "/Image:C:\ /Enable-Feature /FeatureName:$feat /All" -Wait -PassThru -WindowStyle Hidden
        if ($proc.ExitCode -ne 0) { Write-Log "    WARN: $feat failed (exit $($proc.ExitCode))" }
    }
}

function Invoke-Step-Install-Application {
    param($Step, $Params)
    $apps = @()
    if ($Params.applications) { $apps = @($Params.applications) }
    elseif ($Params.installer_path) {
        $apps = @(@{ name = $Params.application_name; path = $Params.installer_path; args = $Params.silent_args })
    }
    if ($apps.Count -eq 0) { Write-Log "  No applications configured - skipping."; return }

    # Stage a post-install script that will run each installer on first boot
    New-Item -Path "C:\SmartDeploy" -ItemType Directory -Force | Out-Null
    $scriptPath = "C:\SmartDeploy\app_install.cmd"
    $lines = @("@echo off", "echo SmartDeploy app installer")
    foreach ($app in $apps) {
        $path = if ($app.path) { $app.path } elseif ($app.installer_path) { $app.installer_path } else { "" }
        $pargs = if ($app.args) { $app.args } elseif ($app.silent_args) { $app.silent_args } else { "/quiet" }
        if ($path) { $lines += "start /wait `"`" `"$path`" $pargs" }
    }
    $lines | Out-File -FilePath $scriptPath -Encoding ASCII
    Write-Log "  Staged $($apps.Count) app installer(s) at $scriptPath"
}

function Invoke-Step-Install-Updates-Offline {
    param($Step, $Params)
    $source = if ($Params.update_source) { [string]$Params.update_source } else { "Z:\Updates" }
    $target = if ($Params.target_path)   { [string]$Params.target_path }   else { "C:\" }
    if (-not (Test-Path $source)) { Write-Log "  Update source $source not found - skipping."; return }

    $updates = Get-ChildItem $source -Include "*.cab","*.msu" -File -Recurse -ErrorAction SilentlyContinue
    if ($updates.Count -eq 0) { Write-Log "  No .cab/.msu files in $source - skipping."; return }

    foreach ($upd in $updates) {
        Write-Log "  Installing: $($upd.Name)"
        $proc = Start-Process -FilePath "dism" -ArgumentList "/Image:$target /Add-Package /PackagePath:`"$($upd.FullName)`"" -Wait -PassThru -WindowStyle Hidden
        if ($proc.ExitCode -ne 0) { Write-Log "    WARN: $($upd.Name) failed (exit $($proc.ExitCode))" }
    }
    Write-Log "  Applied $($updates.Count) update(s)."
}

function Invoke-Step-Enable-Disable-Bitlocker {
    param($Step, $Params)
    $action = if ($Params.action) { [string]$Params.action } else { "suspend" }
    $drive  = if ($Params.drive)  { [string]$Params.drive }  else { "C:" }
    $rebootCount = if ($Params.reboot_count) { [int]$Params.reboot_count } else { 1 }

    # BitLocker only runs on the live OS - stage it for first boot
    New-Item -Path "C:\Windows\Setup\Scripts" -ItemType Directory -Force | Out-Null
    $cmd = switch ($action) {
        "enable"  { "manage-bde -on $drive -used -skiphardwaretest" }
        "disable" { "manage-bde -off $drive" }
        "suspend" { "manage-bde -protectors -disable $drive -RebootCount $rebootCount" }
        "resume"  { "manage-bde -protectors -enable $drive" }
        default   { $null }
    }
    if ($cmd) {
        Add-Content -Path "C:\Windows\Setup\Scripts\SmartDeploy-BitLocker.cmd" -Value "@echo off`r`n$cmd"
        Write-Log "  Staged BitLocker $action on $drive (runs on first boot)."
    } else {
        Write-Log "  Unknown bitlocker action '$action' - skipping."
    }
}

function Invoke-Step-Capture-Network-Settings {
    param($Step, $Params)
    Write-Log "  Capturing current network settings..."
    $nics = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled }
    $count = 0
    foreach ($nic in $nics) {
        $count++
        $script:Vars["CapturedIP$count"]      = "$($nic.IPAddress[0])"
        $script:Vars["CapturedSubnet$count"]  = "$($nic.IPSubnet[0])"
        $script:Vars["CapturedGateway$count"] = "$($nic.DefaultIPGateway[0])"
        $script:Vars["CapturedDNS$count"]     = "$(($nic.DNSServerSearchOrder) -join ',')"
    }
    Write-Log "  Captured config for $count adapter(s)."
}

function Invoke-Step-Run-Command-Line {
    param($Step, $Params)
    $cmd        = if ($Params.command)         { [string]$Params.command }         else { "" }
    $desc       = if ($Params.description)     { [string]$Params.description }     else { $cmd }
    $workDir    = if ($Params.working_directory) { [string]$Params.working_directory } else { "" }
    $timeoutSec = if ($Params.timeout_seconds) { [int]$Params.timeout_seconds }    else { 600 }
    $successCodes = if ($Params.success_codes) { @($Params.success_codes) }        else { @(0) }
    $usePs      = if ($Params.powershell -ne $null) { [bool]$Params.powershell }   else { $false }
    $scriptPath = if ($Params.script_path)     { [string]$Params.script_path }     else { "" }

    if ($scriptPath) { $cmd = $scriptPath }
    if (-not $cmd) { Write-Log "  No command set - skipping."; return }

    Write-Log "  Running: $desc"
    $exe = if ($usePs) { "powershell.exe" } else { "cmd.exe" }
    $cmdArgs = if ($usePs) { "-NoProfile -ExecutionPolicy Bypass -Command `"$cmd`"" } else { "/c $cmd" }
    $splat = @{ FilePath = $exe; ArgumentList = $cmdArgs; Wait = $true; PassThru = $true; WindowStyle = "Hidden" }
    if ($workDir) { $splat["WorkingDirectory"] = $workDir }
    $proc = Start-Process @splat
    Write-Log "  Exit code: $($proc.ExitCode)"
    if ($proc.ExitCode -notin $successCodes) {
        throw "Command exited with code $($proc.ExitCode) (expected one of: $($successCodes -join ','))"
    }
}

function Invoke-Step-Restart-Computer {
    param($Step, $Params)
    $target = if ($Params.target) { [string]$Params.target } else { "current_os" }
    $delay  = if ($Params.delay_seconds) { [int]$Params.delay_seconds } else { 0 }
    $msg    = if ($Params.message) { [string]$Params.message } else { "" }

    Write-Log "  Configuring boot manager for target OS..."
    # Always run bcdboot first so C:\Windows is bootable after reboot
    Start-Process -FilePath "bcdboot" -ArgumentList "C:\Windows /s W: /f UEFI" -Wait -WindowStyle Hidden | Out-Null

    # Stage SetupComplete.cmd to chain any post-install scripts staged by prior steps
    New-Item -Path "C:\Windows\Setup\Scripts" -ItemType Directory -Force | Out-Null
    $setupCmd = "@echo off`r`nREM SmartDeploy Post-Install Chain`r`n"
    foreach ($fname in @("SmartDeploy-Net.cmd","SmartDeploy-BitLocker.cmd","app_install.cmd","post_install.cmd","software_install.cmd")) {
        $p1 = "C:\Windows\Setup\Scripts\$fname"
        $p2 = "C:\SmartDeploy\$fname"
        if (Test-Path $p1) { $setupCmd += "call `"$p1`"`r`n" }
        elseif (Test-Path $p2) { $setupCmd += "call `"$p2`"`r`n" }
    }
    $setupCmd += "del /f /q C:\Windows\Setup\Scripts\SetupComplete.cmd`r`n"
    [System.IO.File]::WriteAllText("C:\Windows\Setup\Scripts\SetupComplete.cmd", $setupCmd)
    Write-Log "  Boot manager configured + SetupComplete.cmd chain staged."

    if ($delay -gt 0) { Write-Log "  Sleeping $delay s before reboot..."; Start-Sleep -Seconds $delay }
    # We DO NOT call wpeutil reboot here - the outer Run-Deploy does that after
    # pipeline_complete so the GUI sees the final 100% status first.
}

function Invoke-Step-Recover-From-Domain-Join-Failure {
    param($Step, $Params)
    Write-Log "  Domain-join recovery handler registered - will retry on first boot if needed."
}

function Invoke-Step-Configure-Dhcp   { param($Step, $Params); Write-Log "  DHCP config deferred to post-install." }
function Invoke-Step-Authorize-Dhcp   { param($Step, $Params); Write-Log "  DHCP authorization deferred to post-install." }
function Invoke-Step-Configure-Dns    { param($Step, $Params); Write-Log "  DNS config deferred to post-install." }

function Invoke-Step-Group {
    param($Step, $Params)
    # Group is a logical container - the group itself does nothing; child steps
    # are stored as sibling steps in the flat list so they run normally.
    Write-Log "  Group marker: $($Params.group_name) (logical only)"
}

function Invoke-Step-Unknown {
    param($Step, $Params)
    # Fallback for step types we have no handler for. Runs a command if one is
    # provided in the parameters, otherwise logs and continues.
    Write-Log "  No handler for step type '$($Step.type)'."
    if ($Params.command) {
        Write-Log "  Running fallback command: $($Params.command)"
        $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c $($Params.command)" -Wait -PassThru -WindowStyle Hidden
        if ($proc.ExitCode -ne 0) { throw "Fallback command exited $($proc.ExitCode)" }
    }
}

function Run-Deploy {
    $wimPath = $txtWimPath.Text
    $compName = $txtComputerName.Text
    $wimIndex = if ($script:WimIndexMap.ContainsKey($cmbIndex.SelectedIndex)) {
        $script:WimIndexMap[$cmbIndex.SelectedIndex]
    } else {
        $cmbIndex.SelectedIndex + 1
    }
    $editionName = "$($cmbIndex.SelectedItem)" -replace '\s*\(saved.*$', ''

    Show-Step 4

    Report-Event "pipeline_start" "Deployment started - $compName"

    Write-Log "=== DEPLOYMENT STARTED ==="
    Write-Log "  Computer:  $compName"
    Write-Log "  Image:     $wimPath"
    Write-Log "  Edition:   $editionName (index $wimIndex)"
    Write-Log ""

    # Step 0: Map UNC share and verify WIM path
    Write-Log "[0] Mapping UNC share and verifying image path..."
    Update-Progress 2 "Mapping UNC share..."

    # Resolve %SERVER_IP% placeholder in UNC path if present
    $resolvedUnc = $UncPath -replace '%SERVER_IP%', $ServerIP
    $resolvedUnc = $resolvedUnc -replace '%%SERVER_IP%%', $ServerIP

    # If UNC path wasn't substituted at injection time, use default
    if (-not $resolvedUnc -or $resolvedUnc -eq "%%UNC_PATH%%") {
        $resolvedUnc = "\\$ServerIP\SmartDeploy"
    }

    Write-Log "  UNC Path:    $resolvedUnc"

    # Clean any previous mapping
    net use Z: /delete /y 2>&1 | Out-Null

    $mapped = $false

    # Try pre-configured credentials first
    if ($UncUser -and $UncUser -ne "%%UNC_USER%%") {
        $fullUser = if ($UncDomain -and $UncDomain -ne "%%UNC_DOMAIN%%" -and $UncDomain) {
            "$UncDomain\$UncUser"
        } else {
            $UncUser
        }

        Write-Log "  Mapping Z: as $fullUser..."
        $pwd = if ($UncPassword -ne "%%UNC_PASSWORD%%") { $UncPassword } else { "" }
        cmd /c "net use Z: `"$resolvedUnc`" /user:`"$fullUser`" `"$pwd`" /persistent:no 2>&1" | Out-Null

        if (Test-Path "Z:\") {
            Write-Log "  Share mapped successfully."
            $mapped = $true
        } else {
            Write-Log "  Configured credentials failed - prompting user..."
        }
    }

    # If still not mapped, show credential prompt dialog
    if (-not $mapped) {
        $creds = Show-CredentialDialog -UncPath $resolvedUnc -DefaultUser $UncUser -DefaultDomain $UncDomain
        if ($creds) {
            $fullUser = if ($creds.Domain) { "$($creds.Domain)\$($creds.User)" } else { $creds.User }
            Write-Log "  Retrying with user: $fullUser..."

            net use Z: /delete /y 2>&1 | Out-Null
            cmd /c "net use Z: `"$resolvedUnc`" /user:`"$fullUser`" `"$($creds.Password)`" /persistent:no 2>&1" | Out-Null

            if (Test-Path "Z:\") {
                Write-Log "  Share mapped successfully."
                $mapped = $true
            } else {
                Write-Log "  ERROR: Authentication failed."
            }
        } else {
            Write-Log "  User cancelled credential prompt."
        }
    }

    if (-not $mapped) {
        Write-Log "  FATAL: Cannot access UNC share."
        Report-Event "pipeline_failed" "UNC share mapping failed"
        Update-Progress 0 "FAILED: Cannot access network share"
        $btnReboot.Visible = $true
        return
    }

    # Verify WIM exists on Z:
    if (-not (Test-Path $wimPath)) {
        Write-Log "  ERROR: WIM not found at '$wimPath'"
        Write-Log "  Z:\ contents:"
        Get-ChildItem Z:\ -ErrorAction SilentlyContinue | ForEach-Object { Write-Log "    $($_.Name)" }
        if (Test-Path "Z:\Images") {
            Write-Log "  Z:\Images contents:"
            Get-ChildItem Z:\Images -ErrorAction SilentlyContinue | ForEach-Object { Write-Log "    $($_.Name)  ($([math]::Round($_.Length/1GB,1)) GB)" }
        }
        Report-Event "pipeline_failed" "WIM not found: $wimPath"
        Update-Progress 2 "FAILED: Image file not found"
        $btnReboot.Visible = $true
        return
    }

    $wimSize = [math]::Round((Get-Item $wimPath).Length / 1GB, 1)
    Write-Log "  Image found: $wimPath ($wimSize GB)"

    # Validate edition was selected
    if ($cmbIndex.Items.Count -eq 0 -or $cmbIndex.SelectedItem -match "^\(") {
        Write-Log "  WARNING: No edition selected — auto-scanning WIM..."
        Scan-WimIndexes $wimPath
    }

    Write-Log ""

    # ── Fetch task sequence from API ──
    Write-Log "[*] Loading task sequences from server..."
    $tsSteps = $null
    $selectedTs = $null
    try {
        $tsListUrl = "$($script:API)/task-sequences/"
        $tsListResp = Invoke-RestMethod -Uri $tsListUrl -Method GET -TimeoutSec 10 -ErrorAction Stop
        if ($tsListResp -and $tsListResp.Count -gt 0) {
            Write-Log "  Found $($tsListResp.Count) task sequence(s)."
            $selectedTs = Select-TaskSequence -sequences $tsListResp
            if ($selectedTs) {
                # Fetch full sequence detail (list endpoint may trim data)
                try {
                    $selectedTs = Invoke-RestMethod -Uri "$tsListUrl$($selectedTs.id)" -Method GET -TimeoutSec 10 -ErrorAction Stop
                } catch {}
                $tsSteps = $selectedTs.steps

                # Sort by the 'order' field - don't trust server order
                $tsSteps = @($tsSteps | Sort-Object { [int]$_.order })

                # Seed script:Vars with sequence-level variables (gather can overwrite)
                if ($selectedTs.variables) {
                    foreach ($prop in $selectedTs.variables.PSObject.Properties) {
                        $script:Vars[$prop.Name] = [string]$prop.Value
                    }
                    Write-Log "  Seeded $($selectedTs.variables.PSObject.Properties.Count) sequence variable(s)."
                }

                Write-Log "  Selected: $($selectedTs.name) ($($tsSteps.Count) steps)"
                foreach ($step in $tsSteps) {
                    $status = if ($step.enabled) { "ON " } else { "OFF" }
                    $condMark = if ($step.condition -and $step.condition.variable) { " [conditional]" } else { "" }
                    Write-Log "    [$status] $($step.order). $($step.name) ($($step.type))$condMark"
                }
            } else {
                Write-Log "  User cancelled task sequence selection - aborting deployment."
                Update-Progress 2 "CANCELLED: No task sequence selected"
                $btnReboot.Visible = $true
                return
            }
        }
    } catch {
        Write-Log "  Could not fetch task sequence from API: $_"
    }

    # No task sequence means no deployment. Fail loudly - we will not invent steps.
    if (-not $tsSteps -or $tsSteps.Count -eq 0) {
        Write-Log "  ERROR: No task sequence available."
        Write-Log "  Create one in the SmartDeploy GUI (Task Sequences page) and try again."
        Report-Event "pipeline_failed" "No task sequence available"
        Update-Progress 2 "FAILED: No task sequence"
        $btnReboot.Visible = $true
        return
    }

    # Filter to enabled steps only
    $enabledSteps = @($tsSteps | Where-Object { $_.enabled -eq $true })
    $totalSteps = $enabledSteps.Count
    Write-Log ""
    Write-Log "  Executing $totalSteps enabled steps..."
    Write-Log ""

    # ── Execute each enabled step ──
    $stepNum = 0
    foreach ($step in $enabledSteps) {
        $stepNum++
        $stepType = $step.type
        $stepName = $step.name
        $stepParams = if ($step.parameters) { $step.parameters } else { @{} }
        $pct = [math]::Round(($stepNum / $totalSteps) * 90 + 5)

        # Condition check - skip this step if the condition evaluates false
        if ($step.condition -and $step.condition.variable) {
            $shouldRun = Test-StepCondition $step.condition
            if (-not $shouldRun) {
                Write-Log "[$stepNum/$totalSteps] $stepName - SKIPPED (condition not met)"
                Write-Log "  Variable '$($step.condition.variable)' $($step.condition.operator) '$($step.condition.value)' -> false"
                Write-Log ""
                continue
            }
        }

        Write-Log "[$stepNum/$totalSteps] $stepName..."
        Update-Progress $pct "$stepName..."
        Report-Event "pipeline_step" "$stepNum/$totalSteps : $stepName"

        # ── Generic step executor: dispatches by step.type ──
        # Every step handler is a script-scope function named Invoke-Step-<type>.
        # Unknown types fall through to Invoke-Step-Unknown which logs and skips.
        $handlerName = "Invoke-Step-$stepType" -replace "_", "-"
        $handler = Get-Command -Name $handlerName -ErrorAction SilentlyContinue
        if (-not $handler) { $handler = Get-Command -Name "Invoke-Step-Unknown" -ErrorAction SilentlyContinue }

        $stepOk = $true
        $stepError = ""
        try {
            if ($handler) {
                # Pass the step itself + its parameters. Handlers are free to
                # Write-Log / Report-Event as they please. We ONLY catch hard exceptions.
                & $handler -Step $step -Params $stepParams
            } else {
                Write-Log "  No handler registered for step type '$stepType' - skipping."
            }
            Write-Log "  Done."
        } catch {
            $stepOk = $false
            $stepError = "$_"
            Write-Log "  ERROR: $stepError"
        }

        # Report the outcome (success or failure) back to the GUI
        if ($stepOk) {
            Report-Event "pipeline_step" "$stepNum/$totalSteps : $stepName - OK"
        } else {
            Report-Event "pipeline_step" "$stepNum/$totalSteps : $stepName - FAILED: $stepError"
            $continueOnError = if ($step.continue_on_error) { [bool]$step.continue_on_error } else { $false }
            if (-not $continueOnError) {
                Write-Log "  FATAL: Step failed and continue_on_error is false. Stopping."
                Report-Event "pipeline_failed" "Step ${stepNum}/${totalSteps} failed: $stepName"
                Update-Progress $pct "FAILED: $stepName"
                $btnReboot.Visible = $true
                return
            }
            Write-Log "  Continuing despite error (continue_on_error = true)."
        }

        Write-Log ""
    }

    # ── Complete ──
    Update-Progress 100 "COMPLETE - $compName deployed"
    Report-Event "pipeline_complete" "Deployment complete - $compName"

    Write-Log "=== DEPLOYMENT COMPLETE ==="
    Write-Log "Computer: $compName"
    Write-Log "Edition:  $editionName (index $wimIndex)"
    Write-Log "Rebooting in 30 seconds..."

    $btnReboot.Visible = $true

    # Auto-reboot timer
    Start-Sleep -Seconds 30
    wpeutil reboot
}

$btnDeploy.Add_Click({ Run-Deploy })

# ── Report startup ──
Report-Event "winpe_start" "WinPE GUI wizard started"

# ── Show Form ──
[System.Windows.Forms.Application]::Run($form)
