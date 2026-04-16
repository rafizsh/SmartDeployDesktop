# SmartDeploy Desktop — Complete File Map & Dependencies

---

## PROJECT STRUCTURE (34 files)

```
SmartDeployDesktop/
│
├── README.md                                    # Project overview & quick start
│
├── Build/
│   ├── build.bat                                # Compiles WPF + bundles Server
│   └── setup-python.bat                         # Downloads embedded Python 3.12
│
├── Server/                                      # Python FastAPI backend
│   ├── server.py                                # ★ Main entry — launches FastAPI on :8000
│   ├── dhcpserver.py                            # ★ Standalone DHCP server (ports 67, 60, 4011)
│   ├── tftpserver.py                            # ★ Standalone TFTP server (ports 69, 60)
│   ├── requirements.txt                         # Python package dependencies
│   │
│   ├── routes/                                  # API endpoint modules
│   │   ├── __init__.py
│   │   ├── images.py                            # /api/images/* — WIM management
│   │   ├── platform_packs.py                    # /api/platform-packs/* — driver packs
│   │   ├── deployment.py                        # /api/deploy/* — USB/network/cloud deploy
│   │   ├── dism.py                              # /api/dism/* — mount/apply/split/export
│   │   ├── task_sequences.py                    # /api/task-sequences/* — 18 step types + templates
│   │   ├── pipeline.py                          # /api/pipeline/* — 19-step deployment flow
│   │   ├── hardware.py                          # /api/hardware/* — inventory + Win11 compat
│   │   ├── dashboard.py                         # /api/dashboard/* — stats/logs/config
│   │   └── settings.py                          # /api/settings/* — AD/DHCP/TFTP/UNC/WDS/MDT
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   └── config_service.py                    # Persistent JSON config manager
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py                           # Pydantic request/response models
│   │
│   └── utils/
│       ├── __init__.py
│       ├── powershell.py                        # Async PowerShell/DISM/diskpart wrapper
│       └── logger.py                            # Rotating file + console logging
│
└── WPF/                                         # C# WPF desktop application
    ├── SmartDeployDesktop.csproj                 # .NET 8 project file + NuGet refs
    ├── App.xaml                                  # Material Design dark theme + color palette
    ├── App.xaml.cs                               # Startup — finds Python, launches server.py
    │
    ├── Views/
    │   ├── MainWindow.xaml                       # Full UI — sidebar nav + all 8 pages
    │   └── MainWindow.xaml.cs                    # Code-behind (click handlers)
    │
    ├── ViewModels/
    │   ├── BaseViewModel.cs                      # MVVM base — loading/error state
    │   └── MainViewModel.cs                      # All page VMs + SettingsViewModel
    │
    ├── Services/
    │   ├── ApiClient.cs                          # Typed HTTP client + all DTOs
    │   └── ServiceManager.cs                     # Manages 3 Python server processes
    │
    ├── Converters/
    │   └── Converters.cs                         # XAML value converters
    │
    └── Resources/                                # (icons, assets — add your own)


```

---

## DEPENDENCY MAP

### What you need to install on your DEV machine:

```
┌─────────────────────────────────────────────────────────────────────┐
│  .NET 8 SDK                                                         │
│  Download: https://dotnet.microsoft.com/download/dotnet/8.0         │
│  Needed for: Building the WPF application                          │
│  Install: dotnet-sdk-8.0.xxx-win-x64.exe                           │
│  Verify:  dotnet --version                                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  Python 3.10+ (3.12 recommended)                                    │
│  Download: https://www.python.org/downloads/                        │
│  Needed for: Running server.py, dhcpserver.py, tftpserver.py       │
│  Install: python-3.12.x-amd64.exe (check "Add to PATH")           │
│  Verify:  python --version                                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  Visual Studio 2022 (optional but recommended)                      │
│  Download: https://visualstudio.microsoft.com/                      │
│  Workload: ".NET Desktop Development"                               │
│  Alternative: VS Code + C# Dev Kit extension                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Python packages (Server/requirements.txt):

```
pip install fastapi==0.115.0 uvicorn[standard]==0.30.0 pydantic==2.9.0
```

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | 0.115.0 | REST API framework (all /api/* endpoints) |
| uvicorn | 0.30.0  | ASGI server (runs FastAPI on localhost:8000) |
| pydantic | 2.9.0  | Data validation & serialization for all models |

No other Python packages needed — dhcpserver.py and tftpserver.py use only stdlib.

### NuGet packages (auto-restored by dotnet build):

| Package | Version | Purpose |
|---------|---------|---------|
| Newtonsoft.Json | 13.0.3 | JSON serialization for API communication |
| CommunityToolkit.Mvvm | 8.2.2 | MVVM framework (ObservableObject, RelayCommand) |
| MaterialDesignThemes | 5.1.0 | Material Design UI components & dark theme |
| MaterialDesignColors | 3.1.0 | Color palette for Material Design |

---

## PROCESS ARCHITECTURE

```
┌──────────────────────────────────────────────────────────────────┐
│  SmartDeployDesktop.exe  (WPF / .NET 8)                          │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  ServiceManager.cs manages 3 child processes:              │   │
│  │                                                            │   │
│  │  ┌─────────────────────────────────────────────┐           │   │
│  │  │  python server.py                            │           │   │
│  │  │  localhost:8000  (REST API)                   │           │   │
│  │  │  Status: /api/health                          │           │   │
│  │  └─────────────────────────────────────────────┘           │   │
│  │                                                            │   │
│  │  ┌─────────────────────────────────────────────┐           │   │
│  │  │  python dhcpserver.py                        │           │   │
│  │  │  Ports: 67 + 60 + 4011 (UDP)                 │           │   │
│  │  │  Status API: localhost:8001/health            │           │   │
│  │  │  Requires: Run as Administrator               │           │   │
│  │  └─────────────────────────────────────────────┘           │   │
│  │                                                            │   │
│  │  ┌─────────────────────────────────────────────┐           │   │
│  │  │  python tftpserver.py                        │           │   │
│  │  │  Ports: 69 + 60 (UDP)                        │           │   │
│  │  │  Status API: localhost:8002/health            │           │   │
│  │  │  Requires: Run as Administrator               │           │   │
│  │  └─────────────────────────────────────────────┘           │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Port Map:

