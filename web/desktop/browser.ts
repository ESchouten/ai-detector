import { spawn } from 'node:child_process';

export function openDashboard(url: string): void {
	if (process.env.OPEN_BROWSER?.trim().toLowerCase() === 'false') return;
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
		process.env.OPEN_BROWSER?.trim().toLowerCase() === 'false'
	)
		return;
	const dialog = spawn(
		'powershell.exe',
		[
			'-NoProfile',
			'-Command',
			`Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('${summary.replaceAll("'", "''")}', 'AI Detector')`
		],
		{ stdio: 'ignore', windowsHide: true }
	);
	await new Promise<void>((resolve) => {
		dialog.once('exit', () => resolve());
		dialog.once('error', () => resolve());
	});
}
