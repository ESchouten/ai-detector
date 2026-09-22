#!/usr/bin/env node
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
const file = process.argv[process.argv.indexOf('-i') + 1];
const settings = JSON.parse(readFileSync(file, 'utf8'));
const directory = path.dirname(file);
process.on('SIGTERM', () => {
	writeFileSync(path.join(directory, 'terminated'), 'SIGTERM');
	if (!settings.ignoreTerm) process.exit(0);
});
writeFileSync(path.join(directory, 'pid'), String(process.pid));
const keepAlive = setInterval(() => {}, 1000);
if (settings.flood) {
	let chunks = 0;
	const chunk = Buffer.alloc(64 * 1024, 1);
	function write() {
		while (chunks < 1024) {
			chunks++;
			if (!process.stdout.write(chunk)) {
				writeFileSync(path.join(directory, 'chunks'), String(chunks));
				process.stdout.once('drain', write);
				return;
			}
		}
		writeFileSync(path.join(directory, 'chunks'), String(chunks));
		clearInterval(keepAlive);
	}
	write();
} else {
	process.stdout.write('preview frame');
	if (settings.endOutput) process.stdout.end();
}
