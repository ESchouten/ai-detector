using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using AIDetector.Desktop;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using Org.BouncyCastle.Crypto.Parameters;
using Velopack;
using Velopack.Exceptions;
using Velopack.Locators;
using Velopack.Logging;
using Velopack.Sources;

[TestFixture]
public sealed class SignatureTests
{
    private string root;
    private string publicKey;
    private string envelope;
    private string cache;
    private byte[] package;
    private FakeDownloader downloader;
    private SignedUpdateSource source;
    private VelopackAsset release;

    [SetUp]
    public void SetUp()
    {
        root = Path.Combine(Path.GetTempPath(), "ai-detector-authenticity-" + Guid.NewGuid());
        Directory.CreateDirectory(root);
        cache = Path.Combine(root, "verified-feed.json");
        var fixture = JObject.Parse(File.ReadAllText(Path.Combine(TestContext.CurrentContext.TestDirectory, "signed-update.json")));
        publicKey = (string)fixture["publicKey"];
        envelope = fixture["envelope"].ToString();
        package = Convert.FromBase64String((string)fixture["package"]);
        downloader = new FakeDownloader(envelope, package);
        source = new SignedUpdateSource("https://example.invalid/updates", publicKey, cache, downloader);
        release = SignedFeed.Verify(envelope, publicKey).Assets.Single(asset => asset.Type == VelopackAssetType.Full);
    }

    [TearDown]
    public void TearDown() => Directory.Delete(root, recursive: true);

    [Test]
    public void PythonSignatureAuthenticatesBothFullAndDeltaHashes()
    {
        var feed = SignedFeed.Verify(envelope, publicKey);
        Assert.That(feed.Assets.Select(asset => asset.Type), Is.EquivalentTo(new[] { VelopackAssetType.Full, VelopackAssetType.Delta }));
        Assert.That(release.SHA256, Is.EqualTo(Convert.ToHexString(SHA256.HashData(package))));
    }

    [Test]
    public void TamperedMetadataIsRejected()
    {
        var changed = JObject.Parse(envelope);
        var bytes = Convert.FromBase64String((string)changed["payload"]);
        bytes[bytes.Length - 2] ^= 1;
        changed["payload"] = Convert.ToBase64String(bytes);
        Assert.Throws<CryptographicException>(() => SignedFeed.Verify(changed.ToString(), publicKey));
    }

    [Test]
    public void WrongKeyAndUnsignedFeedAreRejected()
    {
        var otherKey = new Ed25519PrivateKeyParameters(new byte[32], 0).GeneratePublicKey().GetEncoded();
        Assert.Throws<CryptographicException>(() => SignedFeed.Verify(envelope, Convert.ToBase64String(otherKey)));
        Assert.That(() => SignedFeed.Verify("{\"Assets\":[]}", publicKey), Throws.Exception);
    }

    [Test]
    public async Task RejectedFeedCannotReplaceCachedAttestationOrReachPackageDownloads()
    {
        await source.GetReleaseFeed(new NullVelopackLogger(), "AIDetector", "win");
        downloader.Envelope = "{\"Assets\":[]}";
        var manager = new VerifiedUpdateManager(source, Locator());
        Assert.That(async () => await manager.CheckForUpdatesAsync(), Throws.Exception);
        Assert.That(File.ReadAllText(cache), Is.EqualTo(envelope));
        Assert.That(downloader.Downloads, Is.Zero);
    }

    [Test]
    public async Task ExistingCachedPackageStillRequiresTheSignedHash()
    {
        var locator = Locator();
        var manager = new VerifiedUpdateManager(source, locator);
        var update = await manager.CheckForUpdatesAsync();
        File.WriteAllBytes(Path.Combine(root, Pending().FileName), new byte[package.Length]);
        Assert.ThrowsAsync<ChecksumFailedException>(() => manager.DownloadUpdatesAsync(update));
        Assert.That(downloader.Downloads, Is.Zero);
        Assert.That(File.Exists(Path.Combine(root, Pending().FileName)), Is.False);
        await manager.DownloadUpdatesAsync(update);
        Assert.That(downloader.Downloads, Is.EqualTo(1));
        Assert.That(File.ReadAllBytes(Path.Combine(root, Pending().FileName)), Is.EqualTo(package));
    }

    [Test]
    public async Task TamperedDownloadIsRejectedByVelopacksChecksumVerification()
    {
        downloader.Package = new byte[package.Length];
        var manager = new VerifiedUpdateManager(source, Locator());
        var update = await manager.CheckForUpdatesAsync();
        Assert.ThrowsAsync<ChecksumFailedException>(() => manager.DownloadUpdatesAsync(update));
        Assert.That(downloader.Downloads, Is.EqualTo(1));
        Assert.That(File.Exists(Path.Combine(root, Pending().FileName)), Is.False);
    }

