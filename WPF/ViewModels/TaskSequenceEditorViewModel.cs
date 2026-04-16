using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using Newtonsoft.Json;
using SmartDeployDesktop.Services;

namespace SmartDeployDesktop.ViewModels
{
    // ========================================================================
    // Task Sequence Editor - backing ViewModel for the editor dialog.
    // Handles: step list, reorder, add/delete, parameter editor, variables,
    // conditions, duplicate, import, export, and auto-save (debounced).
    // ========================================================================
    public partial class TaskSequenceEditorViewModel : ObservableObject
    {
        private readonly ApiClient _api;
        private readonly DispatcherTimer _saveTimer;
        private bool _suppressDirty;
        private bool _isSaving;

        // Core sequence state
        [ObservableProperty] private string _sequenceId = "";
        [ObservableProperty] private string _name = "";
        [ObservableProperty] private string _description = "";
        [ObservableProperty] private string _osVersion = "";
        [ObservableProperty] private string _architecture = "x64";
        [ObservableProperty] private string _version = "1.0";
        [ObservableProperty] private string _created = "";
        [ObservableProperty] private string _modified = "";

        // Ordered step list
        [ObservableProperty] private ObservableCollection<TaskStepViewModel> _steps = new();
        [ObservableProperty] private TaskStepViewModel? _selectedStep;

        // Variables (sequence-level)
        [ObservableProperty] private ObservableCollection<VariableEntryViewModel> _variables = new();

        // Catalog + helpers loaded once
        [ObservableProperty] private List<StepCatalogEntryDto> _stepCatalog = new();
        [ObservableProperty] private Dictionary<string, List<StepCatalogEntryDto>> _stepCatalogByCategory = new();
        [ObservableProperty] private List<GatherVariableDto> _gatherVariables = new();
        [ObservableProperty] private List<ConditionOperatorDto> _conditionOperators = new();

        // Status + dirty indicator
        [ObservableProperty] private string _statusMessage = "";
        [ObservableProperty] private bool _hasUnsavedChanges;

        // Architecture options for the header combobox
        public List<string> ArchitectureOptions { get; } = new() { "x64", "x86", "arm64" };

        public TaskSequenceEditorViewModel(ApiClient api)
        {
            _api = api;
            // Debounced auto-save: fires ~500ms after the last change
            _saveTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(500) };
            _saveTimer.Tick += async (_, __) =>
            {
                _saveTimer.Stop();
                await SaveAsync();
            };
        }

        // --------------------------------------------------------------------
        // Loading and initialization
        // --------------------------------------------------------------------

        public async Task InitializeAsync(TaskSequenceDto dto)
        {
            _suppressDirty = true;
            try
            {
                // Load catalog + condition helpers (once per editor open)
                await LoadCatalogAndHelpersAsync();

                // Populate from DTO
                SequenceId = dto.Id;
                Name = dto.Name;
                Description = dto.Description;
                OsVersion = dto.OsVersion;
                Architecture = string.IsNullOrWhiteSpace(dto.Architecture) ? "x64" : dto.Architecture;
                Version = dto.Version;
                Created = dto.Created ?? "";
                Modified = dto.Modified ?? "";

                Steps = new ObservableCollection<TaskStepViewModel>(
                    dto.Steps
                       .OrderBy(s => s.Order)
                       .Select(s => CreateStepVm(s))
                );

                Variables = new ObservableCollection<VariableEntryViewModel>(
                    dto.Variables.Select(kv => CreateVariableVm(kv.Key, kv.Value))
                );

                SelectedStep = Steps.FirstOrDefault();
                HasUnsavedChanges = false;
                StatusMessage = "Loaded.";
            }
            finally
            {
                _suppressDirty = false;
            }
        }

