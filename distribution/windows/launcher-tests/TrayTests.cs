using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.CodeDom.Compiler;
using Microsoft.CSharp;
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

    [TestCase(0)]
    [TestCase(17)]
    public async Task NativeOwnerWaitsForMonitoringToDrainAndRetainsItsFailure(int exitCode)
    {
        var folder = Path.Combine(Path.GetTempPath(), "ai-detector-shell-" + Guid.NewGuid());
        Directory.CreateDirectory(folder);
        try
        {
            var executable = Path.Combine(folder, "web.exe");
            using var compiler = new CSharpCodeProvider();
            var result = compiler.CompileAssemblyFromSource(new CompilerParameters
            {
                GenerateExecutable = true, OutputAssembly = executable
            }, @"using System;
                using System.IO;
                using System.Threading;
                class Web {
                    static void Main() {
                        Console.WriteLine(""AI_DETECTOR_READY"");
                        Console.Out.Flush();
                        if (Console.ReadLine() != ""quit"") Environment.Exit(2);
                        Thread.Sleep(200);
                        File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ""drained""), ""yes"");
                        if (EXIT_CODE != 0) Console.Error.WriteLine(""AI_DETECTOR_ERROR The test detector could not finish."");
                        Environment.Exit(EXIT_CODE);
                    }
                }".Replace("EXIT_CODE", exitCode.ToString()));
            Assert.That(result.Errors.HasErrors, Is.False);
            using var web = new DesktopProcess(executable, background: true);
            var ready = new TaskCompletionSource<bool>();
            var running = web.RunAsync(() => ready.SetResult(true));
            Assert.That(await Task.WhenAny(ready.Task, running, Task.Delay(10000)), Is.SameAs(ready.Task), "Native child did not become ready");
            Assert.That(running.IsCompleted, Is.False);
            web.Stop();
            Assert.That(File.Exists(Path.Combine(folder, "drained")), Is.False);
            Assert.That(await Task.WhenAny(running, Task.Delay(10000)), Is.SameAs(running), "Native child did not exit");
            Assert.That(await running, Is.EqualTo(exitCode));
            Assert.That(web.ErrorMessage, Is.EqualTo(exitCode == 0 ? null : "The test detector could not finish."));
            Assert.That(File.ReadAllText(Path.Combine(folder, "drained")), Is.EqualTo("yes"));
        }
        finally { Directory.Delete(folder, recursive: true); }
    }
}
