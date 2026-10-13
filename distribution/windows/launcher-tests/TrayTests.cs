using System;
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
    public void MonitoringAsksWindowsNotToSleepAndPausingLetsItSleepAgain()
    {
        // Each call answers with what this thread had asked for until then.
        uint Asked() => TrayApplication.SetThreadExecutionState(TrayApplication.Continuous) & TrayApplication.SystemRequired;
        TrayApplication.StayAwake(true);
        Assert.That(Asked(), Is.EqualTo(TrayApplication.SystemRequired));
        TrayApplication.StayAwake(true);
        TrayApplication.StayAwake(false);
        Assert.That(Asked(), Is.EqualTo(0u));
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
        int opened = 0, stopped = 0;
        using var menu = new TrayMenu(preference, () => opened++, () => stopped++);
        var items = menu.Items.OfType<ToolStripMenuItem>().ToArray();
        items[0].PerformClick();
        Assert.That(opened, Is.EqualTo(1));
        Assert.That(stopped, Is.Zero);
        items[1].PerformClick();
        Assert.That(preference.Enabled, Is.True);
        Assert.That(items[1].Checked, Is.True);
        items[1].PerformClick();
        Assert.That(preference.Enabled, Is.False);
        Assert.That(items[1].Checked, Is.False);
        items[2].PerformClick();
        Assert.That(opened, Is.EqualTo(1));
        Assert.That(stopped, Is.EqualTo(1));
        Assert.That(items[2].Enabled, Is.False);
        Assert.That(items[2].Text, Is.EqualTo("Stopping monitoring…"));
    }
}
