import { type ChildProcessWithoutNullStreams, spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import path from 'node:path';

/** The dashboard owns the child; closing stdin removes the native tray icon. */
export function startWindowsTray(open: () => void, quit: () => void): () => Promise<void> {
	const executable = path.join(path.dirname(process.execPath), 'tray', 'AI Detector Tray.exe');
	const child = spawn(executable, [process.execPath], { windowsHide: true });
	return connectTray(child, open, quit);
}

export function connectTray(
	child: ChildProcessWithoutNullStreams,
	open: () => void,
	quit: () => void
): () => Promise<void> {
	const commands = createInterface({ input: child.stdout });
	commands.on('line', (command) => {
		if (command === 'open') open();
		if (command === 'quit') quit();
	});
	child.stderr.pipe(process.stderr, { end: false });
	child.once('error', (error) =>
		console.error('Could not start the AI Detector tray menu:', error)
	);
	// EPIPE means the helper already exited. The dashboard still owns monitoring.
	child.stdin.on('error', (error: NodeJS.ErrnoException) => {
		if (error.code !== 'EPIPE') console.error('AI Detector tray connection failed:', error);
	});
	const closed = new Promise<void>((resolve) =>
		child.once('close', () => {
			commands.close();
			resolve();
		})
	);
	return () => {
		commands.close();
		child.stdin.end();
		return closed;
	};
}
