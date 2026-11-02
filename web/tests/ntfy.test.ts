import assert from 'node:assert/strict';
import { test } from 'node:test';
import { newPhoneAlarmTopic, phoneAlarmLink } from '../src/lib/phone-alarm.ts';
import { sendNtfyNotice, sendPhoneAlarmTest } from '../src/lib/server/ntfy.ts';

test('a phone alarm topic is long and random, and its link opens ntfy on it', () => {
	const topic = newPhoneAlarmTopic();
	assert.match(topic, /^aidetector-[a-z0-9]{20}$/);
	assert.notEqual(topic, newPhoneAlarmTopic());
	assert.equal(phoneAlarmLink(topic), `ntfy://ntfy.sh/${topic}?display=AI%20Detector`);
});

test('a test alarm rings at the highest priority and a refusal reaches the caller', async (t) => {
	const requests: { url: string; init: RequestInit }[] = [];
	let status = 200;
	t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
		requests.push({ url, init });
		return new Response('{}', { status });
	});
	await sendPhoneAlarmTest('aidetector-fixture');
	assert.equal(requests[0].url, 'https://ntfy.sh/aidetector-fixture');
	assert.equal((requests[0].init.headers as Record<string, string>).Priority, 'urgent');
	status = 429;
	await assert.rejects(sendPhoneAlarmTest('aidetector-fixture'), /status 429/);
});

test('a camera notice goes to the alarm topic as a normal notification, not an alarm', async (t) => {
	let init: RequestInit | undefined;
	t.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit) => {
		init = options;
		return new Response('{}');
	});
	await sendNtfyNotice('aidetector-fixture', '⚠️ Not watched: Barn.');
	assert.equal((init!.headers as Record<string, string>).Priority, 'default');
	assert.equal(init!.body, '⚠️ Not watched: Barn.');
});
