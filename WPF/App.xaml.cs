using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using System.Windows;

namespace SmartDeployDesktop
{
    public partial class App : Application
    {
        private Process? _serverProcess;

        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);

            // Show the window FIRST, then start the server in the background
            // This prevents the app from appearing to hang
            _ = StartServerInBackgroundAsync();
        }

        protected override void OnExit(ExitEventArgs e)
        {
            StopServer();
            base.OnExit(e);
        }

        /// <summary>
        /// Starts the server without blocking the UI.
        /// </summary>
        private async Task StartServerInBackgroundAsync()
        {
            // Give the window a moment to render
            await Task.Delay(500);

            try
            {
                string serverDir = FindServerDirectory();
                string pythonExe = FindPythonExecutable(serverDir);
                string serverScript = Path.Combine(serverDir, "server.py");

                if (!File.Exists(serverScript))
                {
                    MessageBox.Show(
                        $"Server script not found:\n{serverScript}\n\nThe Server folder should be next to the WPF folder.",
                        "SmartDeploy - Server Not Found",
                        MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }

                Debug.WriteLine($"[App] Python: {pythonExe}");
                Debug.WriteLine($"[App] Server: {serverScript}");
                Debug.WriteLine($"[App] WorkDir: {serverDir}");

                var psi = new ProcessStartInfo
                {
                    FileName = pythonExe,
                    Arguments = $"\"{serverScript}\"",
                    WorkingDirectory = serverDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };

                psi.Environment["SMARTDEPLOY_DESKTOP"] = "1";

                _serverProcess = Process.Start(psi);

                if (_serverProcess == null)
                {
                    MessageBox.Show(
                        "Failed to start the Python server process.",
                        "SmartDeploy - Process Error",
                        MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }

                // Log server output in background
                _ = Task.Run(async () =>
                {
                    try
                    {
                        while (!_serverProcess.StandardError.EndOfStream)
                        {
                            string? line = await _serverProcess.StandardError.ReadLineAsync();
                            if (line != null) Debug.WriteLine($"[SERVER-ERR] {line}");
                        }
                    }
                    catch { }
                });

                _ = Task.Run(async () =>
                {
                    try
                    {
                        while (!_serverProcess.StandardOutput.EndOfStream)
                        {
                            string? line = await _serverProcess.StandardOutput.ReadLineAsync();
                            if (line != null) Debug.WriteLine($"[SERVER] {line}");
                        }
                    }
                    catch { }
                });

                // Check if the process died immediately
                await Task.Delay(2000);
                if (_serverProcess.HasExited)
                {
                    string stderr = "";
                    try { stderr = await _serverProcess.StandardError.ReadToEndAsync(); } catch { }

                    MessageBox.Show(
                        $"Python server exited immediately (code {_serverProcess.ExitCode}).\n\n" +
                        $"Python: {pythonExe}\n" +
                        $"Script: {serverScript}\n\n" +
                        $"Error output:\n{stderr.Substring(0, Math.Min(stderr.Length, 500))}",
                        "SmartDeploy - Server Crashed",
                        MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }

                // Wait for the server to become ready
                bool ready = await WaitForServerAsync(timeoutSeconds: 15);

                if (!ready)
                {
                    MessageBox.Show(
                        "The backend server started but is not responding on http://localhost:8000\n\n" +
                        "Check that FastAPI and Uvicorn are installed:\n" +
                        "  pip install fastapi uvicorn pydantic",
                        "SmartDeploy - Server Timeout",
                        MessageBoxButton.OK, MessageBoxImage.Warning);
                }
                else
                {
                    Debug.WriteLine("[App] Server is ready on port 8000.");
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    $"Failed to start the backend server:\n\n{ex.Message}\n\n" +
                    "Ensure Python 3.10+ is installed and on your PATH:\n" +
                    "  python --version",
                    "SmartDeploy - Startup Error",
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// Polls localhost:8000/api/health until the server responds.
        /// </summary>
        private async Task<bool> WaitForServerAsync(int timeoutSeconds = 15)
        {
            using var client = new System.Net.Http.HttpClient();
            client.Timeout = TimeSpan.FromSeconds(2);

            for (int i = 0; i < timeoutSeconds * 2; i++)
            {
                try
                {
                    var response = await client.GetAsync("http://127.0.0.1:8000/api/health");
                    if (response.IsSuccessStatusCode)
                        return true;
                }
                catch { }
                await Task.Delay(500);
            }

            return false;
        }

        /// <summary>
        /// Finds the Server directory.
        /// </summary>
        private string FindServerDirectory()
        {
            string exeDir = AppDomain.CurrentDomain.BaseDirectory;

            // Check: [exe_dir]/Server/
            string candidate = Path.Combine(exeDir, "Server");
            if (Directory.Exists(candidate) && File.Exists(Path.Combine(candidate, "server.py")))
                return candidate;

            // Check: [exe_dir]/../../../Server/ (when running from WPF/bin/Debug/net8.0-windows)
            candidate = Path.GetFullPath(Path.Combine(exeDir, "..", "..", "..", "..", "Server"));
            if (Directory.Exists(candidate) && File.Exists(Path.Combine(candidate, "server.py")))
                return candidate;

            // Check: [exe_dir]/../../Server/
            candidate = Path.GetFullPath(Path.Combine(exeDir, "..", "..", "Server"));
            if (Directory.Exists(candidate) && File.Exists(Path.Combine(candidate, "server.py")))
                return candidate;

            // Check: sibling folder
            candidate = Path.GetFullPath(Path.Combine(exeDir, "..", "Server"));
            if (Directory.Exists(candidate) && File.Exists(Path.Combine(candidate, "server.py")))
                return candidate;

            throw new FileNotFoundException(
                $"Cannot locate the Server directory with server.py.\n" +
                $"Searched from: {exeDir}\n" +
                $"Expected: a 'Server' folder containing server.py");
        }

        /// <summary>
        /// Finds a Python executable.
        /// </summary>
        private string FindPythonExecutable(string serverDir)
        {
            // 1. Bundled Python
            string[] bundledPaths = new[]
            {
                Path.Combine(serverDir, "python", "python.exe"),
                Path.Combine(serverDir, "..", "python", "python.exe"),
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "python", "python.exe"),
            };

            foreach (var p in bundledPaths)
            {
                if (File.Exists(p))
                {
                    Debug.WriteLine($"[App] Using bundled Python: {p}");
                    return Path.GetFullPath(p);
                }
            }

            // 2. Venv
            string venvPython = Path.Combine(serverDir, "venv", "Scripts", "python.exe");
            if (File.Exists(venvPython))
            {
                Debug.WriteLine($"[App] Using venv Python: {venvPython}");
                return venvPython;
            }

            // 3. System Python from PATH
            string[] systemNames = { "python", "python3", "python3.13", "python3.12", "python3.11", "python3.10", "py" };
            foreach (var name in systemNames)
            {
                try
                {
                    var psi = new ProcessStartInfo
                    {
                        FileName = name,
                        Arguments = "--version",
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                    };
                    var proc = Process.Start(psi);
                    if (proc != null)
                    {
                        proc.WaitForExit(3000);
                        if (proc.ExitCode == 0)
                        {
                            Debug.WriteLine($"[App] Using system Python: {name}");
                            return name;
                        }
                    }
                }
                catch { }
            }

            throw new FileNotFoundException(
                "Python not found.\n\n" +
                "Install Python 3.10+ from python.org and ensure it's on your PATH,\n" +
                "or place an embedded Python distribution in the 'python' folder.");
        }

        /// <summary>
        /// Stops the server process on application exit.
        /// </summary>
        private void StopServer()
        {
            try
            {
                if (_serverProcess != null && !_serverProcess.HasExited)
                {
                    Debug.WriteLine("[App] Stopping server...");
                    _serverProcess.Kill(entireProcessTree: true);
                    _serverProcess.WaitForExit(5000);
                    _serverProcess.Dispose();
                    _serverProcess = null;
                    Debug.WriteLine("[App] Server stopped.");
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[App] Error stopping server: {ex.Message}");
            }
        }
    }
}
