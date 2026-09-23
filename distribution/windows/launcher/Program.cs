using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using Microsoft.Win32;
using Newtonsoft.Json.Linq;
using Velopack;

namespace AIDetector.Desktop;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        bool firstRun = false;
        // Installer hooks must run before creating windows or starting monitoring.
        VelopackApp.Build().SetAutoApplyOnStartup(false)
            .OnBeforeUninstallFastCallback(_ => SetStartup(false))
            .OnFirstRun(_ => firstRun = true).Run();
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if (Environment.OSVersion.Version < new Version(10, 0, 26100))
        {
            MessageBox.Show("AI Detector requires Windows 11 version 24H2 or newer. Update Windows before opening AI Detector.", "AI Detector", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
        if (firstRun) ConfigureStartup();
        var web = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "ai-detector-web.exe");
        if (args.Contains("--quit"))
        {
            using var quit = Process.Start(new ProcessStartInfo(web, "--quit")
            {
                UseShellExecute = false, CreateNoWindow = true
            });
            quit.WaitForExit();
            return quit.ExitCode;
        }
        using var key = Registry.CurrentUser.CreateSubKey(StartupPreference.RegistryPath);
        var preference = new StartupPreference(key, Application.ExecutablePath);
        var metadata = JObject.Parse(File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "application.json")));
        var feed = (string)metadata["updateFeed"];
        var updateCache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AI Detector", "updates", "releases.win.json");
        var updater = feed == null ? null : new VerifiedUpdateManager(
            new SignedUpdateSource(feed, (string)metadata["updatePublicKey"], updateCache));
        using var desktop = new TrayApplication(preference, web, args.Contains("--background"), updater);
        Application.Run(desktop);
        return desktop.ExitCode;
    }

    private static void SetStartup(bool enabled)
    {
        using var key = Registry.CurrentUser.CreateSubKey(StartupPreference.RegistryPath);
        new StartupPreference(key, Application.ExecutablePath).Enabled = enabled;
    }

    private static void ConfigureStartup()
    {
        using var key = Registry.CurrentUser.CreateSubKey(StartupPreference.RegistryPath);
        var startup = new StartupPreference(key, Application.ExecutablePath);
        // Retarget a previous installation's login entry to the stable 'current' path.
        if (startup.Enabled) { startup.Enabled = true; return; }
        if (MessageBox.Show(
            "Open AI Detector when you sign in? Recommended for daily monitoring. Detection resumes when it is enabled in the dashboard.",
            "AI Detector", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            startup.Enabled = true;
    }
}
