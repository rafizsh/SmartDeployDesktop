using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Net.Http;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using SmartDeployDesktop.Services;

namespace SmartDeployDesktop.ViewModels
{
    public partial class MainViewModel : BaseViewModel
    {
        // Navigation
        [ObservableProperty] private string _currentPage = "Dashboard";
        [ObservableProperty] private bool _isServerConnected;
        [ObservableProperty] private string _serverStatus = "Connecting...";
        [ObservableProperty] private bool _isSettingsPage;
        [ObservableProperty] private bool _isServicesPage;
        [ObservableProperty] private bool _isPxeStatusPage;
        [ObservableProperty] private bool _isTaskSequencesPage;
        [ObservableProperty] private bool _isDashboardPage = true;
        [ObservableProperty] private bool _isImagesPage;
        [ObservableProperty] private bool _isDeploymentsPage;
        [ObservableProperty] private bool _isContentPage;
        [ObservableProperty] private string _activeDeployCount = "";

        // Sub-ViewModels for each page
        public DashboardViewModel Dashboard { get; }
        public ImagesViewModel Images { get; }
        public PlatformPacksViewModel PlatformPacks { get; }
        public DeploymentViewModel Deployment { get; }
        public DismViewModel Dism { get; }
        public TaskSequencesViewModel TaskSequences { get; }
        public HardwareViewModel Hardware { get; }
        public SettingsViewModel Settings { get; }
        public ServicesViewModel Services { get; }
        public PxeStatusViewModel PxeStatus { get; }
        public DeploymentsViewModel Deployments { get; }

        private readonly DispatcherTimer _healthTimer;

        public MainViewModel() : base(new ApiClient())
        {
            // Initialize sub-ViewModels sharing the same API client
            Dashboard = new DashboardViewModel(Api);
            Settings = new SettingsViewModel(Api);
            Images = new ImagesViewModel(Api, Settings);
            PlatformPacks = new PlatformPacksViewModel(Api);
            Deployment = new DeploymentViewModel(Api);
            Dism = new DismViewModel(Api);
            TaskSequences = new TaskSequencesViewModel(Api);
            Hardware = new HardwareViewModel(Api);
            Services = new ServicesViewModel(Api);
            PxeStatus = new PxeStatusViewModel(Api);
            Deployments = new DeploymentsViewModel(Api);

            // Health check timer (every 10 seconds) + deployment/service refresh
            _healthTimer = new DispatcherTimer
            {
                Interval = TimeSpan.FromSeconds(10)
            };
            _healthTimer.Tick += async (s, e) =>
            {
                // Avoid overlapping ticks if health / refresh runs longer than the interval.
                _healthTimer.Stop();
                try
                {
                    await CheckServerHealthAsync();
                    await Services.RefreshStatusAsync();

                    // Auto-refresh deployments if on that page or dashboard
                    if (IsDeploymentsPage || IsDashboardPage)
                    {
                        try
                        {
                            await Deployments.RefreshAsync();
                            // Update sidebar badge
                            var activeCount = 0;
                            if (Deployments.Clients != null)
                            {
                                foreach (var c in Deployments.Clients)
                                {
                                    var status = c?.GetType().GetProperty("Status")?.GetValue(c)?.ToString() ?? "";
                                    if (status == "pipeline_step" || status == "pipeline_start" || status == "winpe_start")
                                        activeCount++;
                                }
                            }
                            ActiveDeployCount = activeCount > 0 ? activeCount.ToString() : "";
                        }
                        catch { }
                    }
                }
                finally
                {
                    _healthTimer.Start();
                }
            };
            _healthTimer.Start();

            // Initial load
            _ = InitializeAsync();
        }

        private async Task InitializeAsync()
        {
            await CheckServerHealthAsync();

            if (IsServerConnected)
            {
                await Dashboard.LoadAsync();
            }
        }

        [RelayCommand]
        private async Task NavigateTo(string page)
        {
            CurrentPage = page;
            IsDashboardPage = page == "Dashboard";
            IsImagesPage = page == "Images";
            IsTaskSequencesPage = page == "TaskSequences";
            IsSettingsPage = page == "Settings";
            IsServicesPage = page == "Services";
            IsPxeStatusPage = false; // merged into Deployments
            IsDeploymentsPage = page == "Deployments";
            IsContentPage = false; // no longer used

            // Load data for the target page
            switch (page)
            {
                case "Dashboard":
                    await Dashboard.LoadAsync();
                    break;
                case "Images":
                    await Images.LoadAsync();
                    break;
                case "TaskSequences":
                    await TaskSequences.LoadAsync();
                    break;
                case "Settings":
                    await Settings.LoadAsync();
                    break;
                case "Services":
                    await Services.RefreshStatusAsync();
                    break;
                case "PXEStatus":
                    await PxeStatus.RefreshAsync();
                    break;
                case "Deployments":
                    await Deployments.RefreshAsync();
                    break;
            }
        }

        [RelayCommand]
        private async Task RefreshCurrentPage()
        {
            await NavigateTo(CurrentPage);
        }

        private async Task CheckServerHealthAsync()
        {
            try
            {
                bool healthy = await Api.IsServerHealthyAsync();
                IsServerConnected = healthy;
                ServerStatus = healthy ? "Connected" : "Disconnected";
            }
            catch
            {
                IsServerConnected = false;
                ServerStatus = "Disconnected";
            }
        }
    }

    // ========================================================================
    // Dashboard ViewModel
    // ========================================================================

    public partial class DashboardViewModel : BaseViewModel
    {
        [ObservableProperty] private DashboardStatsDto? _stats;
        [ObservableProperty] private ObservableCollection<LogEntryDto> _recentLogs = new();

        public DashboardViewModel(ApiClient api) : base(api) { }

        public async Task LoadAsync()
        {
            await RunAsync(async () =>
            {
                Stats = await Api.GetDashboardStatsAsync();
                var logs = await Api.GetLogsAsync(50);
                RecentLogs = new ObservableCollection<LogEntryDto>(logs);
            }, "Loading dashboard...");
        }
    }

    // ========================================================================
    // Images ViewModel
    // ========================================================================

    public partial class ImagesViewModel : BaseViewModel
    {
        [ObservableProperty] private ObservableCollection<WimImageDto> _images = new();
        [ObservableProperty] private WimImageDto? _selectedImage;
        [ObservableProperty] private ObservableCollection<WimIndexDto> _selectedImageIndexes = new();
        [ObservableProperty] private string _imageCountText = "No images found";

        private readonly SettingsViewModel? settingsVm;

        public ImagesViewModel(ApiClient api, SettingsViewModel? settings = null) : base(api)
        {
            settingsVm = settings;
        }

        public async Task LoadAsync()
        {
            await RunAsync(async () =>
            {
                var list = await Api.GetImagesAsync();
                Images = new ObservableCollection<WimImageDto>(list);
                ImageCountText = list.Count > 0
                    ? $"{list.Count} image(s) found"
                    : "No .wim files found in C:\\SmartDeploy\\Images\\";
            }, "Loading images...");
        }

        [RelayCommand]
        private async Task SelectImage(WimImageDto image)
        {
            SelectedImage = image;
            await RunAsync(async () =>
            {
                var indexes = await Api.GetImageInfoAsync(image.Name);
                SelectedImageIndexes = new ObservableCollection<WimIndexDto>(indexes);
            }, "Loading image info...");
        }

        [RelayCommand]
        private async Task DeleteImage(WimImageDto image)
        {
            await RunAsync(async () =>
            {
                await Api.DeleteImageAsync(image.Name);
                Images.Remove(image);
                if (SelectedImage == image) SelectedImage = null;
                ShowStatus($"Deleted {image.Name}");
            });
        }

        [RelayCommand]
        private async Task ImportImage(string sourcePath)
        {
            await RunAsync(async () =>
            {
                await Api.ImportImageAsync(sourcePath);
                await LoadAsync();
                ShowStatus("Image imported successfully");
            }, "Importing image...");
        }

        // Driver Injection
        [ObservableProperty] private string _driverInjectWimPath = @"C:\RemoteInstall\sources\boot.wim";
        [ObservableProperty] private string _driverInjectFolder = @"C:\SmartDeploy\Drivers";
        [ObservableProperty] private string _driverInjectIndex = "1";
        [ObservableProperty] private ObservableCollection<string> _driverInjectLog = new();

        [RelayCommand]
        private void UseBootWim()
        {
            DriverInjectWimPath = @"C:\RemoteInstall\sources\boot.wim";
            DriverInjectIndex = "1";
            ShowStatus("Set to boot.wim (WinPE)");
        }

        [RelayCommand]
        private void UseSelectedImage()
        {
            if (SelectedImage != null)
            {
                DriverInjectWimPath = SelectedImage.Path;
                DriverInjectIndex = "1";
                ShowStatus($"Set to {SelectedImage.Name}");
            }
            else
            {
                ShowStatus("No image selected — click an image first");
            }
        }

