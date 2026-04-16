using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using SmartDeployDesktop.Services;

namespace SmartDeployDesktop.Views
{
    /// <summary>
    /// Secondary dialog for picking a step type from the catalog.
    /// Shows all steps with a category filter and search box.
    /// </summary>
    public partial class StepCatalogPicker : Window
    {
        private readonly List<StepCatalogEntryDto> _allEntries;
        private string _activeCategory = "All";
        private string _searchText = "";

        public StepCatalogEntryDto? SelectedEntry { get; private set; }

        public StepCatalogPicker(List<StepCatalogEntryDto> catalog)
        {
            InitializeComponent();
            _allEntries = catalog ?? new List<StepCatalogEntryDto>();

            // Build the category list (prepend "All") from distinct categories in the catalog.
            var categories = new List<CategoryChip> { new() { Name = "All" } };
            categories.AddRange(
                _allEntries.Select(e => e.Category)
                           .Distinct()
                           .OrderBy(c => c)
                           .Select(c => new CategoryChip { Name = c }));
            CategoryChips.ItemsSource = categories;

            ApplyFilter();
        }

        /// <summary>
        /// Recomputes StepList.ItemsSource based on the active category and search text.
        /// </summary>
        private void ApplyFilter()
        {
            IEnumerable<StepCatalogEntryDto> filtered = _allEntries;

            if (_activeCategory != "All")
                filtered = filtered.Where(e => e.Category == _activeCategory);

            if (!string.IsNullOrWhiteSpace(_searchText))
            {
                var q = _searchText.Trim().ToLowerInvariant();
                filtered = filtered.Where(e =>
                    e.DisplayName.ToLowerInvariant().Contains(q)
                    || e.Description.ToLowerInvariant().Contains(q)
                    || e.Type.ToLowerInvariant().Contains(q));
            }

            StepList.ItemsSource = filtered.OrderBy(e => e.DisplayName).ToList();
        }

        private void SearchBox_TextChanged(object sender, TextChangedEventArgs e)
        {
            _searchText = SearchBox.Text ?? "";
            ApplyFilter();
        }

        private void CategoryChip_Click(object sender, RoutedEventArgs e)
        {
            if (sender is Button btn && btn.Tag is string cat)
            {
                _activeCategory = cat;
                ApplyFilter();
            }
        }

        /// <summary>
        /// Single click selects the entry and enables the Add button.
        /// Double click (ClickCount == 2) selects and adds immediately.
        /// </summary>
        private void StepEntry_Click(object sender, MouseButtonEventArgs e)
        {
            if (sender is FrameworkElement fe && fe.DataContext is StepCatalogEntryDto entry)
            {
                SelectedEntry = entry;
                SelectedLabel.Text = $"Selected: {entry.DisplayName}";
                AddButton.IsEnabled = true;

                if (e.ClickCount == 2)
                {
                    DialogResult = true;
                    Close();
                }
            }
        }

        private void AddButton_Click(object sender, RoutedEventArgs e)
        {
            if (SelectedEntry != null)
            {
                DialogResult = true;
                Close();
            }
        }

        private void CancelButton_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
        }

        private class CategoryChip
        {
            public string Name { get; set; } = "";
        }
    }
}
