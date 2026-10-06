// Run inside the final image, without repository dependencies or host data mounts.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { createRequire } from 'node:module';

const deadline = setTimeout(() => {
	console.error('Container startup or shutdown exceeded 30 seconds');
	process.exit(1);
}, 30000);

const require = createRequire('/app/package.json');
execFileSync(require('ffmpeg-static'), ['-version'], { stdio: 'inherit', timeout: 10000 });
// The detector the web application starts and supervises in this image.
execFileSync(process.env.AIDETECTOR_EXECUTABLE, ['--version'], {
	stdio: 'inherit',
	timeout: 60000
});
process.env.PORT = '0';
await import('/app/node-server.mjs');
const { server } = await import('/app/build/index.js');
try {
	if (!server.server.listening) await once(server.server, 'listening');
	const response = await fetch(`http://127.0.0.1:${server.server.address().port}/setup`);
	assert.equal(response.status, 200, await response.text());
	assert.match(response.headers.get('content-type'), /text\/html/);
	console.info('Container passed: setup page, FFmpeg and detector');
} finally {
	server.server.closeAllConnections();
	await new Promise((resolve, reject) =>
		server.server.close((error) => (error ? reject(error) : resolve()))
	);
	clearTimeout(deadline);
}
