using Microsoft.Win32;

namespace AIDetector.Desktop;

internal sealed class StartupPreference(RegistryKey key, string executable)
{
    internal const string RegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "AI Detector";

    public bool Enabled
    {
        get => key.GetValue(ValueName) is string;
        set
        {
            if (value) key.SetValue(ValueName, $"\"{executable}\"", RegistryValueKind.String);
            else key.DeleteValue(ValueName, throwOnMissingValue: false);
        }
    }
}
