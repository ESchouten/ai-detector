import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import * as v from 'valibot';
import type { LivePreviewFrame, LivePreviewStatus } from '../live-preview.ts';

export interface LivePreviewRule {
	id: string;
	label: string;
	interval: number;
}

const sessionSchema = v.object({
	version: v.literal(1),
	runId: v.string(),
	updatedAt: v.pipe(v.string(), v.isoTimestamp())
});
const coordinate = v.pipe(v.number(), v.finite());
const frameSchema = v.object({
	version: v.literal(1),
	runId: v.string(),
	sourceKey: v.string(),
	ruleId: v.string(),
	capturedAt: v.string(),
	publishedAt: v.pipe(v.string(), v.isoTimestamp()),
	image: v.object({
		width: v.pipe(v.number(), v.integer(), v.minValue(1)),
		height: v.pipe(v.number(), v.integer(), v.minValue(1)),
		jpeg: v.pipe(v.string(), v.minLength(1))
	}),
	boxes: v.array(
		v.object({
			x1: coordinate,
			y1: coordinate,
			x2: coordinate,
			y2: coordinate,
			label: v.nullable(v.string()),
			confidence: v.nullable(coordinate),
			trackId: v.nullable(v.pipe(v.number(), v.integer()))
		})
	)
});

export function liveSourceKey(source: string, configurationDirectory: string): string {
	const resolved = /^(?:[a-z]+:\/\/|\d+$)/i.test(source)
		? source
		: path.resolve(configurationDirectory, source);
	return createHash('sha256').update(resolved).digest('hex');
}

async function json(file: string): Promise<unknown> {
	return JSON.parse(await readFile(file, 'utf8'));
}

function missing(error: unknown): boolean {
	return error instanceof Error && 'code' in error && error.code === 'ENOENT';
}

interface Lease {
	viewers: number;
	pending: Promise<void>;
	timer?: ReturnType<typeof setInterval>;
	error?: unknown;
	renew: () => void;
}
const leases = new Map<string, Lease>();

function newLease(file: string): Lease {
	const lease: Lease = {
		viewers: 0,
		pending: Promise.resolve(),
		renew() {
			lease.pending = lease.pending.then(async () => {
				if (!lease.viewers) return;
				const temporary = `${file}.${randomUUID()}.tmp`;
				try {
					await mkdir(path.dirname(file), { recursive: true });
					await writeFile(
						temporary,
						JSON.stringify({ version: 1, expiresAt: Date.now() / 1000 + 12 })
					);
					await rename(temporary, file);
					lease.error = undefined;
				} catch (error) {
					lease.error = error;
				} finally {
					await unlink(temporary).catch(() => undefined);
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

function status(
	rule: LivePreviewRule,
	state: LivePreviewStatus['state'],
	message: string
): PreviewEvent {
	return {
		event: 'status',
		data: { version: 1, state, message, ruleId: rule.id, ruleLabel: rule.label }
	};
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
	events: PreviewEvent[],
	sent: Map<string, string>,
	seen: Set<string>
): string {
	let chunk = '';
	for (const event of events) {
		const key = event.data.ruleId!;
		if (event.event === 'frame') seen.add(key);
		const value = JSON.stringify(event.data);
		if (sent.get(key) === value) continue;
		sent.set(key, value);
		chunk += `event: ${event.event}\ndata: ${value}\n\n`;
	}
	return chunk || 'event: heartbeat\ndata: {}\n\n';
}

async function readPreview(
	directory: string,
	sourceKey: string,
	rule: LivePreviewRule,
	session: v.InferOutput<typeof sessionSchema> | null
): Promise<PreviewEvent> {
	if (!session)
		return status(rule, 'waiting', 'Waiting for the detector to publish a live picture.');
	if (Date.now() - Date.parse(session.updatedAt) > 6000)
		return status(rule, 'unavailable', 'The detector is no longer publishing live pictures.');
	try {
		const frame = v.parse(
			frameSchema,
			await json(path.join(directory, 'frames', `${sourceKey}.${rule.id}.json`))
		);
		if (frame.runId !== session.runId)
			return status(rule, 'waiting', 'Waiting for a picture from the current detector run.');
		if (frame.sourceKey !== sourceKey || frame.ruleId !== rule.id)
			return status(rule, 'unavailable', 'The live picture does not match this camera and rule.');
		const age = Date.now() - Date.parse(frame.publishedAt);
		if (age < -5000 || age > Math.max(15000, rule.interval * 3000 + 5000))
			return status(
				rule,
				'unavailable',
				'No recent analyzed picture. Check the camera and monitoring status.'
			);
		return { event: 'frame', data: { ...frame, ruleLabel: rule.label } };
	} catch (error) {
		return missing(error)
			? status(rule, 'waiting', 'Waiting for this rule to analyze a picture.')
			: status(rule, 'unavailable', 'The live picture could not be read.');
	}
}

/** Read only the latest records. Slow clients skip intermediate frames instead of accumulating them. */
export function createLivePreviewStream(
	directory: string,
	sourceKey: string,
	rules: LivePreviewRule[],
	signal: AbortSignal
): ReadableStream<Uint8Array> {
	const encoder = new TextEncoder();
	let close: (cancelled?: boolean) => Promise<void> = async () => {};
	return new ReadableStream({
		start(controller) {
			const lease = acquireLease(path.join(directory, 'leases', `${sourceKey}.json`));
			const sent = new Map<string, string>();
			const seen = new Set<string>();
			let stopped = false;
			let polling = false;
			let runId: string | undefined;
			const timer = setInterval(() => void poll(), 500);
			const abort = () => void close();
			close = async (cancelled = false) => {
				if (stopped) return;
				stopped = true;
				clearInterval(timer);
				signal.removeEventListener('abort', abort);
				if (!cancelled) controller.close();
				try {
					await lease.release();
				} catch (error) {
					console.error('Could not remove live preview lease', error);
				}
			};
			async function poll() {
				if (stopped || polling || (controller.desiredSize ?? 0) <= 0) return;
				polling = true;
				try {
					lease.check();
					const session = await readSession(directory);
					if (session && runId && session.runId !== runId) {
						// Reconnecting resolves current camera sources and rule labels after a restart.
						await close();
						return;
					}
					if (session) runId = session.runId;
					const events = await Promise.all(
						rules.map((rule) =>
							!session && seen.has(rule.id)
								? status(rule, 'unavailable', 'The detector is no longer publishing live pictures.')
								: readPreview(directory, sourceKey, rule, session)
						)
					);
					if (stopped) return;
					controller.enqueue(encoder.encode(changedEvents(events, sent, seen)));
				} catch (error) {
					if (stopped) return;
					console.error('Live detection preview unavailable', error);
					const data: LivePreviewStatus = {
						version: 1,
						state: 'unavailable',
						message: 'Live detection preview is unavailable. Close it and try again.'
					};
					controller.enqueue(encoder.encode(`event: status\ndata: ${JSON.stringify(data)}\n\n`));
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
