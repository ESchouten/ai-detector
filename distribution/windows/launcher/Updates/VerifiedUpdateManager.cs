using System;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Velopack;
using Velopack.Exceptions;
using Velopack.Locators;
using Velopack.Logging;

namespace AIDetector.Desktop;

internal class VerifiedUpdateManager(SignedUpdateSource source, IVelopackLocator locator = null)
    : UpdateManager(source, new UpdateOptions
    {
        // The signed policy chooses an eligible build before Velopack compares versions.
        ExplicitChannel = "selected",
        AllowVersionDowngrade = true,
        // Delta reconstruction re-compresses the ZIP, so its bytes need not match
        // the signed full-package hash. Download that exact archive for verification.
        MaximumDeltasBeforeFallback = 0,
    }, locator: locator)
{
    public UpdateChannelPolicy ChannelPolicy => source.Policy;

    public void LogFailure(string operation, Exception error) => Log.Error(error, operation);

    public override VelopackAsset UpdatePendingRestart
    {
        get
        {
            try
            {
                // Velopack's default property only recognizes upgrades. A channel
                // switch can also have downloaded an older (or equal) version.
                var target = source.ReadCachedFeed().Assets.Where(asset => asset.Type == VelopackAssetType.Full)
                    .OrderByDescending(asset => asset.Version).FirstOrDefault();
                // Apply expects a local filename, whereas the signed feed contains
                // immutable download URLs. Preserve the authenticated asset fields.
                return target != null && File.Exists(PackagePath(target))
                    ? target with { FileName = Path.GetFileName(target.FileName) } : null;
            }
            catch (Exception error) when (error is IOException or CryptographicException or JsonException or FormatException or ArgumentException)
            {
                // A missing or invalid cache needs a fresh authenticated update check.
                return null;
            }
        }
    }
    public override async Task DownloadUpdatesAsync(UpdateInfo update, Action<int> progress = null, CancellationToken cancelToken = default)
    {
        cancelToken.ThrowIfCancellationRequested();
        var file = PackagePath(update.TargetFullRelease);
        if (File.Exists(file))
        {
            try
            {
                // Velopack trusts complete cached files without checking them again.
                await VerifyPackageChecksumAsync(update.TargetFullRelease).ConfigureAwait(false);
                cancelToken.ThrowIfCancellationRequested();
                progress?.Invoke(100);
                return;
            }
            catch (ChecksumFailedException error)
            {
                Log.Warn(error, "Cached update failed verification; downloading a fresh full package.");
                File.Delete(file);
            }
        }
        try
        {
            cancelToken.ThrowIfCancellationRequested();
            await base.DownloadUpdatesAsync(update, progress, cancelToken).ConfigureAwait(false);
            await VerifyPackageChecksumAsync(update.TargetFullRelease).ConfigureAwait(false);
        }
        catch (ChecksumFailedException error)
        {
            File.Delete(error.FilePath);
            throw;
        }
    }

    public async Task<VelopackAsset> VerifyPendingUpdateAsync()
    {
        var pending = UpdatePendingRestart;
        if (pending == null) throw new InvalidOperationException("No downloaded update is ready.");
        var file = PackagePath(pending);
        try
        {
            var signed = source.ReadCachedFeed().Assets.SingleOrDefault(asset =>
                asset.Type == VelopackAssetType.Full && asset.PackageId == AppId && asset.Version == pending.Version);
            if (signed == null)
                throw new CryptographicException("The downloaded update has no signed release metadata.");
            await VerifyPackageChecksumAsync(signed, file).ConfigureAwait(false);
            return pending;
        }
        catch (Exception error) when (error is ChecksumFailedException or CryptographicException or IOException or JsonException or FormatException or ArgumentException)
        {
            // Clear the pending state so the next menu action can download again.
            File.Delete(file);
            throw;
        }
    }

    private string PackagePath(VelopackAsset asset) => Path.Combine(Locator.PackagesDir, Path.GetFileName(asset.FileName));
}
