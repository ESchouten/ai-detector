#!/usr/bin/env node
const { appendFileSync, copyFileSync, mkdirSync, readFileSync, writeFileSync } =
	process.getBuiltinModule('fs');
const path = process.getBuiltinModule('path');
const bundle = path.dirname(process.argv[1]);
const settings = JSON.parse(readFileSync(path.join(bundle, 'fixture.json'), 'utf8'));
const args = process.argv.slice(2);
appendFileSync(
	path.join(bundle, 'commands.jsonl'),
	JSON.stringify({ args, cache: process.env.UV_CACHE_DIR }) + '\n'
);
if (args[0] === 'venv') {
	const scripts = path.join(args.at(-1), 'Scripts');
	mkdirSync(scripts, { recursive: true });
	copyFileSync(path.join(bundle, 'python-fixture.cjs'), path.join(scripts, 'python.exe'));
} else {
	console.log('Downloading GPU packages');
	if (args.includes('install') && settings.tensorRtInstallFailure) {
		console.error('TensorRT package download failed');
		process.exit(1);
	}
	if (settings.holdInstall || (args.includes('install') && settings.holdTensorRtInstall)) {
		writeFileSync(path.join(bundle, 'install-pid.txt'), String(process.pid));
		setInterval(() => {}, 1000);
	}
	if (settings.installFailure) {
		console.error('Download failed: hash mismatch');
		process.exit(1);
	}
}
