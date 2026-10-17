import assert from 'node:assert/strict';
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { startServer } from '../production/server.mjs';
import { fakeTelegram, GROUP, PHONE } from './fake-telegram.mjs';
import { rtspCamera } from './rtsp-camera.mjs';

const detector = fileURLToPath(new URL('../../../detector/.venv/bin/aidetector', import.meta.url));
const reports = fileURLToPath(new URL('../../.reports/', import.meta.url));
const token = '123456:e2e-test-token';
const MINUTE = 60_000;

/** Waits until `check` holds; the detector needs minutes to prepare its model on a CI runner. */
async function until(check, timeout, what) {
	const deadline = Date.now() + timeout;
	while (!check()) {
		if (Date.now() > deadline) throw new Error(`Timed out waiting for ${what}`);
		await new Promise((resolve) => setTimeout(resolve, 250));
	}
}

/** The local time `minutes` from now, as the quiet hours fields take it. */
function clock(minutes) {
	const time = new Date(Date.now() + minutes * MINUTE);
	return [time.getHours(), time.getMinutes()]
		.map((part) => String(part).padStart(2, '0'))
		.join(':');
}

test(
	'a farmer sets up Cow Catcher with two Telegram recipients, and both get the mounting it sees',
	{ timeout: 15 * MINUTE },
	async (t) => {
		const telegram = await fakeTelegram(t);
		const camera = await rtspCamera(t);
		const { directory, base, logs } = await startServer(t, {
			env: { AIDETECTOR_EXECUTABLE: detector, ...telegram.env }
		});
		const browser = await chromium.launch({ channel: 'chrome' });
		t.after(() => browser.close());
		const page = await browser.newPage();
		page.setDefaultTimeout(30_000);
		const alerts = (chat) =>
			telegram.calls.filter(
				({ method, payload }) =>
					method.startsWith('send') && payload.chat_id === String(chat) && payload.caption
			);
		try {
			// Setup starts with the cameras: the barn camera, by its stream address. The address field
			// opens by itself once the network search finds no camera, as on a CI runner.
			await page.goto(base);
			const address = page.locator('#camera-stream');
			const instead = page.getByRole('button', { name: 'Enter a stream URL instead' });
			await address.or(instead).waitFor({ timeout: MINUTE });
			if (await instead.isVisible()) await instead.click();
			await address.fill(camera);
			await page.getByRole('button', { name: 'Connect camera' }).click();
			await page.locator('#camera-name-0').fill('Barn');
			await page.getByRole('button', { name: 'Add 1 camera' }).click();

			// Cow Catcher watches the only camera; Phone is connected from the detector editor.
			await page.getByText('Cow Catcher', { exact: true }).click();
			await page.getByRole('button', { name: 'Connect Telegram' }).click();
			const dialog = page.getByRole('dialog');
			await dialog.locator('#notification-token').fill(token);
			await dialog.getByRole('button', { name: 'Connect Telegram' }).click();
			const link = await dialog.getByRole('link', { name: 'Open Telegram' }).getAttribute('href');
			telegram.start(token, new URL(link).searchParams.get('start'));
			await dialog.locator('#notification-label').fill('Phone');
			await dialog.getByRole('button', { name: 'Use this recipient' }).click();
			await page.getByRole('button', { name: 'Save detector' }).click();

			// Monitoring starts once the detector has its model and analyses the camera.
			await page.getByRole('button', { name: 'Start monitoring' }).click();
			await page.waitForURL(/\/detections$/, { timeout: 10 * MINUTE });

			// Barn group: the same bot, its chat ID typed in, quiet for the next hour.
			await page.goto(`${base}/notifications/add`);
			await page.getByRole('button', { name: 'Enter chat ID manually' }).click();
			await page.locator('#notification-chat').fill(String(GROUP));
			await page.getByRole('button', { name: 'Send test alert' }).click();
			// Ticking it confirms the test alert, and the box makes way for the name.
			await page.locator('#alert-received').click();
			await page.locator('#notification-label').fill('Barn group');
			// The only detector is already ticked for a new recipient.
			await page.getByRole('checkbox', { name: 'Cow Catcher' }).check();
			await page.locator('#quiet-start').fill(clock(-60));
			await page.locator('#quiet-end').fill(clock(60));
			await page.getByRole('button', { name: 'Save recipient' }).click();
			await page.waitForURL(/\/notifications$/);

			// The clip shows a mounting every time it loops.
			await until(() => alerts(PHONE).length && alerts(GROUP).length, 5 * MINUTE, 'both alerts');
		} catch (error) {
			// Kept for CI to upload: what the page showed, and what the application logged.
			await mkdir(reports, { recursive: true });
			await page.screenshot({ path: path.join(reports, 'e2e-failure.png'), fullPage: true });
			await writeFile(path.join(reports, 'e2e-application.log'), logs());
			await cp(path.join(directory, 'logs'), path.join(reports, 'e2e-logs'), { recursive: true });
			const calls = telegram.calls.map(({ method, payload }) => ({
				method,
				chat: payload.chat_id
			}));
			await writeFile(path.join(reports, 'e2e-telegram.json'), JSON.stringify(calls, null, '\t'));
			throw error;
		}

		const config = JSON.parse(await readFile(path.join(directory, 'config.json'), 'utf8'));
		const app = JSON.parse(await readFile(path.join(directory, 'app.json'), 'utf8'));
		assert.deepEqual(app.detectors[0], {
			label: 'Cow Catcher',
			preset: 'cow-catcher',
			presetVersion: app.detectors[0].presetVersion
		});
		// Cow Catcher sets nothing for Telegram, so each recipient has only its own settings.
		const quiet = config.detectors[0].exporters.telegram[1].quiet;
		assert.deepEqual(config.detectors[0].exporters.telegram, [
			{ token, chat: String(PHONE) },
			{ token, chat: String(GROUP), quiet }
		]);
		for (const [chat, silent] of [
			[PHONE, 'false'],
			[GROUP, 'true']
		]) {
			const [alert] = alerts(chat);
			assert.equal(alert.method, 'sendVideo');
			assert.equal(alert.payload.video.type, 'video/mp4');
			assert.match(alert.payload.caption, /^\d+%\n\d+ second\(s\)$/);
			assert.equal(alert.payload.disable_notification, silent);
			assert.match(alert.payload.reply_markup, /review:.+:approved/);
		}
	}
);
