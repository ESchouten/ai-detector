import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ffmpeg from 'ffmpeg-static';

const clip = fileURLToPath(new URL('../../../example/sprong24.mp4', import.meta.url));

async function freePort() {
	const server = createServer().listen(0, '127.0.0.1');
	await once(server, 'listening');
	const { port } = server.address();
	await new Promise((resolve) => server.close(resolve));
	return port;
}

/** A process that is stopped after the test; its output is kept to wait on and to report. */
function helper(t, command, args, cwd) {
	const child = spawn(command, args, { cwd });
	let output = '';
	child.stdout.on('data', (chunk) => (output += chunk));
	child.stderr.on('data', (chunk) => (output += chunk));
	t.after(async () => {
		if (child.exitCode !== null || child.signalCode !== null) return;
		child.kill();
		await once(child, 'exit');
	});
	return { child, output: () => output };
}

/** Resolves once `process` has written a line that matches; fails when any of `running` exits. */
async function written(process, pattern, running) {
	while (!pattern.test(process.output())) {
		const ended = running.find(({ child }) => child.exitCode !== null);
		if (ended) throw new Error(`${ended.child.spawnfile} exited:\n${ended.output()}`);
		await new Promise((resolve) => setTimeout(resolve, 100));
	}
}

/**
 * A camera on this computer: mediamtx (on the PATH) serves the example mounting clip over RTSP,
 * in a loop, as a farm camera would show it.
 */
export async function rtspCamera(t) {
	const directory = await mkdtemp(path.join(tmpdir(), 'rtsp-camera-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const port = await freePort();
	const configuration = path.join(directory, 'mediamtx.yml');
	await writeFile(
		configuration,
		[
			`rtspAddress: 127.0.0.1:${port}`,
			'rtspTransports: [tcp]',
			...['rtmp', 'hls', 'webrtc', 'srt', 'moq'].map((protocol) => `${protocol}: no`),
			'paths:',
			'  barn:',
			''
		].join('\n')
	);
	const server = helper(t, 'mediamtx', [configuration], directory);
	await written(server, /\[RTSP\] started with listeners/, [server]);
	const url = `rtsp://127.0.0.1:${port}/barn`;
	// prettier-ignore
	const publisher = helper(t, ffmpeg, [
		'-hide_banner', '-loglevel', 'error', '-re', '-stream_loop', '-1', '-i', clip, '-an',
		'-vf', 'scale=1280:-2,fps=15', '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
		'-g', '30', '-f', 'rtsp', '-rtsp_transport', 'tcp', url
	], directory);
	await written(server, /is publishing to path 'barn'/, [server, publisher]);
	return url;
}