    [Test]
    public async Task DeferredRestartVerifiesOfflineAgainstTheSavedSignature()
    {
        await source.GetReleaseFeed(new NullVelopackLogger(), "AIDetector", "win");
        var pending = Pending();
        var locator = Locator(pending);
        File.WriteAllBytes(Path.Combine(root, pending.FileName), package);
        var restartedSource = new SignedUpdateSource("https://example.invalid/updates", publicKey, cache, new FakeDownloader(null, null));
        var manager = new VerifiedUpdateManager(restartedSource, locator);
        Assert.That(await manager.VerifyPendingUpdateAsync(), Is.SameAs(pending));
        File.WriteAllBytes(Path.Combine(root, pending.FileName), new byte[package.Length]);
        Assert.ThrowsAsync<ChecksumFailedException>(() => manager.VerifyPendingUpdateAsync());
        Assert.That(File.Exists(Path.Combine(root, pending.FileName)), Is.False);
    }

    [Test]
    public async Task MissingDeferredMetadataAllowsAFreshDownload()
    {
        var pending = Pending();
        File.WriteAllBytes(Path.Combine(root, pending.FileName), package);
        var deferred = new VerifiedUpdateManager(source, Locator(pending));
        Assert.ThrowsAsync<FileNotFoundException>(() => deferred.VerifyPendingUpdateAsync());
        Assert.That(File.Exists(Path.Combine(root, pending.FileName)), Is.False);
        var retry = new VerifiedUpdateManager(source, Locator());
        await retry.DownloadUpdatesAsync(await retry.CheckForUpdatesAsync());
        Assert.That(downloader.Downloads, Is.EqualTo(1));
    }

    [TestCase("{\"Assets\":[]}")]
    [TestCase("{")]
    [TestCase("{\"payload\":\"!\",\"signature\":\"\"}")]
    public async Task UnreadableCachedMetadataClearsThePendingDownload(string metadata)
    {
        await source.GetReleaseFeed(new NullVelopackLogger(), "AIDetector", "win");
        var pending = Pending();
        File.WriteAllBytes(Path.Combine(root, pending.FileName), package);
        var manager = new VerifiedUpdateManager(source, Locator(pending));
        File.WriteAllText(cache, metadata);
        Assert.That(async () => await manager.VerifyPendingUpdateAsync(), Throws.Exception);
        Assert.That(File.Exists(Path.Combine(root, pending.FileName)), Is.False);
    }

    [Test]
    public async Task SignedOldVersionCannotDowngradeTheInstalledApplication()
    {
        var manager = new VerifiedUpdateManager(source, Locator(version: "2.0.0"));
        Assert.That(await manager.CheckForUpdatesAsync(), Is.Null);
    }

    [Test]
    public async Task SwitchingChannelsCannotReuseThePreviousChannelsCachedFeed()
    {
        const string stableUrl = "https://example.invalid/app-updates";
        const string previewUrl = "https://example.invalid/app-preview-updates";
        var stableCache = SignedUpdateSource.CachePath(root, stableUrl);
        var previewCache = SignedUpdateSource.CachePath(root, previewUrl);
        Assert.That(stableCache, Is.EqualTo(SignedUpdateSource.CachePath(root, stableUrl + "/")));
        Assert.That(previewCache, Is.Not.EqualTo(stableCache));
        var stable = new SignedUpdateSource(stableUrl, publicKey, stableCache, downloader);
        await stable.GetReleaseFeed(new NullVelopackLogger(), "AIDetector", "win");
        var preview = new SignedUpdateSource(previewUrl, publicKey, previewCache, downloader);
        Assert.Throws<DirectoryNotFoundException>(() => preview.ReadCachedFeed());
        await preview.GetReleaseFeed(new NullVelopackLogger(), "AIDetector", "win");
        Assert.That(downloader.LastFeedUrl, Is.EqualTo(previewUrl + "/releases.win.json"));
        Assert.That(File.ReadAllText(stableCache), Is.EqualTo(envelope));
        Assert.That(preview.ReadCachedFeed().Assets.Length, Is.EqualTo(2));
    }

    private VelopackAsset Pending() => new()
    {
        PackageId = "AIDetector", Version = release.Version, Type = VelopackAssetType.Full,
        FileName = Path.GetFileName(new Uri(release.FileName).LocalPath), Size = package.Length
    };

    private TestVelopackLocator Locator(VelopackAsset pending = null, string version = "1.0.0") =>
        new("AIDetector", version, root, root, root, Path.Combine(root, "Update.exe"), "win", localPackage: pending);

    private sealed class FakeDownloader(string envelope, byte[] package) : IFileDownloader
    {
        public string Envelope { get; set; } = envelope;
        public byte[] Package { get; set; } = package;
        public int Downloads { get; private set; }
        public string LastFeedUrl { get; private set; }
        public Task<string> DownloadString(string url, IDictionary<string, string> headers = null, double timeout = 30)
        {
            LastFeedUrl = url;
            return Task.FromResult(Envelope ?? throw new IOException("offline"));
        }
        public Task<byte[]> DownloadBytes(string url, IDictionary<string, string> headers = null, double timeout = 30) =>
            throw new NotSupportedException();
        public Task DownloadFile(string url, string path, Action<int> progress,
            IDictionary<string, string> headers = null, double timeout = 30, CancellationToken cancelToken = default)
        {
            Downloads++;
            File.WriteAllBytes(path, Package);
            progress(100);
            return Task.CompletedTask;
        }
    }
}
