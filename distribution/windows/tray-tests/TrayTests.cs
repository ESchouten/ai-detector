using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using AIDetector.Desktop;
using Microsoft.Win32;
using NUnit.Framework;

[TestFixture, Apartment(ApartmentState.STA)]
public sealed class TrayTests
{
    private const string Executable = @"C:\Users\A Farmer\AI Detector\AI Detector.exe";
    private string registryPath;
    private RegistryKey key;

    [SetUp]
    public void SetUp()
    {
        // Never register a real login item on the developer's or runner's account.
        registryPath = @"Software\AI Detector Tests\" + Guid.NewGuid();
        key = Registry.CurrentUser.CreateSubKey(registryPath);
    }

    [TearDown]
    public void TearDown()
    {
        key.Dispose();
        Registry.CurrentUser.DeleteSubKeyTree(registryPath);
    }

    [Test]
    public void StartupQuotesTheExecutableAndPreservesOtherEntries()
    {
        key.SetValue("Other application", "untouched");
        var preference = new StartupPreference(key, Executable);
        Assert.That(preference.Enabled, Is.False);
        preference.Enabled = true;
        Assert.That(key.GetValue("AI Detector"), Is.EqualTo($"\"{Executable}\""));
        Assert.That(new StartupPreference(key, Executable).Enabled, Is.True);
        preference.Enabled = false;
        preference.Enabled = false;
        Assert.That(preference.Enabled, Is.False);
        Assert.That(key.GetValue("Other application"), Is.EqualTo("untouched"));
    }

    [Test]
    public void MenuOpensTheDashboardTogglesStartupAndRequestsGracefulQuit()
    {
        var preference = new StartupPreference(key, Executable);
        var commands = new List<string>();
        using var menu = new TrayMenu(preference, commands.Add);
        var items = menu.Items.OfType<ToolStripMenuItem>().ToArray();
        items[0].PerformClick();
        items[1].PerformClick();
        Assert.That(preference.Enabled, Is.True);
        Assert.That(items[1].Checked, Is.True);
        items[1].PerformClick();
        Assert.That(preference.Enabled, Is.False);
        Assert.That(items[1].Checked, Is.False);
        items[2].PerformClick();
        Assert.That(commands, Is.EqualTo(new[] { "open", "quit" }));
        Assert.That(items[2].Enabled, Is.False);
        Assert.That(items[2].Text, Is.EqualTo("Stopping monitoring…"));
    }

    [Test]
    public void HelperExitsWhenTheDashboardClosesItsPipe()
    {
        using var child = Process.Start(new ProcessStartInfo
        {
            FileName = Path.Combine(TestContext.CurrentContext.TestDirectory, "AI Detector Tray.exe"),
            Arguments = $"\"{Executable}\"",
            UseShellExecute = false,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        });
        try
        {
            Assert.That(child.WaitForInputIdle(10000), Is.True, "The native message loop must start");
            Assert.That(child.HasExited, Is.False);
            child.StandardInput.Close();
            Assert.That(child.WaitForExit(10000), Is.True, "EOF must remove the tray and exit");
            Assert.That(child.ExitCode, Is.Zero, child.StandardError.ReadToEnd());
        }
        finally
        {
            if (!child.HasExited) { child.Kill(); child.WaitForExit(); }
        }
    }
}
