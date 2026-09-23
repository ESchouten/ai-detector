import Foundation

/// Owns the web process and its private control pipe, including loss of the parent.
final class DesktopProcess {
    private let process = Process()
    private let commands = Pipe()

    var isRunning: Bool { process.isRunning }

    func start(executable: URL, arguments: [String] = [], exited: @escaping @Sendable (Int32, String?) -> Void) throws {
        let errors = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.standardInput = commands
        process.standardError = errors
        var environment = ProcessInfo.processInfo.environment
        environment["AIDETECTOR_DESKTOP_HOST"] = "1"
        process.environment = environment
        try process.run()
        commands.fileHandleForReading.closeFile()
        errors.fileHandleForWriting.closeFile()
        let child = process
        DispatchQueue.global().async {
            let message = Self.readDiagnostic(errors.fileHandleForReading)
            child.waitUntilExit()
            exited(child.terminationStatus, message)
        }
    }

    /// Drain stderr continuously and retain only the runtime's human-readable error.
    private static func readDiagnostic(_ input: FileHandle) -> String? {
        defer { input.closeFile() }
        let prefix = "AI_DETECTOR_ERROR "
        var pending = Data()
        var message: String?
        while true {
            let chunk = input.availableData
            if chunk.isEmpty { return message }
            FileHandle.standardError.write(chunk)
            pending.append(chunk)
            while let newline = pending.firstIndex(of: 10) {
                let line = String(decoding: pending[..<newline], as: UTF8.self)
                if line.hasPrefix(prefix) { message = String(line.dropFirst(prefix.count)) }
                pending.removeSubrange(...newline)
            }
            // Ordinary logs are forwarded, never retained as an unbounded buffer.
            if pending.count > 16_384 { pending.removeAll(keepingCapacity: true) }
        }
    }

    func stop() throws {
        try commands.fileHandleForWriting.write(contentsOf: Data("quit\n".utf8))
    }

    deinit {
        commands.fileHandleForWriting.closeFile()
    }
}
