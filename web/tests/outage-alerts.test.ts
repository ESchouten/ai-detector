import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { recentMoment, timeOfDay } from '../src/lib/format.ts';
import type { RuntimeStatus } from '../src/lib/runtime.ts';
import type { Configuration } from '../src/lib/schema.ts';
import {
	OutageAlerts,
	outageDelivery,
	outageWatch,
	watchedCameras,
	type Recipient,
	type SavedOutages,
	type WatchedCamera
} from '../src/lib/server/outage-alerts.ts';
import { sourceKey } from '../src/lib/server/source-key.ts';

/** Two o'clock at night on this computer, whatever its time zone. */
const start = new Date(2026, 9, 12, 2, 0).getTime();
const farmer: Recipient = { token: 'fixture-token', chat: '1' };
const vet: Recipient = { token: 'fixture-token', chat: '2' };

function camera(label: string, watched: boolean, recipients = [farmer]): WatchedCamera {
	return { id: label, label, watched, recipients };
}

/**
 * Samples every ten seconds, as the application does; `at` is in seconds after two o'clock.
 * Telegram takes every notice at once, unless `arrives` says otherwise.
 */
function follow(
	alerts: OutageAlerts,
	from: number,
	to: number,
	cameras: (at: number) => WatchedCamera[],
	arrives = true
) {
	const notices: { at: number; chat: string; text: string }[] = [];
	for (let at = from; at <= to; at += 10)
		for (const notice of alerts.sample(cameras(at), start + at * 1000)) {
			if (arrives) alerts.delivered(notice);
			notices.push({ at, chat: notice.recipient.chat, text: notice.text });
		}
	return notices;
}

const at = (seconds: number) => timeOfDay(start + seconds * 1000);
const stopped = (names: string, since: number) =>
	`⚠️ Not watched: ${names} (since ${at(since)}). Open AI Detector to see why.`;
const returned = (names: string, from: number, to: number) =>
	`✅ Watched again: ${names}. Not watched from ${at(from)} to ${at(to)}.`;

test('five minutes without being watched is reported once, and so is the return', () => {
	const notices = follow(new OutageAlerts(), 0, 3600, (at) => [
		camera('Calving pen', at === 0 || at >= 1200)
	]);
	assert.deepEqual(notices, [
		{ at: 300, chat: '1', text: stopped('Calving pen', 0) },
		{ at: 1260, chat: '1', text: returned('Calving pen', 0, 1200) }
	]);
});

test('an interruption shorter than five minutes is not reported', () => {
	// Last seen watched at 590 seconds and seen again at 880: ten seconds short.
	const restart = follow(new OutageAlerts(), 0, 3600, (at) => [
		camera('Calving pen', at < 600 || at >= 880)
	]);
	assert.deepEqual(restart, []);
});

test('cameras that return one after another are reported together, with those still away', () => {
	const notices = follow(new OutageAlerts(), 0, 3600, (at) => [
		camera('Calving pen', at === 0 || at >= 1200),
		camera('Dry cows', at === 0 || at >= 1220),
		camera('Barn', at === 0)
	]);
	assert.deepEqual(notices, [
		{ at: 300, chat: '1', text: stopped('Calving pen, Dry cows, Barn', 0) },
		{
			at: 1280,
			chat: '1',
			text: `${returned('Calving pen, Dry cows', 0, 1220)}\nStill not watched: Barn.`
		}
	]);
});

test('a camera that comes and goes has not returned', () => {
	// Watched for thirty seconds in every two minutes, as when the detector freezes after each start.
	const notices = follow(new OutageAlerts(), 0, 1800, (at) => [
		camera('Calving pen', at === 0 || (at >= 120 && at % 120 < 30) || at >= 1200)
	]);
	assert.deepEqual(notices, [
		{ at: 300, chat: '1', text: stopped('Calving pen', 0) },
		{ at: 1260, chat: '1', text: returned('Calving pen', 0, 1200) }
	]);
});

test('cameras that come and go do not hold back the return of another', () => {
	// Yard and Gate each miss one sample a minute, half a minute apart, all night.
	const notices = follow(new OutageAlerts(), 0, 3600, (at) => [
		camera('Calving pen', at >= 1200),
		camera('Yard', at % 60 !== 0),
		camera('Gate', at % 60 !== 30)
	]);
	assert.deepEqual(notices, [
		{ at: 300, chat: '1', text: stopped('Calving pen, Yard', 0) },
		{
			at: 330,
			chat: '1',
			text: `${stopped('Gate', 20)}\nStill not watched: Calving pen, Yard.`
		},
		{
			at: 1320,
			chat: '1',
			text: `${returned('Calving pen', 0, 1200)}\nStill not watched: Yard, Gate.`
		}
	]);
});