| Port | Protocol | Service | Purpose |
|------|----------|---------|---------|
| 8000 | TCP/HTTP | server.py | REST API (all features) |
| 8001 | TCP/HTTP | dhcpserver.py | DHCP status/health API |
| 8002 | TCP/HTTP | tftpserver.py | TFTP status/health API |
| 67 | UDP | dhcpserver.py | Standard DHCP |
| 60 | UDP | dhcpserver.py + tftpserver.py | Alternate non-privileged port |
| 4011 | UDP | dhcpserver.py | PXE Proxy DHCP (boot info only) |
| 69 | UDP | tftpserver.py | Standard TFTP |

---

## SETUP STEPS (in order)

### Step 1: Install .NET 8 SDK

```
Download: https://dotnet.microsoft.com/download/dotnet/8.0
Run:      dotnet-sdk-8.0.xxx-win-x64.exe
Verify:   dotnet --version  →  8.0.xxx
```

### Step 2: Install Python 3.12

```
Download: https://www.python.org/downloads/release/python-3124/
Run:      python-3.12.4-amd64.exe
          ☑ Check "Add python.exe to PATH"
          ☑ Check "Install for all users"
Verify:   python --version  →  Python 3.12.4
```

### Step 3: Install Python dependencies

```
cd SmartDeployDesktop\Server
pip install -r requirements.txt
```

### Step 4: Test the API server standalone

```
cd SmartDeployDesktop\Server
python server.py
```
Open browser: http://localhost:8000/docs (Swagger API explorer)
Press Ctrl+C to stop.

### Step 5: Test DHCP server standalone (Run as Administrator)

```
cd SmartDeployDesktop\Server
python dhcpserver.py --enable-proxy
```
Status: http://localhost:8001/status

### Step 6: Test TFTP server standalone (Run as Administrator)

```
cd SmartDeployDesktop\Server
python tftpserver.py --root C:\RemoteInstall
```
Status: http://localhost:8002/status

### Step 7: Restore NuGet packages & build WPF

```
cd SmartDeployDesktop\WPF
dotnet restore
dotnet build
```

### Step 8: Run the full application

```
cd SmartDeployDesktop\WPF
dotnet run
```
The WPF app launches, starts server.py automatically,
DHCP/TFTP can be started from the Settings page.

---

## BUILDING FOR DISTRIBUTION

### Option A: Bundled Python (no Python install required on target)

```
cd SmartDeployDesktop\Build
setup-python.bat          ← Downloads Python embeddable + installs deps
build.bat                 ← Builds WPF + bundles everything
```

