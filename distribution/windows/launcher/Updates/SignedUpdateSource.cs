using System;
using System.IO;
using System.Threading.Tasks;
using Velopack;
using Velopack.Logging;
using Velopack.Sources;

namespace AIDetector.Desktop;

// Velopack downloads packages. Only authenticated metadata
// reaches its version selection and checksum verification.
internal sealed class SignedUpdateSource(string url, string publicKey, string cacheFile, UpdateChannelPolicy policy, IFileDownloader downloader = null)
    : SimpleWebSource(url, downloader)
{
    public UpdateChannelPolicy Policy { get; } = policy;

    public override async Task<VelopackAssetFeed> GetReleaseFeed(IVelopackLogger logger, string appId, string channel,
        Guid? stagingId = null, VelopackAsset latestLocalRelease = null)
    {
        var uri = new Uri(BaseUri.AbsoluteUri.TrimEnd('/') + "/releases.win.json");
        var envelope = await Downloader.DownloadString(uri.AbsoluteUri, timeout: Timeout).ConfigureAwait(false);
        var feed = SignedFeed.Verify(envelope, publicKey, Policy);
        Directory.CreateDirectory(Path.GetDirectoryName(cacheFile));
        File.WriteAllText(cacheFile, envelope);
        return feed;
    }

    public VelopackAssetFeed ReadCachedFeed() => SignedFeed.Verify(File.ReadAllText(cacheFile), publicKey, Policy);
}