test('everyone hears about the cameras whose alerts they get, and a later stop names the earlier one', () => {
	const notices = follow(new OutageAlerts(), 0, 1200, (at) => [
		camera('Calving pen', at === 0, [farmer]),
		camera('Dry cows', at < 600, [farmer, vet])
	]);
	assert.deepEqual(notices, [
		{ at: 300, chat: '1', text: stopped('Calving pen', 0) },
		{
			at: 890,
			chat: '1',
			text: `${stopped('Dry cows', 590)}\nStill not watched: Calving pen.`
		},
		{ at: 890, chat: '2', text: stopped('Dry cows', 590) }
	]);
});

test('pausing is not an outage, but a camera someone was warned about still gets its return', () => {
	const unnoticed = new OutageAlerts();
	follow(unnoticed, 0, 120, (at) => [camera('Calving pen', at === 0)]);
	// Paused before anyone was told, for ten minutes, and watched from the start again.
	assert.deepEqual(
		follow(unnoticed, 130, 730, () => []),
		[]
	);
	assert.deepEqual(
		follow(unnoticed, 740, 1400, () => [camera('Calving pen', true)]),
		[]
	);

	const warned = new OutageAlerts();
	const before = follow(warned, 0, 600, (at) => [camera('Calving pen', at === 0)]);
	assert.deepEqual(before, [{ at: 300, chat: '1', text: stopped('Calving pen', 0) }]);
	assert.deepEqual(
		follow(warned, 610, 1200, () => []),
		[]
	);
	assert.deepEqual(
		follow(warned, 1210, 1400, () => [camera('Calving pen', true)]),
		[{ at: 1270, chat: '1', text: returned('Calving pen', 0, 1210) }]
	);
});

test('a camera that is removed takes its outage with it', () => {
	const alerts = new OutageAlerts();
	const cameras = (at: number) => [camera('Calving pen', at === 0), camera('Barn', true)];
	assert.equal(follow(alerts, 0, 600, cameras).length, 1);
	const later = follow(alerts, 610, 3600, () => [camera('Barn', true)]);
	assert.deepEqual(later, []);
	assert.deepEqual(alerts.kept, {});
});

test('time the computer slept is reported once, when the cameras are back', () => {
	const alerts = new OutageAlerts();
	follow(alerts, 0, 60, () => [camera('Calving pen', true)]);
	const hours = 3 * 3600;
	const notices = follow(alerts, hours, hours + 600, (at) => [
		camera('Calving pen', at >= hours + 20)
	]);
	assert.deepEqual(notices, [
		{ at: hours + 80, chat: '1', text: returned('Calving pen', 60, hours + 20) }
	]);
});

test('a camera that stays away after the computer woke is reported two minutes later', () => {
	const alerts = new OutageAlerts();
	follow(alerts, 0, 60, () => [camera('Calving pen', true)]);
	const hours = 3 * 3600;
	const notices = follow(alerts, hours, hours + 600, () => [camera('Calving pen', false)]);
	assert.deepEqual(notices, [{ at: hours + 120, chat: '1', text: stopped('Calving pen', 60) }]);
});

test('time the application was not running counts, and another day is named', () => {
	const evening = start - 4 * 3600 * 1000;
	const notices = follow(new OutageAlerts({}, evening), 0, 600, (at) => [
		camera('Calving pen', at >= 30)
	]);
	const since = recentMoment(evening, new Date(start));
	assert.match(since, /Sun/);
	assert.deepEqual(notices, [
		{
			at: 90,
			chat: '1',
			text: `✅ Watched again: Calving pen. Not watched from ${since} to ${at(30)}.`
		}
	]);
	// Closed for a minute, as for an update: the cameras were away too briefly to mention.
	assert.deepEqual(
		follow(new OutageAlerts({}, start - 60000), 0, 600, (at) => [camera('Calving pen', at >= 30)]),
		[]
	);
});

test('a start that takes almost five minutes is reported once it is over, not while it lasts', () => {
	// Stopped 260 seconds before two o'clock; the detector needs a minute to watch again.
	const notices = follow(new OutageAlerts({}, start - 260000), 0, 600, (at) => [
		camera('Calving pen', at >= 60)
	]);
	assert.deepEqual(notices, [{ at: 120, chat: '1', text: returned('Calving pen', -260, 60) }]);
});

