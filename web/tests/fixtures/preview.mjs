#!/usr/bin/env node
import { readFileSync, writeFileSync } from 'node:fs';
import { once } from 'node:events';
import path from 'node:path';
const file = process.argv[process.argv.indexOf('-i') + 1];
const settings = JSON.parse(readFileSync(file, 'utf8'));
const directory = path.dirname(file);
process.on('SIGTERM', () => {
	writeFileSync(path.join(directory, 'terminated'), 'SIGTERM');
	if (!settings.ignoreTerm) process.exit(0);
});
writeFileSync(path.join(directory, 'pid'), String(process.pid));
setInterval(() => {}, 1000);
const count = settings.flood ? 1500 : 1;
for (let number = 1; number <= count; number++) {
	const body = settings.flood
		? Buffer.alloc(64 * 1024, number % 256)
		: Buffer.from('preview frame');
	if (settings.flood) body.write(String(number).padStart(4, '0'));
	const header = Buffer.from(
		`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${body.length}\r\n\r\n`
	);
	const frame = Buffer.concat([header, body, Buffer.from('\r\n')]);
	// Headers and JPEGs need not align with child-process chunks.
	for (const chunk of [frame.subarray(0, 9), frame.subarray(9)]) {
		if (!process.stdout.write(chunk)) await once(process.stdout, 'drain');
	}
}
process.stdout.write('--frame\r\n');
writeFileSync(path.join(directory, 'frames'), String(count));
if (settings.endOutput) process.stdout.end();
