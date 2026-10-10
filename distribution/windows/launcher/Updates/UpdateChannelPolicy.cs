using System;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace AIDetector.Desktop;

// Release versions belong to their channel. Build versions order both channels.
internal sealed class UpdateChannelPolicy(string installedBuild, string installedChannel, bool includePreviews)
{
    public bool IncludePreviews { get; set; } = includePreviews;
    public bool WaitingForOfficialRelease => !IncludePreviews && installedChannel == "preview";

    public JObject Select(JObject feed)
    {
        var assets = feed["Assets"].Children<JObject>().ToArray();
        var target = assets.Where(asset => (string)asset["Type"] == "Full")
            .Where(asset => (string)asset["ReleaseChannel"] == "stable" ||
                (IncludePreviews && (string)asset["ReleaseChannel"] == "preview"))
            .OrderByDescending(BuildVersion).FirstOrDefault();
        if (target == null || (BuildVersion(target) <= Version.Parse(installedBuild) && !WaitingForOfficialRelease))
            return new JObject { ["Assets"] = new JArray() };

        var channel = (string)target["ReleaseChannel"];
        return new JObject
        {
            ["Assets"] = new JArray(assets.Where(asset => (string)asset["ReleaseChannel"] == channel &&
                // Delta chains are generated within a channel, never across channels.
                (channel == installedChannel || (string)asset["Type"] == "Full")))
        };
    }

    private static Version BuildVersion(JObject asset) => Version.Parse((string)asset["BuildVersion"]);
}
