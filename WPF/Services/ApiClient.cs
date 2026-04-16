using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace SmartDeployDesktop.Services
{
    /// <summary>
    /// Typed HTTP client for communicating with the FastAPI backend on localhost:8000.
    /// All methods return deserialized objects or throw on failure.
    /// </summary>
    public class ApiClient : IDisposable
    {
        private readonly HttpClient _http;
        private const string BaseUrl = "http://127.0.0.1:8000";

        public ApiClient()
        {
            _http = new HttpClient
            {
                BaseAddress = new Uri(BaseUrl),
                Timeout = TimeSpan.FromMinutes(30), // Long timeout for image operations
            };
        }

        // ====================================================================
        // Health
        // ====================================================================

        public async Task<bool> IsServerHealthyAsync()
        {
            try
            {
                var resp = await _http.GetAsync("/api/health");
                return resp.IsSuccessStatusCode;
            }
            catch { return false; }
        }

        // ====================================================================
        // Images
        // ====================================================================

        public async Task<List<WimImageDto>> GetImagesAsync()
            => await GetAsync<List<WimImageDto>>("/api/images/");

        public async Task<List<WimIndexDto>> GetImageInfoAsync(string imageName)
            => await GetAsync<List<WimIndexDto>>($"/api/images/{Uri.EscapeDataString(imageName)}/info");

        public async Task<WimIndexDto> GetIndexDetailsAsync(string imageName, int index)
            => await GetAsync<WimIndexDto>($"/api/images/{Uri.EscapeDataString(imageName)}/index/{index}/details");

        public async Task<ApiResult> CaptureImageAsync(CaptureImageRequest req)
            => await PostAsync<ApiResult>("/api/images/capture", req);

        public async Task<ApiResult> ImportImageAsync(string sourcePath, string? newName = null)
            => await PostAsync<ApiResult>("/api/images/import", new { source_path = sourcePath, new_name = newName });

        public async Task<ApiResult> DeleteImageAsync(string imageName)
            => await DeleteAsync<ApiResult>($"/api/images/{Uri.EscapeDataString(imageName)}");

        // ====================================================================
        // Platform Packs
        // ====================================================================

        public async Task<List<PlatformPackDto>> GetPlatformPacksAsync()
            => await GetAsync<List<PlatformPackDto>>("/api/platform-packs/");

        public async Task<PlatformPackDto> GetPlatformPackAsync(string packId)
            => await GetAsync<PlatformPackDto>($"/api/platform-packs/{Uri.EscapeDataString(packId)}");

        public async Task<ApiResult> InjectDriversAsync(string imagePath, string mountPath, string platformPackId)
            => await PostAsync<ApiResult>("/api/platform-packs/inject", new
            {
                image_path = imagePath,
                mount_path = mountPath,
                platform_pack_id = platformPackId,
                recurse = true
            });

        public async Task<ApiResult> DeletePlatformPackAsync(string packId)
            => await DeleteAsync<ApiResult>($"/api/platform-packs/{Uri.EscapeDataString(packId)}");

        // ====================================================================
        // Deployment
        // ====================================================================

        public async Task<DeploymentDto> StartDeploymentAsync(DeploymentRequest req)
            => await PostAsync<DeploymentDto>("/api/deploy/start", req);

        public async Task<List<DeploymentDto>> GetDeploymentsAsync()
            => await GetAsync<List<DeploymentDto>>("/api/deploy/status");

        public async Task<DeploymentDto> GetDeploymentStatusAsync(string deployId)
            => await GetAsync<DeploymentDto>($"/api/deploy/status/{deployId}");

        public async Task<ApiResult> CancelDeploymentAsync(string deployId)
            => await PostAsync<ApiResult>($"/api/deploy/cancel/{deployId}", null);

        public async Task<List<UsbDriveDto>> GetUsbDrivesAsync()
            => await GetAsync<List<UsbDriveDto>>("/api/deploy/usb-drives");

        public async Task<NetworkShareResult> ValidateNetworkShareAsync(string path)
            => await GetAsync<NetworkShareResult>($"/api/deploy/network-shares?path={Uri.EscapeDataString(path)}");

        // ====================================================================
        // DISM
        // ====================================================================

        public async Task<DismResultDto> MountImageAsync(string imagePath, int index, string? mountPath = null, bool readOnly = false)
            => await PostAsync<DismResultDto>("/api/dism/mount", new
            {
                image_path = imagePath, index, mount_path = mountPath, read_only = readOnly
            });

        public async Task<DismResultDto> UnmountImageAsync(string mountPath, bool commit = false)
            => await PostAsync<DismResultDto>($"/api/dism/unmount?mount_path={Uri.EscapeDataString(mountPath)}&commit={commit}", null);

        public async Task<DismResultDto> ApplyImageAsync(string imagePath, int index, string applyPath, bool verify = true)
            => await PostAsync<DismResultDto>("/api/dism/apply", new
            {
                image_path = imagePath, index, apply_path = applyPath, verify
            });

        public async Task<DismResultDto> CaptureVolumeAsync(string capturePath, string destPath, string name, string description = "", string compress = "maximum")
            => await PostAsync<DismResultDto>("/api/dism/capture", new
            {
                capture_path = capturePath, destination_path = destPath, image_name = name,
                description, compress, verify = true
            });

        public async Task<DismResultDto> SplitImageAsync(string imagePath, string outputPath, int maxSizeMb = 4000)
            => await PostAsync<DismResultDto>("/api/dism/split", new
            {
                image_path = imagePath, output_path = outputPath, max_size_mb = maxSizeMb
            });

        public async Task<DismResultDto> ExportImageAsync(string sourcePath, int sourceIndex, string destPath, string compress = "maximum")
            => await PostAsync<DismResultDto>("/api/dism/export", new
            {
                source_path = sourcePath, source_index = sourceIndex,
                destination_path = destPath, compress
            });

        public async Task<MountedImagesResult> GetMountedImagesAsync()
            => await GetAsync<MountedImagesResult>("/api/dism/mounted");

        public async Task<ApiResult> CleanupWimAsync()
            => await PostAsync<ApiResult>("/api/dism/cleanup", null);

        // ====================================================================
        // Task Sequences
        // ====================================================================

        public async Task<List<TaskSequenceDto>> GetTaskSequencesAsync()
            => await GetAsync<List<TaskSequenceDto>>("/api/task-sequences/");

        public async Task<TaskSequenceDto> GetTaskSequenceAsync(string tsId)
            => await GetAsync<TaskSequenceDto>($"/api/task-sequences/{tsId}");

        public async Task<TaskSequenceDto> CreateTaskSequenceAsync(CreateTaskSequenceRequest req)
            => await PostAsync<TaskSequenceDto>("/api/task-sequences/", req);

        public async Task<ApiResult> DeleteTaskSequenceAsync(string tsId)
            => await DeleteAsync<ApiResult>($"/api/task-sequences/{tsId}");

        public async Task<TemplateListResult> GetTaskSequenceTemplatesAsync()
            => await GetAsync<TemplateListResult>("/api/task-sequences/templates/list");

        public async Task<TaskSequenceDto> UpdateTaskSequenceAsync(string tsId, TaskSequenceDto ts)
            => await PutAsync<TaskSequenceDto>($"/api/task-sequences/{tsId}", ts);

        public async Task<TaskSequenceDto> DuplicateTaskSequenceAsync(string tsId)
            => await PostAsync<TaskSequenceDto>($"/api/task-sequences/{tsId}/duplicate", null);

        public async Task<TaskSequenceDto> ImportTaskSequenceAsync(object payload)
            => await PostAsync<TaskSequenceDto>("/api/task-sequences/import", payload);

        public async Task<string> ExportTaskSequenceAsync(string tsId)
        {
            var resp = await _http.GetAsync($"/api/task-sequences/{tsId}/export");
            resp.EnsureSuccessStatusCode();
            return await resp.Content.ReadAsStringAsync();
        }

        public async Task<TaskSequenceDto> ReorderStepsAsync(string tsId, List<string> stepIds)
            => await PostAsync<TaskSequenceDto>($"/api/task-sequences/{tsId}/steps/reorder",
                new { order = stepIds });

        public async Task<StepCatalogResult> GetStepCatalogAsync()
            => await GetAsync<StepCatalogResult>("/api/task-sequences/step-catalog");

        public async Task<ConditionHelpersResult> GetConditionHelpersAsync()
            => await GetAsync<ConditionHelpersResult>("/api/task-sequences/condition-helpers");

        // Answer Files
        public async Task<List<AnswerFileDto>> GetAnswerFilesAsync()
            => await GetAsync<List<AnswerFileDto>>("/api/task-sequences/answer-files");

        public async Task<ApiResult> GenerateAnswerFileAsync(AnswerFileSettingsDto settings, string name)
            => await PostAsync<ApiResult>($"/api/task-sequences/answer-files/generate?name={Uri.EscapeDataString(name)}", settings);

        public async Task<ApiResult> DeleteAnswerFileAsync(string afId)
            => await DeleteAsync<ApiResult>($"/api/task-sequences/answer-files/{afId}");

        // ====================================================================
        // Hardware
        // ====================================================================

        public async Task<HardwareInfoDto> GetHardwareInventoryAsync()
            => await GetAsync<HardwareInfoDto>("/api/hardware/inventory");

        public async Task<CompatibilityResultDto> CheckCompatibilityAsync()
            => await GetAsync<CompatibilityResultDto>("/api/hardware/compatibility");

        // ====================================================================
        // Dashboard
        // ====================================================================

        public async Task<DashboardStatsDto> GetDashboardStatsAsync()
            => await GetAsync<DashboardStatsDto>("/api/dashboard/stats");

        public async Task<List<LogEntryDto>> GetLogsAsync(int lines = 100, string? level = null)
        {
            string url = $"/api/dashboard/logs?lines={lines}";
            if (!string.IsNullOrEmpty(level)) url += $"&level={level}";
            return await GetAsync<List<LogEntryDto>>(url);
        }

        public async Task<ServerConfigDto> GetConfigAsync()
            => await GetAsync<ServerConfigDto>("/api/dashboard/config");

        public async Task<ApiResult> UpdateConfigAsync(Dictionary<string, object> updates)
            => await PutAsync<ApiResult>("/api/dashboard/config", updates);

        public async Task<DiskSpaceResult> GetDiskSpaceAsync()
            => await GetAsync<DiskSpaceResult>("/api/dashboard/disk-space");

        // ====================================================================
        // Infrastructure Settings
        // ====================================================================

        public async Task<InfrastructureSettingsDto> GetInfrastructureSettingsAsync()
            => await GetAsync<InfrastructureSettingsDto>("/api/settings/");

        public async Task<ApiResult> SaveInfrastructureSettingsAsync(InfrastructureSettingsDto settings)
            => await PutAsync<ApiResult>("/api/settings/", settings);

        public async Task<TestConnectionResult> TestInfrastructureAsync(string section)
        {
            string endpoint = section switch
            {
                "AD" => "/api/settings/test/active-directory",
                "DHCP" => "/api/settings/test/dhcp",
                "TFTP" => "/api/settings/test/tftp-pxe",
                "UNC" => "/api/settings/test/unc-mount",
                "WDS" => "/api/settings/test/wds",
                "MDT" => "/api/settings/test/mdt",
                _ => "/api/settings/test/active-directory",
            };
            return await PostAsync<TestConnectionResult>(endpoint, null);
        }

        public async Task<List<MappedDriveDto>> GetMappedDrivesAsync()
        {
            var result = await GetAsync<MappedDrivesResult>("/api/settings/unc-mounts/mapped");
            return result.Drives ?? new List<MappedDriveDto>();
        }

        // ====================================================================
        // HTTP Helpers
        // ====================================================================

        private async Task<T> GetAsync<T>(string url)
        {
            var resp = await _http.GetAsync(url);
            resp.EnsureSuccessStatusCode();
            var json = await resp.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<T>(json)!;
        }

        private async Task<T> PostAsync<T>(string url, object? body)
        {
            HttpContent? content = null;
            if (body != null)
            {
                var json = JsonConvert.SerializeObject(body);
                content = new StringContent(json, Encoding.UTF8, "application/json");
            }
            var resp = await _http.PostAsync(url, content);
            resp.EnsureSuccessStatusCode();
            var respJson = await resp.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<T>(respJson)!;
        }

        private async Task<T> PutAsync<T>(string url, object body)
        {
            var json = JsonConvert.SerializeObject(body);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            var resp = await _http.PutAsync(url, content);
            resp.EnsureSuccessStatusCode();
            var respJson = await resp.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<T>(respJson)!;
        }

        private async Task<T> DeleteAsync<T>(string url)
        {
            var resp = await _http.DeleteAsync(url);
            resp.EnsureSuccessStatusCode();
            var json = await resp.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<T>(json)!;
        }

        public void Dispose() => _http.Dispose();
    }

    // ====================================================================
    // DTOs - Mirror the Python Pydantic models
    // ====================================================================

    public class ApiResult
    {
        public bool Success { get; set; }
        public string Message { get; set; } = "";
        public string? Output { get; set; }
        public string? Path { get; set; }
    }

    public class WimImageDto
    {
        public string Name { get; set; } = "";
        public string Path { get; set; } = "";
        [JsonProperty("size_bytes")] public long SizeBytes { get; set; }
        [JsonProperty("size_display")] public string SizeDisplay { get; set; } = "";
        [JsonProperty("image_count")] public int ImageCount { get; set; }
        public string Format { get; set; } = "wim";
        public string Architecture { get; set; } = "x64";
        public string? Created { get; set; }
        public string? Modified { get; set; }
    }

    public class WimIndexDto
    {
        public int Index { get; set; }
        public string Name { get; set; } = "";
        public string Description { get; set; } = "";
        [JsonProperty("size_bytes")] public long SizeBytes { get; set; }
        public string Architecture { get; set; } = "";
        public string Edition { get; set; } = "";
        public string Version { get; set; } = "";
        public string Build { get; set; } = "";
    }

    public class CaptureImageRequest
    {
        [JsonProperty("source_path")] public string SourcePath { get; set; } = "";
        [JsonProperty("destination_path")] public string DestinationPath { get; set; } = "";
        [JsonProperty("image_name")] public string ImageName { get; set; } = "";
        public string Description { get; set; } = "";
        public string Compress { get; set; } = "maximum";
        public bool Verify { get; set; } = true;
    }

    public class PlatformPackDto
    {
        public string Id { get; set; } = "";
        public string Manufacturer { get; set; } = "";
        public string Model { get; set; } = "";
        [JsonProperty("os_version")] public string OsVersion { get; set; } = "";
        [JsonProperty("driver_count")] public int DriverCount { get; set; }
        [JsonProperty("size_display")] public string SizeDisplay { get; set; } = "";
        public string? Created { get; set; }
    }

    public class DeploymentDto
    {
        public string Id { get; set; } = "";
        [JsonProperty("image_name")] public string ImageName { get; set; } = "";
        public string Target { get; set; } = "";
        [JsonProperty("target_path")] public string TargetPath { get; set; } = "";
        public string Status { get; set; } = "";
        [JsonProperty("progress_percent")] public double ProgressPercent { get; set; }
        [JsonProperty("started_at")] public string? StartedAt { get; set; }
        [JsonProperty("completed_at")] public string? CompletedAt { get; set; }
        [JsonProperty("error_message")] public string? ErrorMessage { get; set; }
        [JsonProperty("current_step")] public string CurrentStep { get; set; } = "";
        [JsonProperty("elapsed_seconds")] public int ElapsedSeconds { get; set; }
    }

    public class DeploymentRequest
    {
        [JsonProperty("image_path")] public string ImagePath { get; set; } = "";
        [JsonProperty("image_index")] public int ImageIndex { get; set; } = 1;
        public string Target { get; set; } = "usb";
        [JsonProperty("target_path")] public string TargetPath { get; set; } = "";
        [JsonProperty("platform_pack_id")] public string? PlatformPackId { get; set; }
        [JsonProperty("task_sequence_id")] public string? TaskSequenceId { get; set; }
        [JsonProperty("answer_file_path")] public string? AnswerFilePath { get; set; }
        [JsonProperty("format_target")] public bool FormatTarget { get; set; }
        [JsonProperty("boot_files")] public bool BootFiles { get; set; } = true;
        [JsonProperty("verify_after")] public bool VerifyAfter { get; set; } = true;
    }

    public class UsbDriveDto
    {
        [JsonProperty("device_id")] public string DeviceId { get; set; } = "";
        [JsonProperty("drive_letter")] public string DriveLetter { get; set; } = "";
        public string Label { get; set; } = "";
        [JsonProperty("size_display")] public string SizeDisplay { get; set; } = "";
        [JsonProperty("file_system")] public string FileSystem { get; set; } = "";
    }

    public class NetworkShareResult
    {
        public string Path { get; set; } = "";
        public bool Accessible { get; set; }
        public string Message { get; set; } = "";
    }

    public class DismResultDto
    {
        public bool Success { get; set; }
        public string Operation { get; set; } = "";
        public string Message { get; set; } = "";
        public string? Details { get; set; }
        [JsonProperty("elapsed_seconds")] public double ElapsedSeconds { get; set; }
    }

    public class MountedImagesResult
    {
        [JsonProperty("mounted_images")] public List<Dictionary<string, object>> MountedImages { get; set; } = new();
    }

    public class TaskSequenceDto
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string Description { get; set; } = "";
        [JsonProperty("os_version")] public string OsVersion { get; set; } = "";
        [JsonProperty("architecture")] public string Architecture { get; set; } = "x64";
        public List<TaskStepDto> Steps { get; set; } = new();
        public Dictionary<string, string> Variables { get; set; } = new();
        public string? Created { get; set; }
        public string? Modified { get; set; }
        public string Version { get; set; } = "1.0";
    }

    public class TaskStepDto
    {
        public string Id { get; set; } = "";
        public int Order { get; set; }
        public string Name { get; set; } = "";
        public string Type { get; set; } = "";
        public bool Enabled { get; set; } = true;
        [JsonProperty("continue_on_error")] public bool ContinueOnError { get; set; } = false;
        public Dictionary<string, object> Parameters { get; set; } = new();
        public StepConditionDto? Condition { get; set; }
    }

    public class StepConditionDto
    {
        public string Variable { get; set; } = "";
        public string Operator { get; set; } = "equals";
        public string Value { get; set; } = "";
        public bool Negate { get; set; } = false;
    }

    public class StepCatalogEntryDto
    {
        public string Type { get; set; } = "";
        [JsonProperty("display_name")] public string DisplayName { get; set; } = "";
        public string Description { get; set; } = "";
        public string Category { get; set; } = "";
        [JsonProperty("default_parameters")] public Dictionary<string, object> DefaultParameters { get; set; } = new();
    }

    public class StepCatalogResult
    {
        [JsonProperty("step_types")] public List<StepCatalogEntryDto> StepTypes { get; set; } = new();
        public Dictionary<string, List<StepCatalogEntryDto>> Categories { get; set; } = new();
    }

    public class GatherVariableDto
    {
        public string Name { get; set; } = "";
        public string Description { get; set; } = "";
    }

    public class ConditionOperatorDto
    {
        public string Id { get; set; } = "";
        public string Display { get; set; } = "";
        [JsonProperty("takes_value")] public bool TakesValue { get; set; } = true;
    }

    public class ConditionHelpersResult
    {
        [JsonProperty("gather_variables")] public List<GatherVariableDto> GatherVariables { get; set; } = new();
        public List<ConditionOperatorDto> Operators { get; set; } = new();
    }

    public class CreateTaskSequenceRequest
    {
        [JsonProperty("name")] public string Name { get; set; } = "";
        [JsonProperty("description")] public string Description { get; set; } = "";
        [JsonProperty("os_version")] public string OsVersion { get; set; } = "Windows 11 Pro";
        [JsonProperty("template")] public string? Template { get; set; }
    }

    public class TemplateListResult
    {
        public List<TemplateDto> Templates { get; set; } = new();
    }

    public class TemplateDto
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string Description { get; set; } = "";
    }

    public class AnswerFileDto
    {
        public string Id { get; set; } = "";
        public string Name { get; set; } = "";
        public string Path { get; set; } = "";
        public string? Created { get; set; }
    }

    public class AnswerFileSettingsDto
    {
        [JsonProperty("computer_name")] public string ComputerName { get; set; } = "*";
        public string Organization { get; set; } = "";
        public string Owner { get; set; } = "";
        public string Timezone { get; set; } = "Pacific Standard Time";
        public string Locale { get; set; } = "en-US";
        [JsonProperty("product_key")] public string ProductKey { get; set; } = "";
        [JsonProperty("admin_password")] public string AdminPassword { get; set; } = "";
        [JsonProperty("skip_oobe")] public bool SkipOobe { get; set; } = true;
        [JsonProperty("partition_scheme")] public string PartitionScheme { get; set; } = "gpt_uefi";
        [JsonProperty("enable_remote_desktop")] public bool EnableRemoteDesktop { get; set; }
        [JsonProperty("join_domain")] public string JoinDomain { get; set; } = "";
        [JsonProperty("domain_user")] public string DomainUser { get; set; } = "";
        [JsonProperty("domain_password")] public string DomainPassword { get; set; } = "";
    }

    public class HardwareInfoDto
    {
        [JsonProperty("computer_name")] public string ComputerName { get; set; } = "";
        public string Manufacturer { get; set; } = "";
        public string Model { get; set; } = "";
        [JsonProperty("serial_number")] public string SerialNumber { get; set; } = "";
        [JsonProperty("bios_mode")] public string BiosMode { get; set; } = "";
        [JsonProperty("secure_boot")] public bool SecureBoot { get; set; }
        [JsonProperty("tpm_version")] public string TpmVersion { get; set; } = "";
        [JsonProperty("tpm_present")] public bool TpmPresent { get; set; }
        [JsonProperty("cpu_name")] public string CpuName { get; set; } = "";
        [JsonProperty("cpu_cores")] public int CpuCores { get; set; }
        [JsonProperty("ram_gb")] public double RamGb { get; set; }
        public List<Dictionary<string, object>> Disks { get; set; } = new();
        [JsonProperty("os_name")] public string OsName { get; set; } = "";
        [JsonProperty("os_build")] public string OsBuild { get; set; } = "";
    }

    public class CompatibilityResultDto
    {
        public bool Compatible { get; set; }
        public List<CompatibilityCheckDto> Checks { get; set; } = new();
        public string Summary { get; set; } = "";
    }

    public class CompatibilityCheckDto
    {
        public string Name { get; set; } = "";
        public bool Passed { get; set; }
        public string Value { get; set; } = "";
        public string Required { get; set; } = "";
    }

    public class DashboardStatsDto
    {
        [JsonProperty("total_images")] public int TotalImages { get; set; }
        [JsonProperty("total_platform_packs")] public int TotalPlatformPacks { get; set; }
        [JsonProperty("total_task_sequences")] public int TotalTaskSequences { get; set; }
        [JsonProperty("active_deployments")] public int ActiveDeployments { get; set; }
        [JsonProperty("completed_deployments")] public int CompletedDeployments { get; set; }
        [JsonProperty("failed_deployments")] public int FailedDeployments { get; set; }
        [JsonProperty("image_store_size")] public string ImageStoreSize { get; set; } = "";
        [JsonProperty("driver_store_size")] public string DriverStoreSize { get; set; } = "";
        [JsonProperty("system_info")] public Dictionary<string, object> SystemInfo { get; set; } = new();
    }

    public class LogEntryDto
    {
        public string Timestamp { get; set; } = "";
        public string Level { get; set; } = "";
        public string Source { get; set; } = "";
        public string Message { get; set; } = "";
    }

    public class ServerConfigDto
    {
        public Dictionary<string, object> Config { get; set; } = new();
    }

    public class DiskSpaceResult
    {
        public List<Dictionary<string, object>> Volumes { get; set; } = new();
    }

    // ====================================================================
    // Infrastructure Settings DTOs
    // ====================================================================

    public class InfrastructureSettingsDto
    {
        [JsonProperty("active_directory")] public AdSettingsDto? ActiveDirectory { get; set; }
        [JsonProperty("dhcp")] public DhcpSettingsDto? Dhcp { get; set; }
        [JsonProperty("tftp_pxe")] public TftpSettingsDto? TftpPxe { get; set; }
        [JsonProperty("unc_mounts")] public UncSettingsDto? UncMounts { get; set; }
        [JsonProperty("wds")] public WdsSettingsDto? Wds { get; set; }
        [JsonProperty("mdt")] public MdtSettingsDto? Mdt { get; set; }
    }

    public class AdSettingsDto
    {
        public bool Enabled { get; set; }
        [JsonProperty("domain_name")] public string DomainName { get; set; } = "";
        [JsonProperty("domain_controller")] public string DomainController { get; set; } = "";
        [JsonProperty("default_ou")] public string DefaultOu { get; set; } = "";
        [JsonProperty("join_account_username")] public string JoinAccountUsername { get; set; } = "";
        [JsonProperty("join_account_password")] public string JoinAccountPassword { get; set; } = "";
        [JsonProperty("machine_naming_template")] public string MachineNamingTemplate { get; set; } = "%PREFIX%-%SERIAL:8%";
        [JsonProperty("machine_name_prefix")] public string MachineNamePrefix { get; set; } = "WS";
        [JsonProperty("ldap_port")] public int LdapPort { get; set; } = 389;
        [JsonProperty("use_ldaps")] public bool UseLdaps { get; set; }
        [JsonProperty("search_base")] public string SearchBase { get; set; } = "";
        [JsonProperty("computer_group")] public string ComputerGroup { get; set; } = "";
    }

    public class DhcpSettingsDto
    {
        public bool Enabled { get; set; }
        [JsonProperty("dhcp_server")] public string DhcpServer { get; set; } = "";
        [JsonProperty("dns_servers")] public List<string> DnsServers { get; set; } = new();
        [JsonProperty("default_gateway")] public string DefaultGateway { get; set; } = "";
        [JsonProperty("domain_suffix")] public string DomainSuffix { get; set; } = "";
        [JsonProperty("pxe_boot_options")] public Dictionary<string, object>? PxeBootOptions { get; set; } = new();
    }

    public class TftpSettingsDto
    {
        public bool Enabled { get; set; }
        [JsonProperty("tftp_server")] public string TftpServer { get; set; } = "";
        [JsonProperty("tftp_root_path")] public string TftpRootPath { get; set; } = "";
        [JsonProperty("boot_image_path")] public string BootImagePath { get; set; } = "";
        [JsonProperty("boot_file_x64")] public string BootFileX64 { get; set; } = "boot\\x64\\wdsnbp.com";
        [JsonProperty("boot_file_bios")] public string BootFileBios { get; set; } = "boot\\x86\\wdsnbp.com";
        [JsonProperty("boot_file_uefi_http")] public string BootFileUefiHttp { get; set; } = "";
        [JsonProperty("pxe_prompt_policy")] public string PxePromptPolicy { get; set; } = "OptIn";
        [JsonProperty("pxe_prompt_timeout")] public int PxePromptTimeout { get; set; } = 5;
        [JsonProperty("bandwidth_throttle_kbps")] public int BandwidthThrottleKbps { get; set; }
    }

    public class UncSettingsDto
    {
        public List<Dictionary<string, object>> Shares { get; set; } = new();
        [JsonProperty("default_credentials_username")] public string DefaultCredentialsUsername { get; set; } = "";
        [JsonProperty("default_credentials_password")] public string DefaultCredentialsPassword { get; set; } = "";
        [JsonProperty("default_credentials_domain")] public string DefaultCredentialsDomain { get; set; } = "";
        [JsonProperty("share_images")] public string ShareImages { get; set; } = "";
        [JsonProperty("share_drivers")] public string ShareDrivers { get; set; } = "";
        [JsonProperty("share_deployment")] public string ShareDeployment { get; set; } = "";
        [JsonProperty("share_logs")] public string ShareLogs { get; set; } = "";
    }

    public class WdsSettingsDto
    {
        public bool Enabled { get; set; }
        [JsonProperty("wds_server")] public string WdsServer { get; set; } = "";
        [JsonProperty("remote_install_path")] public string RemoteInstallPath { get; set; } = "";
        [JsonProperty("default_boot_image")] public string DefaultBootImage { get; set; } = "";
        [JsonProperty("image_group")] public string ImageGroup { get; set; } = "Windows 11";
        [JsonProperty("auto_add_policy")] public string AutoAddPolicy { get; set; } = "AdminApproval";
        [JsonProperty("multicast_namespace")] public string MulticastNamespace { get; set; } = "";
        [JsonProperty("unattend_file_path")] public string UnattendFilePath { get; set; } = "";
    }

    public class MdtSettingsDto
    {
        public bool Enabled { get; set; }
        [JsonProperty("deployment_share_path")] public string DeploymentSharePath { get; set; } = "";
        [JsonProperty("deployment_share_local")] public string DeploymentShareLocal { get; set; } = "";
        [JsonProperty("toolkit_path")] public string ToolkitPath { get; set; } = "";
        [JsonProperty("monitoring_host")] public string MonitoringHost { get; set; } = "";
        [JsonProperty("monitoring_port")] public int MonitoringPort { get; set; } = 9800;
        [JsonProperty("monitoring_enabled")] public bool MonitoringEnabled { get; set; }
        [JsonProperty("database_server")] public string DatabaseServer { get; set; } = "";
        [JsonProperty("database_name")] public string DatabaseName { get; set; } = "MDT";
        [JsonProperty("rules_file_path")] public string RulesFilePath { get; set; } = "";
        [JsonProperty("bootstrap_file_path")] public string BootstrapFilePath { get; set; } = "";
    }

    public class TestConnectionResult
    {
        public bool Success { get; set; }
        public string? Message { get; set; }
        public List<TestResultItemDto>? Results { get; set; }
    }

    public class TestResultItemDto
    {
        public string Test { get; set; } = "";
        public bool Passed { get; set; }
        public string Detail { get; set; } = "";
    }

    public class MappedDriveDto
    {
        public string Name { get; set; } = "";
        public string DriveLetter { get; set; } = "";
        public string DisplayRoot { get; set; } = "";
        public double FreeGB { get; set; }
        public double UsedGB { get; set; }
    }

    public class MappedDrivesResult
    {
        public List<MappedDriveDto> Drives { get; set; } = new();
    }
}
