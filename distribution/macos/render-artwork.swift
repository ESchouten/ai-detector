// Run with `swift distribution/macos/render-artwork.swift` after editing the SVGs.
import AppKit

let assets = URL(fileURLWithPath: #filePath).deletingLastPathComponent()

func render(_ source: String, to output: URL, width: Int, height: Int) throws {
    let image = NSImage(contentsOf: assets.appendingPathComponent(source))!
    let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
        isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
    )!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    image.draw(in: NSRect(x: 0, y: 0, width: width, height: height))
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: output)
}

for scale in [1, 2] {
    let name = scale == 1 ? "background.png" : "background@2x.png"
    try render("background.svg", to: assets.appendingPathComponent(name),
               width: 660 * scale, height: 420 * scale)
}

let scratch = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
let iconset = scratch.appendingPathComponent("AI Detector.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: scratch) }

for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let suffix = scale == 1 ? "" : "@2x"
        let output = iconset.appendingPathComponent("icon_\(size)x\(size)\(suffix).png")
        try render("app-icon.svg", to: output, width: size * scale, height: size * scale)
    }
}

let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["-c", "icns", iconset.path, "-o", assets.appendingPathComponent("AI Detector.icns").path]
try iconutil.run()
iconutil.waitUntilExit()
exit(iconutil.terminationStatus)
