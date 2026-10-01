#!/usr/bin/env node
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
if (process.argv.includes('--test-vlm')) {
	const file = process.argv[process.argv.indexOf('--test-vlm') + 1];
	const connection = JSON.parse(readFileSync(file, 'utf8'));
	writeFileSync('connection-check.json', JSON.stringify(connection));
	if (connection.model === 'hold') {
		writeFileSync('check-pid.txt', String(process.pid));
		await new Promise((resolve) => setTimeout(resolve, 60000));
	}
	if (connection.model === 'denied') {
		console.error('Check the API key.');
		process.exit(1);
	}
	console.log('{"ok": true}');
	process.exit(0);
}
const configPath = process.argv[process.argv.indexOf('--config') + 1];
const config = JSON.parse(readFileSync(configPath, 'utf8'));
// Test controls are separate from the application's schema-validated settings.
const options = existsSync('fixture-options.json')
	? JSON.parse(readFileSync('fixture-options.json', 'utf8'))
	: {};
if (process.argv.includes('--check-config')) {
	if (options.holdCheck) {
		process.on('SIGTERM', () => {});
		writeFileSync('check-pid.txt', String(process.pid));
		console.log('Checking configuration');
		await new Promise((resolve) => setTimeout(resolve, 60000));
	}
	if (!config.detectors?.length) {
		console.error('Add a detector');
		process.exit(2);
	}
	process.exit(0);
}
appendFileSync('starts.txt', 'started\n');
if (options.failureExitCode !== undefined) {
	process.on('SIGUSR2', () => {
		console.error('Injected inference failure');
		process.exit(options.failureExitCode);
	});
}
process.on('SIGUSR1', () => {
	for (const event of options.modelsReadyEvents ?? [
		{ version: 1, event: 'models_ready', at: new Date().toISOString() }
	])
		console.log('AIDETECTOR_STATUS ' + JSON.stringify(event));
});
writeFileSync('pid.txt', String(process.pid));
console.log('Camera rtsp://farmer:secret@camera.local/live?token=secret');
if (options.crash) process.exit(1);
for (const event of options.statusEvents ?? []) {
	const record = 'AIDETECTOR_STATUS ' + JSON.stringify(event) + '\n';
	process.stdout.write(record.slice(0, 20));
	await new Promise((resolve) => setImmediate(resolve));
	process.stdout.write(record.slice(20));
}
if (options.crashAfterStatus) process.exit(1);

let stopping = false;
function stop() {
	if (options.ignoreStop || stopping) return;
	stopping = true;
	setTimeout(() => {
		writeFileSync('flushed.txt', 'flushed');
		process.exit(options.stopExitCode ?? 0);
	}, options.stopDelayMs ?? 0);
}
process.stdin.on('data', stop);
process.stdin.on('end', stop);
if (options.ignoreStop) setInterval(() => {}, 1000);
process.stdin.resume();
