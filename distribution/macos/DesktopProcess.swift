import Foundation

/// Keeps the background web process running until an explicit application shutdown.
final class DesktopProcess: @unchecked Sendable {
    private struct Run {
        let process: Process
        let commands: Pipe
        let errors: Pipe
        let startedAt = Date()
    }

    // The menu and the worker share only lifecycle state, protected by this condition.
    private let condition = NSCondition()
    private var current: Run?
    private var active = false
    private var stopping = false

    var isRunning: Bool {
        condition.lock()
        defer { condition.unlock() }
        return active
    }

    func start(executable: URL, arguments: [String] = [], exited: @escaping @Sendable (Int32, String?) -> Void) throws {
        let first = try launch(executable: executable, arguments: arguments)
        DispatchQueue.global().async { [self] in
            var run = first
            var delay: TimeInterval = 2
            while true {
                let diagnostic = Self.readDiagnostic(run.errors.fileHandleForReading)
                run.process.waitUntilExit()
                condition.lock()
                run.commands.fileHandleForWriting.closeFile()
                current = nil
                if stopping || diagnostic.shutdown {
                    active = false
                    condition.unlock()
                    exited(run.process.terminationStatus, diagnostic.message)
                    return
                }
                if Date().timeIntervalSince(run.startedAt) >= 600 { delay = 2 }
                condition.unlock()
                while true {
                    fputs("AI Detector background process stopped; restarting in \(Int(delay)) seconds.\n", stderr)
                    condition.lock()
                    let deadline = Date().addingTimeInterval(delay)
                    while !stopping && Date() < deadline { condition.wait(until: deadline) }
                    if stopping {
                        active = false
                        condition.unlock()
                        exited(0, nil)
                        return
                    }
                    condition.unlock()
                    delay = min(delay * 2, 30)
                    do {
                        run = try launch(executable: executable, arguments: arguments + ["--background"])
                        break
                    } catch { fputs("AI Detector restart failed: \(error)\n", stderr) }
                }
            }
        }
    }

    private func launch(executable: URL, arguments: [String]) throws -> Run {
        condition.lock()
        defer { condition.unlock() }
        let run = Run(process: Process(), commands: Pipe(), errors: Pipe())
        run.process.executableURL = executable
        run.process.arguments = arguments
        run.process.standardInput = run.commands
        run.process.standardError = run.errors
        var environment = ProcessInfo.processInfo.environment
        environment["AIDETECTOR_DESKTOP_HOST"] = "1"
        run.process.environment = environment
        try run.process.run()
        run.commands.fileHandleForReading.closeFile()
        run.errors.fileHandleForWriting.closeFile()
        current = run
        active = true
        // A quit can arrive between the retry wait and acquiring this lock.
        if stopping { try run.commands.fileHandleForWriting.write(contentsOf: Data("quit\n".utf8)) }
        return run
    }

    /// Drain stderr continuously; only the private shutdown marker suppresses recovery.
    private static func readDiagnostic(_ input: FileHandle) -> (message: String?, shutdown: Bool) {
        defer { input.closeFile() }
        let prefix = "AI_DETECTOR_ERROR "
        var pending = Data()
        var message: String?
        var shutdown = false
        while true {
            let chunk = input.availableData
            if chunk.isEmpty { return (message, shutdown) }
            FileHandle.standardError.write(chunk)
            pending.append(chunk)
            while let newline = pending.firstIndex(of: 10) {
                let line = String(decoding: pending[..<newline], as: UTF8.self)
                if line.hasPrefix(prefix) { message = String(line.dropFirst(prefix.count)) }
                if line == "AI_DETECTOR_STOPPING" { shutdown = true }
                pending.removeSubrange(...newline)
            }
            if pending.count > 16_384 { pending.removeAll(keepingCapacity: true) }
        }
    }

    func stop() throws {
        condition.lock()
        defer { condition.unlock() }
        stopping = true
        condition.broadcast()
        if let current, current.process.isRunning {
            do { try current.commands.fileHandleForWriting.write(contentsOf: Data("quit\n".utf8)) }
            catch { if current.process.isRunning { throw error } }
        }
    }
}
