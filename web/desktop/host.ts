/** Private pipe to the native shell; only the server that owns the port connects. */
import { createInterface } from 'node:readline';
import type { Readable, Writable } from 'node:stream';

export function connectDesktopHost(
	input: Readable,
	output: Writable,
	quit: (reason: string) => void,
	disconnected: () => void
): () => void {
	const commands = createInterface({ input });
	commands.on('line', (line) => {
		if (line === 'quit') quit('Native launcher sent an explicit quit command');
	});
	// Losing the menu is not a request to stop monitoring; the dashboard remains available.
	commands.once('close', disconnected);
	output.write('AI_DETECTOR_READY\n');
	return () => {
		commands.removeListener('close', disconnected);
		commands.close();
		input.pause();
	};
}
