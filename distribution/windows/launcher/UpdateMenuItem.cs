using System;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Velopack;

namespace AIDetector.Desktop;

internal sealed class UpdateMenuItem : ToolStripMenuItem
{
    private readonly VerifiedUpdateManager updater;
    private readonly Action<Action> shutdownThen;
    private readonly Action notify;
    private readonly CancellationTokenSource cancellation = new();

    public UpdateMenuItem(VerifiedUpdateManager updater, Action<Action> shutdownThen, Action notify) : base("Check for Updates…")
    {
        this.updater = updater;
        this.shutdownThen = shutdownThen;
        this.notify = notify;
        Enabled = updater?.IsInstalled == true && !updater.IsPortable;
        if (!Enabled) Text = "Updates available in installed releases";
        else RefreshText();
        Click += async (_, _) => await CheckAsync(interactive: true);
    }

    public Task CheckInBackgroundAsync() => CheckAsync(interactive: false);
    public void CancelDownload() => cancellation.Cancel();

    private async Task CheckAsync(bool interactive)
    {
        if (!Enabled) return;
        Enabled = false;
        try
        {
            if (updater.UpdatePendingRestart == null)
            {
                Text = "Checking for updates…";
                var update = await updater.CheckForUpdatesAsync();
                if (cancellation.IsCancellationRequested) return;
                if (update == null)
                {
                    if (interactive) MessageBox.Show("AI Detector is up to date.", "AI Detector");
                    return;
                }
                if (!interactive) { notify(); return; }
                if (!Confirm($"Download AI Detector {update.TargetFullRelease.Version}? Monitoring will keep running during the download.")) return;
                var progress = new Progress<int>(value => Text = $"Downloading update… {value}%");
                await updater.DownloadUpdatesAsync(update, value => ((IProgress<int>)progress).Report(value), cancellation.Token);
            }
            if (interactive && !cancellation.IsCancellationRequested && Confirm("The update is ready. Restart AI Detector now? Monitoring will pause briefly and resume if enabled."))
            {
                var verified = await updater.VerifyPendingUpdateAsync();
                if (!cancellation.IsCancellationRequested)
                    shutdownThen(() => updater.WaitExitThenApplyUpdates(verified, silent: false, restart: true));
            }
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            if (interactive && !cancellation.IsCancellationRequested)
                MessageBox.Show("The update could not be downloaded or verified. Nothing was installed and monitoring is still running. Try Check for Updates again.", "AI Detector", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        finally
        {
            Enabled = !cancellation.IsCancellationRequested;
            RefreshText();
        }
    }

    private void RefreshText() => Text = updater.UpdatePendingRestart == null ? "Check for Updates…" : "Update and restart…";
    private static bool Confirm(string message) => MessageBox.Show(message, "AI Detector", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes;

    protected override void Dispose(bool disposing)
    {
        if (disposing) { cancellation.Cancel(); cancellation.Dispose(); }
        base.Dispose(disposing);
    }
}
