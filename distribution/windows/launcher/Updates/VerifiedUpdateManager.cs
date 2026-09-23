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
    : UpdateManager(source, new UpdateOptions { ExplicitChannel = "win" }, locator: locator)
{
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
        var file = Path.Combine(Locator.PackagesDir, pending.FileName);
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
}
