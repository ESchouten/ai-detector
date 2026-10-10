using System;
using System.CodeDom.Compiler;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AIDetector.Desktop;
using Microsoft.CSharp;
using NUnit.Framework;

[TestFixture]
public sealed class DesktopProcessTests
{
    [TestCase(0)]
    [TestCase(17)]
    [TestCase(-1)]
    public async Task UnexpectedExitRestartsButQuitDoesNot(int code)
    {
        var folder = Path.Combine(Path.GetTempPath(), "ai-restart-" + Guid.NewGuid());
        Directory.CreateDirectory(folder);
        try
        {
            var executable = CompileFixture(folder, code, false);
            using var web = new DesktopProcess(executable);
            var first = new TaskCompletionSource<bool>();
            var second = new TaskCompletionSource<bool>();
            var starts = 0;
            var running = web.RunAsync(() => { if (++starts == 1) first.SetResult(true); else second.TrySetResult(true); });
            try
            {
                await Ready(first.Task, running);
                if (code == -1)
                {
                    using var child = Process.GetProcessById(int.Parse(File.ReadAllText(Path.Combine(folder, "pid"))));
                    child.Kill();
                }
                else File.WriteAllText(Path.Combine(folder, "exit"), "now");
                await Ready(second.Task, running);
                web.Stop();
                await Ready(running, Task.Delay(15000));
                Assert.That(await running, Is.EqualTo(0));
                Assert.That(starts, Is.EqualTo(2));
            }
            finally { web.Stop(); await running; }
        }
        finally { Directory.Delete(folder, recursive: true); }
    }

    [TestCase(0)]
    [TestCase(17)]
    public async Task ExplicitShutdownMarkerPreservesTheResultWithoutRestarting(int code)
    {
        var folder = Path.Combine(Path.GetTempPath(), "ai-shutdown-" + Guid.NewGuid());
        Directory.CreateDirectory(folder);
        try
        {
            var executable = CompileFixture(folder, code, true);
            using var web = new DesktopProcess(executable);
            var running = web.RunAsync(() => File.WriteAllText(Path.Combine(folder, "exit"), "now"));
            try
            {
                await Ready(running, Task.Delay(15000));
                Assert.That(await running, Is.EqualTo(code));
                Assert.That(File.ReadAllText(Path.Combine(folder, "starts")), Is.EqualTo("started\n"));
            }
            finally { web.Stop(); await running; }
        }
        finally { Directory.Delete(folder, recursive: true); }
    }

    private static async Task Ready(Task expected, Task exited)
    {
        Assert.That(await Task.WhenAny(expected, exited, Task.Delay(15000)), Is.SameAs(expected));
    }

    private static string CompileFixture(string folder, int code, bool intentional)
    {
        var executable = Path.Combine(folder, "web.exe");
        using var compiler = new CSharpCodeProvider();
        var result = compiler.CompileAssemblyFromSource(new CompilerParameters
        {
            GenerateExecutable = true,
            OutputAssembly = executable,
            ReferencedAssemblies = { "System.dll" }
        }, @"using System;
            using System.Diagnostics;
            using System.IO;
            using System.Threading;
            class Web {
                static void Main() {
                    var folder = AppDomain.CurrentDomain.BaseDirectory;
                    var first = !File.Exists(Path.Combine(folder, ""starts""));
                    File.AppendAllText(Path.Combine(folder, ""starts""), ""started\n"");
                    File.WriteAllText(Path.Combine(folder, ""pid""), Process.GetCurrentProcess().Id.ToString());
                    Console.WriteLine(""AI_DETECTOR_READY"");
                    Console.Out.Flush();
                    if (first) {
                        new Thread(() => {
                            while (!File.Exists(Path.Combine(folder, ""exit""))) Thread.Sleep(10);
                            if (INTENTIONAL) Console.Error.WriteLine(""AI_DETECTOR_STOPPING"");
                            Environment.Exit(EXIT_CODE);
                        }) { IsBackground = true }.Start();
                    }
                    if (Console.ReadLine() != ""quit"") Environment.Exit(2);
                }
            }".Replace("EXIT_CODE", code.ToString()).Replace("INTENTIONAL", intentional ? "true" : "false"));
        Assert.That(result.Errors.HasErrors, Is.False,
            string.Join(Environment.NewLine, result.Errors.Cast<CompilerError>()));
        return executable;
    }
}
