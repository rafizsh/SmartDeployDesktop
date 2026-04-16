# ============================================================================
# SmartDeploy WinPE Deployment Wizard (PowerShell WinForms)
# Runs in WinPE after PXE boot. Replaces HTA which requires mshta.exe.
# ============================================================================

param(
    [string]$ServerIP = "%%SERVER_IP%%",
    [string]$UncPath = "%%UNC_PATH%%",
    [string]$UncUser = "%%UNC_USER%%",
    [string]$UncPassword = "%%UNC_PASSWORD%%",
    [string]$UncDomain = "%%UNC_DOMAIN%%"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ── Global State ──
$script:API = "http://${ServerIP}:8000/api"
$script:MyIP = "detecting..."
$script:MyMAC = "detecting..."
$script:CurrentStep = 0

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
$txtWimPath.Text = "Z:\Images\install.wim"
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
$cmbIndex.Items.AddRange(@("1 - Windows 11 Pro", "2 - Windows 11 Enterprise", "3 - Windows 11 Education"))
$cmbIndex.SelectedIndex = 0
$cmbIndex.Location = New-Object System.Drawing.Point(20, 180)
$cmbIndex.Size = New-Object System.Drawing.Size(300, 28)
$cmbIndex.BackColor = $BgSurface
$cmbIndex.ForeColor = $TextPrimary
$cmbIndex.FlatStyle = "Flat"
$cmbIndex.DropDownStyle = "DropDownList"
$p1.Controls.Add($cmbIndex)

# Auto-detect WIM
if (Test-Path "Z:\Images\install.wim") {
    $wimSize = [math]::Round((Get-Item "Z:\Images\install.wim").Length / 1GB, 1)
    $lblImgStatus.Text = "Found: Z:\Images\install.wim ($wimSize GB)"
    $lblImgStatus.ForeColor = $AccentGreen
} else {
    $lblImgStatus.Text = "install.wim not found on Z:\ — enter path manually"
    $lblImgStatus.ForeColor = $AccentYellow
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

$reviewPanel = New-Object System.Windows.Forms.Panel
$reviewPanel.Location = New-Object System.Drawing.Point(20, 55)
$reviewPanel.Size = New-Object System.Drawing.Size(540, 180)
$reviewPanel.BackColor = $BgDark
$p3.Controls.Add($reviewPanel)

$lblReview = New-Object System.Windows.Forms.Label
$lblReview.Text = "(review loads when you reach this step)"
$lblReview.ForeColor = $AccentGreen
$lblReview.Font = New-Object System.Drawing.Font("Consolas", 10)
$lblReview.Location = New-Object System.Drawing.Point(12, 12)
$lblReview.Size = New-Object System.Drawing.Size(516, 156)
$reviewPanel.Controls.Add($lblReview)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "WARNING: All data on Disk 0 will be permanently erased!"
$lbl.ForeColor = $AccentRed
$lbl.Location = New-Object System.Drawing.Point(20, 250)
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
        $idx = ($cmbIndex.SelectedIndex + 1)
        $lblReview.Text = "Image:          $($txtWimPath.Text)`nImage Index:     $idx`nComputer Name:   $($txtComputerName.Text)`nDisk Layout:     GPT / UEFI`nServer:          $ServerIP`nDrivers:         Z:\Drivers (if available)`nUnattend.xml:    Z:\AnswerFiles (if available)"
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

function Run-Deploy {
    $wimPath = $txtWimPath.Text
    $compName = $txtComputerName.Text
    $wimIndex = $cmbIndex.SelectedIndex + 1

    Show-Step 4

    Report-Event "pipeline_start" "Deployment started - $compName"

    Write-Log "=== DEPLOYMENT STARTED ==="
    Write-Log ""

    # Step 0: Map UNC share and verify WIM path
    Write-Log "[0/7] Mapping UNC share and verifying image path..."
    Update-Progress 2 "Mapping UNC share..."

    # Resolve %SERVER_IP% placeholder in UNC path if present
    $resolvedUnc = $UncPath -replace '%SERVER_IP%', $ServerIP
    $resolvedUnc = $resolvedUnc -replace '%%SERVER_IP%%', $ServerIP

    # If UNC path wasn't substituted at injection time, use default
    if (-not $resolvedUnc -or $resolvedUnc -eq "%%UNC_PATH%%") {
        $resolvedUnc = "\\$ServerIP\SmartDeploy"
    }

    Write-Log "  UNC Path:    $resolvedUnc"
    Write-Log "  UNC User:    $(if ($UncUser -and $UncUser -ne '%%UNC_USER%%') { $UncUser } else { '(none)' })"
    Write-Log "  UNC Domain:  $(if ($UncDomain -and $UncDomain -ne '%%UNC_DOMAIN%%') { $UncDomain } else { '(none)' })"

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
            Write-Log "  Share mapped successfully with configured credentials."
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
        Get-ChildItem Z:\ -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Log "    $($_.Name)"
        }
        if (Test-Path "Z:\Images") {
            Write-Log "  Z:\Images contents:"
            Get-ChildItem Z:\Images -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Log "    $($_.Name)  ($([math]::Round($_.Length/1GB,1)) GB)"
            }
        }
        Report-Event "pipeline_failed" "WIM not found: $wimPath"
        Update-Progress 2 "FAILED: Image file not found"
        $btnReboot.Visible = $true
        return
    }

    $wimSize = [math]::Round((Get-Item $wimPath).Length / 1GB, 1)
    Write-Log "  Image found: $wimPath ($wimSize GB)"

    # Step 1: Partition
    Write-Log ""
    Write-Log "[1/7] Partitioning disk (GPT/UEFI)..."
    Update-Progress 5 "Partitioning disk..."
    Report-Event "pipeline_step" "1: Partitioning disk"

    $dpScript = @"