        private async Task LoadCatalogAndHelpersAsync()
        {
            try
            {
                var catalog = await _api.GetStepCatalogAsync();
                StepCatalog = catalog.StepTypes.OrderBy(e => e.DisplayName).ToList();
                StepCatalogByCategory = catalog.Categories;
            }
            catch (Exception ex)
            {
                StatusMessage = $"Failed to load step catalog: {ex.Message}";
            }

            try
            {
                var helpers = await _api.GetConditionHelpersAsync();
                GatherVariables = helpers.GatherVariables;
                ConditionOperators = helpers.Operators;
            }
            catch (Exception ex)
            {
                StatusMessage = $"Failed to load condition helpers: {ex.Message}";
            }
        }

        private TaskStepViewModel CreateStepVm(TaskStepDto dto)
        {
            var vm = new TaskStepViewModel(dto, StepCatalog, GatherVariables, ConditionOperators);
            vm.AnyFieldChanged += OnStepChanged;
            return vm;
        }

        private VariableEntryViewModel CreateVariableVm(string key, string value)
        {
            var vm = new VariableEntryViewModel { Key = key, Value = value };
            vm.PropertyChanged += (_, __) => MarkDirty();
            return vm;
        }

        // --------------------------------------------------------------------
        // Dirty-tracking + auto-save
        // --------------------------------------------------------------------

        partial void OnNameChanged(string value)          => MarkDirty();
        partial void OnDescriptionChanged(string value)   => MarkDirty();
        partial void OnOsVersionChanged(string value)     => MarkDirty();
        partial void OnArchitectureChanged(string value)  => MarkDirty();

        partial void OnSelectedStepChanged(TaskStepViewModel? oldValue, TaskStepViewModel? newValue)
        {
            if (oldValue != null) oldValue.IsSelected = false;
            if (newValue != null) newValue.IsSelected = true;
        }

        private void OnStepChanged(object? sender, EventArgs e) => MarkDirty();

        private void MarkDirty()
        {
            if (_suppressDirty) return;
            HasUnsavedChanges = true;
            StatusMessage = "Unsaved changes...";
            _saveTimer.Stop();
            _saveTimer.Start();
        }

        public async Task SaveAsync()
        {
            if (_isSaving || string.IsNullOrEmpty(SequenceId)) return;
            _isSaving = true;
            try
            {
                StatusMessage = "Saving...";
                var dto = ToDto();
                var saved = await _api.UpdateTaskSequenceAsync(SequenceId, dto);
                Modified = saved.Modified ?? DateTime.Now.ToString("o");
                HasUnsavedChanges = false;
                StatusMessage = $"Saved at {DateTime.Now:HH:mm:ss}";
            }
            catch (Exception ex)
            {
                StatusMessage = $"Save failed: {ex.Message}";
            }
            finally
            {
                _isSaving = false;
            }
        }

        public TaskSequenceDto ToDto()
        {
            return new TaskSequenceDto
            {
                Id = SequenceId,
                Name = Name,
                Description = Description,
                OsVersion = OsVersion,
                Architecture = Architecture,
                Version = Version,
                Created = Created,
                Modified = Modified,
                Steps = Steps.Select((s, i) => s.ToDto(i + 1)).ToList(),
                Variables = Variables
                    .Where(v => !string.IsNullOrWhiteSpace(v.Key))
                    .ToDictionary(v => v.Key, v => v.Value ?? ""),
            };
        }

        // --------------------------------------------------------------------
        // Step operations: add, delete, move up/down
        // --------------------------------------------------------------------

        [RelayCommand]
        private void MoveStepUp(TaskStepViewModel? step)
        {
            if (step == null) return;
            var idx = Steps.IndexOf(step);
            if (idx > 0)
            {
                Steps.Move(idx, idx - 1);
                RenumberSteps();
                MarkDirty();
            }
        }

        [RelayCommand]
        private void MoveStepDown(TaskStepViewModel? step)
        {
            if (step == null) return;
            var idx = Steps.IndexOf(step);
            if (idx >= 0 && idx < Steps.Count - 1)
            {
                Steps.Move(idx, idx + 1);
                RenumberSteps();
                MarkDirty();
            }
        }

