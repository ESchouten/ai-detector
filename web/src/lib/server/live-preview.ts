import { mkdir, readFile, unlink } from 'node:fs/promises';
import path from 'node:path';
import * as v from 'valibot';
import writeFileAtomic from 'write-file-atomic';
import {
	frameSchema,
	type CameraOverlayFrame,
	type LivePreviewFrame,
	type LivePreviewStatus
} from '../live-preview.ts';
import type { Config, AppConfig } from '../schema.ts';

export interface LivePreviewRule {
	id: string;
	label: string;
	preset?: string;
	interval: number;
}

export function livePreviewRules(
	source: string,
	config: Config,
	app: AppConfig
): LivePreviewRule[] {
	return config.detectors.flatMap((rule, index) =>
		rule.detection.source.includes(source)
			? [
					{
						id: `detector-${index + 1}`,
						label: app.detectors[index].label,
						preset: app.detectors[index].preset,
						interval: rule.detection.interval ?? 1
					}
				]
			: []
	);
}

export interface LivePreviewCamera {
	id: string;
	sourceKey: string;
	rules: LivePreviewRule[];
}

interface PreviewTarget {
	cameraId: string;
	sourceKey: string;
	rule: LivePreviewRule;
}

function targetKey(target: PreviewTarget): string {
	return `${target.cameraId}.${target.rule.id}`;
}

const sessionSchema = v.object({
	version: v.literal(1),
	runId: v.string(),
	updatedAt: v.pipe(v.string(), v.isoTimestamp())
});

async function json(file: string): Promise<unknown> {
	return JSON.parse(await readFile(file, 'utf8'));
}

function missing(error: unknown): boolean {
	return error instanceof Error && 'code' in error && error.code === 'ENOENT';
}

interface Lease {
	viewers: number;
	pending: Promise<void>;
	/** When the lease was last written; it is valid for twelve seconds from then. */
	renewedAt: number;
	timer?: ReturnType<typeof setInterval>;
	error?: unknown;
	renew: () => void;
}
const leases = new Map<string, Lease>();

function newLease(file: string): Lease {
	const lease: Lease = {
		viewers: 0,
		pending: Promise.resolve(),
		renewedAt: 0,
		renew() {
			lease.pending = lease.pending.then(async () => {
				if (!lease.viewers) return;
				try {
					await mkdir(path.dirname(file), { recursive: true });
					await writeFileAtomic(
						file,
						JSON.stringify({ version: 1, expiresAt: Date.now() / 1000 + 12 }),
						// Viewer leases are transient and do not need disk synchronization.
						{ fsync: false }
					);
					lease.error = undefined;
					lease.renewedAt = Date.now();
				} catch (error) {
					// Windows refuses to replace the file at the moment the detector reads it. The
					// lease on disk is still good then; only one that could not be kept is a failure.
					if (Date.now() - lease.renewedAt > 9000) lease.error = error;
				}
			});
		}
	};
	return lease;
}

/** Serialize renewal and final removal so closing one viewer cannot remove another's lease. */
function acquireLease(file: string): { check: () => void; release: () => Promise<void> } {
	const lease = leases.get(file) ?? newLease(file);
	leases.set(file, lease);
	lease.viewers++;
	if (!lease.timer) lease.timer = setInterval(lease.renew, 3000);
	lease.renew();
	return {
		check() {
			if (lease.error) throw lease.error;
		},
		async release() {
			lease.viewers--;
			if (lease.viewers) return;
			clearInterval(lease.timer);
			lease.timer = undefined;
			lease.pending = lease.pending.then(async () => {
				if (lease.viewers) return;
				try {
					await unlink(file);
				} catch (error) {
					if (!missing(error)) console.error('Could not remove live preview lease', error);
				} finally {
					if (!lease.viewers) leases.delete(file);
				}
			});
			await lease.pending;
		}
	};
}

type PreviewEvent =
	| { event: 'frame'; data: LivePreviewFrame }
	| { event: 'status'; data: LivePreviewStatus };

function status(rule: LivePreviewRule): PreviewEvent {
	return { event: 'status', data: { ruleId: rule.id } };
}

async function readSession(directory: string) {
	try {
		return v.parse(sessionSchema, await json(path.join(directory, 'session.json')));
	} catch (error) {
		if (missing(error)) return null;
		throw error;
	}
}

