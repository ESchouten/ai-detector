import { appendFileSync } from 'node:fs';
import { startDesktop } from '../runtime.ts';

await startDesktop(async () => {
	const data = process.env.AIDETECTOR_DATA_DIR!;
	appendFileSync(`${data}/starts`, 'started\n');
	process.once('sveltekit:shutdown', async () => {
		const response = await fetch(`http://127.0.0.1:${process.env.PORT}/`);
		appendFileSync(`${data}/drained`, String(response.status));
		if (process.env.FIXTURE_FAIL_SHUTDOWN === 'true')
			throw new Error('The test detector could not finish.');
	});
	return () => new Response('fixture dashboard');
});
