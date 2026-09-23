/** Private pipe to the native shell; only the server that owns the port connects. */
import { createInterface } from 'node:readline';
import type { Readable, Writable } from 'node:stream';

export function connectDesktopHost(
	input: Readable,
	output: Writable,
	quit: () => void
): () => void {
	const commands = createInterface({ input });
	commands.on('line', (line) => {
		if (line === 'quit') quit();
	});
	// A crashed shell must not leave monitoring running without its controls.
	commands.once('close', quit);
	output.write('AI_DETECTOR_READY\n');
	return () => {
		commands.removeListener('close', quit);
		commands.close();
		input.pause();
	};
}
