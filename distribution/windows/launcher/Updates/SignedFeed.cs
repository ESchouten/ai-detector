using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Crypto.Signers;
using Velopack;

namespace AIDetector.Desktop;

internal static class SignedFeed
{
    // Must match release_signatures.py; binds signatures to this app and update format.
    private static readonly byte[] Context = Encoding.UTF8.GetBytes("AI Detector Windows updates v1\n");

    public static VelopackAssetFeed Verify(string envelope, string publicKey)
    {
        var signed = JObject.Parse(envelope);
        var payload = Convert.FromBase64String((string)signed["payload"]);
        var signature = Convert.FromBase64String((string)signed["signature"]);
        var verifier = new Ed25519Signer();
        verifier.Init(false, new Ed25519PublicKeyParameters(Convert.FromBase64String(publicKey), 0));
        verifier.BlockUpdate(Context, 0, Context.Length);
        verifier.BlockUpdate(payload, 0, payload.Length);
        if (!verifier.VerifySignature(signature))
            throw new CryptographicException("The update metadata was not signed by AI Detector.");

        var feed = VelopackAssetFeed.FromJson(Encoding.UTF8.GetString(payload));
        foreach (var asset in feed.Assets)
        {
            if (asset.PackageId != "AIDetector" || asset.Size <= 0 ||
                !Regex.IsMatch(asset.SHA256 ?? "", @"\A[0-9a-fA-F]{64}\z"))
                throw new InvalidDataException("Signed updates must include their identity, size and SHA256.");
        }
        return feed;
    }
}
