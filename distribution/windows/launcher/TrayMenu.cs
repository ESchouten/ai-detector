using System;
using System.IO;
using System.Security;
using System.Windows.Forms;

namespace AIDetector.Desktop;

internal sealed class TrayMenu : ContextMenuStrip
{
    private readonly StartupPreference startup;
    private readonly ToolStripMenuItem login;

    public TrayMenu(StartupPreference startup, Action<string> send)
    {
        this.startup = startup;
        var open = new ToolStripMenuItem("Open dashboard", MenuIcon.Create("\uE80F"), (_, _) => send("open"));
        Items.Add(open);
        Items.Add(new ToolStripSeparator());
        login = new ToolStripMenuItem("Open at login", MenuIcon.Create("\uE77B"), (_, _) => ToggleStartup());
        Items.Add(login);
        Items.Add(new ToolStripSeparator());
        var quit = new ToolStripMenuItem("Quit AI Detector", MenuIcon.Create("\uE7E8"));
        quit.Click += (_, _) =>
        {
            quit.Text = "Stopping monitoring…";
            quit.Enabled = false;
            send("quit");
        };
        Items.Add(quit);
        Opening += (_, _) => UpdateStartup(() => login.Checked = startup.Enabled);
        ShowImageMargin = true;
        ShowCheckMargin = true;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
            foreach (ToolStripItem item in Items) item.Image?.Dispose();
        base.Dispose(disposing);
    }

    private void ToggleStartup() => UpdateStartup(() =>
    {
        startup.Enabled = !startup.Enabled;
        login.Checked = startup.Enabled;
    });

    private static void UpdateStartup(Action update)
    {
        try { update(); }
        catch (Exception error) when (error is UnauthorizedAccessException or SecurityException or IOException)
        {
            MessageBox.Show(
                "Windows could not change your startup preference. You can manage AI Detector in Windows Settings → Apps → Startup.",
                "AI Detector", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }
}
