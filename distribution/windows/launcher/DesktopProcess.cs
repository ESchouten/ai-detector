using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace AIDetector.Desktop;

// The web process retains ownership of the instance lock and detector shutdown.
internal sealed class DesktopProcess(string executable) : IDisposable
{
    private Process process;
    private bool stopping;
    private readonly CancellationTokenSource restart = new();
    public string ErrorMessage { get; private set; }

    // What the web process said on its way out is the only trace of a crash, and a windowed
    // launcher has no console to show it. The diagnostics download picks this file up.
    private static readonly string LogPath = Path.Combine(
        Environment.GetEnvironmentVariable("AIDETECTOR_DATA_DIR")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AI Detector"),
        "logs", "launcher.log");

    private static void Log(string line)
    {
        Console.Error.WriteLine(line);
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(LogPath));
            var file = new FileInfo(LogPath);
            if (file.Exists && file.Length > 1_000_000) file.Delete();
            File.AppendAllText(LogPath, $"{DateTime.UtcNow:O} {line}{Environment.NewLine}");
        }
        catch (IOException) { /* A log that cannot be written must not stop the application. */ }
        catch (UnauthorizedAccessException) { }
    }

    public async Task<int> RunAsync(Action ready)
    {
        var delay = 2000;
        var first = true;
        while (!stopping)
        {
            var startedAt = DateTime.UtcNow;
            try
            {
                var code = await RunOnceAsync(ready, !first);
                if (stopping) return code;
                Log($"The web process ended by itself with exit code {code} (0x{code:X8}).");
            }
            catch (Exception error)
            {
                Log(error.ToString());
                ErrorMessage = error.Message;
                if (stopping) return 1;
            }
            finally
            {
                process?.Dispose();
                process = null;
            }
            first = false;
            if (DateTime.UtcNow - startedAt >= TimeSpan.FromMinutes(10)) delay = 2000;
            Log($"Restarting the web process in {delay / 1000} seconds.");
            try { await Task.Delay(delay, restart.Token); }
            catch (OperationCanceledException) { return 0; }
            delay = Math.Min(delay * 2, 30000);
        }
        return 0;
    }

    private async Task<int> RunOnceAsync(Action ready, bool inBackground)
    {
        ErrorMessage = null;
        var start = new ProcessStartInfo(executable, inBackground ? "--background" : "")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        start.EnvironmentVariables["AIDETECTOR_DESKTOP_HOST"] = "1";
        process = Process.Start(start);
        var errors = CopyErrorsAsync(process.StandardError);
        string line;
        while ((line = await process.StandardOutput.ReadLineAsync()) != null)
        {
            if (line == "AI_DETECTOR_READY") ready();
            else Console.Out.WriteLine(line);
        }
        await Task.Run(() => process.WaitForExit());
        await errors;
        return process.ExitCode;
    }

    private async Task CopyErrorsAsync(StreamReader reader)
    {
        const string prefix = "AI_DETECTOR_ERROR ";
        string line;
        while ((line = await reader.ReadLineAsync()) != null)
        {
            if (line.StartsWith(prefix, StringComparison.Ordinal)) ErrorMessage = line.Substring(prefix.Length);
            if (line == "AI_DETECTOR_STOPPING") stopping = true;
            Log(line);
        }
    }

    public void OpenDashboard()
    {
        // A second invocation authenticates the running instance before opening it.
        using var opener = Process.Start(new ProcessStartInfo(executable)
        {
            UseShellExecute = false, CreateNoWindow = true
        });
    }

    public void Stop()
    {
        if (stopping) return;
        stopping = true;
        restart.Cancel();
        if (process == null || process.HasExited) return;
        try { process.StandardInput.WriteLine("quit"); process.StandardInput.Flush(); }
        catch (IOException) { /* The child already closed its pipe while exiting. */ }
    }

    public void Dispose()
    {
        restart.Dispose();
        process?.Dispose();
    }
}
