using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using AIDetector.Desktop;
using NUnit.Framework;
using Velopack;
using Velopack.Locators;

[TestFixture, Apartment(ApartmentState.STA)]
public sealed class UpdateTests
{
    private string folder;

    [SetUp]
    public void SetUp()
    {
        folder = Path.Combine(Path.GetTempPath(), "ai-detector-updates-" + Guid.NewGuid());
        Directory.CreateDirectory(folder);
    }

    [TearDown]
    public void TearDown() => Directory.Delete(folder, recursive: true);

    [Test]
    public async Task BackgroundCheckNotifiesWithoutDownloadingOrStoppingMonitoring()
    {
        var manager = new TestUpdater(folder);
        int notices = 0;
        using var item = new UpdateMenuItem(manager, _ => Assert.Fail("No automatic restart"), () => notices++);
        var checking = item.CheckInBackgroundAsync();
        await item.CheckInBackgroundAsync();
        Assert.That(item.Enabled, Is.False);
        Assert.That(manager.Checks, Is.EqualTo(1));
        manager.Check.SetResult(new UpdateInfo(Release(), false, null, Array.Empty<VelopackAsset>()));
        await checking;
        Assert.That(notices, Is.EqualTo(1));
        Assert.That(item.Enabled, Is.True);
        Assert.That(item.Text, Is.EqualTo("Check for Updates…"));
    }

    [Test]
    public async Task FailedBackgroundCheckLeavesManualRetryAvailable()
    {
        var manager = new TestUpdater(folder);
        using var item = new UpdateMenuItem(manager, _ => Assert.Fail("No restart"), () => Assert.Fail("No update"));
        var checking = item.CheckInBackgroundAsync();
        manager.Check.SetException(new IOException("offline"));
        await checking;
        Assert.That(item.Enabled, Is.True);
    }

    [Test]
    public async Task DownloadedUpdateWaitsForAnExplicitRestart()
    {
        var manager = new TestUpdater(folder) { Pending = Release() };
        using var item = new UpdateMenuItem(manager, _ => Assert.Fail("No automatic restart"), () => { });
        await item.CheckInBackgroundAsync();
        Assert.That(item.Text, Is.EqualTo("Update and restart…"));
        Assert.That(manager.Checks, Is.Zero);
    }

    [Test]
    public void PreviewBuildDoesNotOfferAnUpdateItCannotInstall()
    {
        using var item = new UpdateMenuItem(null, _ => Assert.Fail(), () => Assert.Fail());
        Assert.That(item.Enabled, Is.False);
    }

    private static VelopackAsset Release() => new() { Version = SemanticVersion.Parse("1.0.1"), Type = VelopackAssetType.Full };

    private sealed class TestUpdater(string folder) : VerifiedUpdateManager(
        new SignedUpdateSource("https://example.invalid", "unused test key", Path.Combine(folder, "feed.json")),
        new TestVelopackLocator("AIDetectorTest", "1.0.0", folder))
    {
        public TaskCompletionSource<UpdateInfo> Check { get; } = new();
        public int Checks { get; private set; }
        public VelopackAsset Pending { get; set; }
        public override bool IsInstalled => true;
        public override bool IsPortable => false;
        public override VelopackAsset UpdatePendingRestart => Pending;
        public override Task<UpdateInfo> CheckForUpdatesAsync() { Checks++; return Check.Task; }
        public override Task DownloadUpdatesAsync(UpdateInfo update, Action<int> progress = null, CancellationToken cancelToken = default)
            => throw new AssertionException("Background checks must not download without consent");
    }
}
