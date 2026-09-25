import { createHash } from 'node:crypto';
import path from 'node:path';
import * as v from 'valibot';
import type { AppConfig, Config, DetectorConfig } from '../schema.ts';
import type { CameraRuntimeStatus, RuntimeReadiness } from '../runtime.ts';

export const STATUS_PREFIX = 'AIDETECTOR_STATUS ';
const eventSchema = v.object({
	version: v.literal(1),
	event: v.picklist([
		'preparing',
		'preparation_failed',
		'ready',
		'frame',
		'inference',
		'processed',
		'recording',
		'offline',
		'recording_failed',
		'notice'
	]),
	at: v.pipe(
		v.string(),
		v.check((value) => Number.isFinite(Date.parse(value)))
	),
	sourceKey: v.optional(v.pipe(v.string(), v.regex(/^[a-f0-9]{64}$/))),
	message: v.optional(v.string()),
	ruleId: v.optional(v.pipe(v.string(), v.regex(/^detector-[1-9]\d*$/))),
	destinationId: v.optional(v.pipe(v.string(), v.regex(/^disk-[1-9]\d*$/)))
});

type ProgressEvent = v.InferOutput<typeof eventSchema>;
interface RuleProgress {
	index: number;
	label: string;
	timeout: number;
	lastProcessedAt: string | null;
	recordings: Map<string, string | undefined>;
}
interface CameraProgress {
	status: CameraRuntimeStatus;
	source: string;
	connectedAt: string | null;
	rules: Map<string, RuleProgress>;
}

function ruleProgress(detector: DetectorConfig, index: number, app: AppConfig): RuleProgress {
	const disk = detector.exporters?.disk;
	const recordings = disk === undefined ? [] : Array.isArray(disk) ? disk : [disk];
	return {
		index,
		label: app.detectors?.[index]?.label || `Detector ${index + 1}`,
		timeout: Math.max(15000, (detector.detection.interval ?? 0) * 3000 + 5000),
		lastProcessedAt: null,
		recordings: new Map(recordings.map((_, index) => [`disk-${index + 1}`, undefined]))
	};
}

/** Only these structured observations can establish camera readiness. */
export class RuntimeProgress {
	private prepared = false;
	private cameras = new Map<string, CameraProgress>();
	preparation: string | undefined;
	preparationFailure: string | undefined;
	notice: string | undefined;

	configure(config: Config, app: AppConfig, directory: string): void {
		this.prepared = false;
		this.cameras.clear();
		this.preparation = undefined;
		this.preparationFailure = undefined;
		this.notice = undefined;
		for (const [index, detector] of config.detectors.entries()) {
			const sources = detector.detection.source;
			for (const source of typeof sources === 'string' ? [sources] : sources) {
				const resolved = /^(?:[a-z]+:\/\/|\d+$)/i.test(source)
					? source
					: path.resolve(directory, source);
				const sourceKey = createHash('sha256').update(resolved).digest('hex');
				let camera = this.cameras.get(sourceKey);
				if (!camera) {
					camera = {
						source,
						connectedAt: null,
						rules: new Map(),
						status: {
							id: sourceKey,
							label: `Camera ${this.cameras.size + 1}`,
							sourceKey,
							state: 'connecting',
							lastFrameAt: null,
							lastProcessedAt: null,
							lastInferenceAt: null,
							lastRecordingAt: null
						}
					};
					this.cameras.set(sourceKey, camera);
				}
				camera.rules.set(`detector-${index + 1}`, ruleProgress(detector, index, app));
			}
		}
		this.updateMetadata(app);
	}

	updateMetadata(app: AppConfig): void {
		for (const camera of this.cameras.values()) {
			const meta = app.streams?.find((stream) => stream.source === camera.source);
			if (meta) {
				camera.status.id = meta.id ?? camera.status.id;
				camera.status.label = meta.label || camera.status.label;
			}
			for (const rule of camera.rules.values())
				rule.label = app.detectors?.[rule.index]?.label || rule.label;
		}
	}

