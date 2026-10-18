import { spawn } from 'node:child_process';

const browserDisabled = () => process.env.OPEN_BROWSER?.trim().toLowerCase() === 'false';

export function openDashboard(url: string): void {
	if (browserDisabled()) return;
	const command =
		process.platform === 'win32' ? 'cmd' : process.platform === 'darwin' ? 'open' : 'xdg-open';
	const args = process.platform === 'win32' ? ['/c', 'start', '', url] : [url];
	const child = spawn(command, args, { detached: true, stdio: 'ignore', windowsHide: true });
	child.on('error', () => console.warn(`Open ${url} in your browser to continue setup.`));
	child.unref();
}

/** The native shell owns dialogs; standalone Windows downloads need their own. */
export async function reportFailure(message: string): Promise<void> {
	const summary = message.replace(/\s+/g, ' ').slice(0, 4000);
	console.error(`AI_DETECTOR_ERROR ${summary}`);
	if (
		process.env.AIDETECTOR_DESKTOP_HOST === '1' ||
		process.platform !== 'win32' ||
		browserDisabled()
	)
		return;
	const dialog = spawn(
		'powershell.exe',
		[
			'-NoProfile',
			'-Command',
			// The text travels in the environment: PowerShell also ends a quoted string at ’ and ‘.
			"Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show($env:AIDETECTOR_FAILURE, 'AI Detector')"
		],
		{ env: { ...process.env, AIDETECTOR_FAILURE: summary }, stdio: 'ignore', windowsHide: true }
	);
	await new Promise<void>((resolve) => {
		dialog.once('exit', () => resolve());
		dialog.once('error', () => resolve());
	});
}