        [RelayCommand]
        private void DeleteStep(TaskStepViewModel? step)
        {
            if (step == null) return;
            var confirm = MessageBox.Show(
                $"Delete step '{step.Name}'?", "Confirm Delete",
                MessageBoxButton.YesNo, MessageBoxImage.Question);
            if (confirm != MessageBoxResult.Yes) return;

            Steps.Remove(step);
            RenumberSteps();
            if (SelectedStep == step)
                SelectedStep = Steps.FirstOrDefault();
            MarkDirty();
        }

        public void AddStepFromCatalog(StepCatalogEntryDto entry)
        {
            var nextOrder = Steps.Count + 1;
            var dto = new TaskStepDto
            {
                Id = $"s{Guid.NewGuid().ToString("N").Substring(0, 6)}",
                Order = nextOrder,
                Name = entry.DisplayName,
                Type = entry.Type,
                Enabled = true,
                ContinueOnError = false,
                Parameters = new Dictionary<string, object>(entry.DefaultParameters),
            };
            var vm = CreateStepVm(dto);
            Steps.Add(vm);
            SelectedStep = vm;
            RenumberSteps();
            MarkDirty();
        }

        private void RenumberSteps()
        {
            for (int i = 0; i < Steps.Count; i++)
                Steps[i].Order = i + 1;
        }

        // --------------------------------------------------------------------
        // Variables
        // --------------------------------------------------------------------

        [RelayCommand]
        private void AddVariable()
        {
            Variables.Add(CreateVariableVm("", ""));
            MarkDirty();
        }

        [RelayCommand]
        private void DeleteVariable(VariableEntryViewModel? v)
        {
            if (v == null) return;
            Variables.Remove(v);
            MarkDirty();
        }

        // --------------------------------------------------------------------
        // Duplicate / Export / Import (called from the dialog's toolbar)
        // --------------------------------------------------------------------

