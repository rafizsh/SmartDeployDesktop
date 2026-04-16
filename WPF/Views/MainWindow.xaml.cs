using System.Windows;
using System.Windows.Controls;

namespace SmartDeployDesktop.Views
{
    public partial class MainWindow : Window
    {
        public MainWindow()
        {
            InitializeComponent();
        }

        private void PasswordField_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (sender is TextBox tb && tb.Tag is string maskName)
            {
                var mask = this.FindName(maskName) as TextBox;
                if (mask != null)
                {
                    mask.Text = new string('●', tb.Text?.Length ?? 0);
                }
            }
        }
    }
}
