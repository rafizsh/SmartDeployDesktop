using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using Newtonsoft.Json;

namespace SmartDeployDesktop.Services
{
    /// <summary>
    /// Represents a managed Python server process (API server, DHCP, or TFTP).
    /// </summary>
    public partial class ManagedService : ObservableObject
    {
        [ObservableProperty] private string _name;
        [ObservableProperty] private string _scriptName;
        [ObservableProperty] private int _port;
        [ObservableProperty] private int _statusPort;
        [ObservableProperty] private bool _isRunning;
        [ObservableProperty] private string _status = "Stopped";
        [ObservableProperty] private string _uptime = "";
        [ObservableProperty] private Dictionary<string, object> _serviceStats = new();
        [ObservableProperty] private string _lastError = "";
        [ObservableProperty] private bool _requiresAdmin;

        public Process? Process { get; set; }

        public ManagedService(string name, string scriptName, int port, int statusPort, bool requiresAdmin = false)
        {
            _name = name;
            _scriptName = scriptName;
            _port = port;
            _statusPort = statusPort;
            _requiresAdmin = requiresAdmin;
        }
    }

    /// <summary>
    /// Manages the lifecycle of all Python server processes.
    /// Handles start, stop, restart, and health monitoring.
    /// </summary>
    public class ServiceManager : IDisposable
    {
        private readonly HttpClient _http;
        private readonly string _serverDir;
        private readonly string _pythonExe;

        public ManagedService ApiServer { get; }
        public ManagedService DhcpServer { get; }
        public ManagedService TftpServer { get; }

        public List<ManagedService> AllServices { get; }

        public ServiceManager(string serverDir, string pythonExe)
        {
            _serverDir = serverDir;
            _pythonExe = pythonExe;
            _http = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };

            ApiServer = new ManagedService("API Server", "server.py", 8000, 8000);
            DhcpServer = new ManagedService("DHCP Server", "dhcpserver.py", 67, 8001, requiresAdmin: true);
            TftpServer = new ManagedService("TFTP Server", "tftpserver.py", 69, 8002, requiresAdmin: true);

            AllServices = new List<ManagedService> { ApiServer, DhcpServer, TftpServer };
        }