select disk 0
clean
convert gpt
create partition efi size=260
format fs=fat32 quick label="System"
assign letter=S
create partition msr size=16
create partition primary
format fs=ntfs quick label="Windows"
assign letter=W
exit
"@
    $dpScript | Out-File -FilePath "X:\diskpart.txt" -Encoding ASCII
    $proc = Start-Process -FilePath "diskpart" -ArgumentList "/s X:\diskpart.txt" -Wait -PassThru -WindowStyle Hidden
    if ($proc.ExitCode -ne 0) {
        Write-Log "  ERROR: diskpart failed (exit: $($proc.ExitCode))"
        Report-Event "pipeline_failed" "diskpart failed"
        Update-Progress 5 "FAILED: Disk partitioning error"
        $btnReboot.Visible = $true
        return
    }
    if (-not (Test-Path "W:\")) {
        Write-Log "  ERROR: W:\ partition not created"
        Report-Event "pipeline_failed" "W: not created"
        Update-Progress 5 "FAILED: Partition not created"
        $btnReboot.Visible = $true
        return
    }
    Write-Log "  Done (W:\ ready, S:\ ready)"

    # Step 2: Apply image
    Write-Log ""
    Write-Log "[2/7] Applying Windows image..."
    Write-Log "  Image: $wimPath"
    Write-Log "  Index: $wimIndex"
    Write-Log "  This will take 10-20 minutes..."
    Update-Progress 14 "Applying Windows image (10-20 min)..."
    Report-Event "pipeline_step" "2: Applying Windows image"

    $proc = Start-Process -FilePath "dism" -ArgumentList "/Apply-Image /ImageFile:`"$wimPath`" /Index:$wimIndex /ApplyDir:W:\" -Wait -PassThru -WindowStyle Hidden
    if ($proc.ExitCode -ne 0) {
        Write-Log "  ERROR: DISM failed (exit: $($proc.ExitCode))"
        Write-Log "  Common causes:"
        Write-Log "    exit 2: index not found in WIM"
        Write-Log "    exit 3: path doesn't exist (check $wimPath)"
        Write-Log "    exit 5: access denied (run WinPE as admin)"
        Write-Log "    exit 50: WIM corrupted"
        Write-Log "    exit 112: disk full"
        Report-Event "pipeline_failed" "DISM apply failed exit $($proc.ExitCode)"
        Update-Progress 14 "FAILED: Image apply error"
        $btnReboot.Visible = $true
        return
    }
    Write-Log "  Image applied successfully."

    # Step 3: Inject drivers
    Write-Log ""
    Write-Log "[3/7] Injecting drivers..."
    Update-Progress 40 "Injecting drivers..."
    Report-Event "pipeline_step" "3: Injecting drivers"

    if (Test-Path "Z:\Drivers") {
        Start-Process -FilePath "dism" -ArgumentList "/Image:W:\ /Add-Driver /Driver:`"Z:\Drivers`" /Recurse /ForceUnsigned" -Wait -WindowStyle Hidden
        Write-Log "  Drivers injected."
    } else {
        Write-Log "  No driver folder found - skipping."
    }

    # Step 4: Unattend.xml
    Write-Log ""
    Write-Log "[4/7] Applying unattend.xml..."
    Update-Progress 55 "Applying unattend.xml..."
    Report-Event "pipeline_step" "4: Applying unattend.xml"

    $unattendPath = ""
    if (Test-Path "Z:\AnswerFiles\unattend.xml") { $unattendPath = "Z:\AnswerFiles\unattend.xml" }
    elseif (Test-Path "Z:\unattend.xml") { $unattendPath = "Z:\unattend.xml" }

    if ($unattendPath) {
        New-Item -Path "W:\Windows\Panther" -ItemType Directory -Force | Out-Null
        $unattendContent = Get-Content $unattendPath -Raw
        $unattendContent = $unattendContent -replace '<ComputerName>\*</ComputerName>', "<ComputerName>$compName</ComputerName>"
        [System.IO.File]::WriteAllText("W:\Windows\Panther\unattend.xml", $unattendContent)
        Write-Log "  Applied with computer name: $compName"
    } else {
        Write-Log "  No unattend.xml found - using OOBE."
    }

    # Step 5: Task sequences
    Write-Log ""
    Write-Log "[5/7] Running task sequence scripts..."
    Update-Progress 68 "Task sequences..."
    Report-Event "pipeline_step" "5: Task sequence scripts"

    if (Test-Path "Z:\TaskSequences") {
        if (Test-Path "Z:\TaskSequences\pre_install.cmd") {
            Write-Log "  Running pre_install.cmd..."
            Start-Process -FilePath "cmd" -ArgumentList "/c Z:\TaskSequences\pre_install.cmd" -Wait -WindowStyle Hidden
        }
        New-Item -Path "W:\SmartDeploy" -ItemType Directory -Force | Out-Null
        if (Test-Path "Z:\TaskSequences\post_install.cmd") {
            Copy-Item "Z:\TaskSequences\post_install.cmd" "W:\SmartDeploy\post_install.cmd" -Force
            Write-Log "  Staged post_install.cmd"
        }
        if (Test-Path "Z:\TaskSequences\software_install.cmd") {
            Copy-Item "Z:\TaskSequences\software_install.cmd" "W:\SmartDeploy\software_install.cmd" -Force
            Write-Log "  Staged software_install.cmd"
        }
    } else {
        Write-Log "  No task sequences found - skipping."
    }

    # Step 6: Boot config
    Write-Log ""
    Write-Log "[6/7] Configuring boot manager..."
    Update-Progress 82 "Configuring boot..."
    Report-Event "pipeline_step" "6: Boot configuration"

    Start-Process -FilePath "bcdboot" -ArgumentList "W:\Windows /s S: /f UEFI" -Wait -WindowStyle Hidden

    # Create SetupComplete.cmd
    New-Item -Path "W:\Windows\Setup\Scripts" -ItemType Directory -Force | Out-Null
    @"
@echo off
REM SmartDeploy Post-Install
if exist C:\SmartDeploy\post_install.cmd call C:\SmartDeploy\post_install.cmd
if exist C:\SmartDeploy\software_install.cmd call C:\SmartDeploy\software_install.cmd
del /f /q C:\Windows\Setup\Scripts\SetupComplete.cmd
"@ | Out-File -FilePath "W:\Windows\Setup\Scripts\SetupComplete.cmd" -Encoding ASCII
    Write-Log "  Boot configured + SetupComplete.cmd staged."

    # Step 7: Complete
    Write-Log ""
    Write-Log "[7/7] Deployment complete!"
    Update-Progress 100 "COMPLETE - $compName deployed"
    Report-Event "pipeline_complete" "Deployment complete - $compName"

    Write-Log ""
    Write-Log "=== DEPLOYMENT COMPLETE ==="
    Write-Log "Computer: $compName"
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