function changedEvents(
	events: { target: PreviewTarget; event: PreviewEvent }[],
	sent: Map<string, string>
): string {
	let chunk = '';
	for (const { target, event } of events) {
		const key = targetKey(target);
		const data: CameraOverlayFrame | LivePreviewStatus = {
			...event.data,
			cameraId: target.cameraId
		};
		const value = JSON.stringify(data);
		if (sent.get(key) === value) continue;
		sent.set(key, value);
		chunk += `event: ${event.event}\ndata: ${value}\n\n`;
	}
	return chunk || 'event: heartbeat\ndata: {}\n\n';
}

/** A frame counts only from the running detector, for this camera and rule, while it is fresh. */
async function readPreview(
	directory: string,
	sourceKey: string,
	rule: LivePreviewRule,
	session: v.InferOutput<typeof sessionSchema> | null
): Promise<PreviewEvent> {
	if (!session || Date.now() - Date.parse(session.updatedAt) > 6000) return status(rule);
	try {
		const frame = v.parse(
			frameSchema,
			await json(path.join(directory, 'frames', `${sourceKey}.${rule.id}.json`))
		);
		const age = Date.now() - Date.parse(frame.publishedAt);
		if (
			frame.runId !== session.runId ||
			frame.sourceKey !== sourceKey ||
			frame.ruleId !== rule.id ||
			age < -5000 ||
			age > Math.max(15000, rule.interval * 3000 + 5000)
		)
			return status(rule);
		return { event: 'frame', data: { ...frame, ruleLabel: rule.label, rulePreset: rule.preset } };
	} catch {
		return status(rule);
	}
}

/** All visible camera cards share one connection, leaving room for video and navigation. */
export function createCameraOverlayStream(
	directory: string,
	cameras: LivePreviewCamera[],
	signal: AbortSignal
): ReadableStream<Uint8Array> {
	return previewStream(
		directory,
		cameras.flatMap((camera) =>
			camera.rules.map((rule) => ({ cameraId: camera.id, sourceKey: camera.sourceKey, rule }))
		),
		signal
	);
}

/** Slow clients skip intermediate results instead of accumulating them. */
function previewStream(
	directory: string,
	targets: PreviewTarget[],
	signal: AbortSignal
): ReadableStream<Uint8Array> {
	const encoder = new TextEncoder();
	let close: (cancelled?: boolean) => Promise<void> = async () => {};
	return new ReadableStream({
		start(controller) {
			const leases = [...new Set(targets.map((target) => target.sourceKey))].map((key) =>
				acquireLease(path.join(directory, 'leases', `${key}.json`))
			);
			const sent = new Map<string, string>();
			let stopped = false;
			let polling = false;
			let runId: string | undefined;
			const timer = setInterval(() => void poll(), 100);
			const abort = () => void close();
			close = async (cancelled = false) => {
				if (stopped) return;
				stopped = true;
				clearInterval(timer);
				signal.removeEventListener('abort', abort);
				if (!cancelled) controller.close();
				try {
					await Promise.all(leases.map((lease) => lease.release()));
				} catch (error) {
					console.error('Could not remove live preview lease', error);
				}
			};
			async function poll() {
				if (stopped || polling || (controller.desiredSize ?? 0) <= 0) return;
				polling = true;
				try {
					for (const lease of leases) lease.check();
					const session = await readSession(directory);
					if (session && runId && session.runId !== runId) {
						// Reconnecting resolves current camera sources and rule labels after a restart.
						await close();
						return;
					}
					if (session) runId = session.runId;
					const events = await Promise.all(
						targets.map(async (target) => ({
							target,
							event: await readPreview(directory, target.sourceKey, target.rule, session)
						}))
					);
					if (stopped) return;
					controller.enqueue(encoder.encode(changedEvents(events, sent)));
				} catch (error) {
					if (stopped) return;
					console.error('Live detection preview unavailable', error);
					controller.enqueue(encoder.encode('event: status\ndata: {}\n\n'));
					await close();
				} finally {
					polling = false;
				}
			}
			signal.addEventListener('abort', abort, { once: true });
			if (signal.aborted) void close();
			else void poll();
		},
		cancel() {
			return close(true);
		}
	});
}
