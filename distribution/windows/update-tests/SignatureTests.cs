using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using AIDetector.Desktop;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Crypto.Signers;
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
    private UpdateChannelPolicy stablePolicy;
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
        stablePolicy = new UpdateChannelPolicy("1.0.0", "stable", false);
        source = new SignedUpdateSource("https://example.invalid/updates", publicKey, cache, stablePolicy, downloader);
        release = SignedFeed.Verify(envelope, publicKey, stablePolicy).Assets.Single(asset => asset.Type == VelopackAssetType.Full);
    }

    [TearDown]
    public void TearDown() => Directory.Delete(root, recursive: true);

    [Test]
    public void PythonSignatureAuthenticatesBothFullAndDeltaHashes()
    {
        var feed = SignedFeed.Verify(envelope, publicKey, stablePolicy);
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
        Assert.Throws<CryptographicException>(() => SignedFeed.Verify(changed.ToString(), publicKey, stablePolicy));
    }

    [Test]
    public void WrongKeyAndUnsignedFeedAreRejected()
    {
        var otherKey = new Ed25519PrivateKeyParameters(new byte[32], 0).GeneratePublicKey().GetEncoded();
        Assert.Throws<CryptographicException>(() => SignedFeed.Verify(envelope, Convert.ToBase64String(otherKey), stablePolicy));
        Assert.That(() => SignedFeed.Verify("{\"Assets\":[]}", publicKey, stablePolicy), Throws.Exception);
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
    public async Task CorruptCachedPackageIsReplacedInTheSameDownloadAttempt()
    {
        var locator = Locator();
        var manager = new VerifiedUpdateManager(source, locator);
        var update = await manager.CheckForUpdatesAsync();
        File.WriteAllBytes(Path.Combine(root, Pending().FileName), new byte[package.Length]);
        await manager.DownloadUpdatesAsync(update);
        Assert.That(downloader.Downloads, Is.EqualTo(1));
        Assert.That(File.ReadAllBytes(Path.Combine(root, Pending().FileName)), Is.EqualTo(package));
    }

    [Test]
    public async Task ValidCachedPackageIsVerifiedWithoutDownloadingAgain()
    {
        var manager = new VerifiedUpdateManager(source, Locator());
        var update = await manager.CheckForUpdatesAsync();
        File.WriteAllBytes(Path.Combine(root, Pending().FileName), package);
        await manager.DownloadUpdatesAsync(update);
        Assert.That(downloader.Downloads, Is.Zero);
    }

    [Test]
    public async Task SignedFullArchiveIsDownloadedEvenWhenADeltaIsAvailable()
    {
        var previous = Pending() with { Version = SemanticVersion.Parse("1.0.0"), FileName = "AIDetector-1.0.0-full.nupkg" };
        File.WriteAllBytes(Path.Combine(root, previous.FileName), package);
        var manager = new DeltaRejectingManager(source, Locator(previous));
        var update = await manager.CheckForUpdatesAsync();
        Assert.That(update.DeltasToTarget, Is.Not.Empty, "Fixture must offer a delta from the installed package");
        Assert.That(update.DeltasToTarget.Sum(asset => asset.Size), Is.LessThanOrEqualTo(release.Size));
        await manager.DownloadUpdatesAsync(update);
        Assert.That(downloader.Downloads, Is.EqualTo(1));
        Assert.That(downloader.LastPackageUrl, Is.EqualTo(release.FileName));
        Assert.That(File.ReadAllBytes(Path.Combine(root, Pending().FileName)), Is.EqualTo(package));
    }

    [Test]
    public async Task CancellationDoesNotStartACacheRepairOrDownload()
    {
        var manager = new VerifiedUpdateManager(source, Locator());
        var update = await manager.CheckForUpdatesAsync();
        var file = Path.Combine(root, Pending().FileName);
        File.WriteAllBytes(file, new byte[package.Length]);
        Assert.ThrowsAsync<OperationCanceledException>(() => manager.DownloadUpdatesAsync(update,
            cancelToken: new CancellationToken(canceled: true)));
        Assert.That(downloader.Downloads, Is.Zero);
        Assert.That(File.Exists(file), Is.True);
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
        var restartedSource = new SignedUpdateSource("https://example.invalid/updates", publicKey, cache, stablePolicy, new FakeDownloader(null, null));
        var manager = new VerifiedUpdateManager(restartedSource, locator);
        Assert.That(await manager.VerifyPendingUpdateAsync(), Is.EqualTo(release with { FileName = pending.FileName }));
        File.WriteAllBytes(Path.Combine(root, pending.FileName), new byte[package.Length]);
        Assert.ThrowsAsync<ChecksumFailedException>(() => manager.VerifyPendingUpdateAsync());
        Assert.That(File.Exists(Path.Combine(root, pending.FileName)), Is.False);
    }

    [Test]
    public async Task MissingDeferredMetadataKeepsThePackageForTheNextCheckToVerify()
    {
        var pending = Pending();
        File.WriteAllBytes(Path.Combine(root, pending.FileName), package);
        var manager = new VerifiedUpdateManager(source, Locator(pending));
        Assert.That(manager.UpdatePendingRestart, Is.Null);
        Assert.ThrowsAsync<InvalidOperationException>(() => manager.VerifyPendingUpdateAsync());
        await manager.DownloadUpdatesAsync(await manager.CheckForUpdatesAsync());
        Assert.That(downloader.Downloads, Is.Zero);
        Assert.That(manager.UpdatePendingRestart, Is.Not.Null);
    }

    [TestCase("{\"Assets\":[]}")]
    [TestCase("{")]
    [TestCase("{\"payload\":\"!\",\"signature\":\"\"}")]
    public void UnreadableCachedMetadataLeavesNoPendingUpdateAndKeepsThePackage(string metadata)
    {
        var pending = Pending();
        File.WriteAllBytes(Path.Combine(root, pending.FileName), package);
        File.WriteAllText(cache, metadata);
        var manager = new VerifiedUpdateManager(source, Locator(pending));
        Assert.That(manager.UpdatePendingRestart, Is.Null);
        Assert.ThrowsAsync<InvalidOperationException>(() => manager.VerifyPendingUpdateAsync());
        Assert.That(File.Exists(Path.Combine(root, pending.FileName)), Is.True);
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
        var stable = new SignedUpdateSource(stableUrl, publicKey, stableCache, stablePolicy, downloader);
        await stable.GetReleaseFeed(new NullVelopackLogger(), "AIDetector", "win");
        var preview = new SignedUpdateSource(previewUrl, publicKey, previewCache, stablePolicy, downloader);
        Assert.Throws<DirectoryNotFoundException>(() => preview.ReadCachedFeed());
        await preview.GetReleaseFeed(new NullVelopackLogger(), "AIDetector", "win");
        Assert.That(downloader.LastFeedUrl, Is.EqualTo(previewUrl + "/releases.win.json"));
        Assert.That(File.ReadAllText(stableCache), Is.EqualTo(envelope));
        Assert.That(preview.ReadCachedFeed().Assets.Length, Is.EqualTo(2));
    }

    [TestCase("0.0.51", "51.0.0", "preview", "2.0.0", "50.0.0", "stable")]
    [TestCase("2.0.0", "52.0.0", "stable", "0.0.51", "51.0.0", "preview")]
    [TestCase("0.0.51", "52.0.0", "stable", "0.0.51", "51.0.0", "preview")]
    public async Task PreviewOptInSelectsTheNewestBuildAcrossBothVersionSequences(
        string targetVersion, string targetBuild, string targetChannel,
        string installedVersion, string installedBuild, string installedChannel)
    {
        var policy = new UpdateChannelPolicy(installedBuild, installedChannel, true);
        var manager = ChannelManager(policy, installedVersion,
            ChannelAsset(installedVersion, installedBuild, installedChannel),
            ChannelAsset(targetVersion, targetBuild, targetChannel));
        var update = await manager.CheckForUpdatesAsync();
        Assert.That(update.TargetFullRelease.Version.ToString(), Is.EqualTo(targetVersion));
        Assert.That(update.DeltasToTarget, Is.Empty);
    }

    [Test]
    public async Task OptingOutCanDownloadAndDeferAnOlderOfficialRelease()
    {
        var policy = new UpdateChannelPolicy("51.0.0", "preview", false);
        var manager = ChannelManager(policy, "0.0.51",
            ChannelAsset("0.0.20", "20.0.0", "stable"), ChannelAsset("0.0.51", "51.0.0", "preview"));
        var update = await manager.CheckForUpdatesAsync();
        Assert.That(update.TargetFullRelease.Version.ToString(), Is.EqualTo("0.0.20"));
        await manager.DownloadUpdatesAsync(update);
        // Recreate the manager offline, as happens after quitting before applying.
        downloader.Envelope = null;
        var restarted = new VerifiedUpdateManager(new SignedUpdateSource(
            "https://example.invalid", publicKey, cache, policy, downloader), Locator(version: "0.0.51"));
        Assert.That(restarted.UpdatePendingRestart.Version.ToString(), Is.EqualTo("0.0.20"));
        var pending = await restarted.VerifyPendingUpdateAsync();
        Assert.That(pending.Version.ToString(), Is.EqualTo("0.0.20"));
        Assert.That(pending.FileName, Is.EqualTo("AIDetector-0.0.20-full.nupkg"));
    }

    [Test]
    public async Task DisablingPreviewsIgnoresAnAlreadyDownloadedPreview()
    {
        var policy = new UpdateChannelPolicy("40.0.0", "stable", true);
        var manager = ChannelManager(policy, "1.0.0",
            ChannelAsset("1.0.0", "40.0.0", "stable"), ChannelAsset("0.0.51", "51.0.0", "preview"));
        await manager.DownloadUpdatesAsync(await manager.CheckForUpdatesAsync());
        Assert.That(manager.UpdatePendingRestart, Is.Not.Null);
        policy.IncludePreviews = false;
        Assert.That(manager.UpdatePendingRestart, Is.Null);
        Assert.That(await manager.CheckForUpdatesAsync(), Is.Null);
    }

    [TestCase(true)]
    [TestCase(false)]
    public async Task ChannelSelectionCannotRollBackAnInstalledOfficialBuild(bool previews)
    {
        var manager = ChannelManager(new UpdateChannelPolicy("60.0.0", "stable", previews), "2.0.0",
            ChannelAsset("2.0.0", "50.0.0", "stable"), ChannelAsset("0.0.51", "51.0.0", "preview"));
        Assert.That(await manager.CheckForUpdatesAsync(), Is.Null);
    }

    [Test]
    public async Task OptingOutBeforeTheFirstOfficialReleaseKeepsTheInstalledPreview()
    {
        var manager = ChannelManager(new UpdateChannelPolicy("40.0.0", "preview", false), "0.0.40",
            ChannelAsset("0.0.51", "51.0.0", "preview"));
        Assert.That(await manager.CheckForUpdatesAsync(), Is.Null);
    }

    private JObject ChannelAsset(string version, string build, string channel) => new()
    {
        ["PackageId"] = "AIDetector", ["Type"] = "Full", ["Version"] = version,
        ["FileName"] = $"https://example.invalid/{channel}/AIDetector-{version}-full.nupkg",
        ["SHA256"] = release.SHA256, ["Size"] = package.Length,
        ["BuildVersion"] = build, ["ReleaseChannel"] = channel,
    };

    private VerifiedUpdateManager ChannelManager(UpdateChannelPolicy policy, string version, params JObject[] assets)
    {
        var payload = Encoding.UTF8.GetBytes(new JObject { ["Assets"] = new JArray(assets) }.ToString());
        // Public RFC 8032 fixture seed, shared with distribution/fixtures/keys.py.
        var seed = Convert.FromHexString("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60");
        var signer = new Ed25519Signer();
        signer.Init(true, new Ed25519PrivateKeyParameters(seed, 0));
        var context = Encoding.UTF8.GetBytes("AI Detector Windows updates v1\n");
        signer.BlockUpdate(context, 0, context.Length);
        signer.BlockUpdate(payload, 0, payload.Length);
        downloader.Envelope = new JObject
        {
            ["payload"] = Convert.ToBase64String(payload), ["signature"] = Convert.ToBase64String(signer.GenerateSignature())
        }.ToString();
        return new VerifiedUpdateManager(new SignedUpdateSource("https://example.invalid", publicKey, cache, policy, downloader), Locator(version: version));
    }

    private VelopackAsset Pending() => new()
    {
        PackageId = "AIDetector", Version = release.Version, Type = VelopackAssetType.Full,
        FileName = Path.GetFileName(new Uri(release.FileName).LocalPath), Size = package.Length
    };

    private TestVelopackLocator Locator(VelopackAsset pending = null, string version = "1.0.0") =>
        new("AIDetector", version, root, root, root, Path.Combine(root, "Update.exe"), "win", localPackage: pending);

    private sealed class DeltaRejectingManager(SignedUpdateSource source, TestVelopackLocator locator)
        : VerifiedUpdateManager(source, locator)
    {
        protected override Task DownloadAndApplyDeltaUpdates(UpdateInfo update, string targetFile,
            Action<int> progress, CancellationToken cancelToken) =>
            throw new AssertionException("Reconstructed ZIP bytes cannot be authenticated by the signed full-archive hash");
    }

    private sealed class FakeDownloader(string envelope, byte[] package) : IFileDownloader
    {
        public string Envelope { get; set; } = envelope;
        public byte[] Package { get; set; } = package;
        public int Downloads { get; private set; }
        public string LastFeedUrl { get; private set; }
        public string LastPackageUrl { get; private set; }
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
            cancelToken.ThrowIfCancellationRequested();
            Downloads++;
            LastPackageUrl = url;
            File.WriteAllBytes(path, Package);
            progress(100);
            return Task.CompletedTask;
        }
    }
}
