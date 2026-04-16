using System;
using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace SmartDeployDesktop.Converters
{
    /// <summary>
    /// Converts a non-null object to Visible, null to Collapsed.
    /// </summary>
    public class NullToVisibilityConverter : IValueConverter
    {
        public object Convert(object? value, Type targetType, object parameter, CultureInfo culture)
            => value != null ? Visibility.Visible : Visibility.Collapsed;

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotImplementedException();
    }

    /// <summary>
    /// Converts a non-empty string to Visible, empty/null to Collapsed.
    /// </summary>
    public class StringToVisibilityConverter : IValueConverter
    {
        public object Convert(object? value, Type targetType, object parameter, CultureInfo culture)
            => !string.IsNullOrWhiteSpace(value?.ToString()) ? Visibility.Visible : Visibility.Collapsed;

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotImplementedException();
    }

    /// <summary>
    /// Converts deployment status to visibility (shows cancel button only for active deployments).
    /// </summary>
    public class ActiveDeploymentVisibilityConverter : IValueConverter
    {
        public object Convert(object? value, Type targetType, object parameter, CultureInfo culture)
        {
            var status = value?.ToString()?.ToLower();
            return status == "in_progress" || status == "pending" ? Visibility.Visible : Visibility.Collapsed;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotImplementedException();
    }

    /// <summary>
    /// Converts bytes to a human-readable size string.
    /// </summary>
    public class BytesToSizeConverter : IValueConverter
    {
        public object Convert(object? value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is long bytes)
            {
                string[] units = { "B", "KB", "MB", "GB", "TB" };
                double size = bytes;
                int unit = 0;
                while (size >= 1024 && unit < units.Length - 1)
                {
                    size /= 1024;
                    unit++;
                }
                return $"{size:F1} {units[unit]}";
            }
            return "0 B";
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotImplementedException();
    }
}
