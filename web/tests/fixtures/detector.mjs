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
process.stdin.on('data', () => {
	writeFileSync('flushed.txt', 'flushed');
	process.exit(0);
});
process.stdin.on('end', () => process.exit(0));
process.stdin.resume();
