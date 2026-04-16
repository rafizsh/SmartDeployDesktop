using System;
using System.Net.Http;
using System.Threading.Tasks;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using SmartDeployDesktop.Services;

namespace SmartDeployDesktop.ViewModels
{
    /// <summary>
    /// Base ViewModel with common infrastructure: API client, loading state, error handling.
    /// </summary>
    public abstract partial class BaseViewModel : ObservableObject
    {
        protected readonly ApiClient Api;

        [ObservableProperty] private bool _isLoading;
        [ObservableProperty] private string _statusMessage = "";
        [ObservableProperty] private bool _hasError;
        [ObservableProperty] private string _errorMessage = "";

        protected BaseViewModel(ApiClient api)
        {
            Api = api;
        }

        /// <summary>
        /// Wraps an async operation with loading/error state management.
        /// </summary>
        protected async Task RunAsync(Func<Task> action, string? loadingMessage = null)
        {
            IsLoading = true;
            HasError = false;
            ErrorMessage = "";
            if (loadingMessage != null) StatusMessage = loadingMessage;

            try
            {
                await action();
            }
            catch (HttpRequestException ex)
            {
                HasError = true;
                ErrorMessage = $"Server communication error: {ex.Message}";
                StatusMessage = "Error";
            }
            catch (Exception ex)
            {
                HasError = true;
                ErrorMessage = ex.Message;
                StatusMessage = "Error";
            }
            finally
            {
                IsLoading = false;
            }
        }

        /// <summary>
        /// Show a simple toast/status message that auto-clears.
        /// </summary>
        protected async void ShowStatus(string message, int durationMs = 3000)
        {
            StatusMessage = message;
            await Task.Delay(durationMs);
            if (StatusMessage == message) StatusMessage = "";
        }
    }
}