        [RelayCommand]
        private async Task Duplicate()
        {
            if (string.IsNullOrEmpty(SequenceId)) return;

            // Save current state before duplicating
            if (HasUnsavedChanges) await SaveAsync();

            try
            {
                var dup = await _api.DuplicateTaskSequenceAsync(SequenceId);
                MessageBox.Show(
                    $"Duplicated as '{dup.Name}'.\n\nClose this editor and open '{dup.Name}' from the list to edit it.",
                    "Duplicated", MessageBoxButton.OK, MessageBoxImage.Information);
                StatusMessage = $"Duplicated: {dup.Name}";
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Duplicate failed: {ex.Message}", "Error",
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        [RelayCommand]
        private async Task Export()
        {
            if (string.IsNullOrEmpty(SequenceId)) return;

            // Save any pending changes first
            if (HasUnsavedChanges) await SaveAsync();

            var dlg = new SaveFileDialog
            {
                Filter = "Task Sequence JSON|*.json",
                FileName = $"{SanitizeFilename(Name)}.json",
                Title = "Export Task Sequence",
            };
            if (dlg.ShowDialog() != true) return;

            try
            {
                var json = await _api.ExportTaskSequenceAsync(SequenceId);
                File.WriteAllText(dlg.FileName, json);
                StatusMessage = $"Exported to {dlg.FileName}";
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Export failed: {ex.Message}", "Error",
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        [RelayCommand]
        private async Task Import()
        {
            var dlg = new OpenFileDialog
            {
                Filter = "Task Sequence JSON|*.json",
                Title = "Import Task Sequence",
            };
            if (dlg.ShowDialog() != true) return;

            try
            {
                var json = File.ReadAllText(dlg.FileName);
                var payload = JsonConvert.DeserializeObject<object>(json);
                var imported = await _api.ImportTaskSequenceAsync(payload!);
                MessageBox.Show(
                    $"Imported as '{imported.Name}'.\n\nOpen it from the Task Sequences list to edit.",
                    "Imported", MessageBoxButton.OK, MessageBoxImage.Information);
                StatusMessage = $"Imported: {imported.Name}";
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Import failed: {ex.Message}", "Error",
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private static string SanitizeFilename(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return "sequence";
            foreach (var c in Path.GetInvalidFileNameChars())
                name = name.Replace(c, '_');
            return name;
        }
    }

    // ========================================================================
    // Per-step ViewModel - wraps a TaskStepDto with UI-friendly properties
    // and a dynamic parameter list generated from the catalog defaults.
    // ========================================================================
    public partial class TaskStepViewModel : ObservableObject
    {
        public event EventHandler? AnyFieldChanged;

        private readonly List<StepCatalogEntryDto> _catalog;
        public List<GatherVariableDto> GatherVariables { get; }
        public List<ConditionOperatorDto> ConditionOperators { get; }

        [ObservableProperty] private string _id = "";
        [ObservableProperty] private int _order;
        [ObservableProperty] private string _name = "";
        [ObservableProperty] private string _type = "";
        [ObservableProperty] private string _category = "";
        [ObservableProperty] private bool _enabled = true;
        [ObservableProperty] private bool _continueOnError;
        [ObservableProperty] private bool _isSelected;
        [ObservableProperty] private ObservableCollection<ParameterEditorViewModel> _parameters = new();

        // Condition (nullable - means "no condition")
        [ObservableProperty] private bool _hasCondition;
        [ObservableProperty] private string _conditionVariable = "";
        [ObservableProperty] private string _conditionOperator = "equals";
        [ObservableProperty] private string _conditionValue = "";
        [ObservableProperty] private bool _conditionNegate;

        public TaskStepViewModel(
            TaskStepDto dto,
            List<StepCatalogEntryDto> catalog,
            List<GatherVariableDto> gatherVars,
            List<ConditionOperatorDto> operators)
        {
            _catalog = catalog;
            GatherVariables = gatherVars;
            ConditionOperators = operators;

            Id = dto.Id;
            Order = dto.Order;
            Name = dto.Name;
            Type = dto.Type;
            Enabled = dto.Enabled;
            ContinueOnError = dto.ContinueOnError;

            var entry = catalog.FirstOrDefault(c => c.Type == dto.Type);
            Category = entry?.Category ?? "General";

            // Build typed parameter editors. Merge catalog defaults with saved values
            // so newly-added parameters appear even on older saved steps.
            var defaults = entry?.DefaultParameters ?? new Dictionary<string, object>();
            var merged = new Dictionary<string, object>(defaults);
            foreach (var kv in dto.Parameters) merged[kv.Key] = kv.Value;

            foreach (var kv in merged)
            {
                var pvm = new ParameterEditorViewModel(kv.Key, kv.Value);
                pvm.ValueChanged += (_, __) => AnyFieldChanged?.Invoke(this, EventArgs.Empty);
                Parameters.Add(pvm);
            }

            if (dto.Condition != null)
            {
                HasCondition = true;
                ConditionVariable = dto.Condition.Variable;
                ConditionOperator = dto.Condition.Operator;
                ConditionValue = dto.Condition.Value;
                ConditionNegate = dto.Condition.Negate;
            }
        }

        partial void OnNameChanged(string value)            => AnyFieldChanged?.Invoke(this, EventArgs.Empty);
        partial void OnEnabledChanged(bool value)           => AnyFieldChanged?.Invoke(this, EventArgs.Empty);
        partial void OnContinueOnErrorChanged(bool value)   => AnyFieldChanged?.Invoke(this, EventArgs.Empty);
        partial void OnHasConditionChanged(bool value)      => AnyFieldChanged?.Invoke(this, EventArgs.Empty);
        partial void OnConditionVariableChanged(string value) => AnyFieldChanged?.Invoke(this, EventArgs.Empty);
        partial void OnConditionOperatorChanged(string value) => AnyFieldChanged?.Invoke(this, EventArgs.Empty);
        partial void OnConditionValueChanged(string value)  => AnyFieldChanged?.Invoke(this, EventArgs.Empty);
        partial void OnConditionNegateChanged(bool value)   => AnyFieldChanged?.Invoke(this, EventArgs.Empty);

        public TaskStepDto ToDto(int newOrder)
        {
            var dto = new TaskStepDto
            {
                Id = Id,
                Order = newOrder,
                Name = Name,
                Type = Type,
                Enabled = Enabled,
                ContinueOnError = ContinueOnError,
                Parameters = Parameters.ToDictionary(p => p.Key, p => p.GetTypedValue()),
            };

            if (HasCondition && !string.IsNullOrWhiteSpace(ConditionVariable))
            {
                dto.Condition = new StepConditionDto
                {
                    Variable = ConditionVariable,
                    Operator = ConditionOperator,
                    Value = ConditionValue,
                    Negate = ConditionNegate,
                };
            }
            return dto;
        }
    }

    // ========================================================================
    // Dynamic parameter editor - one per step parameter.
    // Decides which control to show (Bool / Int / List / String) based on
    // the default value's JSON type. The XAML uses DataTriggers on Kind.
    // ========================================================================
    public partial class ParameterEditorViewModel : ObservableObject
    {
        public event EventHandler? ValueChanged;

        public string Key { get; }
        public string DisplayLabel { get; }
        public string Kind { get; }                     // "bool", "int", "list", "string"

        [ObservableProperty] private bool _boolValue;
        [ObservableProperty] private int _intValue;
        [ObservableProperty] private string _stringValue = "";
        [ObservableProperty] private string _listValue = "";   // newline-separated in the editor

        public ParameterEditorViewModel(string key, object? rawValue)
        {
            Key = key;
            DisplayLabel = HumanizeKey(key);

            switch (rawValue)
            {
                case bool b:
                    Kind = "bool";
                    BoolValue = b;
                    break;

                case int i:
                    Kind = "int";
                    IntValue = i;
                    break;

                case long l:
                    Kind = "int";
                    IntValue = (int)l;
                    break;

                case double d:
                    // Treat whole-number doubles (common from JSON) as ints
                    if (Math.Abs(d - Math.Round(d)) < 0.0001)
                    {
                        Kind = "int";
                        IntValue = (int)d;
                    }
                    else
                    {
                        Kind = "string";
                        StringValue = d.ToString();
                    }
                    break;

                case System.Collections.IEnumerable enumerable when rawValue is not string:
                    Kind = "list";
                    ListValue = string.Join(Environment.NewLine,
                        enumerable.Cast<object>().Select(x => x?.ToString() ?? ""));
                    break;

                case null:
                    Kind = "string";
                    StringValue = "";
                    break;

                default:
                    Kind = "string";
                    StringValue = rawValue.ToString() ?? "";
                    break;
            }
        }

        partial void OnBoolValueChanged(bool value)     => ValueChanged?.Invoke(this, EventArgs.Empty);
        partial void OnIntValueChanged(int value)       => ValueChanged?.Invoke(this, EventArgs.Empty);
        partial void OnStringValueChanged(string value) => ValueChanged?.Invoke(this, EventArgs.Empty);
        partial void OnListValueChanged(string value)   => ValueChanged?.Invoke(this, EventArgs.Empty);

        public object GetTypedValue()
        {
            return Kind switch
            {
                "bool" => BoolValue,
                "int"  => IntValue,
                "list" => ListValue
                          .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                          .Select(s => s.Trim())
                          .Where(s => !string.IsNullOrEmpty(s))
                          .ToList<object>(),
                _      => (object)(StringValue ?? ""),
            };
        }

        // Convert snake_case keys into "Nicer Labels"
        private static string HumanizeKey(string key)
        {
            if (string.IsNullOrEmpty(key)) return key;
            var parts = key.Split('_');
            return string.Join(" ", parts.Select(p =>
                p.Length == 0 ? p : char.ToUpper(p[0]) + p.Substring(1)));
        }

        public bool IsBool   => Kind == "bool";
        public bool IsInt    => Kind == "int";
        public bool IsList   => Kind == "list";
        public bool IsString => Kind == "string";
    }

    // ========================================================================
    // Simple key/value row for the Variables tab
    // ========================================================================
    public partial class VariableEntryViewModel : ObservableObject
    {
        [ObservableProperty] private string _key = "";
        [ObservableProperty] private string _value = "";
    }
}
