import { setTimeout as wait } from 'node:timers/promises';
import * as v from 'valibot';
import { recentMoment } from '../format.ts';
import type { RuntimeStatus } from '../runtime.ts';
import type { Configuration, TelegramConfig } from '../schema.ts';
import { RuntimeProgress } from './runtime-status.ts';
import { serialQueue } from './serial.ts';
import { sourceKey } from './source-key.ts';

/** How long a camera may go unwatched before the people who get its alerts are told. */
const UNNOTICED = 5 * 60000;
/** A camera has returned once it was watched this long; one that comes and goes has not. */
const SETTLED = 60000;
/** Longer than this between two samples, and the computer slept or the application did not run. */
const INTERRUPTED = 30000;
/** After such an interruption, cameras get this long to return before their absence is news. */
const WAKING = 2 * 60000;

export type Recipient = Pick<TelegramConfig, 'token' | 'chat' | 'quiet'>;

export interface WatchedCamera {
	id: string;
	label: string;
	watched: boolean;
	recipients: Recipient[];
}

export interface OutageNotice {
	recipient: Recipient;
	text: string;
	/** The cameras this notice warns about, by id. */
	stopped: string[];
}

const savedOutages = v.record(v.string(), v.pipe(v.string(), v.isoTimestamp()));
/** What a later run needs: each camera people were warned about, and since when it is away. */
export type SavedOutages = v.InferOutput<typeof savedOutages>;

interface Outage {
	camera: WatchedCamera;
	since: number;
	/** When the camera was first seen watched again. */
	until?: number;
	/** A warning was made for it. */
	told: boolean;
	/** That warning reached someone. */
	sent: boolean;
}

function chat(recipient: Recipient): string {
	return `${recipient.token}\n${recipient.chat}`;
}

/** The cameras the detectors watch, whether each is watched now, and who gets its alerts. */
export function watchedCameras(
	{ config, app }: Configuration,
	status: RuntimeStatus,
	directory: string
): WatchedCamera[] {
	const recipients = new Map<string, Recipient[]>();
	for (const detector of config.detectors)
		for (const source of detector.detection.source) {
			const key = sourceKey(source, directory);
			recipients.set(key, [
				...(recipients.get(key) ?? []),
				...(detector.exporters?.telegram ?? [])
			]);
		}
	// The status loses its cameras while the detector restarts; the settings name them as it does.
	const configured = new RuntimeProgress();
	configured.configure(config, app, directory);
	const watched = new Set(
		status.cameras
			.filter((camera) => camera.state === 'monitoring')
			.map((camera) => camera.sourceKey)
	);
	return configured.snapshot().cameras.map((camera) => ({
		id: camera.id,
		label: camera.label,
		watched: watched.has(camera.sourceKey),
		recipients: recipients.get(camera.sourceKey)!
	}));
}

function wording(stopped: Outage[], returned: Outage[], still: Outage[], now: number): string {
	const names = (outages: Outage[]) => outages.map((outage) => outage.camera.label).join(', ');
	const moment = (at: number) => recentMoment(at, new Date(now));
	const lines: string[] = [];
	// Cameras that stopped at the same moment are told about in one sentence.
	for (const since of new Set(returned.map((outage) => outage.since))) {
		const together = returned.filter((outage) => outage.since === since);
		const until = Math.max(...together.map((outage) => outage.until!));
		const back = `Watched again: ${names(together)}. Not watched from ${moment(since)} to ${moment(until)}.`;
		lines.push(/* @wc-ignore */ `✅ ${back}`);
	}
	if (stopped.length) {
		const since = Math.min(...stopped.map((outage) => outage.since));
		const away = `Not watched: ${names(stopped)} (since ${moment(since)}). Open AI Detector to see why.`;
		lines.push(/* @wc-ignore */ `⚠️ ${away}`);
	}
	if (still.length) lines.push(`Still not watched: ${names(still)}.`);
	return lines.join('\n');
}