Output: `Build\Output\` → zip and distribute.

### Option B: System Python required

```
cd SmartDeployDesktop\Build
build.bat
```

Target machine needs: .NET 8 Runtime + Python 3.10+ with fastapi/uvicorn.

---

## FILE-BY-FILE PURPOSE

### Server Core (3 files)

| File | Lines | Purpose |
|------|-------|---------|
| server.py | ~120 | FastAPI app, registers all 9 route modules, lifespan events |
| dhcpserver.py | ~790 | Full DHCP server: packet parse/build, lease manager, scopes, PXE options, proxy DHCP (4011), multi-port bind, HTTP status API |
| tftpserver.py | ~560 | Full TFTP server: RRQ handler, block transfer, blksize negotiation, session tracking, multi-port bind, HTTP status API |

### API Routes (9 files)

| File | Endpoints | Purpose |
|------|-----------|---------|
| images.py | /api/images/* | List, capture, import, delete WIM files; parse DISM index info |
| platform_packs.py | /api/platform-packs/* | List, import, delete driver packs; inject into mounted images |
| deployment.py | /api/deploy/* | Start deployments to USB/network/cloud; track progress; list USB drives |
| dism.py | /api/dism/* | Mount, unmount, apply, capture, split, export WIM; cleanup |
| task_sequences.py | /api/task-sequences/* | 18 step-type catalog; create from 5 templates; answer file generator |
| pipeline.py | /api/pipeline/* | 19-step deployment flow; state persistence; client callback; computer naming |
| hardware.py | /api/hardware/* | Full hardware inventory via WMI; Windows 11 compatibility checker |
| dashboard.py | /api/dashboard/* | Stats, recent logs, disk space, server config CRUD |
| settings.py | /api/settings/* | AD, DHCP, TFTP, UNC, WDS, MDT config; test connection endpoints |

### Services & Utilities (3 files)

| File | Purpose |
|------|---------|
| config_service.py | Loads/saves config.json in %LOCALAPPDATA%\SmartDeployDesktop |
| powershell.py | Async subprocess wrapper for PowerShell, DISM.exe, diskpart |
| logger.py | Rotating file handler (10MB, 5 backups) + console logging |

### WPF Application (9 files)

| File | Purpose |
|------|---------|
| SmartDeployDesktop.csproj | Project file: .NET 8, WPF, NuGet package references |
| App.xaml | Material Design dark theme, color palette (Catppuccin Mocha) |
| App.xaml.cs | Startup: finds Python (bundled or system), launches server.py, polls health, kills on exit |
| MainWindow.xaml | Full UI: sidebar nav, 8 content pages (Dashboard, Images, Platform Packs, DISM, Deploy, Task Sequences, Hardware, Settings) |
| MainWindow.xaml.cs | Click event handlers |
| BaseViewModel.cs | MVVM base: IsLoading, HasError, RunAsync wrapper |
| MainViewModel.cs | 9 sub-ViewModels (one per page) + navigation + health timer |
| ApiClient.cs | Typed HttpClient with all DTOs mirroring Pydantic models |
| ServiceManager.cs | Manages lifecycle of 3 Python processes: start/stop/restart/health poll |
| Converters.cs | XAML value converters (null→visibility, string→visibility, bytes→size) |

---

## WORKING DIRECTORIES (created automatically)

```
C:\SmartDeploy\
├── Images\              ← WIM image store
├── PlatformPacks\       ← Driver collections (Manufacturer_Model_OS)
├── Mount\               ← DISM mount points
├── TaskSequences\       ← Saved task sequences (.json)
├── AnswerFiles\         ← Generated unattend.xml files
├── Drivers\             ← General driver store
├── Logs\                ← Operation logs
└── USBTemplate\         ← USB boot media template

C:\RemoteInstall\        ← TFTP root (PXE boot files)

%LOCALAPPDATA%\SmartDeployDesktop\
├── config.json          ← Server configuration
├── infrastructure.json  ← AD/DHCP/TFTP/UNC/WDS/MDT settings
├── dhcp_config.json     ← DHCP server scopes & options
├── tftp_config.json     ← TFTP server settings
└── Logs\
    └── server.log       ← API server log (rotating)
```

---

## 19-STEP DEPLOYMENT PIPELINE

```
PHASE 1: WinPE                    PHASE 2         PHASE 3: Post-Install
┌─────────────────────────┐  ┌──────────┐  ┌──────────────────────────────┐
│  1. PXE Boot             │  │ 11. Save │  │ 13. DHCP Network Connect     │
│  2. TFTP → winpe.wim     │  │     state│  │ 14. Callback to server       │
│  3. Boot WinPE           │  │     and  │  │     + map deployment share   │
│  4. Format disk (GPT)    │  │     reboot│  │ 15. Admin auto-logon         │
│  5. Stage matching drivers│  │          │  │ 16. Resume task sequence     │
│  6. Rename computer      │  │ 12. First│  │     (progress window)        │
│  7. Apply install.wim    │  │     boot │  │ 17. Install software +       │
│  8. Inject drivers       │  │     OOBE │  │     Windows updates          │
│  9. Copy custom scripts  │  │          │  │ 18. Join domain              │
│ 10. Apply unattend.xml   │  │          │  │ 19. Final reboot             │
└─────────────────────────┘  └──────────┘  └──────────────────────────────┘
```

State survives reboot via pipeline_state.json written in step 11,
read back in step 14 when the client calls POST /api/pipeline/callback.
