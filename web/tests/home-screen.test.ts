import assert from 'node:assert/strict';
import { test } from 'node:test';
import { holdsOnlyShortcut, lacksHomeScreenIcon } from '../src/lib/home-screen.ts';

const iphone =
	'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1';
const mac =
	'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15';
const android =
	'Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36';
const windows =
	'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const device = (userAgent: string, maxTouchPoints = 0, standalone = false) => ({
	userAgent,
	maxTouchPoints,
	standalone
});

test('a phone or tablet is offered the home screen, a computer is not', () => {
	assert.equal(lacksHomeScreenIcon(device(iphone, 5)), true);
	// An iPad says it is a Mac; only its touch screen tells them apart.
	assert.equal(lacksHomeScreenIcon(device(mac, 5)), true);
	assert.equal(lacksHomeScreenIcon(device(android, 5)), true);
	assert.equal(lacksHomeScreenIcon(device(mac)), false);
	// A Windows laptop with a touch screen is still a computer.
	assert.equal(lacksHomeScreenIcon(device(windows, 10)), false);
});

test('nothing is offered once the application was opened from the home screen', () => {
	assert.equal(lacksHomeScreenIcon(device(iphone, 5, true)), false);
	assert.equal(lacksHomeScreenIcon(device(android, 5, true)), false);
});

test('Android over plain HTTP can only hold a shortcut', () => {
	assert.equal(holdsOnlyShortcut({ userAgent: android, secure: false }), true);
	assert.equal(holdsOnlyShortcut({ userAgent: android, secure: true }), false);
	// An iPhone makes the page an app over plain HTTP too.
	assert.equal(holdsOnlyShortcut({ userAgent: iphone, secure: false }), false);
});
