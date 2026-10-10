import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { CameraOverlays } from '../src/lib/camera-overlays.ts';
import type { CameraOverlayFrame } from '../src/lib/live-preview.ts';

class Connection extends EventTarget {
	closed = false;
	close() {
		this.closed = true;
	}
	frame(cameraId: string, ruleId = 'detector-1', boxes: CameraOverlayFrame['boxes'] = []) {
		this.dispatchEvent(
			new MessageEvent('frame', {
				data: JSON.stringify({
					version: 1,
					cameraId,
					ruleId,
					ruleLabel: ruleId,
					runId: 'run-1',
					sourceKey: cameraId,
					publishedAt: new Date().toISOString(),
					image: { width: 960, height: 540 },
					boxes
				} satisfies CameraOverlayFrame)
			})
		);
	}
	status(cameraId?: string, ruleId?: string) {
		this.dispatchEvent(
			new MessageEvent('status', {
				data: JSON.stringify({ cameraId, ruleId })
			})
		);
	}
}

function fixture(t: TestContext) {
	const connections: { url: string; source: Connection }[] = [];
	const overlays = new CameraOverlays(
		() => '/cameras/live',
		(url) => {
			const source = new Connection();
			connections.push({ url, source });
			return source;
		}
	);
	const watch = (id: string) => {
		let frames: CameraOverlayFrame[] = [];
		const stop = overlays.subscribe(id, (value) => {
			frames = value;
		});
		t.after(stop);
		return {
			get frames() {
				return frames;
			},
			stop
		};
	};
	return { watch, connections };
}

test('visible camera cards share one connection and release it when the last viewer leaves', async (t) => {
	const { watch, connections } = fixture(t);
	const pen = watch('pen');
	const shed = watch('shed');
	await Promise.resolve();
	assert.equal(connections.length, 1);
	assert.equal(connections[0].url, '/cameras/live?camera=pen&camera=shed');
	const duplicate = watch('pen');
	await Promise.resolve();
	assert.equal(connections.length, 1);
	duplicate.stop();
	await Promise.resolve();
	assert.equal(connections.length, 1);
	shed.stop();
	await Promise.resolve();
	assert.equal(connections[0].source.closed, true);
	assert.equal(connections[1].url, '/cameras/live?camera=pen');
	pen.stop();
	await Promise.resolve();
	assert.equal(connections[1].source.closed, true);
});

test('each camera retains its own rules and clears boxes on empty inference or a rule-specific failure', async (t) => {
	const { watch, connections } = fixture(t);
	const shed = watch('shed');
	const pen = watch('pen');
	await Promise.resolve();
	const source = connections[0].source;
	const boxes = [
		{ x1: 10, y1: 20, x2: 300, y2: 400, label: 'mounting', confidence: 0.93, trackId: 7 }
	];
	source.frame('shed', 'detector-1', boxes);
	source.frame('shed', 'detector-2');
	source.frame('pen');
	assert.deepEqual(
		shed.frames.map((frame) => frame.ruleId),
		['detector-1', 'detector-2']
	);
	assert.deepEqual(shed.frames[0].boxes, boxes);
	assert.equal(pen.frames.length, 1);
	assert.equal(pen.frames[0].cameraId, 'pen');
	source.frame('shed', 'detector-1');
	assert.deepEqual(shed.frames[0].boxes, []);
	source.status('shed', 'detector-1');
	assert.deepEqual(
		shed.frames.map((frame) => frame.ruleId),
		['detector-2']
	);
	assert.equal(pen.frames.length, 1);
	source.status();
	assert.deepEqual(shed.frames, []);
	assert.deepEqual(pen.frames, []);
});

test('disconnected or stalled metadata cannot leave old boxes on moving video', async (t) => {
	t.mock.timers.enable({ apis: ['setInterval', 'Date'] });
	const { watch, connections } = fixture(t);
	const shed = watch('shed');
	await Promise.resolve();
	const source = connections[0].source;
	source.frame('shed');
	source.dispatchEvent(new Event('error'));
	assert.deepEqual(shed.frames, []);
	source.frame('shed');
	t.mock.timers.tick(6000);
	source.dispatchEvent(new Event('heartbeat'));
	t.mock.timers.tick(6000);
	assert.equal(shed.frames.length, 1);
	t.mock.timers.tick(2000);
	assert.deepEqual(shed.frames, []);
});
