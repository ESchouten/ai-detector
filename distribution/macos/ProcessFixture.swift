import Foundation

/// Command-line harness for the production process owner; no menu or login settings.
@main
struct ProcessFixture {
    static func main() throws {
        let child = DesktopProcess()
        try child.start(
            executable: URL(fileURLWithPath: CommandLine.arguments[1]),
            arguments: Array(CommandLine.arguments.dropFirst(2))
        ) { status, message in
            if let message { print("NATIVE_ERROR \(message)") }
            exit(status)
        }
        DispatchQueue.global().async {
            if readLine() == "quit" {
                do { try child.stop() }
                catch { fputs("\(error)\n", stderr); exit(1) }
            }
        }
        dispatchMain()
    }
}
