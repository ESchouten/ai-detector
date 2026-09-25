using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Velopack;
using Velopack.Logging;
using Velopack.Sources;

namespace AIDetector.Desktop;

// Velopack still downloads and reconstructs packages. Only authenticated metadata
// reaches its version selection and checksum verification.
internal sealed class SignedUpdateSource(string url, string publicKey, string cacheFile, IFileDownloader downloader = null)
    : SimpleWebSource(url, downloader)
{
    public static string CachePath(string directory, string feedUrl)
    {
        using var hash = SHA256.Create();
        var name = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(feedUrl.TrimEnd('/')))).Replace("-", "");
        return Path.Combine(directory, name, "releases.win.json");
    }

    public override async Task<VelopackAssetFeed> GetReleaseFeed(IVelopackLogger logger, string appId, string channel,
        Guid? stagingId = null, VelopackAsset latestLocalRelease = null)
    {
        var uri = new Uri(BaseUri.AbsoluteUri.TrimEnd('/') + "/releases.win.json");
        var envelope = await Downloader.DownloadString(uri.AbsoluteUri, timeout: Timeout).ConfigureAwait(false);
        var feed = SignedFeed.Verify(envelope, publicKey);
        Directory.CreateDirectory(Path.GetDirectoryName(cacheFile));
        File.WriteAllText(cacheFile, envelope);
        return feed;
    }

    public VelopackAssetFeed ReadCachedFeed() => SignedFeed.Verify(File.ReadAllText(cacheFile), publicKey);
}