        [RelayCommand]
        private async Task InjectDrivers()
        {
            if (string.IsNullOrWhiteSpace(DriverInjectWimPath))
            {
                ShowStatus("Enter a WIM file path");
                return;
            }
            if (string.IsNullOrWhiteSpace(DriverInjectFolder))
            {
                ShowStatus("Enter a driver folder path");
                return;
            }

            var log = new ObservableCollection<string>();
            DriverInjectLog = log;

            var idx = int.TryParse(DriverInjectIndex, out var i) ? i : 1;
            var wimPath = DriverInjectWimPath;
            var driverFolder = DriverInjectFolder;

            void AddLog(string msg) => System.Windows.Application.Current.Dispatcher.Invoke(() => log.Add(msg));

            await Task.Run(() =>
            {
                try
                {
                    AddLog("=== DRIVER INJECTION ===");
                    AddLog($"WIM: {wimPath}");
                    AddLog($"Drivers: {driverFolder}");
                    AddLog($"Index: {idx}");
                    AddLog("");

                    // PRE-FLIGHT: Check WIM
                    if (!System.IO.File.Exists(wimPath))
                    {
                        AddLog($"ERROR: WIM not found: {wimPath}");
                        return;
                    }
                    var wimSize = new System.IO.FileInfo(wimPath).Length / 1024 / 1024;
                    AddLog($"  WIM size: {wimSize} MB");

                    // Remove read-only if set
                    var attr = System.IO.File.GetAttributes(wimPath);
                    if (attr.HasFlag(System.IO.FileAttributes.ReadOnly))
                    {
                        System.IO.File.SetAttributes(wimPath, attr & ~System.IO.FileAttributes.ReadOnly);
                        AddLog("  Removed read-only attribute");
                    }

                    // PRE-FLIGHT: Check drivers
                    if (!System.IO.Directory.Exists(driverFolder))
                    {
                        AddLog($"ERROR: Driver folder not found: {driverFolder}");
                        return;
                    }
                    var infFiles = System.IO.Directory.GetFiles(driverFolder, "*.inf", System.IO.SearchOption.AllDirectories);
                    AddLog($"  Found {infFiles.Length} .inf driver file(s)");
                    if (infFiles.Length == 0)
                    {
                        AddLog("ERROR: No .inf files found. Put driver folders in the driver path.");
                        return;
                    }
                    AddLog("");

                    // STEP 1: CLEANUP
                    AddLog("[1/4] Cleaning up stale mounts...");
                    NuclearDismCleanup(AddLog);

                    // STEP 2: MOUNT
                    AddLog("");
                    AddLog("[2/4] Mounting WIM image...");

                    string mountDir = "";
                    string[] candidates = {
                        @"C:\SmartDeploy\Mount\drivers",
                        System.IO.Path.Combine(System.IO.Path.GetTempPath(), "SD_Driver_Mount"),
                    };
                    foreach (var c in candidates)
                    {
                        try
                        {
                            if (System.IO.Directory.Exists(c))
                                System.IO.Directory.Delete(c, true);
                            System.IO.Directory.CreateDirectory(c);
                            var tf = System.IO.Path.Combine(c, "t.tmp");
                            System.IO.File.WriteAllText(tf, "t");
                            System.IO.File.Delete(tf);
                            mountDir = c;
                            AddLog($"  Mount dir: {c}");
                            break;
                        }
                        catch { AddLog($"  Skip: {c} (not writable)"); }
                    }
                    if (string.IsNullOrEmpty(mountDir))
                    {
                        AddLog("ERROR: No writable mount directory!");
                        return;
                    }

                    var (mCode, mOut, mErr) = RunCmdCapture("dism",
                        $"/Mount-Wim /WimFile:\"{wimPath}\" /Index:{idx} /MountDir:\"{mountDir}\"");

                    if (mCode != 0)
                    {
                        AddLog($"  Mount failed (code {mCode})");
                        if (mErr.Contains("already mounted") || mErr.Contains("0xc1420127"))
                        {
                            AddLog("  WIM already mounted — force cleanup and retry...");
                            RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{mountDir}\" /Discard");
                            RunCmdCapture("dism", "/Cleanup-Mountpoints");
                            RunCmdCapture("dism", "/Cleanup-Wim");
                            if (System.IO.Directory.Exists(mountDir))
                                try { System.IO.Directory.Delete(mountDir, true); } catch { }
                            System.IO.Directory.CreateDirectory(mountDir);
                            (mCode, mOut, mErr) = RunCmdCapture("dism",
                                $"/Mount-Wim /WimFile:\"{wimPath}\" /Index:{idx} /MountDir:\"{mountDir}\"");
                        }
                        if (mCode != 0)
                        {
                            AddLog($"  ERROR: {mErr.Substring(0, Math.Min(mErr.Length, 300))}");
                            AddLog("  Fix: Reboot machine, get fresh WIM, try again");
                            return;
                        }
                    }

                    var sys32 = System.IO.Path.Combine(mountDir, "Windows", "System32");
                    if (!System.IO.Directory.Exists(sys32))
                    {
                        AddLog("ERROR: Mount is empty — no Windows\\System32");
                        RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{mountDir}\" /Discard");
                        return;
                    }
                    AddLog("  Mounted successfully");

                    // STEP 3: INJECT DRIVERS
                    AddLog("");
                    AddLog($"[3/4] Injecting {infFiles.Length} driver(s)...");
                    AddLog($"  DISM /Image:\"{mountDir}\" /Add-Driver /Driver:\"{driverFolder}\" /Recurse /ForceUnsigned");
                    AddLog("  This may take several minutes...");

                    var (dCode, dOut, dErr) = RunCmdCapture("dism",
                        $"/Image:\"{mountDir}\" /Add-Driver /Driver:\"{driverFolder}\" /Recurse /ForceUnsigned");

                    if (dCode != 0)
                    {
                        AddLog($"  WARNING: DISM returned code {dCode}");
                        if (!string.IsNullOrEmpty(dErr))
                            AddLog($"  {dErr.Substring(0, Math.Min(dErr.Length, 300))}");
                        AddLog("  Some drivers may have failed — continuing with commit");
                    }

                    // Parse DISM output for driver count
                    int addedCount = 0;
                    foreach (var line in dOut.Split('\n'))
                    {
                        var trimmed = line.Trim();
                        if (trimmed.Contains(".inf") && (trimmed.Contains("installed") || trimmed.Contains("added")))
                            addedCount++;
                        // Show interesting lines
                        if (trimmed.Contains("Total") || trimmed.Contains("installed") || trimmed.Contains("Warning"))
                            AddLog($"  {trimmed}");
                    }
                    if (addedCount > 0)
                        AddLog($"  {addedCount} driver(s) processed");
                    else
                        AddLog("  Drivers processed (count not available from DISM output)");

                    // STEP 4: COMMIT
                    AddLog("");
                    AddLog("[4/4] Committing changes (1-2 minutes)...");

                    var (cCode, _, cErr) = RunCmdCapture("dism",
                        $"/Unmount-Wim /MountDir:\"{mountDir}\" /Commit");

                    if (cCode != 0)
                    {
                        AddLog($"  Commit failed: {cErr.Substring(0, Math.Min(cErr.Length, 300))}");
                        AddLog("  Discarding changes...");
                        RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{mountDir}\" /Discard");
                        AddLog("  Fix: Reboot, fresh WIM, try again");
                        return;
                    }

                    try { System.IO.Directory.Delete(mountDir, true); } catch { }

                    AddLog("");
                    AddLog("SUCCESS! Drivers injected into WIM.");
                    AddLog($"  WIM: {wimPath}");
                    AddLog($"  Drivers: {infFiles.Length} .inf files from {driverFolder}");
                    AddLog("=== COMPLETE ===");

                    System.Windows.Application.Current.Dispatcher.Invoke(() =>
                        ShowStatus($"Drivers injected into {System.IO.Path.GetFileName(wimPath)}"));
                }
                catch (Exception ex)
                {
                    AddLog($"ERROR: {ex.Message}");
                    System.Windows.Application.Current.Dispatcher.Invoke(() =>
                        ShowStatus($"Driver injection failed: {ex.Message}"));
                }
            });
        }

        // WinPE Agent Injection
        [ObservableProperty] private string _winpeWimPath = @"C:\RemoteInstall\sources\boot.wim";
        [ObservableProperty] private string _winpeServerIp = "10.10.10.1";
        [ObservableProperty] private ObservableCollection<string> _winpeInjectLog = new();

        [RelayCommand]
        private async Task CreateSmbShare()
        {
            var log = new ObservableCollection<string>();
            WinpeInjectLog = log;

            void AddLog(string msg) => System.Windows.Application.Current.Dispatcher.Invoke(() => log.Add(msg));

            await Task.Run(async () =>
            {
                AddLog("Creating SMB share for C:\\SmartDeploy...");
                try
                {
                    var psi = new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = "powershell",
                        Arguments = "-NoProfile -Command \"New-SmbShare -Name 'SmartDeploy' -Path 'C:\\SmartDeploy' -FullAccess 'Everyone' -ErrorAction Stop; Write-Host 'SHARE_OK'\"",
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                        Verb = "runas",
                    };
                    var proc = System.Diagnostics.Process.Start(psi);
                    if (proc != null)
                    {
                        var output = await proc.StandardOutput.ReadToEndAsync();
                        var err = await proc.StandardError.ReadToEndAsync();
                        await proc.WaitForExitAsync();

                        if (output.Contains("SHARE_OK") || output.Contains("SmartDeploy"))
                        {
                            AddLog("✅ Share created: \\\\<server>\\SmartDeploy → C:\\SmartDeploy");
                            AddLog("   WinPE clients can now access images via SMB");
                        }
                        else if (err.Contains("already"))
                        {
                            AddLog("✅ Share already exists: \\\\<server>\\SmartDeploy");
                        }
                        else
                        {
                            AddLog($"⚠️ {err.Trim()}");
                            AddLog("Try running as Administrator:");
                            AddLog("  New-SmbShare -Name 'SmartDeploy' -Path 'C:\\SmartDeploy' -FullAccess 'Everyone'");
                        }
                    }
                }
                catch (Exception ex)
                {
                    AddLog($"❌ {ex.Message}");
                    AddLog("Run manually as Admin:");
                    AddLog("  New-SmbShare -Name 'SmartDeploy' -Path 'C:\\SmartDeploy' -FullAccess 'Everyone'");
                }
            });
        }

        [RelayCommand]
        private async Task InjectWinpeAgent()
        {
            var log = new ObservableCollection<string>();
            WinpeInjectLog = log;

            var wimPath = WinpeWimPath;
            var serverIp = WinpeServerIp;

            void AddLog(string msg) => System.Windows.Application.Current.Dispatcher.Invoke(() => log.Add(msg));

            await Task.Run(() =>
            {
                try
                {
                    AddLog("=== WINPE AGENT INJECTION ===");
                    AddLog($"WIM: {wimPath}");
                    AddLog($"Server IP: {serverIp}");
                    AddLog("");

                    // PRE-FLIGHT
                    if (!System.IO.File.Exists(wimPath))
                    {
                        AddLog($"ERROR: boot.wim not found: {wimPath}");
                        AddLog("  Copy from Windows ISO: copy D:\\sources\\boot.wim C:\\RemoteInstall\\sources\\boot.wim");
                        return;
                    }
                    var size = new System.IO.FileInfo(wimPath).Length / 1024 / 1024;
                    AddLog($"  WIM size: {size} MB");

                    var attr = System.IO.File.GetAttributes(wimPath);
                    if (attr.HasFlag(System.IO.FileAttributes.ReadOnly))
                    {
                        System.IO.File.SetAttributes(wimPath, attr & ~System.IO.FileAttributes.ReadOnly);
                        AddLog("  Removed read-only attribute");
                    }

                    // STEP 1: AGGRESSIVE CLEANUP
                    AddLog("");
                    AddLog("[1/5] Cleaning up ALL stale mounts...");
                    NuclearDismCleanup(AddLog);

                    // STEP 2: FIND MOUNT DIR
                    AddLog("");
                    AddLog("[2/5] Preparing mount directory...");
                    string mountDir = "";
                    string[] candidates = {
                        @"C:\SmartDeploy\Mount\winpe",
                        System.IO.Path.Combine(System.IO.Path.GetTempPath(), "SD_WinPE_Mount"),
                    };
                    foreach (var c in candidates)
                    {
                        try
                        {
                            if (System.IO.Directory.Exists(c))
                                System.IO.Directory.Delete(c, true);
                            System.IO.Directory.CreateDirectory(c);
                            var tf = System.IO.Path.Combine(c, "t.tmp");
                            System.IO.File.WriteAllText(tf, "t");
                            System.IO.File.Delete(tf);
                            mountDir = c;
                            AddLog($"  Using: {c}");
                            break;
                        }
                        catch { AddLog($"  Skip: {c} (not writable)"); }
                    }
                    if (string.IsNullOrEmpty(mountDir))
                    {
                        AddLog("ERROR: No writable mount directory found!");
                        return;
                    }

                    // STEP 3: MOUNT
                    AddLog("");
                    AddLog("[3/5] Mounting boot.wim (30-60 seconds)...");
                    var (mCode, mOut, mErr) = RunCmdCapture("dism",
                        $"/Mount-Wim /WimFile:\"{wimPath}\" /Index:1 /MountDir:\"{mountDir}\"");

                    if (mCode != 0)
                    {
                        AddLog($"  Mount failed (code {mCode})");
                        if (mErr.Contains("already mounted") || mErr.Contains("0xc1420127"))
                        {
                            AddLog("  WIM already mounted - force cleanup and retry...");
                            RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{mountDir}\" /Discard");
                            RunCmdCapture("dism", "/Cleanup-Mountpoints");
                            RunCmdCapture("dism", "/Cleanup-Wim");
                            if (System.IO.Directory.Exists(mountDir))
                                try { System.IO.Directory.Delete(mountDir, true); } catch { }
                            System.IO.Directory.CreateDirectory(mountDir);
                            (mCode, mOut, mErr) = RunCmdCapture("dism",
                                $"/Mount-Wim /WimFile:\"{wimPath}\" /Index:1 /MountDir:\"{mountDir}\"");
                        }
                        if (mCode != 0)
                        {
                            AddLog($"  ERROR: {mErr.Substring(0, Math.Min(mErr.Length, 300))}");
                            AddLog("  Fix: Reboot machine, get fresh boot.wim from ISO, try again");
                            return;
                        }
                    }

                    var sys32 = System.IO.Path.Combine(mountDir, "Windows", "System32");
                    if (!System.IO.Directory.Exists(sys32))
                    {
                        AddLog("ERROR: Mount is empty - no Windows\\System32");
                        AddLog("  WIM may be corrupt. Get fresh copy from ISO.");
                        RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{mountDir}\" /Discard");
                        return;
                    }
                    AddLog("  Mounted successfully");

                    // STEP 4: INJECT
                    AddLog("");
                    AddLog("[4/5] Injecting SmartDeploy agent...");
                    var startnet = BuildStartnetScript(serverIp);
                    try
                    {
                        System.IO.File.WriteAllText(
                            System.IO.Path.Combine(sys32, "startnet.cmd"),
                            startnet, System.Text.Encoding.ASCII);
                        AddLog("  startnet.cmd created");
                    }
                    catch (Exception ex)
                    {
                        AddLog($"  ERROR writing startnet.cmd: {ex.Message}");
                        RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{mountDir}\" /Discard");
                        return;
                    }

                    // Inject PowerShell + .NET optional components (needed for GUI wizard)
                    try
                    {
                        AddLog("");
                        AddLog("  Injecting PowerShell + .NET optional components...");

                        // ADK WinPE OC paths (x64)
                        string[] adkBases = {
                            @"C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit\Windows Preinstallation Environment\amd64\WinPE_OCs",
                            @"C:\Program Files\Windows Kits\10\Assessment and Deployment Kit\Windows Preinstallation Environment\amd64\WinPE_OCs",
                        };

                        string adkBase = "";
                        foreach (var b in adkBases)
                        {
                            if (System.IO.Directory.Exists(b)) { adkBase = b; break; }
                        }

                        if (string.IsNullOrEmpty(adkBase))
                        {
                            AddLog("  WARNING: Windows ADK WinPE add-on not found!");
                            AddLog("  Install from: https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install");
                            AddLog("  The WinPE GUI wizard requires PowerShell which is not in base boot.wim");
                            AddLog("  Required: Windows ADK + 'Windows PE Add-on for the Windows ADK'");
                        }
                        else
                        {
                            AddLog($"  ADK found: {adkBase}");

                            // Required packages in correct order (dependencies first)
                            // WMI → NetFx → Scripting → PowerShell → DismCmdlets → SecureStartup → DISM
                            var packages = new (string name, string file)[] {
                                ("WMI",         "WinPE-WMI.cab"),
                                ("WMI Lang",    "en-us\\WinPE-WMI_en-us.cab"),
                                (".NET Framework", "WinPE-NetFx.cab"),
                                (".NET Framework Lang", "en-us\\WinPE-NetFx_en-us.cab"),
                                ("Scripting",   "WinPE-Scripting.cab"),
                                ("Scripting Lang", "en-us\\WinPE-Scripting_en-us.cab"),
                                ("PowerShell",  "WinPE-PowerShell.cab"),
                                ("PowerShell Lang", "en-us\\WinPE-PowerShell_en-us.cab"),
                                ("DISM Cmdlets", "WinPE-DismCmdlets.cab"),
                                ("DISM Cmdlets Lang", "en-us\\WinPE-DismCmdlets_en-us.cab"),
                                ("StorageWMI",  "WinPE-StorageWMI.cab"),
                                ("StorageWMI Lang", "en-us\\WinPE-StorageWMI_en-us.cab"),
                                ("Secure Boot Cmdlets", "WinPE-SecureBootCmdlets.cab"),
                                ("Enhanced Storage", "WinPE-EnhancedStorage.cab"),
                                ("Enhanced Storage Lang", "en-us\\WinPE-EnhancedStorage_en-us.cab"),
                                ("MDAC (SQL)",  "WinPE-MDAC.cab"),
                                ("MDAC Lang",   "en-us\\WinPE-MDAC_en-us.cab"),
                                ("HTA",         "WinPE-HTA.cab"),
                                ("HTA Lang",    "en-us\\WinPE-HTA_en-us.cab"),
                                ("Font Support", "WinPE-FontSupport-WinRE.cab"),
                                ("Dot3 Services (802.1x)", "WinPE-Dot3Svc.cab"),
                                ("Dot3 Lang",   "en-us\\WinPE-Dot3Svc_en-us.cab"),
                            };

                            int addedCount = 0;
                            foreach (var (name, file) in packages)
                            {
                                var pkgPath = System.IO.Path.Combine(adkBase, file);
                                if (!System.IO.File.Exists(pkgPath))
                                {
                                    continue;  // Optional language packs may not exist
                                }

                                var dismArgs = $"/Image:\"{mountDir}\" /Add-Package /PackagePath:\"{pkgPath}\"";
                                AddLog($"  dism {dismArgs}");

                                var (pkCode, _, pkErr) = RunCmdCapture("dism", dismArgs);

                                if (pkCode == 0)
                                {
                                    AddLog($"  ✓ {name}");
                                    addedCount++;
                                }
                                else if (pkErr.Contains("already present") || pkErr.Contains("0x800f081e"))
                                {
                                    AddLog($"  ✓ {name} (already present)");
                                }
                                else
                                {
                                    AddLog($"  ✗ {name} failed (code {pkCode})");
                                    if (!string.IsNullOrEmpty(pkErr))
                                        AddLog($"    {pkErr.Substring(0, Math.Min(pkErr.Length, 200))}");
                                }
                            }
                            AddLog($"  Added {addedCount} package(s)");
                        }
                    }
                    catch (Exception ex) { AddLog($"  Package injection error: {ex.Message}"); }

                    try
                    {
                        if (System.IO.File.Exists(@"C:\Windows\System32\curl.exe"))
                        {
                            System.IO.File.Copy(@"C:\Windows\System32\curl.exe",
                                System.IO.Path.Combine(sys32, "curl.exe"), true);
                            AddLog("  curl.exe copied");
                        }
                    }
                    catch (Exception ex) { AddLog($"  curl.exe failed: {ex.Message}"); }

                    // Copy deploy_wizard.ps1 (PowerShell GUI wizard - works in WinPE)
                    try
                    {
                        string ps1Src = "";
                        string[] ps1Paths = {
                            System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Server", "winpe", "deploy_wizard.ps1"),
                            System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "Server", "winpe", "deploy_wizard.ps1"),
                            System.IO.Path.Combine(System.IO.Path.GetDirectoryName(wimPath) ?? "", "..", "..", "Server", "winpe", "deploy_wizard.ps1"),
                        };
                        foreach (var p in ps1Paths)
                        {
                            if (System.IO.File.Exists(p)) { ps1Src = p; break; }
                        }

                        if (!string.IsNullOrEmpty(ps1Src))
                        {
                            var ps1Content = System.IO.File.ReadAllText(ps1Src);
                            ps1Content = ps1Content.Replace("%%SERVER_IP%%", serverIp);

                            // Substitute UNC credentials from the UNC tab in Settings
                            // Prefer DeployShare (root share), fall back to ImageShare
                            var uncPath = !string.IsNullOrWhiteSpace(settingsVm?.UncDeployShare)
                                ? settingsVm.UncDeployShare
                                : (settingsVm?.UncImageShare ?? $@"\\{serverIp}\SmartDeploy");
                            ps1Content = ps1Content.Replace("%%UNC_PATH%%",     uncPath ?? "");
                            ps1Content = ps1Content.Replace("%%UNC_USER%%",     settingsVm?.UncUsername ?? "");
                            ps1Content = ps1Content.Replace("%%UNC_PASSWORD%%", settingsVm?.UncPassword ?? "");
                            ps1Content = ps1Content.Replace("%%UNC_DOMAIN%%",   settingsVm?.UncDomain ?? "");

                            System.IO.File.WriteAllText(
                                System.IO.Path.Combine(sys32, "deploy_wizard.ps1"),
                                ps1Content, System.Text.Encoding.UTF8);
                            AddLog($"  deploy_wizard.ps1 copied (UNC: {uncPath}, user: {settingsVm?.UncUsername})");
                        }
                        else
                        {
                            AddLog("  WARNING: deploy_wizard.ps1 not found");
                            AddLog("  Looked in: Server\\winpe\\deploy_wizard.ps1");
                        }
                    }
                    catch (Exception ex) { AddLog($"  PS1 wizard copy failed: {ex.Message}"); }

                    // Also copy deploy_wizard.hta as fallback
                    try
                    {
                        string htaSrc = "";
                        string[] htaPaths = {
                            System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Server", "winpe", "deploy_wizard.hta"),
                            System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "Server", "winpe", "deploy_wizard.hta"),
                            System.IO.Path.Combine(System.IO.Path.GetDirectoryName(wimPath) ?? "", "..", "..", "Server", "winpe", "deploy_wizard.hta"),
                        };
                        foreach (var p in htaPaths)
                        {
                            if (System.IO.File.Exists(p)) { htaSrc = p; break; }
                        }

                        if (!string.IsNullOrEmpty(htaSrc))
                        {
                            var htaContent = System.IO.File.ReadAllText(htaSrc);
                            htaContent = htaContent.Replace("%%SERVER_IP%%", serverIp);
                            System.IO.File.WriteAllText(
                                System.IO.Path.Combine(sys32, "deploy_wizard.hta"),
                                htaContent, System.Text.Encoding.UTF8);
                            AddLog("  deploy_wizard.hta copied (fallback)");
                        }
                    }
                    catch { }

                    // STEP 5: COMMIT
                    AddLog("");
                    AddLog("[5/5] Saving changes (1-2 minutes)...");
                    var (cCode, _, cErr) = RunCmdCapture("dism",
                        $"/Unmount-Wim /MountDir:\"{mountDir}\" /Commit");

                    if (cCode != 0)
                    {
                        AddLog($"  Commit failed: {cErr.Substring(0, Math.Min(cErr.Length, 300))}");
                        AddLog("  Discarding...");
                        RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{mountDir}\" /Discard");
                        AddLog("  Fix: Reboot, fresh boot.wim, try again");
                        return;
                    }

                    try { System.IO.Directory.Delete(mountDir, true); } catch { }

                    AddLog("");
                    AddLog("SUCCESS! WinPE agent injected.");
                    AddLog("");
                    AddLog("Next steps:");
                    AddLog("  1. Ensure SMB share: New-SmbShare -Name SmartDeploy -Path C:\\SmartDeploy -FullAccess Everyone");
                    AddLog("  2. Put install.wim in C:\\SmartDeploy\\Images\\");
                    AddLog("  3. Start DHCP + TFTP");
                    AddLog("  4. PXE boot machine");
                    AddLog("  5. Type 'deploy' at prompt");
                    AddLog("=== COMPLETE ===");

                    System.Windows.Application.Current.Dispatcher.Invoke(() =>
                        ShowStatus("WinPE agent injected - PXE boot to test"));
                }
                catch (Exception ex)
                {
                    AddLog($"ERROR: {ex.Message}");
                }
            });
        }

        private static string BuildStartnetScript(string serverIp)
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("@echo off");
            sb.AppendLine("wpeinit");
            sb.AppendLine("echo.");
            sb.AppendLine("echo   SmartDeploy WinPE Agent v2.0");
            sb.AppendLine("echo   Initializing network...");
            sb.AppendLine("ping -n 5 127.0.0.1 >nul");
            sb.AppendLine();
            sb.AppendLine($"set SERVER_IP={serverIp}");
            sb.AppendLine();
            sb.AppendLine("echo   Waiting for server...");
            sb.AppendLine(":wait_net");
            sb.AppendLine("ping -n 1 %SERVER_IP% >nul 2>&1");
            sb.AppendLine("if errorlevel 1 (");
            sb.AppendLine("    ping -n 3 127.0.0.1 >nul");
            sb.AppendLine("    goto :wait_net");
            sb.AppendLine(")");
            sb.AppendLine("echo   Server reachable.");
            sb.AppendLine();
            sb.AppendLine("echo   Launching deployment wizard...");
            sb.AppendLine("echo   (Wizard will map UNC share using configured credentials)");
            sb.AppendLine();
            sb.AppendLine("if exist \"%SYSTEMROOT%\\System32\\deploy_wizard.ps1\" (");
            sb.AppendLine("    powershell -ExecutionPolicy Bypass -File \"%SYSTEMROOT%\\System32\\deploy_wizard.ps1\" -ServerIP %SERVER_IP%");
            sb.AppendLine(") else if exist \"%SYSTEMROOT%\\System32\\deploy_wizard.hta\" (");
            sb.AppendLine("    mshta \"%SYSTEMROOT%\\System32\\deploy_wizard.hta\"");
            sb.AppendLine(") else (");
            sb.AppendLine("    echo   ERROR: No deployment wizard found!");
            sb.AppendLine("    echo   Dropping to command prompt.");
            sb.AppendLine(")");
            sb.AppendLine("cmd /k");
            return sb.ToString();
        }

        /// <summary>
        /// Aggressively cleans ALL stale DISM mounts. Tries multiple approaches.
        /// </summary>
        private static void NuclearDismCleanup(Action<string> addLog)
        {
            addLog("Cleaning up ALL stale DISM mounts...");

            // 1. Parse Get-MountedWimInfo and unmount each one
            var (_, mountInfo, _) = RunCmdCapture("dism", "/Get-MountedWimInfo");
            var mountDirs = new List<string>();
            foreach (var line in mountInfo.Split('\n'))
            {
                var trimmed = line.Trim();
                if (trimmed.StartsWith("Mount Dir"))
                {
                    var parts = trimmed.Split(':', 2);
                    if (parts.Length > 1)
                    {
                        var dir = parts[1].Trim();
                        if (!string.IsNullOrEmpty(dir))
                            mountDirs.Add(dir);
                    }
                }
            }

            foreach (var dir in mountDirs)
            {
                addLog($"  Unmounting: {dir}");
                RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{dir}\" /Discard");
            }

            // 2. Force cleanup mountpoints (handles orphaned mounts)
            RunCmdCapture("dism", "/Cleanup-Mountpoints");

            // 3. Cleanup-Wim (handles corrupt WIM state)
            RunCmdCapture("dism", "/Cleanup-Wim");

            // 4. Try to unmount known mount directories directly
            string[] knownMountDirs = {
                @"C:\SmartDeploy\Mount\drivers",
                @"C:\SmartDeploy\Mount\winpe",
                @"C:\SmartDeploy\Mount\inject_1",
                @"C:\SmartDeploy\Mount\mount_1",
                @"C:\SD_Driver_Mount",
                @"C:\SD_WinPE_Mount",
                @"C:\SmartDeploy\Mount\driver_list_temp",
                @"C:\WinPE_Mount",
                @"E:\WinPE_Mount",
                @"E:\SD_WinPE_Mount",
                @"E:\SmartDeploy_WinPE_Inject",
            };
            foreach (var dir in knownMountDirs)
            {
                if (System.IO.Directory.Exists(dir))
                {
                    addLog($"  Force unmount: {dir}");
                    RunCmdCapture("dism", $"/Unmount-Wim /MountDir:\"{dir}\" /Discard");
                    try { System.IO.Directory.Delete(dir, true); } catch { }
                }
            }

            // 5. One more cleanup pass
            RunCmdCapture("dism", "/Cleanup-Mountpoints");
            RunCmdCapture("dism", "/Cleanup-Wim");

            // 6. Verify nothing is still mounted
            var (_, checkInfo, _) = RunCmdCapture("dism", "/Get-MountedWimInfo");
            if (checkInfo.Contains("Mount Dir"))
            {
                addLog("  WARNING: Some mounts may still be active.");
                addLog("  If injection fails, reboot the machine to clear all mounts.");
            }
            else
            {
                addLog("  All mounts cleared");
            }
        }

        private static (int exitCode, string stdout, string stderr) RunCmdCapture(string exe, string args)
        {
            // First try running directly (works if already elevated)
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = exe, Arguments = args,
                    UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true,
                };
                var proc = System.Diagnostics.Process.Start(psi);
                if (proc == null) return (-1, "", "Process failed to start");
                var o = proc.StandardOutput.ReadToEnd();
                var e = proc.StandardError.ReadToEnd();
                proc.WaitForExit(300000);

                // If exit code 740, need elevation
                if (proc.ExitCode == 740)
                    return RunCmdElevated(exe, args);

                return (proc.ExitCode, o, e);
            }
            catch (System.ComponentModel.Win32Exception w) when (w.NativeErrorCode == 740)
            {
                return RunCmdElevated(exe, args);
            }
            catch (Exception ex) { return (-1, "", ex.Message); }
        }

        private static (int exitCode, string stdout, string stderr) RunCmdElevated(string exe, string args)
        {
            try
            {
                var tempDir = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "SmartDeploy_Cmd");
                System.IO.Directory.CreateDirectory(tempDir);
                var outFile = System.IO.Path.Combine(tempDir, "stdout.txt");
                var errFile = System.IO.Path.Combine(tempDir, "stderr.txt");
                var exitFile = System.IO.Path.Combine(tempDir, "exitcode.txt");
                var batFile = System.IO.Path.Combine(tempDir, "run.bat");

                // Write batch file that captures output
                var batContent = $"@echo off\r\n\"{exe}\" {args} >\"{outFile}\" 2>\"{errFile}\"\r\necho %ERRORLEVEL% >\"{exitFile}\"\r\n";
                System.IO.File.WriteAllText(batFile, batContent, System.Text.Encoding.ASCII);

                // Delete old output files
                foreach (var f in new[] { outFile, errFile, exitFile })
                    if (System.IO.File.Exists(f)) System.IO.File.Delete(f);

                // Run elevated
                var psi = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = batFile,
                    UseShellExecute = true,
                    Verb = "runas",
                    WindowStyle = System.Diagnostics.ProcessWindowStyle.Hidden,
                    CreateNoWindow = true,
                };
                var proc = System.Diagnostics.Process.Start(psi);
                proc?.WaitForExit(300000);

                // Read output
                var stdout = System.IO.File.Exists(outFile) ? System.IO.File.ReadAllText(outFile) : "";
                var stderr = System.IO.File.Exists(errFile) ? System.IO.File.ReadAllText(errFile) : "";
                var exitCode = 0;
                if (System.IO.File.Exists(exitFile))
                    int.TryParse(System.IO.File.ReadAllText(exitFile).Trim(), out exitCode);

                // Cleanup
                try { System.IO.Directory.Delete(tempDir, true); } catch { }

                return (exitCode, stdout, stderr);
            }
            catch (Exception ex) { return (-1, "", $"Elevation failed: {ex.Message}"); }
        }
    }

    // ========================================================================
    // Platform Packs ViewModel
    // ========================================================================

    public partial class PlatformPacksViewModel : BaseViewModel
    {
        [ObservableProperty] private ObservableCollection<PlatformPackDto> _packs = new();
        [ObservableProperty] private PlatformPackDto? _selectedPack;

        public PlatformPacksViewModel(ApiClient api) : base(api) { }

        public async Task LoadAsync()
        {
            await RunAsync(async () =>
            {
                var list = await Api.GetPlatformPacksAsync();
                Packs = new ObservableCollection<PlatformPackDto>(list);
            }, "Loading platform packs...");
        }

        [RelayCommand]
        private async Task DeletePack(PlatformPackDto pack)
        {
            await RunAsync(async () =>
            {
                await Api.DeletePlatformPackAsync(pack.Id);
                Packs.Remove(pack);
                ShowStatus($"Deleted {pack.Manufacturer} {pack.Model}");
            });
        }
    }

    // ========================================================================
    // Deployment ViewModel
    // ========================================================================

    public partial class DeploymentViewModel : BaseViewModel
    {
        [ObservableProperty] private ObservableCollection<DeploymentDto> _deployments = new();
        [ObservableProperty] private ObservableCollection<UsbDriveDto> _usbDrives = new();
        [ObservableProperty] private ObservableCollection<WimImageDto> _availableImages = new();
        [ObservableProperty] private ObservableCollection<PlatformPackDto> _availablePacks = new();

        // Deploy form fields
        [ObservableProperty] private string _selectedTarget = "usb";
        [ObservableProperty] private string _targetPath = "";
        [ObservableProperty] private WimImageDto? _selectedImage;
        [ObservableProperty] private PlatformPackDto? _selectedPack;
        [ObservableProperty] private bool _formatTarget = true;
        [ObservableProperty] private bool _verifyAfter = true;
        [ObservableProperty] private string _networkShareValidation = "";

        private readonly DispatcherTimer _progressTimer;

        public DeploymentViewModel(ApiClient api) : base(api)
        {
            _progressTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
            _progressTimer.Tick += async (s, e) => await RefreshDeploymentsAsync();
        }

        public async Task LoadAsync()
        {
            await RunAsync(async () =>
            {
                var deployments = await Api.GetDeploymentsAsync();
                Deployments = new ObservableCollection<DeploymentDto>(deployments);

                var images = await Api.GetImagesAsync();
                AvailableImages = new ObservableCollection<WimImageDto>(images);

                var packs = await Api.GetPlatformPacksAsync();
                AvailablePacks = new ObservableCollection<PlatformPackDto>(packs);
            }, "Loading deployment data...");
        }

        [RelayCommand]
        private async Task RefreshUsbDrives()
        {
            await RunAsync(async () =>
            {
                var drives = await Api.GetUsbDrivesAsync();
                UsbDrives = new ObservableCollection<UsbDriveDto>(drives);
            }, "Scanning USB drives...");
        }

        [RelayCommand]
        private async Task ValidateNetworkShare()
        {
            if (string.IsNullOrWhiteSpace(TargetPath)) return;
            await RunAsync(async () =>
            {
                var result = await Api.ValidateNetworkShareAsync(TargetPath);
                NetworkShareValidation = result.Accessible ? "✓ Accessible" : "✗ Not accessible";
            });
        }

        [RelayCommand]
        private async Task StartDeployment()
        {
            if (SelectedImage == null)
            {
                ShowStatus("Select an image first");
                return;
            }

            await RunAsync(async () =>
            {
                var req = new DeploymentRequest
                {
                    ImagePath = SelectedImage.Path,
                    ImageIndex = 1,
                    Target = SelectedTarget,
                    TargetPath = TargetPath,
                    PlatformPackId = SelectedPack?.Id,
                    FormatTarget = FormatTarget,
                    VerifyAfter = VerifyAfter,
                };

                var dep = await Api.StartDeploymentAsync(req);
                Deployments.Insert(0, dep);
                _progressTimer.Start();
                ShowStatus($"Deployment {dep.Id} started");
            }, "Starting deployment...");
        }

        [RelayCommand]
        private async Task CancelDeployment(DeploymentDto deployment)
        {
            await RunAsync(async () =>
            {
                await Api.CancelDeploymentAsync(deployment.Id);
                await RefreshDeploymentsAsync();
                ShowStatus($"Deployment {deployment.Id} cancelled");
            });
        }

        private async Task RefreshDeploymentsAsync()
        {
            try
            {
                var list = await Api.GetDeploymentsAsync();
                Deployments = new ObservableCollection<DeploymentDto>(list);

                // Stop polling if no active deployments
                bool anyActive = false;
                foreach (var d in list)
                {
                    if (d.Status == "in_progress" || d.Status == "pending")
                    {
                        anyActive = true;
                        break;
                    }
                }
                if (!anyActive) _progressTimer.Stop();
            }
            catch { }
        }
    }

    // ========================================================================
    // DISM ViewModel
    // ========================================================================

    public partial class DismViewModel : BaseViewModel
    {
        [ObservableProperty] private ObservableCollection<Dictionary<string, object>> _mountedImages = new();
        [ObservableProperty] private string _lastOperationResult = "";

        // Mount form
        [ObservableProperty] private string _mountImagePath = "";
        [ObservableProperty] private int _mountIndex = 1;
        [ObservableProperty] private string _mountPath = "";
        [ObservableProperty] private bool _mountReadOnly;

        // Apply form
        [ObservableProperty] private string _applyImagePath = "";
        [ObservableProperty] private int _applyIndex = 1;
        [ObservableProperty] private string _applyTargetPath = "";

        // Split form
        [ObservableProperty] private string _splitImagePath = "";
        [ObservableProperty] private string _splitOutputPath = "";
        [ObservableProperty] private int _splitMaxSizeMb = 4000;

        public DismViewModel(ApiClient api) : base(api) { }

        public async Task LoadAsync()
        {
            await RunAsync(async () =>
            {
                var result = await Api.GetMountedImagesAsync();
                MountedImages = new ObservableCollection<Dictionary<string, object>>(result.MountedImages);
            }, "Loading mounted images...");
        }

        [RelayCommand]
        private async Task MountImage()
        {
            await RunAsync(async () =>
            {
                var result = await Api.MountImageAsync(MountImagePath, MountIndex, MountPath, MountReadOnly);
                LastOperationResult = result.Message;
                await LoadAsync();
                ShowStatus(result.Success ? "Image mounted" : "Mount failed");
            }, "Mounting image...");
        }

        [RelayCommand]
        private async Task UnmountImage(string mountPath)
        {
            await RunAsync(async () =>
            {
                var result = await Api.UnmountImageAsync(mountPath, commit: false);
                LastOperationResult = result.Message;
                await LoadAsync();
            }, "Unmounting...");
        }

        [RelayCommand]
        private async Task ApplyImage()
        {
            await RunAsync(async () =>
            {
                var result = await Api.ApplyImageAsync(ApplyImagePath, ApplyIndex, ApplyTargetPath);
                LastOperationResult = result.Message;
                ShowStatus(result.Success ? "Image applied" : "Apply failed");
            }, "Applying image...");
        }

        [RelayCommand]
        private async Task SplitImage()
        {
            await RunAsync(async () =>
            {
                var result = await Api.SplitImageAsync(SplitImagePath, SplitOutputPath, SplitMaxSizeMb);
                LastOperationResult = result.Message;
                ShowStatus(result.Success ? "Image split complete" : "Split failed");
            }, "Splitting image...");
        }

        [RelayCommand]
        private async Task CleanupWim()
        {
            await RunAsync(async () =>
            {
                var result = await Api.CleanupWimAsync();
                LastOperationResult = result.Message;
                await LoadAsync();
                ShowStatus("Cleanup complete");
            }, "Cleaning up...");
        }
    }

    // ========================================================================
    // Task Sequences ViewModel
    // ========================================================================

    public partial class TaskSequencesViewModel : BaseViewModel
    {
        [ObservableProperty] private ObservableCollection<TaskSequenceDto> _taskSequences = new();
        [ObservableProperty] private ObservableCollection<AnswerFileDto> _answerFiles = new();
        [ObservableProperty] private ObservableCollection<TemplateDto> _templates = new();
        [ObservableProperty] private TaskSequenceDto? _selectedSequence;

        // Create form
        [ObservableProperty] private string _newTsName = "";
        [ObservableProperty] private string _newTsDescription = "";
        [ObservableProperty] private string _selectedTemplate = "bare_metal";

        // Answer file form
        [ObservableProperty] private AnswerFileSettingsDto _answerFileSettings = new();
        [ObservableProperty] private string _newAfName = "";

        public TaskSequencesViewModel(ApiClient api) : base(api) { }

        public async Task LoadAsync()
        {
            // Load templates first (needed for the dropdown)
            try
            {
                var tpl = await Api.GetTaskSequenceTemplatesAsync();
                Templates = new ObservableCollection<TemplateDto>(tpl.Templates);
            }
            catch
            {
                // Provide hardcoded fallback if API fails
                Templates = new ObservableCollection<TemplateDto>
                {
                    new() { Id = "bare_metal", Name = "Bare Metal Deployment" },
                    new() { Id = "refresh", Name = "PC Refresh" },
                    new() { Id = "upgrade", Name = "In-Place Upgrade" },
                    new() { Id = "capture", Name = "Reference Image Capture" },
                    new() { Id = "network_deploy", Name = "Network Deployment Server" },
                    new() { Id = "custom", Name = "Custom (Empty)" },
                };
            }

            // Load saved task sequences
            try
            {
                var ts = await Api.GetTaskSequencesAsync();
                TaskSequences = new ObservableCollection<TaskSequenceDto>(ts);
            }
            catch { TaskSequences = new ObservableCollection<TaskSequenceDto>(); }

            // Load answer files
            try
            {
                var af = await Api.GetAnswerFilesAsync();
                AnswerFiles = new ObservableCollection<AnswerFileDto>(af);
            }
            catch { AnswerFiles = new ObservableCollection<AnswerFileDto>(); }
        }

        [RelayCommand]
        private async Task CreateTaskSequence()
        {
            if (string.IsNullOrWhiteSpace(NewTsName))
            {
                ShowStatus("Enter a name for the task sequence");
                return;
            }

            await RunAsync(async () =>
            {
                var req = new CreateTaskSequenceRequest
                {
                    Name = NewTsName,
                    Description = NewTsDescription,
                    Template = SelectedTemplate ?? "bare_metal",
                };
                var created = await Api.CreateTaskSequenceAsync(req);
                TaskSequences.Add(created);
                NewTsName = "";
                NewTsDescription = "";
                ShowStatus($"Created: {created.Name}");
            }, "Creating task sequence...");
        }

        [RelayCommand]
        private async Task DeleteTaskSequence(TaskSequenceDto ts)
        {
            await RunAsync(async () =>
            {
                await Api.DeleteTaskSequenceAsync(ts.Id);
                TaskSequences.Remove(ts);
                ShowStatus($"Deleted: {ts.Name}");
            });
        }

        [RelayCommand]
        private async Task OpenEditor(TaskSequenceDto ts)
        {
            try
            {
                // Fetch the latest copy from the server so we get the full step list
                // (GetTaskSequencesAsync returns all fields but the UI only reads a subset).
                var latest = await Api.GetTaskSequenceAsync(ts.Id);
                var editor = new SmartDeployDesktop.Views.TaskSequenceEditor(Api, latest);
                if (Application.Current?.MainWindow != null)
                    editor.Owner = Application.Current.MainWindow;
                editor.ShowDialog();

                // Refresh the list after close so step counts/names reflect any edits.
                var refreshed = await Api.GetTaskSequencesAsync();
                TaskSequences = new ObservableCollection<TaskSequenceDto>(refreshed);
            }
            catch (Exception ex)
            {
                ShowStatus($"Failed to open editor: {ex.Message}");
            }
        }

        [RelayCommand]
        private async Task ImportTaskSequence()
        {
            var dlg = new Microsoft.Win32.OpenFileDialog
            {
                Filter = "Task Sequence JSON|*.json",
                Title = "Import Task Sequence",
            };
            if (dlg.ShowDialog() != true) return;

            await RunAsync(async () =>
            {
                var json = System.IO.File.ReadAllText(dlg.FileName);
                var payload = Newtonsoft.Json.JsonConvert.DeserializeObject<object>(json);
                var imported = await Api.ImportTaskSequenceAsync(payload!);
                TaskSequences.Add(imported);
                ShowStatus($"Imported: {imported.Name}");
            }, "Importing task sequence...");
        }

        [RelayCommand]
        private async Task GenerateAnswerFile()
        {
            if (string.IsNullOrWhiteSpace(NewAfName)) return;

            await RunAsync(async () =>
            {
                await Api.GenerateAnswerFileAsync(AnswerFileSettings, NewAfName);
                await LoadAsync();
                ShowStatus($"Answer file generated: {NewAfName}");
            }, "Generating answer file...");
        }

        [RelayCommand]
        private async Task DeleteAnswerFile(AnswerFileDto af)
        {
            await RunAsync(async () =>
            {
                await Api.DeleteAnswerFileAsync(af.Id);
                AnswerFiles.Remove(af);
            });
        }
    }

    // ========================================================================
    // Hardware ViewModel
    // ========================================================================

    public partial class HardwareViewModel : BaseViewModel
    {
        [ObservableProperty] private HardwareInfoDto? _hardwareInfo;
        [ObservableProperty] private CompatibilityResultDto? _compatibility;

        public HardwareViewModel(ApiClient api) : base(api) { }

        public async Task LoadAsync()
        {
            await RunAsync(async () =>
            {
                HardwareInfo = await Api.GetHardwareInventoryAsync();
            }, "Scanning hardware...");
        }

        [RelayCommand]
        private async Task CheckCompatibility()
        {
            await RunAsync(async () =>
            {
                Compatibility = await Api.CheckCompatibilityAsync();
                ShowStatus(Compatibility.Compatible ? "System is Windows 11 compatible" : "System does NOT meet Windows 11 requirements");
            }, "Checking Windows 11 compatibility...");
        }
    }

    // ========================================================================
    // Settings ViewModel - Infrastructure Configuration
    // ========================================================================

    public partial class SettingsViewModel : BaseViewModel
    {
        [ObservableProperty] private string _currentTab = "AD";
        [ObservableProperty] private string _currentTabTitle = "Active Directory / Domain Configuration";

        // Tab visibility flags
        [ObservableProperty] private bool _isAdTab = true;
        [ObservableProperty] private bool _isDhcpTab;
        [ObservableProperty] private bool _isTftpTab;
        [ObservableProperty] private bool _isUncTab;
        [ObservableProperty] private bool _isWdsTab;
        [ObservableProperty] private bool _isMdtTab;
        [ObservableProperty] private bool _isDbTab;
        [ObservableProperty] private bool _isAdminTab;

        // Connection status display
        [ObservableProperty] private string _connectionStatusIcon = "⚪";
        [ObservableProperty] private string _connectionStatusText = "Not tested";
        [ObservableProperty] private string _connectionStatusDetail = "Click 'Test Connection' to verify settings";
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _connectionStatusBg =
            new(System.Windows.Media.Color.FromRgb(0x31, 0x32, 0x44));

        // Per-tab status indicator dots (gray=untested, green=ok, yellow=partial, red=fail)
        private static readonly System.Windows.Media.SolidColorBrush _gray = new(System.Windows.Media.Color.FromRgb(0x6C, 0x70, 0x86));
        private static readonly System.Windows.Media.SolidColorBrush _green = new(System.Windows.Media.Color.FromRgb(0xA6, 0xE3, 0xA1));
        private static readonly System.Windows.Media.SolidColorBrush _yellow = new(System.Windows.Media.Color.FromRgb(0xF9, 0xE2, 0xAF));
        private static readonly System.Windows.Media.SolidColorBrush _red = new(System.Windows.Media.Color.FromRgb(0xF3, 0x8B, 0xA8));

        [ObservableProperty] private System.Windows.Media.SolidColorBrush _adStatusColor = _gray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _dhcpStatusColor = _gray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _tftpStatusColor = _gray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _uncStatusColor = _gray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _wdsStatusColor = _gray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _mdtStatusColor = _gray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _dbStatusColor = _gray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _adminStatusColor = _gray;

        // Test results list
        [ObservableProperty] private ObservableCollection<TestResultItemDto> _testResults = new();

        // Database fields
        [ObservableProperty] private string _dbHost = "localhost";
        [ObservableProperty] private string _dbPort = "5432";
        [ObservableProperty] private string _dbName = "smartdeploy";
        [ObservableProperty] private string _dbUser = "smartdeploy";
        [ObservableProperty] private string _dbPassword = "SmartDeploy2026!";
        [ObservableProperty] private string _dbPostgresPassword = "postgres";
        [ObservableProperty] private ObservableCollection<string> _dbSetupLog = new();

        // Admin Credentials (for unattend.xml)
        [ObservableProperty] private string _adminUsername = "Administrator";
        [ObservableProperty] private string _adminPassword = "Password123!";
        [ObservableProperty] private string _adminTimezone = "Eastern Standard Time";
        [ObservableProperty] private string _adminLocale = "en-US";
        [ObservableProperty] private ObservableCollection<string> _adminLog = new();

        // AD fields
        [ObservableProperty] private string _adDomainName = "";
        [ObservableProperty] private string _adDomainController = "";
        [ObservableProperty] private string _adDefaultOu = "";
        [ObservableProperty] private string _adJoinUser = "";
        [ObservableProperty] private string _adJoinPassword = "";
        [ObservableProperty] private string _adMachinePrefix = "WS";
        [ObservableProperty] private string _adNamingTemplate = "%PREFIX%-%SERIAL:8%";
        [ObservableProperty] private string _adLdapPort = "389";
        [ObservableProperty] private string _adSearchBase = "";

        // DHCP - External server (optional)
        [ObservableProperty] private string _dhcpServer = "";

        // DHCP Scope config
        [ObservableProperty] private string _scopeServerIp = "";
        [ObservableProperty] private string _scopeSubnet = "";
        [ObservableProperty] private string _scopeSubnetMask = "255.255.255.0";
        [ObservableProperty] private string _scopeRangeStart = "";
        [ObservableProperty] private string _scopeRangeEnd = "";
        [ObservableProperty] private string _scopeGateway = "";
        [ObservableProperty] private string _scopeDns = "";
        [ObservableProperty] private string _scopeDomain = "HIROFUMI.COM";
        [ObservableProperty] private string _scopeBootServer = "";
        [ObservableProperty] private string _scopeBootFile = "Boot\\x64\\bootmgfw.efi";

        // TFTP fields
        [ObservableProperty] private string _tftpServer = "";
        [ObservableProperty] private string _tftpRootPath = @"C:\RemoteInstall";
        [ObservableProperty] private string _tftpBootImage = "";
        [ObservableProperty] private string _tftpBootFileX64 = @"boot\x64\wdsnbp.com";
        [ObservableProperty] private string _tftpBootFileBios = @"boot\x86\wdsnbp.com";
        [ObservableProperty] private string _tftpPromptTimeout = "5";

        // UNC fields
        [ObservableProperty] private string _uncUsername = "";
        [ObservableProperty] private string _uncPassword = "";
        [ObservableProperty] private string _uncDomain = "";
        [ObservableProperty] private string _uncImageShare = "";
        [ObservableProperty] private string _uncDriverShare = "";
        [ObservableProperty] private string _uncDeployShare = "";
        [ObservableProperty] private string _uncLogShare = "";

        // WDS fields
        [ObservableProperty] private string _wdsServer = "";
        [ObservableProperty] private string _wdsRemoteInstall = "";
        [ObservableProperty] private string _wdsBootImage = "";
        [ObservableProperty] private string _wdsImageGroup = "Windows 11";
        [ObservableProperty] private string _wdsAutoAddPolicy = "AdminApproval";

        // MDT fields
        [ObservableProperty] private string _mdtSharePath = "";
        [ObservableProperty] private string _mdtShareLocal = "";
        [ObservableProperty] private string _mdtToolkitPath = "";
        [ObservableProperty] private string _mdtMonitorHost = "";
        [ObservableProperty] private string _mdtMonitorPort = "9800";
        [ObservableProperty] private string _mdtDbServer = "";
        [ObservableProperty] private string _mdtRulesPath = "";

        public SettingsViewModel(ApiClient api) : base(api) { }

        public async Task LoadAsync()
        {
            try
            {
                var settings = await Api.GetInfrastructureSettingsAsync();
                if (settings != null) await LoadFromDto(settings);
            }
            catch { }
            SwitchToTab(CurrentTab);
        }

        [RelayCommand]
        private void SwitchTab(string tab)
        {
            if (string.IsNullOrEmpty(tab)) return;
            SwitchToTab(tab);
        }

        private void SwitchToTab(string tab)
        {
            CurrentTab = tab;
            IsAdTab = tab == "AD";
            IsDhcpTab = tab == "DHCP";
            IsTftpTab = tab == "TFTP";
            IsUncTab = tab == "UNC";
            IsWdsTab = tab == "WDS";
            IsMdtTab = tab == "MDT";
            IsDbTab = tab == "DB";
            IsAdminTab = tab == "ADMIN";

            CurrentTabTitle = tab switch
            {
                "AD" => "Active Directory / Domain Configuration",
                "DHCP" => "DHCP Server Configuration",
                "TFTP" => "TFTP / PXE Boot Server",
                "UNC" => "UNC Network Share Mount Points",
                "WDS" => "Windows Deployment Services (WDS)",
                "MDT" => "Microsoft Deployment Toolkit (MDT)",
                "DB" => "PostgreSQL Database",
                "ADMIN" => "Administrator Credentials (Unattend.xml)",
                _ => tab,
            };

            // Reset status when switching tabs
            ConnectionStatusIcon = "⚪";
            ConnectionStatusText = "Not tested";
            ConnectionStatusDetail = "Click 'Test Connection' to verify settings";
            ConnectionStatusBg = new System.Windows.Media.SolidColorBrush(
                System.Windows.Media.Color.FromRgb(0x31, 0x32, 0x44));
            TestResults = new ObservableCollection<TestResultItemDto>();
        }

        [RelayCommand]
        private async Task TestConnection()
        {
            // Set testing state
            ConnectionStatusIcon = "🔄";
            ConnectionStatusText = "Testing...";
            ConnectionStatusDetail = $"Verifying {CurrentTabTitle}";
            ConnectionStatusBg = new System.Windows.Media.SolidColorBrush(
                System.Windows.Media.Color.FromRgb(0x31, 0x32, 0x44));
            TestResults = new ObservableCollection<TestResultItemDto>();

            await RunAsync(async () =>
            {
                var result = await Api.TestInfrastructureAsync(CurrentTab);

                if (result?.Results != null)
                {
                    TestResults = new ObservableCollection<TestResultItemDto>(result.Results);

                    int passed = 0, total = result.Results.Count;
                    foreach (var r in result.Results)
                        if (r.Passed) passed++;

                    if (result.Success)
                    {
                        ConnectionStatusIcon = "✅";
                        ConnectionStatusText = $"Connected — {passed}/{total} tests passed";
                        ConnectionStatusDetail = $"All {CurrentTabTitle} checks passed successfully";
                        ConnectionStatusBg = new System.Windows.Media.SolidColorBrush(
                            System.Windows.Media.Color.FromArgb(0x30, 0xA6, 0xE3, 0xA1));
                        SetTabDotColor(_green);
                    }
                    else
                    {
                        ConnectionStatusIcon = "⚠️";
                        ConnectionStatusText = $"Issues found — {passed}/{total} tests passed";
                        ConnectionStatusDetail = "Review the failed tests below and update your settings";
                        ConnectionStatusBg = new System.Windows.Media.SolidColorBrush(
                            System.Windows.Media.Color.FromArgb(0x30, 0xF9, 0xE2, 0xAF));
                        SetTabDotColor(_yellow);
                    }
                }
                else
                {
                    ConnectionStatusIcon = "❌";
                    ConnectionStatusText = "Connection failed";
                    ConnectionStatusDetail = result?.Message ?? "Could not reach the service. Check your settings and try again.";
                    ConnectionStatusBg = new System.Windows.Media.SolidColorBrush(
                        System.Windows.Media.Color.FromArgb(0x30, 0xF3, 0x8B, 0xA8));
                    SetTabDotColor(_red);
                }
            }, $"Testing {CurrentTabTitle}...");
        }

        private void SetTabDotColor(System.Windows.Media.SolidColorBrush color)
        {
            switch (CurrentTab)
            {
                case "AD": AdStatusColor = color; break;
                case "DHCP": DhcpStatusColor = color; break;
                case "TFTP": TftpStatusColor = color; break;
                case "UNC": UncStatusColor = color; break;
                case "WDS": WdsStatusColor = color; break;
                case "MDT": MdtStatusColor = color; break;
                case "DB": DbStatusColor = color; break;
                case "ADMIN": AdminStatusColor = color; break;
            }
        }

        [RelayCommand]
        private async Task SaveSettings()
        {
            await RunAsync(async () =>
            {
                var dto = BuildDto();
                await Api.SaveInfrastructureSettingsAsync(dto);
                ShowStatus("Settings saved successfully");
            }, "Saving settings...");
        }

        [RelayCommand]
        private async Task LoadSettings()
        {
            try
            {
                var settings = await Api.GetInfrastructureSettingsAsync();
                if (settings != null)
                {
                    await LoadFromDto(settings);
                    ShowStatus("Settings loaded from server");
                }
            }
            catch
            {
                ShowStatus("Could not load settings from server");
            }
        }

        private async Task LoadFromDto(InfrastructureSettingsDto s)
        {
            var ad = s.ActiveDirectory;
            if (ad != null)
            {
                AdDomainName = ad.DomainName; AdDomainController = ad.DomainController;
                AdDefaultOu = ad.DefaultOu; AdJoinUser = ad.JoinAccountUsername;
                AdJoinPassword = ad.JoinAccountPassword;
                AdMachinePrefix = ad.MachineNamePrefix; AdNamingTemplate = ad.MachineNamingTemplate;
                AdLdapPort = ad.LdapPort.ToString(); AdSearchBase = ad.SearchBase;
            }
            var dh = s.Dhcp;
            if (dh != null)
            {
                DhcpServer = dh.DhcpServer;
            }

            // Load DHCP scope from dhcp_config.json
            await LoadDhcpScopeAsync();
            var tf = s.TftpPxe;
            if (tf != null)
            {
                TftpServer = tf.TftpServer; TftpRootPath = tf.TftpRootPath;
                TftpBootImage = tf.BootImagePath; TftpBootFileX64 = tf.BootFileX64;
                TftpBootFileBios = tf.BootFileBios; TftpPromptTimeout = tf.PxePromptTimeout.ToString();
            }
            var unc = s.UncMounts;
            if (unc != null)
            {
                UncUsername = unc.DefaultCredentialsUsername; UncDomain = unc.DefaultCredentialsDomain;
                UncPassword = unc.DefaultCredentialsPassword;
                UncImageShare = unc.ShareImages; UncDriverShare = unc.ShareDrivers;
                UncDeployShare = unc.ShareDeployment; UncLogShare = unc.ShareLogs;
            }
            var wds = s.Wds;
            if (wds != null)
            {
                WdsServer = wds.WdsServer; WdsRemoteInstall = wds.RemoteInstallPath;
                WdsBootImage = wds.DefaultBootImage; WdsImageGroup = wds.ImageGroup;
                WdsAutoAddPolicy = wds.AutoAddPolicy;
            }
            var mdt = s.Mdt;
            if (mdt != null)
            {
                MdtSharePath = mdt.DeploymentSharePath; MdtShareLocal = mdt.DeploymentShareLocal;
                MdtToolkitPath = mdt.ToolkitPath; MdtMonitorHost = mdt.MonitoringHost;
                MdtMonitorPort = mdt.MonitoringPort.ToString(); MdtDbServer = mdt.DatabaseServer;
                MdtRulesPath = mdt.RulesFilePath;
            }
        }

        private InfrastructureSettingsDto BuildDto()
        {
            return new InfrastructureSettingsDto
            {
                ActiveDirectory = new AdSettingsDto
                {
                    DomainName = AdDomainName, DomainController = AdDomainController,
                    DefaultOu = AdDefaultOu, JoinAccountUsername = AdJoinUser,
                    JoinAccountPassword = AdJoinPassword,
                    MachineNamePrefix = AdMachinePrefix, MachineNamingTemplate = AdNamingTemplate,
                    LdapPort = int.TryParse(AdLdapPort, out var p) ? p : 389, SearchBase = AdSearchBase,
                },
                Dhcp = new DhcpSettingsDto
                {
                    DhcpServer = DhcpServer,
                },
                TftpPxe = new TftpSettingsDto
                {
                    TftpServer = TftpServer, TftpRootPath = TftpRootPath,
                    BootImagePath = TftpBootImage, BootFileX64 = TftpBootFileX64,
                    BootFileBios = TftpBootFileBios,
                    PxePromptTimeout = int.TryParse(TftpPromptTimeout, out var t) ? t : 5,
                },
                UncMounts = new UncSettingsDto
                {
                    DefaultCredentialsUsername = UncUsername, DefaultCredentialsDomain = UncDomain,
                    DefaultCredentialsPassword = UncPassword,
                    ShareImages = UncImageShare, ShareDrivers = UncDriverShare,
                    ShareDeployment = UncDeployShare, ShareLogs = UncLogShare,
                },
                Wds = new WdsSettingsDto
                {
                    WdsServer = WdsServer, RemoteInstallPath = WdsRemoteInstall,
                    DefaultBootImage = WdsBootImage, ImageGroup = WdsImageGroup,
                    AutoAddPolicy = WdsAutoAddPolicy,
                },
                Mdt = new MdtSettingsDto
                {
                    DeploymentSharePath = MdtSharePath, DeploymentShareLocal = MdtShareLocal,
                    ToolkitPath = MdtToolkitPath, MonitoringHost = MdtMonitorHost,
                    MonitoringPort = int.TryParse(MdtMonitorPort, out var mp) ? mp : 9800,
                    DatabaseServer = MdtDbServer, RulesFilePath = MdtRulesPath,
                },
            };
        }

        private async Task LoadDhcpScopeAsync()
        {
            try
            {
                var http = new System.Net.Http.HttpClient { Timeout = TimeSpan.FromSeconds(3) };

                // Try loading from the DHCP config file via the API debug endpoint
                string configPath = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "SmartDeployDesktop", "dhcp_config.json");

                if (System.IO.File.Exists(configPath))
                {
                    var json = System.IO.File.ReadAllText(configPath);
                    var data = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                    if (data != null)
                    {
                        ScopeServerIp = data.GetValueOrDefault("server_ip")?.ToString() ?? "";

                        var scopes = data.GetValueOrDefault("scopes");
                        if (scopes != null)
                        {
                            var scopeList = Newtonsoft.Json.JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(scopes.ToString()!);
                            if (scopeList != null && scopeList.Count > 0)
                            {
                                var scope = scopeList[0];
                                ScopeSubnet = scope.GetValueOrDefault("subnet")?.ToString() ?? "";
                                ScopeSubnetMask = scope.GetValueOrDefault("mask")?.ToString() ?? "255.255.255.0";
                                ScopeRangeStart = scope.GetValueOrDefault("range_start")?.ToString() ?? "";
                                ScopeRangeEnd = scope.GetValueOrDefault("range_end")?.ToString() ?? "";
                                ScopeGateway = scope.GetValueOrDefault("gateway")?.ToString() ?? "";
                                ScopeDomain = scope.GetValueOrDefault("domain")?.ToString() ?? "";
                                ScopeBootServer = scope.GetValueOrDefault("boot_server")?.ToString() ?? "";
                                ScopeBootFile = scope.GetValueOrDefault("boot_file")?.ToString() ?? "Boot\\x64\\bootmgfw.efi";

                                var dns = scope.GetValueOrDefault("dns");
                                if (dns != null)
                                {
                                    var dnsList = Newtonsoft.Json.JsonConvert.DeserializeObject<List<string>>(dns.ToString()!);
                                    ScopeDns = dnsList != null ? string.Join(", ", dnsList) : "";
                                }
                            }
                        }
                    }
                }
            }
            catch { }
        }

        [RelayCommand]
        private async Task ApplyDhcpConfig()
        {
            try
            {
                var dnsList = ScopeDns.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

                var scope = new Dictionary<string, object>
                {
                    ["name"] = "PXE Deploy",
                    ["subnet"] = ScopeSubnet,
                    ["mask"] = ScopeSubnetMask,
                    ["range_start"] = ScopeRangeStart,
                    ["range_end"] = ScopeRangeEnd,
                    ["lease_hours"] = 8,
                    ["pxe_enabled"] = true,
                    ["boot_server"] = ScopeBootServer,
                    ["boot_file"] = ScopeBootFile,
                    ["reservations"] = new List<object>(),
                };

                // Only include gateway/DNS/domain if actually set (empty values confuse PXE clients)
                if (!string.IsNullOrWhiteSpace(ScopeGateway))
                    scope["gateway"] = ScopeGateway;
                if (dnsList.Count > 0)
                    scope["dns"] = dnsList;
                if (!string.IsNullOrWhiteSpace(ScopeDomain))
                    scope["domain"] = ScopeDomain;

                var config = new Dictionary<string, object>
                {
                    ["server_ip"] = ScopeServerIp,
                    // ProxyDHCP is only for environments where another DHCP server exists.
                    // For isolated PXE networks (no external DHCP), this MUST be false
                    // so the server handles full DHCP (DISCOVER/OFFER/REQUEST/ACK).
                    ["enable_proxy_dhcp"] = false,
                    ["scopes"] = new List<Dictionary<string, object>> { scope },
                };

                string configPath = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "SmartDeployDesktop", "dhcp_config.json");

                System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(configPath)!);
                var json = Newtonsoft.Json.JsonConvert.SerializeObject(config, Newtonsoft.Json.Formatting.Indented);
                System.IO.File.WriteAllText(configPath, json, new System.Text.UTF8Encoding(false));

                ShowStatus($"DHCP config saved to {configPath} — restart DHCP server to apply");
            }
            catch (Exception ex)
            {
                ShowStatus($"Failed to save DHCP config: {ex.Message}");
            }
        }

        /// <summary>Parse JSON boolean from Dictionary deserialized by Newtonsoft (bool, JValue, or string).</summary>
        private static bool JsonBool(Dictionary<string, object> d, string key)
        {
            if (!d.TryGetValue(key, out var v) || v is null)
                return false;
            if (v is bool b)
                return b;
            if (v is Newtonsoft.Json.Linq.JValue jv && jv.Type == Newtonsoft.Json.Linq.JTokenType.Boolean)
                return jv.ToObject<bool>();
            return string.Equals(v.ToString(), "true", StringComparison.OrdinalIgnoreCase);
        }

        [RelayCommand]
        private async Task SaveDbConfig()
        {
            var log = new ObservableCollection<string>();
            DbSetupLog = log;

            void AddLog(string msg) => System.Windows.Application.Current.Dispatcher.Invoke(() => log.Add(msg));

            await Task.Run(async () =>
            {
                try
                {
                    AddLog("Saving db_config.json...");
                    if (!int.TryParse(DbPort, out var port))
                        port = 5432;

                    using var http = new System.Net.Http.HttpClient { Timeout = TimeSpan.FromSeconds(30) };
                    var payload = new
                    {
                        host = DbHost,
                        port,
                        database = DbName,
                        user = DbUser,
                        password = DbPassword,
                    };
                    var json = Newtonsoft.Json.JsonConvert.SerializeObject(payload);
                    var content = new System.Net.Http.StringContent(json, System.Text.Encoding.UTF8, "application/json");
                    var resp = await http.PostAsync("http://127.0.0.1:8000/api/db/config", content);
                    var body = await resp.Content.ReadAsStringAsync();
                    var result = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(body);

                    if (result != null)
                    {
                        var ok = JsonBool(result, "success");
                        var msg = result.GetValueOrDefault("message")?.ToString() ?? "";
                        var path = result.GetValueOrDefault("path")?.ToString() ?? "";
                        AddLog(msg);
                        if (!string.IsNullOrEmpty(path))
                            AddLog(path);
                        System.Windows.Application.Current.Dispatcher.Invoke(() =>
                        {
                            DbStatusColor = ok ? _green : _red;
                            ShowStatus(ok ? "Database configuration saved" : msg);
                        });
                    }
                }
                catch (Exception ex)
                {
                    AddLog($"ERROR: {ex.Message}");
                    System.Windows.Application.Current.Dispatcher.Invoke(() =>
                    {
                        DbStatusColor = _red;
                        ShowStatus($"Save failed: {ex.Message}");
                    });
                }
            });
        }

        [RelayCommand]
        private async Task SetupPostgres()
        {
            var log = new ObservableCollection<string>();
            DbSetupLog = log;

            void AddLog(string msg) => System.Windows.Application.Current.Dispatcher.Invoke(() => log.Add(msg));

            await Task.Run(async () =>
            {
                try
                {
                    AddLog("=== PostgreSQL Setup ===");
                    AddLog("");

                    using var http = new System.Net.Http.HttpClient { Timeout = TimeSpan.FromMinutes(10) };
                    var payload = new
                    {
                        postgres_password = DbPostgresPassword,
                        db_name = DbName,
                        db_user = DbUser,
                        db_password = DbPassword,
                    };

                    var json = Newtonsoft.Json.JsonConvert.SerializeObject(payload);
                    var content = new System.Net.Http.StringContent(json, System.Text.Encoding.UTF8, "application/json");

                    AddLog("Calling server setup endpoint...");
                    AddLog("This may download and install PostgreSQL (5-10 minutes)...");
                    AddLog("");

                    var resp = await http.PostAsync("http://127.0.0.1:8000/api/db/setup", content);
                    var body = await resp.Content.ReadAsStringAsync();
                    var result = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(body);

                    if (result != null)
                    {
                        var serverLog = result.GetValueOrDefault("log");
                        if (serverLog != null)
                        {
                            var logList = Newtonsoft.Json.JsonConvert.DeserializeObject<List<string>>(serverLog.ToString()!);
                            if (logList != null)
                                foreach (var line in logList)
                                    AddLog(line);
                        }

                        // Newtonsoft may deserialize JSON booleans as bool or JValue, not the string "true".
                        var success = JsonBool(result, "success");
                        var msg = result.GetValueOrDefault("message")?.ToString() ?? "";

                        AddLog("");
                        if (success)
                        {
                            AddLog("=== SETUP COMPLETE ===");
                            System.Windows.Application.Current.Dispatcher.Invoke(() =>
                            {
                                DbStatusColor = _green;
                                ShowStatus("PostgreSQL setup complete");
                            });
                        }
                        else
                        {
                            AddLog($"Setup issue: {msg}");
                            System.Windows.Application.Current.Dispatcher.Invoke(() =>
                            {
                                DbStatusColor = _red;
                                ShowStatus(msg);
                            });
                        }
                    }
                }
                catch (Exception ex)
                {
                    AddLog($"ERROR: {ex.Message}");
                    System.Windows.Application.Current.Dispatcher.Invoke(() => ShowStatus($"Setup failed: {ex.Message}"));
                }
            });
        }

        [RelayCommand]
        private async Task TestDbConnection()
        {
            var log = new ObservableCollection<string>();
            DbSetupLog = log;

            void AddLog(string msg) => System.Windows.Application.Current.Dispatcher.Invoke(() => log.Add(msg));

            await Task.Run(async () =>
            {
                try
                {
                    AddLog("Testing PostgreSQL connection...");
                    if (!int.TryParse(DbPort, out var port))
                        port = 5432;

                    using var http = new System.Net.Http.HttpClient { Timeout = TimeSpan.FromSeconds(90) };
                    var payload = new
                    {
                        host = DbHost,
                        port,
                        database = DbName,
                        user = DbUser,
                        password = DbPassword,
                    };
                    var json = Newtonsoft.Json.JsonConvert.SerializeObject(payload);
                    var content = new System.Net.Http.StringContent(json, System.Text.Encoding.UTF8, "application/json");
                    var resp = await http.PostAsync("http://127.0.0.1:8000/api/db/test", content);
                    var body = await resp.Content.ReadAsStringAsync();
                    var result = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(body);

                    if (result == null)
                    {
                        AddLog($"Invalid response (HTTP {(int)resp.StatusCode}). First 200 chars:");
                        AddLog(body.Length > 200 ? body.Substring(0, 200) : body);
                        System.Windows.Application.Current.Dispatcher.Invoke(() =>
                        {
                            DbStatusColor = _red;
                            ShowStatus("Test failed: bad response from server");
                        });
                        return;
                    }

                    var connected = JsonBool(result, "connected");

                    if (connected)
                    {
                        var version = result.GetValueOrDefault("version")?.ToString() ?? "";
                        var tables = result.GetValueOrDefault("tables")?.ToString() ?? "0";
                        var deployments = result.GetValueOrDefault("deployments")?.ToString() ?? "0";
                        var clients = result.GetValueOrDefault("clients")?.ToString() ?? "0";

                        AddLog($"Connected: {version}");
                        AddLog($"Tables: {tables}");
                        AddLog($"Deployments: {deployments}");
                        AddLog($"PXE Clients: {clients}");
                        AddLog("");
                        AddLog("Connection successful!");
                        AddLog("Tip: click Save configuration to write db_config.json for the next app restart.");

                        System.Windows.Application.Current.Dispatcher.Invoke(() =>
                        {
                            DbStatusColor = _green;
                            ShowStatus("Database connected");
                        });
                    }
                    else
                    {
                        var error = result.GetValueOrDefault("error")?.ToString() ?? "Unknown error";
                        AddLog($"Connection failed: {error}");

                        System.Windows.Application.Current.Dispatcher.Invoke(() =>
                        {
                            DbStatusColor = _red;
                            ShowStatus("Database connection failed");
                        });
                    }
                }
                catch (Exception ex)
                {
                    AddLog($"ERROR: {ex.Message}");
                    System.Windows.Application.Current.Dispatcher.Invoke(() =>
                    {
                        DbStatusColor = _red;
                        ShowStatus($"Test failed: {ex.Message}");
                    });
                }
            });
        }

        [RelayCommand]
        private async Task GenerateUnattend()
        {
            var log = new ObservableCollection<string>();
            AdminLog = log;

            void AddLog(string msg) => System.Windows.Application.Current.Dispatcher.Invoke(() => log.Add(msg));

            await Task.Run(() =>
            {
                try
                {
                    var username = AdminUsername;
                    var password = AdminPassword;
                    var timezone = AdminTimezone;
                    var locale = AdminLocale;

                    // AD settings (from AD tab)
                    var joinDomain = !string.IsNullOrWhiteSpace(AdDomainName) && !string.IsNullOrWhiteSpace(AdJoinUser);
                    var domain = AdDomainName?.Trim() ?? "";
                    var domainOu = AdDefaultOu?.Trim() ?? "";
                    var joinUser = AdJoinUser?.Trim() ?? "";
                    var joinPassword = AdJoinPassword ?? "";

                    AddLog("=== GENERATING UNATTEND.XML ===");
                    AddLog($"Username: {username}");
                    AddLog($"Timezone: {timezone}");
                    AddLog($"Locale:   {locale}");
                    if (joinDomain)
                    {
                        AddLog($"Domain:   {domain}");
                        AddLog($"OU:       {(string.IsNullOrEmpty(domainOu) ? "(default)" : domainOu)}");
                        AddLog($"Join as:  {joinUser}");
                    }
                    else
                    {
                        AddLog("Domain:   (not configured - workgroup only)");
                    }
                    AddLog("");

                    if (string.IsNullOrWhiteSpace(password))
                    {
                        AddLog("ERROR: Password cannot be empty");
                        return;
                    }

                    // Build unattend.xml using StringBuilder to avoid XML tag stripping
                    var sb = new System.Text.StringBuilder();
                    sb.AppendLine("<?xml version=\"1.0\" encoding=\"utf-8\"?>");
                    sb.AppendLine("<unattend xmlns=\"urn:schemas-microsoft-com:unattend\" xmlns:wcm=\"http://schemas.microsoft.com/WMIConfig/2002/State\">");
                    sb.AppendLine("  <settings pass=\"oobeSystem\">");
                    sb.AppendLine("    <component name=\"Microsoft-Windows-International-Core\" processorArchitecture=\"amd64\" publicKeyToken=\"31bf3856ad364e35\" language=\"neutral\" versionScope=\"nonSxS\">");
                    sb.AppendLine($"      <InputLocale>{locale}</InputLocale>");
                    sb.AppendLine($"      <SystemLocale>{locale}</SystemLocale>");
                    sb.AppendLine($"      <UILanguage>{locale}</UILanguage>");
                    sb.AppendLine($"      <UserLocale>{locale}</UserLocale>");
                    sb.AppendLine("    </component>");
                    sb.AppendLine("    <component name=\"Microsoft-Windows-Shell-Setup\" processorArchitecture=\"amd64\" publicKeyToken=\"31bf3856ad364e35\" language=\"neutral\" versionScope=\"nonSxS\">");
                    sb.AppendLine("      <OOBE>");
                    sb.AppendLine("        <HideEULAPage>true</HideEULAPage>");
                    sb.AppendLine("        <HideLocalAccountScreen>true</HideLocalAccountScreen>");
                    sb.AppendLine("        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>");
                    sb.AppendLine("        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>");
                    sb.AppendLine("        <NetworkLocation>Work</NetworkLocation>");
                    sb.AppendLine("        <ProtectYourPC>3</ProtectYourPC>");
                    sb.AppendLine("        <SkipMachineOOBE>true</SkipMachineOOBE>");
                    sb.AppendLine("        <SkipUserOOBE>true</SkipUserOOBE>");
                    sb.AppendLine("      </OOBE>");
                    sb.AppendLine("      <UserAccounts>");
                    sb.AppendLine("        <LocalAccounts>");
                    sb.AppendLine("          <LocalAccount wcm:action=\"add\">");
                    sb.Append("            <"); sb.Append("Name"); sb.Append(">"); sb.Append(username); sb.Append("</"); sb.Append("Name"); sb.AppendLine(">");
                    sb.AppendLine("            <Group>Administrators</Group>");
                    sb.AppendLine("            <Password>");
                    sb.AppendLine($"              <Value>{password}</Value>");
                    sb.AppendLine("              <PlainText>true</PlainText>");
                    sb.AppendLine("            </Password>");
                    sb.AppendLine("          </LocalAccount>");
                    sb.AppendLine("        </LocalAccounts>");
                    sb.AppendLine("      </UserAccounts>");
                    sb.AppendLine("      <AutoLogon>");
                    sb.AppendLine("        <Enabled>true</Enabled>");
                    sb.AppendLine($"        <Username>{username}</Username>");
                    sb.AppendLine("        <Password>");
                    sb.AppendLine($"          <Value>{password}</Value>");
                    sb.AppendLine("          <PlainText>true</PlainText>");
                    sb.AppendLine("        </Password>");
                    sb.AppendLine("        <LogonCount>1</LogonCount>");
                    sb.AppendLine("      </AutoLogon>");
                    sb.AppendLine($"      <TimeZone>{timezone}</TimeZone>");
                    sb.AppendLine("    </component>");
                    sb.AppendLine("  </settings>");

                    // SPECIALIZE PASS - computer name, domain join, misc
                    sb.AppendLine("  <settings pass=\"specialize\">");
                    sb.AppendLine("    <component name=\"Microsoft-Windows-Deployment\" processorArchitecture=\"amd64\" publicKeyToken=\"31bf3856ad364e35\" language=\"neutral\" versionScope=\"nonSxS\">");
                    sb.AppendLine("      <RunSynchronous>");
                    sb.AppendLine("        <RunSynchronousCommand wcm:action=\"add\">");
                    sb.AppendLine("          <Order>1</Order>");
                    sb.AppendLine("          <Path>net accounts /maxpwage:unlimited</Path>");
                    sb.AppendLine("          <Description>Disable password expiry</Description>");
                    sb.AppendLine("        </RunSynchronousCommand>");
                    sb.AppendLine("      </RunSynchronous>");
                    sb.AppendLine("    </component>");
                    sb.AppendLine("    <component name=\"Microsoft-Windows-Shell-Setup\" processorArchitecture=\"amd64\" publicKeyToken=\"31bf3856ad364e35\" language=\"neutral\" versionScope=\"nonSxS\">");
                    sb.AppendLine("      <ComputerName>*</ComputerName>");
                    sb.AppendLine("    </component>");

                    // Domain Join component
                    if (joinDomain)
                    {
                        sb.AppendLine("    <component name=\"Microsoft-Windows-UnattendedJoin\" processorArchitecture=\"amd64\" publicKeyToken=\"31bf3856ad364e35\" language=\"neutral\" versionScope=\"nonSxS\">");
                        sb.AppendLine("      <Identification>");
                        sb.AppendLine("        <Credentials>");
                        sb.AppendLine($"          <Domain>{domain}</Domain>");
                        sb.AppendLine($"          <Password>{joinPassword}</Password>");
                        sb.AppendLine($"          <Username>{joinUser}</Username>");
                        sb.AppendLine("        </Credentials>");
                        sb.AppendLine($"        <JoinDomain>{domain}</JoinDomain>");
                        if (!string.IsNullOrEmpty(domainOu))
                            sb.AppendLine($"        <MachineObjectOU>{domainOu}</MachineObjectOU>");
                        sb.AppendLine("      </Identification>");
                        sb.AppendLine("    </component>");
                    }

                    sb.AppendLine("  </settings>");
                    sb.AppendLine("</unattend>");

                    // Save to C:\SmartDeploy\AnswerFiles\unattend.xml
                    var answerDir = @"C:\SmartDeploy\AnswerFiles";
                    System.IO.Directory.CreateDirectory(answerDir);
                    var path = System.IO.Path.Combine(answerDir, "unattend.xml");

                    System.IO.File.WriteAllText(path, sb.ToString(), new System.Text.UTF8Encoding(false));

                    AddLog($"Saved to: {path}");
                    AddLog("");
                    AddLog("Unattend.xml will:");
                    AddLog($"  - Create local account: {username}");
                    AddLog("  - Skip all OOBE screens");
                    AddLog("  - Auto-logon once (for SetupComplete.cmd)");
                    AddLog($"  - Set timezone: {timezone}");
                    AddLog("  - Disable password expiry");
                    AddLog("  - Computer name set by WinPE wizard (or * for random)");
                    if (joinDomain)
                    {
                        AddLog($"  - Join domain: {domain}");
                        if (!string.IsNullOrEmpty(domainOu))
                            AddLog($"  - Target OU: {domainOu}");
                    }
                    AddLog("");
                    AddLog("=== COMPLETE ===");

                    System.Windows.Application.Current.Dispatcher.Invoke(() =>
                    {
                        AdminStatusColor = _green;
                        ShowStatus("unattend.xml saved to C:\\SmartDeploy\\AnswerFiles\\");
                    });
                }
                catch (Exception ex)
                {
                    AddLog($"ERROR: {ex.Message}");
                }
            });
        }
    }

    // ========================================================================
    // Services ViewModel - Start/Stop DHCP, TFTP, API servers
    // ========================================================================

    public partial class ServicesViewModel : BaseViewModel
    {
        // API Server
        [ObservableProperty] private bool _apiServerRunning;
        [ObservableProperty] private bool _apiServerStopped = true;
        [ObservableProperty] private string _apiServerStatus = "Checking...";

        // DHCP Server
        [ObservableProperty] private bool _dhcpServerRunning;
        [ObservableProperty] private bool _dhcpServerStopped = true;
        [ObservableProperty] private string _dhcpServerStatus = "Stopped";

        // TFTP Server
        [ObservableProperty] private bool _tftpServerRunning;
        [ObservableProperty] private bool _tftpServerStopped = true;
        [ObservableProperty] private string _tftpServerStatus = "Stopped";

        // Server Logs
        [ObservableProperty] private ObservableCollection<string> _dhcpLog = new() { "DHCP server not started" };
        [ObservableProperty] private ObservableCollection<string> _tftpLog = new() { "TFTP server not started" };
        [ObservableProperty] private ObservableCollection<string> _apiLog = new() { "Waiting for API server..." };

        // Sidebar dot colors
        private static readonly System.Windows.Media.SolidColorBrush _dotGray = new(System.Windows.Media.Color.FromRgb(0x6C, 0x70, 0x86));
        private static readonly System.Windows.Media.SolidColorBrush _dotGreen = new(System.Windows.Media.Color.FromRgb(0xA6, 0xE3, 0xA1));
        private static readonly System.Windows.Media.SolidColorBrush _dotRed = new(System.Windows.Media.Color.FromRgb(0xF3, 0x8B, 0xA8));
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _dhcpDotColor = _dotGray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _tftpDotColor = _dotGray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _apiDotColor = _dotGray;

        private readonly System.Net.Http.HttpClient _statusHttp = new()
        {
            Timeout = TimeSpan.FromSeconds(3)
        };

        public ServicesViewModel(ApiClient api) : base(api) { }

        [RelayCommand]
        private async Task Refresh()
        {
            await RefreshStatusAsync();
        }

        public async Task RefreshStatusAsync()
        {
            // Check API server (port 8000)
            ApiServerRunning = await CheckHealthAsync("http://127.0.0.1:8000/api/health");
            ApiServerStopped = !ApiServerRunning;
            ApiServerStatus = ApiServerRunning ? "Running on :8000" : "Stopped";
            ApiDotColor = ApiServerRunning ? _dotGreen : _dotRed;

            // Check DHCP server (port 8001)
            DhcpServerRunning = await CheckHealthAsync("http://127.0.0.1:8001/health");
            DhcpServerStopped = !DhcpServerRunning;
            DhcpServerStatus = DhcpServerRunning ? "Running on :67, :60, :4011" : "Stopped";
            DhcpDotColor = DhcpServerRunning ? _dotGreen : _dotRed;

            // Check TFTP server (port 8002)
            TftpServerRunning = await CheckHealthAsync("http://127.0.0.1:8002/health");
            TftpServerStopped = !TftpServerRunning;
            TftpServerStatus = TftpServerRunning ? "Running on :69, :60" : "Stopped";
            TftpDotColor = TftpServerRunning ? _dotGreen : _dotRed;

            // Fetch logs
            await FetchLogsAsync();
        }

        [RelayCommand]
        private async Task StartApiServer()
        {
            await RunAsync(async () =>
            {
                await StartPythonServerAsync("server.py", 8000);
                await Task.Delay(3000);
                await RefreshStatusAsync();
            }, "Starting API Server...");
        }

        [RelayCommand]
        private async Task StopApiServer()
        {
            await RunAsync(async () =>
            {
                await StopByPortAsync(8000);
                await Task.Delay(1000);
                await RefreshStatusAsync();
            }, "Stopping API Server...");
        }

        [RelayCommand]
        private async Task StartDhcpServer()
        {
            await RunAsync(async () =>
            {
                await StartPythonServerAsync("dhcpserver.py --enable-proxy", 8001, admin: true);
                await Task.Delay(3000);
                await RefreshStatusAsync();
            }, "Starting DHCP Server (requires Admin)...");
        }

        [RelayCommand]
        private async Task StopDhcpServer()
        {
            await RunAsync(async () =>
            {
                await StopByPortAsync(8001);
                await Task.Delay(1000);
                await RefreshStatusAsync();
            }, "Stopping DHCP Server...");
        }

        [RelayCommand]
        private async Task StartTftpServer()
        {
            await RunAsync(async () =>
            {
                await StartPythonServerAsync("tftpserver.py", 8002, admin: true);
                await Task.Delay(3000);
                await RefreshStatusAsync();
            }, "Starting TFTP Server (requires Admin)...");
        }

        [RelayCommand]
        private async Task StopTftpServer()
        {
            await RunAsync(async () =>
            {
                await StopByPortAsync(8002);
                await Task.Delay(1000);
                await RefreshStatusAsync();
            }, "Stopping TFTP Server...");
        }

        [RelayCommand]
        private async Task StartAll()
        {
            await RunAsync(async () =>
            {
                if (!ApiServerRunning) await StartPythonServerAsync("server.py", 8000);
                await Task.Delay(2000);
                if (!DhcpServerRunning) await StartPythonServerAsync("dhcpserver.py --enable-proxy", 8001, admin: true);
                await Task.Delay(1000);
                if (!TftpServerRunning) await StartPythonServerAsync("tftpserver.py", 8002, admin: true);
                await Task.Delay(3000);
                await RefreshStatusAsync();
            }, "Starting all services...");
        }

        [RelayCommand]
        private async Task StopAll()
        {
            await RunAsync(async () =>
            {
                await StopByPortAsync(8002);
                await StopByPortAsync(8001);
                await StopByPortAsync(8000);
                await Task.Delay(2000);
                await RefreshStatusAsync();
            }, "Stopping all services...");
        }

        private async Task<bool> CheckHealthAsync(string url)
        {
            try
            {
                var resp = await _statusHttp.GetAsync(url);
                return resp.IsSuccessStatusCode;
            }
            catch { return false; }
        }

        private async Task FetchLogsAsync()
        {
            // DHCP log from status endpoint
            if (DhcpServerRunning)
            {
                try
                {
                    var resp = await _statusHttp.GetStringAsync("http://127.0.0.1:8001/status");
                    var data = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(resp);
                    var lines = new ObservableCollection<string>();
                    if (data != null)
                    {
                        var stats = data.GetValueOrDefault("stats");
                        if (stats != null)
                        {
                            var statsDict = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(stats.ToString()!);
                            if (statsDict != null)
                            {
                                lines.Add($"Started: {statsDict.GetValueOrDefault("started")}");
                                lines.Add($"Discovers: {statsDict.GetValueOrDefault("discovers")}  Offers: {statsDict.GetValueOrDefault("offers")}");
                                lines.Add($"Requests: {statsDict.GetValueOrDefault("requests")}  ACKs: {statsDict.GetValueOrDefault("acks")}");
                                lines.Add($"NAKs: {statsDict.GetValueOrDefault("naks")}  Releases: {statsDict.GetValueOrDefault("releases")}");
                                lines.Add($"Proxy DHCP: {statsDict.GetValueOrDefault("proxy_dhcp_requests")}  Errors: {statsDict.GetValueOrDefault("errors")}");
                                var ports = statsDict.GetValueOrDefault("listening_ports");
                                if (ports != null) lines.Add($"Listening ports: {ports}");
                            }
                        }
                        lines.Add($"Active leases: {data.GetValueOrDefault("active_leases")}");
                        lines.Add($"Scopes: {data.GetValueOrDefault("scopes")}");
                    }
                    DhcpLog = lines;
                }
                catch { DhcpLog = new ObservableCollection<string> { "Error fetching DHCP status" }; }
            }
            else
            {
                DhcpLog = new ObservableCollection<string> { "DHCP server not running" };
            }

            // TFTP log from status endpoint
            if (TftpServerRunning)
            {
                try
                {
                    var resp = await _statusHttp.GetStringAsync("http://127.0.0.1:8002/status");
                    var data = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(resp);
                    var lines = new ObservableCollection<string>();
                    if (data != null)
                    {
                        lines.Add($"Root: {data.GetValueOrDefault("root_path")}");
                        lines.Add($"Port: {data.GetValueOrDefault("port")}");
                        var stats = data.GetValueOrDefault("stats");
                        if (stats != null)
                        {
                            var statsDict = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(stats.ToString()!);
                            if (statsDict != null)
                            {
                                lines.Add($"Started: {statsDict.GetValueOrDefault("started")}");
                                lines.Add($"Total requests: {statsDict.GetValueOrDefault("total_requests")}");
                                lines.Add($"Completed: {statsDict.GetValueOrDefault("completed_transfers")}  Failed: {statsDict.GetValueOrDefault("failed_transfers")}");
                                lines.Add($"Active: {statsDict.GetValueOrDefault("active_transfers")}");
                                lines.Add($"Bytes served: {statsDict.GetValueOrDefault("bytes_served")}");
                                var ports = statsDict.GetValueOrDefault("listening_ports");
                                if (ports != null) lines.Add($"Listening ports: {ports}");
                            }
                        }
                        // Recent transfers
                        var recent = data.GetValueOrDefault("recent_transfers");
                        if (recent != null)
                        {
                            var transfers = Newtonsoft.Json.JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(recent.ToString()!);
                            if (transfers != null)
                            {
                                lines.Add($"--- Recent transfers ({transfers.Count}) ---");
                                foreach (var t in transfers)
                                {
                                    lines.Add($"  {t.GetValueOrDefault("time")} | {t.GetValueOrDefault("client")} | {t.GetValueOrDefault("file")} | {t.GetValueOrDefault("speed_kbps")} KB/s");
                                }
                            }
                        }
                    }
                    TftpLog = lines;
                }
                catch { TftpLog = new ObservableCollection<string> { "Error fetching TFTP status" }; }
            }
            else
            {
                TftpLog = new ObservableCollection<string> { "TFTP server not running" };
            }

            // API server log
            if (ApiServerRunning)
            {
                try
                {
                    var logs = await Api.GetLogsAsync(30);
                    var lines = new ObservableCollection<string>();
                    foreach (var l in logs)
                        lines.Add($"{l.Timestamp} [{l.Level}] {l.Message}");
                    if (lines.Count == 0) lines.Add("No recent log entries");
                    ApiLog = lines;
                }
                catch { ApiLog = new ObservableCollection<string> { "Error fetching API logs" }; }
            }
            else
            {
                ApiLog = new ObservableCollection<string> { "API server not running" };
            }
        }

        private async Task StartPythonServerAsync(string scriptAndArgs, int port, bool admin = false)
        {
            // Find the Server directory
            string exeDir = AppDomain.CurrentDomain.BaseDirectory;
            string serverDir = "";
            foreach (var candidate in new[]
            {
                System.IO.Path.Combine(exeDir, "Server"),
                System.IO.Path.GetFullPath(System.IO.Path.Combine(exeDir, "..", "..", "..", "..", "Server")),
                System.IO.Path.GetFullPath(System.IO.Path.Combine(exeDir, "..", "..", "Server")),
                System.IO.Path.GetFullPath(System.IO.Path.Combine(exeDir, "..", "Server")),
            })
            {
                if (System.IO.Directory.Exists(candidate))
                {
                    serverDir = candidate;
                    break;
                }
            }

            if (string.IsNullOrEmpty(serverDir))
            {
                ShowStatus($"Server directory not found (searched from {exeDir})");
                return;
            }

            var parts = scriptAndArgs.Split(' ', 2);
            var script = parts[0];
            var args = parts.Length > 1 ? parts[1] : "";
            var scriptPath = System.IO.Path.Combine(serverDir, script);

            if (!System.IO.File.Exists(scriptPath))
            {
                ShowStatus($"Script not found: {scriptPath}");
                return;
            }

            // Resolve full path to python.exe (elevated process may have different PATH)
            string pythonExe = FindPythonExe(serverDir);
            if (string.IsNullOrEmpty(pythonExe))
            {
                ShowStatus("Python not found. Install Python 3.10+ and add to PATH.");
                return;
            }

            try
            {
                if (admin)
                {
                    var tempBat = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"smartdeploy_start_{script.Replace(".py", "")}.bat");
                    System.IO.File.WriteAllText(tempBat,
                        $"@echo off\r\n" +
                        $"title SmartDeploy - {script}\r\n" +
                        $"cd /d \"{serverDir}\"\r\n" +
                        $"echo Starting {script}...\r\n" +
                        $"echo Python: {pythonExe}\r\n" +
                        $"echo.\r\n" +
                        $"\"{pythonExe}\" \"{scriptPath}\" {args}\r\n" +
                        $"echo.\r\n" +
                        $"echo === Server exited with code %ERRORLEVEL% ===\r\n" +
                        $"pause\r\n");

                    var psi = new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = tempBat,
                        Verb = "runas",
                        UseShellExecute = true,
                        WindowStyle = System.Diagnostics.ProcessWindowStyle.Normal,
                    };
                    System.Diagnostics.Process.Start(psi);
                    ShowStatus($"Started {script} (elevated)");
                }
                else
                {
                    var psi = new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = pythonExe,
                        Arguments = $"\"{scriptPath}\" {args}".Trim(),
                        WorkingDirectory = serverDir,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                    };
                    System.Diagnostics.Process.Start(psi);
                    ShowStatus($"Started {script}");
                }
            }
            catch (System.ComponentModel.Win32Exception ex) when (ex.NativeErrorCode == 1223)
            {
                ShowStatus("UAC elevation cancelled by user");
            }
            catch (Exception ex)
            {
                ShowStatus($"Failed to start {script}: {ex.Message}");
            }
        }

        private async Task StopByPortAsync(int statusPort)
        {
            // Find the Python process using this port and kill it
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "powershell",
                    Arguments = $"-NoProfile -Command \"Get-NetTCPConnection -LocalPort {statusPort} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}\"",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                var proc = System.Diagnostics.Process.Start(psi);
                proc?.WaitForExit(5000);
            }
            catch { }
        }

        /// <summary>
        /// Resolves the full absolute path to python.exe so elevated processes can find it.
        /// </summary>
        private string FindPythonExe(string serverDir)
        {
            // All possible Python executable names
            string[] pythonNames = { "python.exe", "python3.exe", "python3.13.exe", "python3.12.exe", "python3.11.exe", "python3.10.exe", "py.exe" };

            // 1. Venv in Server dir
            string venvPython = System.IO.Path.Combine(serverDir, "venv", "Scripts", "python.exe");
            if (System.IO.File.Exists(venvPython))
                return System.IO.Path.GetFullPath(venvPython);

            // 2. Bundled Python
            foreach (var p in new[] {
                System.IO.Path.Combine(serverDir, "python", "python.exe"),
                System.IO.Path.Combine(serverDir, "..", "python", "python.exe"),
            })
            {
                if (System.IO.File.Exists(p))
                    return System.IO.Path.GetFullPath(p);
            }

            // 3. Use 'where' to find each Python name on PATH
            foreach (var name in pythonNames)
            {
                try
                {
                    var psi = new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = "where",
                        Arguments = name,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        RedirectStandardOutput = true,
                    };
                    var proc = System.Diagnostics.Process.Start(psi);
                    if (proc != null)
                    {
                        string output = proc.StandardOutput.ReadToEnd();
                        proc.WaitForExit(3000);
                        if (proc.ExitCode == 0)
                        {
                            string firstLine = output.Split('\n')[0].Trim();
                            if (System.IO.File.Exists(firstLine))
                                return firstLine;
                        }
                    }
                }
                catch { }
            }

            // 4. Common install locations
            foreach (var ver in new[] { "313", "312", "311", "310" })
            {
                foreach (var p in new[]
                {
                    $@"C:\Python{ver}\python.exe",
                    System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), $@"Programs\Python\Python{ver}\python.exe"),
                    $@"C:\Program Files\Python{ver}\python.exe",
                })
                {
                    if (System.IO.File.Exists(p))
                        return p;
                }
            }

            return "";
        }
    }

    // ========================================================================
    // PXE Status ViewModel
    // ========================================================================

    public partial class PxeStatusViewModel : BaseViewModel
    {
        // Service indicators
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _dhcpColor = _grayBrush;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _tftpColor = _grayBrush;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _apiColor = _grayBrush;
        [ObservableProperty] private string _dhcpDetail = "Checking...";
        [ObservableProperty] private string _tftpDetail = "Checking...";
        [ObservableProperty] private string _apiDetail = "Checking...";

        // DHCP Leases
        [ObservableProperty] private ObservableCollection<DhcpLeaseItem> _dhcpLeases = new();
        [ObservableProperty] private string _leaseCountText = "DHCP Leases (0)";

        // TFTP Transfers
        [ObservableProperty] private ObservableCollection<TftpTransferItem> _tftpTransfers = new();
        [ObservableProperty] private string _transferCountText = "Recent TFTP Transfers (0)";

        // Log
        [ObservableProperty] private ObservableCollection<LogItem> _logEntries = new();

        private static readonly System.Windows.Media.SolidColorBrush _grayBrush = new(System.Windows.Media.Color.FromRgb(0x6C, 0x70, 0x86));
        private static readonly System.Windows.Media.SolidColorBrush _greenBrush = new(System.Windows.Media.Color.FromRgb(0xA6, 0xE3, 0xA1));
        private static readonly System.Windows.Media.SolidColorBrush _redBrush = new(System.Windows.Media.Color.FromRgb(0xF3, 0x8B, 0xA8));

        private readonly System.Net.Http.HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(3) };

        public PxeStatusViewModel(ApiClient api) : base(api) { }

        [RelayCommand]
        public async Task Refresh()
        {
            await RefreshAsync();
        }

        public async Task RefreshAsync()
        {
            // Check services
            ApiColor = await CheckAsync("http://127.0.0.1:8000/api/health") ? _greenBrush : _redBrush;
            ApiDetail = ApiColor == _greenBrush ? "Running :8000" : "Stopped";

            DhcpColor = await CheckAsync("http://127.0.0.1:8001/health") ? _greenBrush : _redBrush;
            DhcpDetail = DhcpColor == _greenBrush ? "Running :67, :60, :4011" : "Stopped";

            TftpColor = await CheckAsync("http://127.0.0.1:8002/health") ? _greenBrush : _redBrush;
            TftpDetail = TftpColor == _greenBrush ? "Running :69, :60" : "Stopped";

            // Fetch DHCP leases
            try
            {
                var resp = await _http.GetStringAsync("http://127.0.0.1:8001/leases");
                var data = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(resp);
                if (data?.ContainsKey("leases") == true)
                {
                    var leases = Newtonsoft.Json.JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(data["leases"]?.ToString() ?? "[]");
                    var items = new ObservableCollection<DhcpLeaseItem>();
                    if (leases != null)
                        foreach (var l in leases)
                            items.Add(new DhcpLeaseItem
                            {
                                Ip = l.GetValueOrDefault("ip")?.ToString() ?? "",
                                Mac = l.GetValueOrDefault("mac")?.ToString() ?? "",
                                Hostname = l.GetValueOrDefault("hostname")?.ToString() ?? "",
                                Expires = l.GetValueOrDefault("expires")?.ToString() ?? "",
                            });
                    DhcpLeases = items;
                    LeaseCountText = $"DHCP Leases ({items.Count})";
                }
            }
            catch
            {
                DhcpLeases = new ObservableCollection<DhcpLeaseItem>();
                LeaseCountText = "DHCP Leases (unavailable)";
            }

            // Fetch TFTP transfers
            try
            {
                var resp = await _http.GetStringAsync("http://127.0.0.1:8002/transfers");
                var data = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(resp);
                if (data?.ContainsKey("recent") == true)
                {
                    var transfers = Newtonsoft.Json.JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(data["recent"]?.ToString() ?? "[]");
                    var items = new ObservableCollection<TftpTransferItem>();
                    if (transfers != null)
                        foreach (var t in transfers)
                            items.Add(new TftpTransferItem
                            {
                                Client = t.GetValueOrDefault("client")?.ToString() ?? "",
                                File = t.GetValueOrDefault("file")?.ToString() ?? "",
                                Speed = $"{t.GetValueOrDefault("speed_kbps")} KB/s",
                                Time = $"{t.GetValueOrDefault("elapsed")}s",
                            });
                    TftpTransfers = items;
                    TransferCountText = $"Recent TFTP Transfers ({items.Count})";
                }
            }
            catch
            {
                TftpTransfers = new ObservableCollection<TftpTransferItem>();
                TransferCountText = "Recent TFTP Transfers (unavailable)";
            }

            // Fetch server log
            try
            {
                var logs = await Api.GetLogsAsync(50);
                var items = new ObservableCollection<LogItem>();
                foreach (var l in logs)
                    items.Add(new LogItem { Timestamp = l.Timestamp, Level = l.Level, Message = l.Message });
                LogEntries = items;
            }
            catch { }
        }

        private async Task<bool> CheckAsync(string url)
        {
            try { var r = await _http.GetAsync(url); return r.IsSuccessStatusCode; }
            catch { return false; }
        }
    }

    // PXE Status data items
    public class DhcpLeaseItem
    {
        public string Ip { get; set; } = "";
        public string Mac { get; set; } = "";
        public string Hostname { get; set; } = "";
        public string Expires { get; set; } = "";
    }

    public class TftpTransferItem
    {
        public string Client { get; set; } = "";
        public string File { get; set; } = "";
        public string Speed { get; set; } = "";
        public string Time { get; set; } = "";
    }

    public class LogItem
    {
        public string Timestamp { get; set; } = "";
        public string Level { get; set; } = "";
        public string Message { get; set; } = "";
    }

    // ========================================================================
    // Deployments ViewModel - Live PXE client tracking
    // ========================================================================

    public partial class DeploymentsViewModel : BaseViewModel
    {
        [ObservableProperty] private ObservableCollection<PxeClientDto> _clients = new();
        [ObservableProperty] private string _clientCountText = "No PXE clients detected";
        [ObservableProperty] private PxeClientDto? _selectedClient;
        [ObservableProperty] private string _selectedClientTitle = "Client Event Log (click a client above)";
        [ObservableProperty] private ObservableCollection<ClientEventDto> _selectedClientEvents = new();

        // PXE service status (merged from PxeStatus page)
        private static readonly System.Windows.Media.SolidColorBrush _sGray = new(System.Windows.Media.Color.FromRgb(0x6C, 0x70, 0x86));
        private static readonly System.Windows.Media.SolidColorBrush _sGreen = new(System.Windows.Media.Color.FromRgb(0xA6, 0xE3, 0xA1));
        private static readonly System.Windows.Media.SolidColorBrush _sRed = new(System.Windows.Media.Color.FromRgb(0xF3, 0x8B, 0xA8));
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _dhcpColor = _sGray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _tftpColor = _sGray;
        [ObservableProperty] private System.Windows.Media.SolidColorBrush _apiColor = _sGray;
        [ObservableProperty] private string _dhcpDetail = "Checking...";
        [ObservableProperty] private string _tftpDetail = "Checking...";
        [ObservableProperty] private string _apiDetail = "Checking...";

        private readonly System.Net.Http.HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(5) };

        public DeploymentsViewModel(ApiClient api) : base(api) { }

        [RelayCommand]
        public async Task Refresh()
        {
            await RefreshAsync();
        }

        public async Task RefreshAsync()
        {
            // Refresh PXE service status
            try
            {
                await _http.GetStringAsync("http://127.0.0.1:8001/status");
                DhcpColor = _sGreen; DhcpDetail = "Running";
            }
            catch { DhcpColor = _sRed; DhcpDetail = "Stopped"; }

            try
            {
                await _http.GetStringAsync("http://127.0.0.1:8002/status");
                TftpColor = _sGreen; TftpDetail = "Running";
            }
            catch { TftpColor = _sRed; TftpDetail = "Stopped"; }

            try
            {
                await _http.GetStringAsync("http://127.0.0.1:8000/api/health");
                ApiColor = _sGreen; ApiDetail = "Running";
            }
            catch { ApiColor = _sRed; ApiDetail = "Stopped"; }

            // Refresh client list
            try
            {
                var resp = await _http.GetStringAsync("http://127.0.0.1:8000/api/pipeline/clients");
                var data = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(resp);
                if (data?.ContainsKey("clients") == true)
                {
                    var clientList = Newtonsoft.Json.JsonConvert.DeserializeObject<List<PxeClientDto>>(data["clients"]?.ToString() ?? "[]");
                    if (clientList != null)
                    {
                        Clients = new ObservableCollection<PxeClientDto>(clientList);
                        ClientCountText = $"{clientList.Count} client(s) detected";
                    }
                }
            }
            catch
            {
                ClientCountText = "Cannot connect to API server";
            }
        }

        [RelayCommand]
        private async Task SelectClient(PxeClientDto client)
        {
            SelectedClient = client;
            SelectedClientTitle = $"Event Log: {client.Mac} ({client.Hostname ?? client.Ip})";

            try
            {
                var mac = Uri.EscapeDataString(client.Mac);
                var resp = await _http.GetStringAsync($"http://127.0.0.1:8000/api/pipeline/clients/{mac}");
                var data = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, object>>(resp);
                if (data?.ContainsKey("events") == true)
                {
                    var events = Newtonsoft.Json.JsonConvert.DeserializeObject<List<ClientEventDto>>(data["events"]?.ToString() ?? "[]");
                    if (events != null)
                        SelectedClientEvents = new ObservableCollection<ClientEventDto>(events);
                }
            }
            catch { }
        }

        [RelayCommand]
        private async Task ClearClients()
        {
            try
            {
                await _http.DeleteAsync("http://127.0.0.1:8000/api/pipeline/clients");
                await RefreshAsync();
                SelectedClientEvents = new ObservableCollection<ClientEventDto>();
                SelectedClientTitle = "Client Event Log (click a client above)";
                ShowStatus("Client registry cleared");
            }
            catch { }
        }
    }

    public class PxeClientDto
    {
        [Newtonsoft.Json.JsonProperty("mac")] public string Mac { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("ip")] public string Ip { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("hostname")] public string Hostname { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("status")] public string Status { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("current_step")] public string CurrentStep { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("progress")] public int Progress { get; set; }
        [Newtonsoft.Json.JsonProperty("first_seen")] public string FirstSeen { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("last_seen")] public string LastSeen { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("pipeline_id")] public string PipelineId { get; set; } = "";
    }

    public class ClientEventDto
    {
        [Newtonsoft.Json.JsonProperty("time")] public string Time { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("event")] public string Event { get; set; } = "";
        [Newtonsoft.Json.JsonProperty("detail")] public string Detail { get; set; } = "";
    }
}
