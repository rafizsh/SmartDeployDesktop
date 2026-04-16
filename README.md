# SmartDeploy Desktop

A standalone Windows application for OS imaging, driver management, and deployment — full feature parity with the SmartDeploy web tool, packaged as a native WPF desktop app with a Python backend.

## Architecture

```
┌─────────────────────────────────────────────────┐
│              SmartDeploy Desktop                 │
│                                                  │
│  ┌──────────────┐       ┌─────────────────────┐  │
│  │  WPF (.exe)  │──────▶│  server.py (FastAPI) │  │
│  │  C# / .NET 8 │ HTTP  │  Python / Uvicorn    │  │
│  │              │◀──────│  localhost:8000       │  │
│  │  • GUI       │       │                      │  │
│  │  • Navigation│       │  • DISM operations    │  │
│  │  • Forms     │       │  • PowerShell calls   │  │
│  │  • Status    │       │  • WIM management     │  │
│  └──────────────┘       │  • Driver injection   │  │
│        ▲                │  • Deploy logic       │  │
│        │ launches       │  • Task sequences     │  │
│        │ & kills        │  • Answer file gen    │  │
│        └────────────────│  • Hardware inventory  │  │
│                         └─────────────────────┘  │
└─────────────────────────────────────────────────┘
```

**Flow:**
1. User double-clicks `SmartDeployDesktop.exe`
2. WPF app launches `server.py` as a child process (localhost:8000)
3. WPF sends HTTP requests to `http://127.0.0.1:8000/api/...`
4. Python backend executes DISM, PowerShell, diskpart, etc.
5. WPF displays results in the native GUI
6. Closing the app kills the server process

## Features

| Module | Capabilities |
|--------|-------------|
| **WIM Images** | List, capture, import, delete, inspect indexes |
| **Platform Packs** | Browse driver collections, inject into images |
| **Deployment** | Deploy to USB, network share, cloud (Azure/S3) |
| **DISM Operations** | Mount, unmount, apply, capture, split, export, cleanup |
| **Task Sequences** | Create from templates (bare metal, refresh, upgrade, capture) |
| **Answer Files** | Generate unattend.xml with partition, domain, OOBE settings |
| **Hardware** | Full inventory, Windows 11 compatibility check |
| **Dashboard** | Stats, logs, disk space, server configuration |

## Project Structure

```
SmartDeployDesktop/
├── Server/                     # Python FastAPI backend
│   ├── server.py               # Entry point (uvicorn on :8000)
│   ├── requirements.txt        # fastapi, uvicorn, pydantic
│   ├── routes/                 # API route modules
│   │   ├── images.py           # /api/images/*
│   │   ├── platform_packs.py   # /api/platform-packs/*
│   │   ├── deployment.py       # /api/deploy/*
│   │   ├── dism.py             # /api/dism/*
│   │   ├── task_sequences.py   # /api/task-sequences/*
│   │   ├── hardware.py         # /api/hardware/*
│   │   └── dashboard.py        # /api/dashboard/*
│   ├── services/
│   │   └── config_service.py   # Persistent config management
│   ├── models/
│   │   └── schemas.py          # Pydantic request/response models
│   └── utils/
│       ├── powershell.py       # Async PowerShell execution wrapper
│       └── logger.py           # Rotating file + console logging
│
├── WPF/                        # C# WPF desktop application
│   ├── SmartDeployDesktop.csproj
│   ├── App.xaml / App.xaml.cs  # Startup, server lifecycle
│   ├── Views/
│   │   └── MainWindow.xaml     # Full UI with 7 feature pages
│   ├── ViewModels/
│   │   ├── BaseViewModel.cs    # MVVM base with loading/error states
│   │   └── MainViewModel.cs    # All page ViewModels + navigation
│   ├── Services/
│   │   └── ApiClient.cs        # Typed HTTP client + all DTOs
│   ├── Converters/
│   │   └── Converters.cs       # XAML value converters
│   └── Resources/
│
├── Build/
│   ├── build.bat               # Build + bundle script
│   └── setup-python.bat        # Download embedded Python
│
└── README.md
```

## Prerequisites

**Development:**
- .NET 8 SDK
- Python 3.10+ with pip
- Visual Studio 2022 or VS Code

**End-user (bundled Python):**
- Windows 10/11 (64-bit)
- .NET 8 Runtime
- No Python installation needed

**End-user (system Python):**
- Windows 10/11 (64-bit)
- .NET 8 Runtime
- Python 3.10+ with FastAPI and Uvicorn installed

## Quick Start (Development)

```bash
# 1. Install Python dependencies
cd Server
pip install -r requirements.txt

# 2. Test the server standalone
python server.py
# Visit http://localhost:8000/docs for the API explorer

# 3. Build and run the WPF app
cd ../WPF
dotnet run
```

## Building for Distribution

### Option A: With bundled Python (recommended)

```bash
# One-time setup: downloads Python embeddable + installs deps
cd Build
setup-python.bat

# Build the distributable package
build.bat
```

Output in `Build/Output/` — a single folder you can zip and distribute.

### Option B: Requiring system Python

```bash
cd Build
build.bat
```

Users must have Python 3.10+ installed with `pip install fastapi uvicorn`.

## API Documentation

When the server is running, visit:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Health check:** http://localhost:8000/api/health

## Configuration

Server configuration is stored at:
```
%LOCALAPPDATA%\SmartDeployDesktop\config.json
```

Default working directories:
```
C:\SmartDeploy\Images\          # WIM image store
C:\SmartDeploy\PlatformPacks\   # Driver collections
C:\SmartDeploy\Mount\           # DISM mount points
C:\SmartDeploy\TaskSequences\   # Saved task sequences
C:\SmartDeploy\AnswerFiles\     # Generated unattend.xml files
C:\SmartDeploy\Logs\            # Operation logs
```

All paths are configurable via the Dashboard → Config page or directly in the JSON file.