        /// <summary>
        /// Start a specific service.
        /// </summary>
        public async Task<bool> StartServiceAsync(ManagedService service)
        {
            if (service.IsRunning)
                return true;

            try
            {
                string scriptPath = Path.Combine(_serverDir, service.ScriptName);
                if (!File.Exists(scriptPath))
                {
                    service.LastError = $"Script not found: {scriptPath}";
                    service.Status = "Error";
                    return false;
                }

                var args = $"\"{scriptPath}\"";

                // Add status port argument for DHCP/TFTP
                if (service != ApiServer)
                {
                    args += $" --status-port {service.StatusPort}";
                }

                var psi = new ProcessStartInfo
                {
                    FileName = _pythonExe,
                    Arguments = args,
                    WorkingDirectory = _serverDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };

                // DHCP and TFTP need admin for low ports
                if (service.RequiresAdmin)
                {
                    psi.Verb = "runas";
                    psi.UseShellExecute = true;  // Required for runas
                    psi.RedirectStandardOutput = false;
                    psi.RedirectStandardError = false;
                    psi.CreateNoWindow = true;
                    psi.WindowStyle = ProcessWindowStyle.Hidden;
                }

                psi.Environment["SMARTDEPLOY_DESKTOP"] = "1";

                service.Process = Process.Start(psi);

                if (service.Process == null)
                {
                    service.LastError = "Failed to create process";
                    service.Status = "Error";
                    return false;
                }

                // Read output in background (only for non-admin processes)
                if (!service.RequiresAdmin)
                {
                    _ = Task.Run(() => ReadOutputAsync(service));
                }

                service.Status = "Starting...";

                // Wait for the service to become healthy
                bool ready = await WaitForHealthAsync(service, timeoutSeconds: 10);

                if (ready)
                {
                    service.IsRunning = true;
                    service.Status = "Running";
                    service.LastError = "";
                    Debug.WriteLine($"[ServiceManager] {service.Name} started on port {service.Port}");
                    return true;
                }
                else
                {
                    service.Status = "Failed to start";
                    service.LastError = "Health check timeout";
                    return false;
                }
            }
            catch (System.ComponentModel.Win32Exception ex) when (ex.NativeErrorCode == 1223)
            {
                // User cancelled UAC prompt
                service.Status = "Cancelled (UAC)";
                service.LastError = "Administrator elevation was cancelled";
                return false;
            }
            catch (Exception ex)
            {
                service.LastError = ex.Message;
                service.Status = "Error";
                Debug.WriteLine($"[ServiceManager] Failed to start {service.Name}: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Stop a specific service.
        /// </summary>
        public async Task StopServiceAsync(ManagedService service)
        {
            try
            {
                if (service.Process != null && !service.Process.HasExited)
                {
                    service.Status = "Stopping...";
                    service.Process.Kill(entireProcessTree: true);
                    await Task.Run(() => service.Process.WaitForExit(5000));
                    service.Process.Dispose();
                    service.Process = null;
                }

                service.IsRunning = false;
                service.Status = "Stopped";
                service.ServiceStats = new Dictionary<string, object>();
                Debug.WriteLine($"[ServiceManager] {service.Name} stopped");
            }
            catch (Exception ex)
            {
                service.LastError = ex.Message;
                service.Status = "Error stopping";
                Debug.WriteLine($"[ServiceManager] Error stopping {service.Name}: {ex.Message}");
            }
        }

        /// <summary>
        /// Restart a service.
        /// </summary>
        public async Task<bool> RestartServiceAsync(ManagedService service)
        {
            await StopServiceAsync(service);
            await Task.Delay(1000);
            return await StartServiceAsync(service);
        }

        /// <summary>
        /// Poll health/status of all running services.
        /// </summary>
        public async Task RefreshAllStatusAsync()
        {
            foreach (var service in AllServices)
            {
                await RefreshServiceStatusAsync(service);
            }
        }

        /// <summary>
        /// Poll health/status for a single service.
        /// </summary>
        public async Task RefreshServiceStatusAsync(ManagedService service)
        {
            try
            {
                string healthUrl = service == ApiServer
                    ? $"http://127.0.0.1:{service.StatusPort}/api/health"
                    : $"http://127.0.0.1:{service.StatusPort}/health";

                var resp = await _http.GetAsync(healthUrl);

                if (resp.IsSuccessStatusCode)
                {
                    service.IsRunning = true;
                    service.Status = "Running";

                    // Fetch detailed status for DHCP/TFTP
                    if (service != ApiServer)
                    {
                        try
                        {
                            var statusResp = await _http.GetAsync($"http://127.0.0.1:{service.StatusPort}/status");
                            if (statusResp.IsSuccessStatusCode)
                            {
                                var json = await statusResp.Content.ReadAsStringAsync();
                                var stats = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                                if (stats != null)
                                    service.ServiceStats = stats;
                            }
                        }
                        catch { }
                    }
                }
                else
                {
                    if (service.IsRunning)
                    {
                        service.IsRunning = false;
                        service.Status = "Not responding";
                    }
                }
            }
            catch
            {
                if (service.Process != null && service.Process.HasExited)
                {
                    service.IsRunning = false;
                    service.Status = "Crashed";
                    service.LastError = $"Process exited with code {service.Process.ExitCode}";
                }
                else if (service.IsRunning)
                {
                    service.Status = "Not responding";
                }
            }
        }

        /// <summary>
        /// Stop all services on application shutdown.
        /// </summary>
        public async Task StopAllAsync()
        {
            foreach (var service in AllServices)
            {
                await StopServiceAsync(service);
            }
        }

        /// <summary>
        /// Get DHCP lease information.
        /// </summary>
        public async Task<List<Dictionary<string, object>>> GetDhcpLeasesAsync()
        {
            try
            {
                var resp = await _http.GetAsync($"http://127.0.0.1:{DhcpServer.StatusPort}/leases");
                if (resp.IsSuccessStatusCode)
                {
                    var json = await resp.Content.ReadAsStringAsync();
                    var data = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                    if (data?.ContainsKey("leases") == true)
                    {
                        return JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(data["leases"]?.ToString() ?? "[]")
                            ?? new List<Dictionary<string, object>>();
                    }
                }
            }
            catch { }
            return new List<Dictionary<string, object>>();
        }

        /// <summary>
        /// Get TFTP transfer history.
        /// </summary>
        public async Task<List<Dictionary<string, object>>> GetTftpTransfersAsync()
        {
            try
            {
                var resp = await _http.GetAsync($"http://127.0.0.1:{TftpServer.StatusPort}/transfers");
                if (resp.IsSuccessStatusCode)
                {
                    var json = await resp.Content.ReadAsStringAsync();
                    var data = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                    if (data?.ContainsKey("recent") == true)
                    {
                        return JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(data["recent"]?.ToString() ?? "[]")
                            ?? new List<Dictionary<string, object>>();
                    }
                }
            }
            catch { }
            return new List<Dictionary<string, object>>();
        }

        // ---- Private helpers ----

        private async Task<bool> WaitForHealthAsync(ManagedService service, int timeoutSeconds = 10)
        {
            string url = service == ApiServer
                ? $"http://127.0.0.1:{service.StatusPort}/api/health"
                : $"http://127.0.0.1:{service.StatusPort}/health";

            for (int i = 0; i < timeoutSeconds * 2; i++)
            {
                try
                {
                    var resp = await _http.GetAsync(url);
                    if (resp.IsSuccessStatusCode) return true;
                }
                catch { }
                await Task.Delay(500);
            }
            return false;
        }

        private async Task ReadOutputAsync(ManagedService service)
        {
            try
            {
                if (service.Process?.StandardOutput != null)
                {
                    while (!service.Process.StandardOutput.EndOfStream)
                    {
                        string? line = await service.Process.StandardOutput.ReadLineAsync();
                        if (line != null)
                            Debug.WriteLine($"[{service.Name}] {line}");
                    }
                }
            }
            catch { }
        }

        public void Dispose()
        {
            _ = StopAllAsync();
            _http.Dispose();
        }
    }
}
