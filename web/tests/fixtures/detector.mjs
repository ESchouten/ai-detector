#!/usr/bin/env node
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
const configPath = process.argv[process.argv.indexOf('--config') + 1];
const config = JSON.parse(readFileSync(configPath, 'utf8'));
if (process.argv.includes('--check-config')) {
	if (config.holdCheck) {
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
console.log('Camera rtsp://farmer:secret@camera.local/live?token=secret');
if (config.crash) process.exit(1);
for (const event of config.statusEvents ?? []) {
	const record = 'AIDETECTOR_STATUS ' + JSON.stringify(event) + '\n';
	process.stdout.write(record.slice(0, 20));
	await new Promise((resolve) => setImmediate(resolve));
	process.stdout.write(record.slice(20));
}
if (config.crashAfterStatus) process.exit(1);

process.stdin.on('data', () => {
	if (config.ignoreStop) return;
	writeFileSync('flushed.txt', 'flushed');
	process.exit(config.stopExitCode ?? 0);
});
process.stdin.on('end', () => {
	if (!config.ignoreStop) process.exit(config.stopExitCode ?? 0);
});
if (config.ignoreStop) setInterval(() => {}, 1000);
process.stdin.resume();
