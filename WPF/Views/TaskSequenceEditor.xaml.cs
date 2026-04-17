using System;
using System.Windows;
using System.Windows.Input;
using SmartDeployDesktop.Services;
using SmartDeployDesktop.ViewModels;

namespace SmartDeployDesktop.Views
{
    /// <summary>
    /// Modal dialog for editing a single task sequence.
    /// Uses explicit Save / Cancel buttons - no auto-save.
    /// </summary>
    public partial class TaskSequenceEditor : Window
    {
        private readonly TaskSequenceEditorViewModel _vm;
        private readonly ApiClient _api;

        // Set when Save or Cancel triggers the close via RequestClose so the
        // Closing handler knows not to show the "unsaved changes" prompt.
        private bool _programmaticClose;

        public TaskSequenceEditor(ApiClient api, TaskSequenceDto sequence)
        {
            InitializeComponent();
            _api = api;
            _vm = new TaskSequenceEditorViewModel(api);
            DataContext = _vm;

            // VM raises this when Save (after successful save) or Cancel is clicked.
            _vm.RequestClose += (_, __) =>
            {
                _programmaticClose = true;
                Close();
            };

            // Load the sequence after the window is visible so any errors surface in the UI.
            Loaded += async (_, __) => await _vm.InitializeAsync(sequence);

            // Warn the user if they X-out the window with unsaved changes.
            Closing += (_, e) =>
            {
                if (_programmaticClose) return;
                if (!_vm.HasUnsavedChanges) return;

                var result = MessageBox.Show(
                    "You have unsaved changes. Close without saving?",
                    "Unsaved Changes",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Warning,
                    MessageBoxResult.No);

                if (result != MessageBoxResult.Yes)
                {
                    e.Cancel = true;
                }
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
    }
}
