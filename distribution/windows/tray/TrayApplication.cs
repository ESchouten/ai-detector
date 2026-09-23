using System;
using System.Drawing;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace AIDetector.Desktop;

// The dashboard owns detection and shutdown. This process only provides native controls.
internal sealed class TrayApplication : ApplicationContext
{
    private readonly TrayMenu menu;
    private readonly NotifyIcon tray;
    private readonly Icon icon;

    public TrayApplication(StartupPreference startup)
    {
        using var artwork = Assembly.GetExecutingAssembly().GetManifestResourceStream("app.ico");
        icon = new Icon(artwork, 32, 32);
        menu = new TrayMenu(startup, Send);
        tray = new NotifyIcon
        {
            Icon = icon,
            Text = "AI Detector — Open dashboard",
            ContextMenuStrip = menu,
            Visible = true
        };
        tray.DoubleClick += (_, _) => Send("open");
        Application.Idle += WaitForParent;
    }

    private static void Send(string command)
    {
        Console.Out.WriteLine(command);
        Console.Out.Flush();
    }

    private async void WaitForParent(object sender, EventArgs args)
    {
        Application.Idle -= WaitForParent;
        // EOF also arrives when the dashboard crashes; no orphaned tray process remains.
        await Task.Run(() => Console.In.ReadToEnd());
        ExitThread();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Application.Idle -= WaitForParent;
            tray.Visible = false;
            tray.Dispose();
            menu.Dispose();
            icon.Dispose();
        }
        base.Dispose(disposing);
    }
}
