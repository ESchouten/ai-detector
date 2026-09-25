import assert from 'node:assert/strict';
import { test } from 'node:test';
import { TelegramPairing, type TelegramPairingState } from '../src/lib/telegram-pairing.ts';
import type {
	TelegramPairing as Session,
	TelegramPairingState as PollResult
} from '../src/lib/telegram.ts';
import { recipientDetectorLabels } from '../src/lib/alert-recipients.ts';

const flush = () => new Promise<void>((resolve) => setImmediate(resolve));
const session = (id: string): Session => ({
	id,
	bot: { name: 'Farm', username: 'farm_bot' },
	url: 'https://t.me/farm_bot?start=fixture',
	expiresAt: Date.now() + 300000,
	qrDataUrl: 'data:image/png;base64,fixture'
});

test('recipient selections distinguish detectors that watch the same cameras', () => {
	const recipient = { label: 'Phone', token: 'token', chat: 'chat' };
	const detectors = [
		{
			meta: { label: 'Calving' },
			detector: { detection: { source: ['barn', 'yard'] }, exporters: { telegram: [recipient] } }
		},
		{ meta: { label: 'Mounting' }, detector: { detection: { source: ['barn'] } } },
		{
			meta: { label: 'Gate' },
			detector: { detection: { source: ['gate'] }, exporters: { telegram: [recipient] } }
		}
	];
	const original = structuredClone(detectors);
	assert.deepEqual(recipientDetectorLabels(detectors, recipient), ['Calving', 'Gate']);
	assert.deepEqual(recipientDetectorLabels(detectors, recipient, 'Mounting'), [
		'Calving',
		'Mounting',
		'Gate'
	]);
	assert.deepEqual(recipientDetectorLabels(detectors, undefined, 'Mounting'), ['Mounting']);
	assert.deepEqual(detectors, original);
});

test('abandoning a pending begin cancels its eventual server session without updating the screen', async (t) => {
	t.mock.timers.enable({ apis: ['setTimeout'] });
	const begin = Promise.withResolvers<Session>();
	const cancelled: string[] = [];
	const states: TelegramPairingState[] = [];
	const pairing = new TelegramPairing(
		{
			begin: () => begin.promise,
			poll: async () => {
				assert.fail('Abandoned pairing must not poll');
			},
			cancel: async ({ id }) => {
				cancelled.push(id);
			}
		},
		(state) => states.push(state)
	);
	const starting = pairing.start('fixture-token');
	await flush();
	await pairing.cancel();
	begin.resolve(session('late-session'));
	await starting;
	t.mock.timers.tick(10000);
	assert.deepEqual(cancelled, ['late-session']);
	assert.deepEqual(states.at(-1), { state: 'idle' });
	assert.ok(!states.some((state) => state.state === 'waiting'));
});

test('navigation or switching to manual setup retires an in-flight poll result', async (t) => {
	t.mock.timers.enable({ apis: ['setTimeout'] });
	const poll = Promise.withResolvers<PollResult>();
	const states: TelegramPairingState[] = [];
	const cancelled: string[] = [];
	const pairing = new TelegramPairing(
		{
			begin: async () => session('pending-poll'),
			poll: () => poll.promise,
			cancel: async ({ id }) => {
				cancelled.push(id);
			}
		},
		(state) => states.push(state)
	);
	await pairing.start('fixture-token');
	t.mock.timers.tick(2000);
	await pairing.cancel();
	poll.resolve({ state: 'matched', chat: { id: '123', name: 'Old recipient' } });
	await flush();
	assert.deepEqual(states.at(-1), { state: 'idle' });
	assert.ok(!states.some((state) => state.state === 'matched'));
	assert.deepEqual(cancelled, ['pending-poll']);
});

test('a matched phone stops polling and releases the session exactly once', async (t) => {
	t.mock.timers.enable({ apis: ['setTimeout'] });
	const states: TelegramPairingState[] = [];
	let polls = 0;
	const cancelled: string[] = [];
	const pairing = new TelegramPairing(
		{
			begin: async () => session('match'),
			poll: async () => {
				polls++;
				return { state: 'matched', chat: { id: '123', name: 'Farmer' } };
			},
			cancel: async ({ id }) => {
				cancelled.push(id);
			}
		},
		(state) => states.push(state)
	);
	await pairing.start('fixture-token');
	t.mock.timers.tick(2000);
	await flush();
	t.mock.timers.tick(20000);
	assert.equal(polls, 1);
	assert.deepEqual(states.at(-1), {
		state: 'matched',
		chat: { id: '123', name: 'Farmer' },
		bot: { name: 'Farm', username: 'farm_bot' }
	});
	await pairing.cancel();
	assert.deepEqual(cancelled, ['match']);
});

test('slow polling does not overlap and replacing a session waits for cancellation', async (t) => {
	t.mock.timers.enable({ apis: ['setTimeout'] });
	const firstPoll = Promise.withResolvers<PollResult>();
	const cancellation = Promise.withResolvers<void>();
	let polls = 0;
	const beginnings: string[] = [];
	const pairing = new TelegramPairing(
		{
			begin: async ({ token }) => {
				beginnings.push(token);
				return session(token);
			},
			poll: () => {
				polls++;
				return firstPoll.promise;
			},
			cancel: () => cancellation.promise
		},
		() => {}
	);
	await pairing.start('first');
	t.mock.timers.tick(2000);
	t.mock.timers.tick(10000);
	assert.equal(polls, 1);
	const replacing = pairing.start('second');
	await flush();
	assert.deepEqual(beginnings, ['first']);
	cancellation.resolve();
	await replacing;
	assert.deepEqual(beginnings, ['first', 'second']);
	firstPoll.resolve({ state: 'waiting' });
	await flush();
	await pairing.cancel();
	t.mock.timers.tick(10000);
	assert.equal(polls, 1);
});

test('expired pairing links stop locally and offer a fresh connection', async (t) => {
	t.mock.timers.enable({ apis: ['setTimeout'] });
	const states: TelegramPairingState[] = [];
	const cancelled: string[] = [];
	const pairing = new TelegramPairing(
		{
			begin: async () => ({ ...session('expired'), expiresAt: Date.now() - 1 }),
			poll: async () => {
				assert.fail('Expired pairing must not poll');
			},
			cancel: async ({ id }) => {
				cancelled.push(id);
			}
		},
		(state) => states.push(state)
	);
	await pairing.start('fixture-token');
	t.mock.timers.tick(2000);
	await flush();
	const last = states.at(-1);
	assert.ok(last?.state === 'failed');
	assert.match(last.message, /expired.*Connect my bot/);
	assert.deepEqual(cancelled, ['expired']);
});
