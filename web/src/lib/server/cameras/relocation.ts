import type { RuntimeStatus } from '../../runtime.ts';
import type { CameraDevice, Configuration, StreamMeta } from '../../schema.ts';
import { isPhoneAlarm } from '../../phone-alarm.ts';
import { outagesNotified, type OutageRecipient } from '../outage-alerts.ts';
import { sourceKey } from '../source-key.ts';
import { learnDevice, locateCameras, type CameraMove } from './identity.ts';

/** How long a camera goes without pictures before it is looked for at other addresses. */
const LOST = 2 * 60000;
/** The least time between two searches; one search looks for every lost camera at once. */
const SEARCH_INTERVAL = 5 * 60000;
/** How long to wait before asking a camera that told nothing of itself again. */
const RELEARN = 60 * 60000;

export interface RelocationWatch {
	/** The detector's supervisor: whether monitoring is switched on, and what is watched now. */
	monitored: { readonly monitoring: boolean; status(): RuntimeStatus };
	/** The data folder, against which the detector resolves a local source. */
	directory: string;
	settings(): Promise<Configuration>;
	remember(id: string, source: string, device: CameraDevice): Promise<void>;
	/** Saves the moves and gives back those that were made. */
	relocate(moves: CameraMove[]): Promise<CameraMove[]>;
	send(recipient: OutageRecipient, text: string): Promise<void>;
	log(message: string): void;
	warn(message: string, error: unknown): void;
	learn?: (camera: StreamMeta) => Promise<CameraDevice | undefined>;
	locate?: (lost: StreamMeta[]) => Promise<CameraMove[]>;
}

/** The phone alarm, when a detector that watches a camera with this source rings it. */
function recipientsOf({ config, app }: Configuration, source: string): OutageRecipient[] {
	const topic = app.phoneAlarm?.topic;
	if (!topic) return [];
	const rings = config.detectors.some(
		(detector) =>
			detector.detection.source.includes(source) &&
			detector.exporters?.webhook?.some((item) => isPhoneAlarm(item, topic))
	);
	return rings ? [{ topic }] : [];
}

/** One message for each phone alarm that rings for a camera that moved. */
export function relocationNotices(
	settings: Configuration,
	moves: CameraMove[]
): { recipient: OutageRecipient; text: string }[] {
	const recipients = new Map<string, { recipient: OutageRecipient; lines: string[] }>();
	for (const move of moves) {
		const camera = settings.app.streams.find((stream) => stream.id === move.id);
		const label = camera?.label ?? 'Camera';
		const moved = `${label} got a new network address (${move.host}) and is watched there again.`;
		const line = /* @wc-ignore */ `📍 ${moved}`;
		for (const recipient of recipientsOf(settings, move.source)) {
			const entry = recipients.get(recipient.topic) ?? { recipient, lines: [] };
			recipients.set(recipient.topic, entry);
			if (!entry.lines.includes(line)) entry.lines.push(line);
		}
	}
	const tip =
		'Tip: give your cameras a fixed address in your router (a DHCP reservation), so they keep their address.';
	return Array.from(recipients.values(), ({ recipient, lines }) => ({
		recipient,
		text: [...lines, tip].join('\n')
	}));
}

/**
 * Follows cameras whose network address changed, as happens when a router hands out addresses
 * by itself. While a camera is watched, it is asked once what tells it apart. When it has had no
 * pictures for two minutes, the computer's networks are searched for it, and once it is found at
 * exactly one other address, its settings follow it there.
 */
export class CameraRelocation {
	private readonly lostSince = new Map<string, number>();
	private readonly askedAt = new Map<string, number>();
	private searchedAt = -Infinity;
	private busy = false;
	private readonly watch: RelocationWatch;

	constructor(watch: RelocationWatch) {
		this.watch = watch;
	}

	/** Takes a look every ten seconds; a look still busy is not started again. */
	sample(now = Date.now()): Promise<void> {
		if (this.busy) return Promise.resolve();
		this.busy = true;
		return this.look(now)
			.catch((error) =>
				this.watch.warn(/* @wc-ignore */ 'Could not follow cameras to a new address', error)
			)
			.finally(() => {
				this.busy = false;
			});
	}

	private async look(now: number): Promise<void> {
		if (!this.watch.monitored.monitoring) {
			this.lostSince.clear();
			return;
		}
		const settings = await this.watch.settings();
		const { unknown, lost } = this.sort(settings, now);
		for (const camera of unknown) {
			this.askedAt.set(camera.id!, now);
			const device = await (this.watch.learn ?? learnDevice)(camera);
			if (device) await this.watch.remember(camera.id!, camera.source, device);
		}
		if (!lost.length || now - this.searchedAt < SEARCH_INTERVAL) return;
		this.searchedAt = now;
		const found = await (this.watch.locate ?? locateCameras)(lost);
		if (found.length) this.moved(settings, await this.watch.relocate(found));
	}

	/** The watched cameras not yet asked what tells them apart, and those lost long enough. */
	private sort(settings: Configuration, now: number) {
		const { monitored, directory } = this.watch;
		const states = new Map(
			monitored.status().cameras.map((camera) => [camera.sourceKey, camera.state])
		);
		const unknown: StreamMeta[] = [];
		const lost: StreamMeta[] = [];
		for (const camera of settings.app.streams) {
			if (!camera.id) continue;
			const state = states.get(sourceKey(camera.source, directory));
			if (state === 'monitoring' || state === 'receiving') {
				this.lostSince.delete(camera.id);
				if (!camera.device && now - (this.askedAt.get(camera.id) ?? -Infinity) >= RELEARN)
					unknown.push(camera);
			} else if (state === 'offline' || state === 'failed' || state === 'connecting') {
				const since = this.lostSince.get(camera.id) ?? now;
				this.lostSince.set(camera.id, since);
				if (camera.device && now - since >= LOST) lost.push(camera);
			}
			// Paused, or not watched by any detector: nothing to follow.
			else this.lostSince.delete(camera.id);
		}
		return { unknown, lost };
	}

	private moved(settings: Configuration, moves: CameraMove[]): void {
		for (const move of moves) {
			this.lostSince.delete(move.id);
			const from = new URL(move.source).hostname;
			this.watch.log(
				/* @wc-ignore */ `Camera ${move.id.slice(0, 12)} moved from ${from} to ${move.host}`
			);
		}
		if (!outagesNotified(settings.app)) return;
		for (const { recipient, text } of relocationNotices(settings, moves))
			this.watch
				.send(recipient, text)
				.catch((error) =>
					this.watch.warn(/* @wc-ignore */ 'Could not tell through ntfy that a camera moved', error)
				);
	}
}