/** One message for everyone who gets the alerts of a camera that stopped or returned. */
function notices(
	stopped: Outage[],
	returned: Outage[],
	still: Outage[],
	now: number
): OutageNotice[] {
	const recipients = new Map<string, Recipient>();
	for (const outage of [...stopped, ...returned])
		for (const recipient of outage.camera.recipients)
			if (!recipients.has(chat(recipient))) recipients.set(chat(recipient), recipient);
	return Array.from(recipients, ([key, recipient]) => {
		const theirs = (outages: Outage[]) =>
			outages.filter((outage) =>
				outage.camera.recipients.some((recipient) => chat(recipient) === key)
			);
		return {
			recipient,
			text: wording(theirs(stopped), theirs(returned), theirs(still), now),
			stopped: theirs(stopped).map((outage) => outage.camera.id)
		};
	});
}

/**
 * Tells the people who get a camera's alerts when it has not been watched for five minutes, and
 * when it is watched again. Time in which the application itself did not run counts as unwatched.
 */
export class OutageAlerts {
	private readonly outages = new Map<string, Outage>();
	private sampledAt: number | undefined;
	private wakingUntil = 0;

	/**
	 * `kept` is what an earlier run of the application left, and `lastRunning` the last moment it
	 * is known to have lived.
	 */
	constructor(kept: SavedOutages = {}, lastRunning?: number) {
		this.sampledAt = lastRunning;
		for (const [id, since] of Object.entries(kept))
			this.outages.set(id, {
				// Its name and recipients come with the first sample that lists it.
				camera: { id, label: id, watched: false, recipients: [] },
				since: Date.parse(since),
				told: true,
				sent: true
			});
	}

	/** What to keep for a later run: the outages whose warning reached someone. */
	get kept(): SavedOutages {
		return Object.fromEntries(
			Array.from(this.outages)
				.filter(([, outage]) => outage.sent)
				.map(([id, outage]) => [id, new Date(outage.since).toISOString()])
		);
	}

	delivered(notice: OutageNotice): void {
		for (const id of notice.stopped) {
			const outage = this.outages.get(id);
			if (outage) outage.sent = true;
		}
	}

	/** Takes the cameras that should be watched at this moment: none while monitoring is paused. */
	sample(cameras: WatchedCamera[], now: number): OutageNotice[] {
		this.observe(cameras, now);
		const outages = Array.from(this.outages.values());
		const stopped = outages.filter(
			(outage) =>
				!outage.told &&
				outage.until === undefined &&
				now - outage.since >= UNNOTICED &&
				now >= this.wakingUntil
		);
		for (const outage of stopped) outage.told = true;
		const returning = outages.filter((outage) => outage.until !== undefined);
		const settled = returning.filter((outage) => now - outage.until! >= SETTLED);
		// Cameras return one after another and are told about together, but nobody waits longer
		// than another minute for one that comes and goes.
		const returned =
			settled.length === returning.length ||
			settled.some((outage) => now - outage.until! >= 2 * SETTLED)
				? settled
				: [];
		for (const outage of returned) this.outages.delete(outage.camera.id);
		// An interruption nobody was told about and that stayed short is not worth a message.
		const reported = returned.filter(
			(outage) => outage.told || outage.until! - outage.since >= UNNOTICED
		);
		// Warned about earlier and not back for good: that includes one that comes and goes.
		const still = outages.filter(
			(outage) => outage.told && !stopped.includes(outage) && !returned.includes(outage)
		);
		return notices(stopped, reported, still, now);
	}

	/** Starts, continues and forgets outages as the cameras are seen now. */
	private observe(cameras: WatchedCamera[], now: number): void {
		const before = this.sampledAt ?? now;
		this.sampledAt = now;
		const away = now - before >= UNNOTICED;
		if (now - before > INTERRUPTED) this.wakingUntil = now + WAKING;
		const expected = new Map(cameras.map((camera) => [camera.id, camera]));
		for (const [id, outage] of this.outages) {
			const camera = expected.get(id);
			if (camera) {
				outage.camera = camera;
				outage.until = camera.watched ? (outage.until ?? now) : undefined;
			}
			// While monitoring is paused, a camera someone was warned about is still owed its return.
			// A camera that was removed is not.
			else if (cameras.length || !outage.told) this.outages.delete(id);
			else outage.until = undefined;
		}
		for (const camera of cameras)
			if (!this.outages.has(camera.id) && (away || !camera.watched))
				this.outages.set(camera.id, {
					camera,
					since: before,
					until: camera.watched ? now : undefined,
					told: false,
					sent: false
				});
	}
}

