#!/usr/bin/env node
const { appendFileSync, readFileSync } = process.getBuiltinModule('fs');
const path = process.getBuiltinModule('path');
const bundle = path.dirname(process.argv[4]);
const settings = JSON.parse(readFileSync(path.join(bundle, 'fixture.json'), 'utf8'));
if (process.argv.includes('--check-cuda')) {
	appendFileSync(path.join(bundle, 'gpu-checks.txt'), process.env.CUDA_VISIBLE_DEVICES + '\n');
	if (settings.gpuFailure) {
		console.error('NVIDIA driver is unavailable');
		process.exit(1);
	}
	console.log('NVIDIA acceleration ready');
} else if (process.argv.includes('--check-tensorrt')) {
	if (settings.tensorRtCheckFailure) {
		console.error('TensorRT library could not be loaded');
		process.exit(1);
	}
	console.log('Direct TensorRT ready');
} else {
	console.log('Using NVIDIA runtime: ' + process.env.CUDA_VISIBLE_DEVICES);
	import(process.getBuiltinModule('url').pathToFileURL(path.join(bundle, 'detector-fixture.mjs')));
}
