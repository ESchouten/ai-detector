import AppKit
import ServiceManagement
import Sparkle

// The native shell owns only the menu and login preference. The bundled web
// executable owns instance identity, detection and graceful shutdown.
@MainActor
final class Application: NSObject, NSApplicationDelegate {
    private var child: DesktopProcess?
    private var item: NSStatusItem!
    private var loginItem: NSMenuItem!
    private var quitting = false
    private let service = SMAppService.mainApp
    private var updater: SPUStandardUpdaterController?
    private var executable: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/ai-detector-web")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "video", accessibilityDescription: "AI Detector")
        item.button?.image?.isTemplate = true
        item.button?.toolTip = "AI Detector"
        item.button?.setAccessibilityLabel("AI Detector")
        let menu = NSMenu()
        menu.addItem(withTitle: "Open dashboard", action: #selector(openDashboard), keyEquivalent: "o")
        loginItem = menu.addItem(withTitle: "Open at login", action: #selector(toggleLogin), keyEquivalent: "")
        menu.addItem(NSMenuItem.separator())
        menu.addItem(withTitle: "Quit AI Detector", action: #selector(quit), keyEquivalent: "q")
        for entry in menu.items { entry.target = self }
        if Bundle.main.object(forInfoDictionaryKey: "SUFeedURL") != nil {
            let controller = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
            updater = controller
            let check = NSMenuItem(title: "Check for Updates…", action: #selector(SPUStandardUpdaterController.checkForUpdates(_:)), keyEquivalent: "")
            check.target = controller
            menu.insertItem(check, at: 2)
        }
        item.menu = menu
        updateLoginState()
        launch()
        if !UserDefaults.standard.bool(forKey: "askedAboutLogin") {
            UserDefaults.standard.set(true, forKey: "askedAboutLogin")
            let alert = NSAlert()
            alert.messageText = "Open AI Detector when you log in?"
            alert.informativeText = "Recommended for daily monitoring. Detection resumes only when you have enabled it in the dashboard. This computer must stay awake."
            alert.addButton(withTitle: "Enable")
            alert.addButton(withTitle: "Not now")
            if alert.runModal() == .alertFirstButtonReturn { toggleLogin() }
        }
    }

    private func launch() {
        let process = DesktopProcess()
        do {
            try process.start(executable: executable) { [weak self] status, message in
                Task { @MainActor in
                    guard let self else { return }
                    self.child = nil
                    if self.quitting {
                        NSApp.reply(toApplicationShouldTerminate: status == 0)
                        self.quitting = false
                    } else if status == 0 {
                        // A second invocation opened the existing owner's dashboard.
                        NSApp.terminate(nil)
                    }
                    if status != 0 {
                        self.showError(message ?? "AI Detector stopped unexpectedly. Reopen the application to retry.")
                    }
                }
            }
            child = process
        } catch { showError(error.localizedDescription) }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openDashboard()
        return false
    }

    @objc private func openDashboard() {
        // A second invocation verifies the private local instance before opening it.
        if child == nil { launch() }
        else {
            let opener = Process()
            opener.executableURL = executable
            do { try opener.run() } catch { showError(error.localizedDescription) }
        }
    }

    @objc private func toggleLogin() {
        do {
            if service.status == .enabled { try service.unregister() }
            else if service.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
            else { try service.register() }
            updateLoginState()
        } catch { showError(error.localizedDescription) }
    }

    private func updateLoginState() {
        loginItem.state = service.status == .enabled ? .on : .off
        loginItem.title = service.status == .requiresApproval ? "Approve Open at login in System Settings…" : "Open at login"
    }

    @objc private func quit() { NSApp.terminate(nil) }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let child, child.isRunning else { return .terminateNow }
        do {
            try child.stop()
            quitting = true
            return .terminateLater
        } catch {
            showError("AI Detector could not request shutdown: \(error.localizedDescription)")
            return .terminateCancel
        }
    }

    private func showError(_ text: String) {
        let alert = NSAlert()
        alert.messageText = "AI Detector needs attention"
        alert.informativeText = text
        alert.runModal()
    }
}

@main
struct Launcher {
    @MainActor
    static func main() {
        let application = NSApplication.shared
        let delegate = Application()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        application.run()
    }
}