/** Whether a recipient's alerts arrive without sound at this moment, as the detector decides it. */
function quiet(hours: Recipient['quiet'], at: Date): boolean {
	if (!hours) return false;
	const time = at.toTimeString().slice(0, 5);
	return hours.start <= hours.end
		? hours.start <= time && time < hours.end
		: time >= hours.start || time < hours.end;
}

/**
 * Sends each recipient their notices in order. What stops the cameras often stops the internet
 * too, so a notice that cannot be sent is tried again every minute, for a day. `failed` hears of
 * the first attempt that fails.
 */
export function outageDelivery(
	send: (recipient: Recipient, text: string, silent: boolean) => Promise<void>,
	failed: (error: unknown) => void,
	pause: () => Promise<unknown> = () => wait(60000, undefined, { ref: false })
): (notice: OutageNotice) => Promise<void> {
	const queues = new Map<string, ReturnType<typeof serialQueue>>();
	return ({ recipient, text }) => {
		const queue = queues.get(chat(recipient)) ?? serialQueue();
		queues.set(chat(recipient), queue);
		return queue(async () => {
			for (let attempt = 1; ; attempt++)
				try {
					return await send(recipient, text, quiet(recipient.quiet, new Date()));
				} catch (error) {
					if (attempt === 1) failed(error);
					if (attempt === 24 * 60) throw error;
					await pause();
				}
		});
	};
}

export interface OutageWatch {
	/** The detector's supervisor: whether monitoring is switched on, and what is watched now. */
	monitored: { readonly monitoring: boolean; status(): RuntimeStatus };
	/** The data folder, against which the detector resolves a local source. */
	directory: string;
	/** What an earlier run noted, as it was read, and how to note it for the next. */
	noted: unknown;
	note(outages: SavedOutages): Promise<void>;
	settings(): Promise<Configuration>;
	send(recipient: Recipient, text: string, silent: boolean): Promise<void>;
	warn(message: string, error: unknown): void;
}

/**
 * Gives back what to do every ten seconds: take a sample, send what it brings and note what
 * people were told for the next start. `known` are the settings as read at the start.
 * `lastRunning` is the last moment an earlier run lived, given only when monitoring was switched
 * on then.
 */
export function outageWatch(
	watch: OutageWatch,
	known: Configuration | undefined,
	lastRunning: number | undefined
): () => void {
	// A note that cannot be read is no memory at all.
	const noted = v.safeParse(savedOutages, watch.noted);
	let outages = new OutageAlerts(noted.success ? noted.output : {}, lastRunning);
	let enabled: boolean | undefined;
	let generation = 0;
	let written = JSON.stringify(outages.kept);
	const keep = () => {
		const kept = JSON.stringify(outages.kept);
		if (kept === written) return;
		written = kept;
		watch
			.note(outages.kept)
			.catch((error) =>
				watch.warn(/* @wc-ignore */ 'Could not note the outages for the next start', error)
			);
	};
	const delivery = () => {
		const current = generation;
		return outageDelivery(
			async (...args) => {
				// Switching off also cancels queued retries, including after a later switch on.
				if (current === generation && known?.app.notifyCameraOutages === true)
					await watch.send(...args);
			},
			(error) =>
				watch.warn(
					/* @wc-ignore */ 'Could not send an outage notice through Telegram; trying each minute',
					error
				)
		);
	};
	let deliver = delivery();
	return () => {
		if (known) {
			const next = known.app.notifyCameraOutages === true;
			if (!next && enabled !== false) {
				generation++;
				outages = new OutageAlerts();
			} else if (next && enabled === false) deliver = delivery();
			enabled = next;
			const cameras = watch.monitored.monitoring
				? watchedCameras(known, watch.monitored.status(), watch.directory)
				: [];
			const current = generation;
			for (const notice of next ? outages.sample(cameras, Date.now()) : [])
				deliver(notice).then(
					() => {
						if (current !== generation || known?.app.notifyCameraOutages !== true) return;
						outages.delivered(notice);
						keep();
					},
					() => undefined
				);
			keep();
		}
		// Unreadable settings are reported on every page; the cameras last known still count.
		void watch.settings().then(
			(latest) => (known = latest),
			() => undefined
		);
	};
}
