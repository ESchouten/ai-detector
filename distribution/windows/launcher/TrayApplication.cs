using System;
using System.Drawing;
using System.Reflection;
using System.Windows.Forms;
using Velopack;

namespace AIDetector.Desktop;

internal sealed class TrayApplication : ApplicationContext
{
    private readonly TrayMenu menu;
    private readonly NotifyIcon tray;
    private readonly Icon icon;
    private readonly DesktopProcess web;
    private readonly UpdateMenuItem updates;
    private readonly Timer updateTimer = new() { Interval = 24 * 60 * 60 * 1000 };
    private Action afterShutdown;
    public int ExitCode { get; private set; }

    public TrayApplication(StartupPreference startup, string executable, bool background, VerifiedUpdateManager updater)
    {
        web = new DesktopProcess(executable, background);
        using var artwork = Assembly.GetExecutingAssembly().GetManifestResourceStream("app.ico");
        icon = new Icon(artwork, 32, 32);
        menu = new TrayMenu(startup, command =>
        {
            if (command == "open") web.OpenDashboard();
            else Stop();
        });
        tray = new NotifyIcon { Icon = icon, Text = "AI Detector — Open dashboard", ContextMenuStrip = menu };
        updates = new UpdateMenuItem(updater, apply => { afterShutdown = apply; Stop(); }, () =>
            tray.ShowBalloonTip(5000, "AI Detector update available", "Choose Check for Updates in the AI Detector menu.", ToolTipIcon.Info));
        menu.Items.Insert(3, updates);
        tray.DoubleClick += (_, _) => web.OpenDashboard();
        updateTimer.Tick += async (_, _) => await updates.CheckInBackgroundAsync();
        Application.Idle += Run;
    }

    private async void Run(object sender, EventArgs args)
    {
        Application.Idle -= Run;
        try
        {
            ExitCode = await web.RunAsync(() =>
            {
                tray.Visible = true;
                updateTimer.Start();
                _ = updates.CheckInBackgroundAsync();
            });
            // Start Velopack's exit wait only after the detector has finished draining.
            if (ExitCode == 0) afterShutdown?.Invoke();
            else MessageBox.Show(web.ErrorMessage ?? "AI Detector stopped unexpectedly. Reopen it to resume monitoring.", "AI Detector", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            ExitCode = 1;
            MessageBox.Show("AI Detector could not start or restart. Reopen the application to retry. Your settings and recordings are preserved.", "AI Detector", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        ExitThread();
    }

    private void Stop()
    {
        menu.Enabled = false;
        tray.Text = "AI Detector — Stopping monitoring…";
        updateTimer.Stop();
        updates.CancelDownload();
        web.Stop();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Application.Idle -= Run;
            updateTimer.Dispose();
            tray.Visible = false;
            tray.Dispose();
            menu.Dispose();
            icon.Dispose();
            web.Dispose();
        }
        base.Dispose(disposing);
    }
}
