using System;
using System.Windows.Forms;
using Microsoft.Win32;

namespace AIDetector.Desktop;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        // Only the dashboard process starts this helper, with its executable path.
        if (args.Length != 1) return;
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using var startupKey = Registry.CurrentUser.CreateSubKey(StartupPreference.RegistryPath);
        using var tray = new TrayApplication(new StartupPreference(startupKey, args[0]));
        Application.Run(tray);
    }
}
