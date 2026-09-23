using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

namespace AIDetector.Desktop;

// The web process retains ownership of the instance lock and detector shutdown.
internal sealed class DesktopProcess(string executable, bool background) : IDisposable
{
    private Process process;
    private bool stopping;
    public string ErrorMessage { get; private set; }

    public async Task<int> RunAsync(Action ready)
    {
        var start = new ProcessStartInfo(executable, background ? "--background" : "")
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
            Console.Error.WriteLine(line);
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
        try { process.StandardInput.WriteLine("quit"); process.StandardInput.Flush(); }
        catch (IOException) { /* The child already closed its pipe while exiting. */ }
    }

    public void Dispose() => process?.Dispose();
}