test('a restart of the application keeps what people were told', () => {
	const away = (until: number) => (at: number) => [camera('Barn', at === 0 || at >= until)];
	const first = new OutageAlerts();
	assert.deepEqual(follow(first, 0, 1800, away(Infinity)), [
		{ at: 300, chat: '1', text: stopped('Barn', 0) }
	]);
	assert.deepEqual(first.kept, { Barn: new Date(start).toISOString() });

	// Back two minutes later with Barn still away: no second warning, and the true start.
	const stillAway = new OutageAlerts(first.kept, start + 1800000);
	assert.deepEqual(follow(stillAway, 1920, 3600, away(3000)), [
		{ at: 3060, chat: '1', text: returned('Barn', 0, 3000) }
	]);
	assert.deepEqual(stillAway.kept, {});

	// Or the restart cured it: the people who were warned hear that too.
	const cured = new OutageAlerts(first.kept, start + 1800000);
	assert.deepEqual(follow(cured, 1920, 3600, away(1940)), [
		{ at: 2000, chat: '1', text: returned('Barn', 0, 1940) }
	]);
});

test('only a warning that arrived is kept, so one that did not is given again after a restart', () => {
	const away = (at: number) => [camera('Barn', at === 0)];
	// Not yet five minutes: nothing to remember.
	const short = new OutageAlerts();
	assert.deepEqual(follow(short, 0, 240, away), []);
	assert.deepEqual(short.kept, {});

	// Telegram could not be reached before the application stopped.
	const unheard = new OutageAlerts();
	assert.equal(follow(unheard, 0, 600, away, false).length, 1);
	assert.deepEqual(unheard.kept, {});
	const again = new OutageAlerts(unheard.kept, start + 600000);
	assert.deepEqual(follow(again, 660, 1200, away), [
		{ at: 900, chat: '1', text: stopped('Barn', 600) }
	]);
});

test('a notice that cannot be sent is tried again each minute, and later notices wait their turn', async () => {
	const sent: string[] = [];
	const failures: unknown[] = [];
	let refusals = 3;
	let pauses = 0;
	const deliver = outageDelivery(
		async (recipient, text) => {
			if (recipient.chat === '1' && refusals-- > 0) throw new Error('No internet');
			sent.push(`${recipient.chat}: ${text}`);
		},
		(error) => failures.push(error),
		async () => void pauses++
	);
	await Promise.all([
		deliver({ recipient: farmer, text: 'stopped', stopped: [] }),
		deliver({ recipient: farmer, text: 'returned', stopped: [] }),
		deliver({ recipient: vet, text: 'stopped', stopped: [] })
	]);
	assert.deepEqual(sent, ['2: stopped', '1: stopped', '1: returned']);
	assert.equal(pauses, 3);
	// Said once, at the first attempt that failed.
	assert.equal(failures.length, 1);
});

test('a notice is given up after a day, and the next one is still sent', async () => {
	let attempts = 0;
	const sent: string[] = [];
	const deliver = outageDelivery(
		async (_recipient, text) => {
			if (text === 'stopped') {
				attempts++;
				throw new Error('Chat not found');
			}
			sent.push(text);
		},
		() => undefined,
		async () => undefined
	);
	const first = deliver({ recipient: farmer, text: 'stopped', stopped: [] });
	const second = deliver({ recipient: farmer, text: 'returned', stopped: [] });
	await assert.rejects(first, /Chat not found/);
	await second;
	assert.equal(attempts, 24 * 60);
	assert.deepEqual(sent, ['returned']);
});

test('a notice arrives without sound in the quiet hours of its recipient', async (t) => {
	const silent: boolean[] = [];
	const deliver = outageDelivery(
		async (_recipient, _text, quiet) => void silent.push(quiet),
		() => undefined
	);
	const night: Recipient = { ...farmer, quiet: { start: '22:00', end: '06:00' } };
	const midday: Recipient = { ...farmer, quiet: { start: '12:00', end: '13:00' } };
	t.mock.timers.enable({ apis: ['Date'], now: start });
	for (const recipient of [night, midday, farmer])
		await deliver({ recipient, text: 'stopped', stopped: [] });
	t.mock.timers.setTime(new Date(2026, 9, 12, 12, 30).getTime());
	for (const recipient of [night, midday])
		await deliver({ recipient, text: 'stopped', stopped: [] });
	assert.deepEqual(silent, [true, false, false, false, true]);
});

