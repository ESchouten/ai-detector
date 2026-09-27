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

namespace AIDetector.Desktop;

internal class VerifiedUpdateManager(SignedUpdateSource source, IVelopackLocator locator = null)
    : UpdateManager(source, new UpdateOptions
    {
        // The signed policy chooses an eligible build before Velopack compares versions.
        ExplicitChannel = source.Policy == null ? "win" : "selected",
        AllowVersionDowngrade = source.Policy != null,
    }, locator: locator)
{
    public UpdateChannelPolicy ChannelPolicy => source.Policy;

    public override VelopackAsset UpdatePendingRestart
    {
        get
        {
            if (source.Policy == null) return base.UpdatePendingRestart;
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
        try
        {
            await base.DownloadUpdatesAsync(update, progress, cancelToken).ConfigureAwait(false);
            // Velopack skips its checksum check when a complete package is already cached.
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