	accept(line: string): void {
		let value: unknown;
		try {
			value = JSON.parse(line.slice(STATUS_PREFIX.length));
		} catch {
			return;
		}
		const parsed = v.safeParse(eventSchema, value);
		if (!parsed.success) return;
		const event = parsed.output;
		if (event.event === 'ready') {
			this.prepared = true;
			this.preparation = undefined;
			return;
		}
		if (event.event === 'preparing') {
			const rule = Array.from(this.cameras.values(), (camera) =>
				camera.rules.get(event.ruleId ?? '')
			).find(Boolean);
			this.preparation = rule && event.message ? `${rule.label}: ${event.message}` : event.message;
			return;
		}
		if (event.event === 'preparation_failed') {
			this.preparationFailure =
				event.message ?? 'Model preparation failed. Check the details and try again.';
			return;
		}
		if (event.event === 'notice') {
			this.notice = event.message;
			return;
		}
		const camera = event.sourceKey ? this.cameras.get(event.sourceKey) : undefined;
		if (camera) this.observe(camera, event);
	}

	private observe(camera: CameraProgress, event: ProgressEvent): void {
		const status = camera.status;
		if (event.event === 'frame') {
			if (!camera.connectedAt || status.state === 'offline') {
				camera.connectedAt = event.at;
				for (const rule of camera.rules.values()) rule.lastProcessedAt = null;
			}
			status.lastFrameAt = event.at;
			status.error = undefined;
			status.state = 'receiving';
		} else if (event.event === 'offline') {
			status.state = 'offline';
			status.error = event.message;
		} else {
			const rule = event.ruleId ? camera.rules.get(event.ruleId) : undefined;
			if (rule) this.observeRule(status, rule, event);
		}
	}

	private observeRule(camera: CameraRuntimeStatus, rule: RuleProgress, event: ProgressEvent): void {
		if (event.event === 'inference' || event.event === 'processed') {
			// Completing an old batch cannot recover a disconnected camera.
			if (camera.state !== 'offline') rule.lastProcessedAt = event.at;
			camera.lastProcessedAt = event.at;
			if (event.event === 'inference') camera.lastInferenceAt = event.at;
		} else if (event.destinationId && rule.recordings.has(event.destinationId)) {
			if (event.event === 'recording') {
				camera.lastRecordingAt = event.at;
				rule.recordings.set(event.destinationId, undefined);
			} else if (event.event === 'recording_failed') {
				rule.recordings.set(
					event.destinationId,
					event.message || 'A recording could not be saved.'
				);
			}
		}
	}

	private cameraStatus(camera: CameraProgress, now: number): CameraRuntimeStatus {
		const status = { ...camera.status };
		const rules = Array.from(camera.rules.values());
		const failures = rules.flatMap((rule) =>
			Array.from(rule.recordings.values())
				.filter((error): error is string => !!error)
				.map((error) => `${rule.label}: ${error}`)
		);
		status.recordingError = failures.length ? Array.from(new Set(failures)).join(' ') : undefined;
		if (status.lastFrameAt && now - Date.parse(status.lastFrameAt) > 15000) {
			status.state = 'offline';
			status.error = 'No recent camera frames. Waiting for the connection to recover.';
		} else if (status.lastFrameAt && status.state !== 'offline') {
			const stale = rules.find(
				(rule) => now - Date.parse(rule.lastProcessedAt ?? camera.connectedAt!) > rule.timeout
			);
			if (stale) {
				status.state = 'receiving';
				status.error = `${stale.label}: processing has not completed recently.`;
			} else
				status.state = rules.every((rule) => rule.lastProcessedAt) ? 'monitoring' : 'receiving';
		}
		return status;
	}

	snapshot(now = Date.now()): { cameras: CameraRuntimeStatus[]; readiness: RuntimeReadiness } {
		const cameras = Array.from(this.cameras.values(), (camera) => this.cameraStatus(camera, now));
		if (this.preparationFailure) return { cameras, readiness: 'failed' };
		if (
			cameras.some((camera) => camera.state === 'offline' || camera.recordingError || camera.error)
		)
			return { cameras, readiness: 'degraded' };
		if (cameras.length && cameras.every((camera) => camera.state === 'monitoring'))
			return { cameras, readiness: 'monitoring' };
		return {
			cameras,
			readiness:
				this.prepared || cameras.some((camera) => camera.lastFrameAt) ? 'connecting' : 'preparing'
		};
	}
}
