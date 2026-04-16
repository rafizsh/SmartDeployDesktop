using System;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using SmartDeployDesktop.Services;
using SmartDeployDesktop.ViewModels;

namespace SmartDeployDesktop.Views
{
    /// <summary>
    /// Modal dialog for editing a single task sequence.
    /// Auto-saves on every change (debounced in the ViewModel) - there is no Cancel.
    /// </summary>
    public partial class TaskSequenceEditor : Window
    {
        private readonly TaskSequenceEditorViewModel _vm;
        private readonly ApiClient _api;

        private bool _closingHandled;

        public TaskSequenceEditor(ApiClient api, TaskSequenceDto sequence)
        {
            InitializeComponent();
            _api = api;
            _vm = new TaskSequenceEditorViewModel(api);
            DataContext = _vm;

            // Kick off async initialization without blocking the constructor.
            Loaded += async (_, __) => await _vm.InitializeAsync(sequence);

            // Flush any pending auto-save when the user closes the window.
            Closing += async (_, e) =>
            {
                if (_closingHandled || !_vm.HasUnsavedChanges) return;
                _closingHandled = true;
                e.Cancel = true;
                await _vm.SaveAsync();
                Dispatcher.InvokeAsync(Close);
            };
        }

        /// <summary>
        /// Clicking anywhere on a step row selects it in the ViewModel.
        /// </summary>
        private void StepRow_Click(object sender, MouseButtonEventArgs e)
        {
            if (sender is FrameworkElement fe && fe.DataContext is TaskStepViewModel step)
            {
                _vm.SelectedStep = step;
            }
        }

        /// <summary>
        /// Opens the step-catalog picker dialog and adds the chosen step.
        /// </summary>
        private void AddStepButton_Click(object sender, RoutedEventArgs e)
        {
            var picker = new StepCatalogPicker(_vm.StepCatalog)
            {
                Owner = this,
            };
            if (picker.ShowDialog() == true && picker.SelectedEntry != null)
            {
                _vm.AddStepFromCatalog(picker.SelectedEntry);
            }
        }

        private void CloseButton_Click(object sender, RoutedEventArgs e) => Close();
    }
}
