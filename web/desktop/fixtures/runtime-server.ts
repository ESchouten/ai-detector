import { appendFileSync, writeFileSync } from 'node:fs';
import { startDesktop } from '../runtime.ts';

await startDesktop(async () => {
	const data = process.env.AIDETECTOR_DATA_DIR!;
	appendFileSync(`${data}/starts`, 'started\n');
	writeFileSync(`${data}/web-pid`, String(process.pid));
	process.on('SIGUSR2', () => process.exit(0));
	process.once('aidetector:launcher-disconnected', () => {
		appendFileSync(`${data}/launcher-disconnected`, 'disconnected\n');
	});
	process.once('sveltekit:shutdown', async (reason: string) => {
		appendFileSync(`${data}/shutdown-reasons`, reason + '\n');
		const response = await fetch(`http://127.0.0.1:${process.env.PORT}/`);
		appendFileSync(`${data}/drained`, String(response.status));
		if (process.env.FIXTURE_FAIL_SHUTDOWN === 'true')
			throw new Error('The test detector could not finish.');
	});
	return () => {
		console.error('Dashboard request received');
		return new Response('fixture dashboard');
	};
});