test('the cameras to watch come from the settings, also while the status has lost them', () => {
	const directory = '/data';
	const sources = ['rtsp://calving.local/live', 'rtsp://barn.local/live'];
	const configuration = {
		config: {
			detectors: [
				{ detection: { source: sources }, exporters: { telegram: [farmer] } },
				{ detection: { source: [sources[1]] }, exporters: { telegram: [vet] } }
			]
		},
		app: {
			streams: [
				{ id: 'camera-a', label: 'Calving pen', source: sources[0] },
				{ id: 'camera-b', label: 'Barn', source: sources[1] }
			],
			telegrams: [],
			llms: [],
			detectors: []
		}
	};
	const status: RuntimeStatus = {
		managed: true,
		phase: 'running',
		message: '',
		dataDirectory: directory,
		readiness: 'degraded',
		// The running detector may know a camera under another id than the settings read now.
		cameras: [
			{
				id: 'another-id',
				label: 'Calving pen',
				sourceKey: sourceKey(sources[0], directory),
				state: 'monitoring',
				lastFrameAt: null
			},
			{
				id: 'camera-b',
				label: 'Barn',
				sourceKey: sourceKey(sources[1], directory),
				state: 'offline',
				lastFrameAt: null
			}
		]
	};
	const expected = [
		{ id: 'camera-a', label: 'Calving pen', watched: true, recipients: [farmer] },
		{ id: 'camera-b', label: 'Barn', watched: false, recipients: [farmer, vet] }
	];
	assert.deepEqual(watchedCameras(configuration, status, directory), expected);
	// Waiting to restart, the detector lists no cameras at all.
	assert.deepEqual(
		watchedCameras(configuration, { ...status, phase: 'starting', cameras: [] }, directory),
		expected.map((camera) => ({ ...camera, watched: false }))
	);
});

/** One camera watched by one detector whose alerts go to the farmer, and a detector to answer for it. */
function watching(t: TestContext, lastRunning?: number, known = true) {
	const directory = '/data';
	const source = 'rtsp://barn.local/live';
	const settings = {
		config: {
			detectors: [{ detection: { source: [source] }, exporters: { telegram: [farmer] } }]
		},
		app: {
			streams: [{ id: 'barn', label: 'Barn', source }],
			telegrams: [],
			llms: [],
			detectors: []
		}
	} as Configuration;
	const state = { monitoring: true, watched: false };
	const sent: string[] = [];
	/** What was noted for the next start, each time it changed. */
	const notes: SavedOutages[] = [];
	const watch = (noted?: unknown) =>
		outageWatch(
			{
				monitored: {
					get monitoring() {
						return state.monitoring;
					},
					status: () => ({
						managed: true,
						phase: 'running',
						message: '',
						dataDirectory: directory,
						readiness: 'connecting',
						cameras: state.watched
							? [
									{
										id: 'barn',
										label: 'Barn',
										sourceKey: sourceKey(source, directory),
										state: 'monitoring',
										lastFrameAt: null
									}
								]
							: []
					})
				},
				directory,
				noted,
				note: async (outages) => void notes.push(outages),
				settings: async () => settings,
				send: async (_recipient, text) => void sent.push(text),
				warn: (message) => assert.fail(message)
			},
			known ? settings : undefined,
			lastRunning
		);
	t.mock.timers.enable({ apis: ['Date'], now: start });
	/** Samples every ten seconds for this long, letting what each sample started finish. */
	async function run(sample: () => void, seconds: number) {
		for (let passed = 0; passed < seconds; passed += 10) {
			sample();
			await new Promise((resolve) => setImmediate(resolve));
			t.mock.timers.tick(10000);
		}
	}
	return { state, sent, notes, watch, run };
}

test('the watch warns, notes what it told through a pause and a restart, and reports the return', async (t) => {
	const { state, sent, notes, watch, run } = watching(t);
	await run(watch(), 310);
	assert.deepEqual(sent, [stopped('Barn', 0)]);
	assert.deepEqual(notes, [{ barn: new Date(start).toISOString() }]);

	// The application is started again with that note: nobody is warned a second time.
	const restarted = watch(notes[0]);
	await run(restarted, 400);
	assert.equal(sent.length, 1);

	// Paused and switched on again, with the camera watched from then on.
	state.monitoring = false;
	await run(restarted, 60);
	state.monitoring = true;
	state.watched = true;
	await run(restarted, 80);
	assert.deepEqual(sent, [stopped('Barn', 0), returned('Barn', 0, 770)]);
	assert.deepEqual(notes, [{ barn: new Date(start).toISOString() }, {}]);
});

test('a note that cannot be read is no memory: the watch warns as if nothing was told', async (t) => {
	const { sent, watch, run } = watching(t);
	for (const noted of ['', 5, ['barn'], { barn: 'midnight' }, { barn: start }]) {
		sent.length = 0;
		await run(watch(noted), 310);
		assert.deepEqual(
			sent.map((text) => text.slice(0, 14)),
			['⚠️ Not watched'],
			JSON.stringify(noted)
		);
	}
});

test('the watch waits for settings it can read before it counts the time it was not running', async (t) => {
	const evening = start - 4 * 3600 * 1000;
	const { state, sent, watch, run } = watching(t, evening, false);
	state.watched = true;
	await run(watch(), 100);
	assert.deepEqual(sent, [
		`✅ Watched again: Barn. Not watched from ${recentMoment(evening, new Date(start))} to ${at(10)}.`
	]);
});
