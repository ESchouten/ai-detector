import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readDetectorChoices, writeDetectorChoices } from '../src/lib/detector-draft-storage.ts';

const choices = {
	label: 'Barn',
	preset: 'activity',
	cameras: ['camera-id'],
	telegrams: ['Phone'],
	connection: 'Validator',
	validatorEnabled: true
};

test('draft choices survive reopening and can be discarded; invalid drafts start fresh', () => {
	const values = new Map<string, string>();
	const storage = () => ({
		getItem: (key: string) => values.get(key) ?? null,
		setItem: (key: string, value: string) => {
			values.set(key, value);
		},
		removeItem: (key: string) => {
			values.delete(key);
		}
	});
	writeDetectorChoices('draft', choices, storage);
	assert.deepEqual(readDetectorChoices('draft', storage), choices);
	writeDetectorChoices('draft', null, storage);
	assert.equal(readDetectorChoices('draft', storage), null);
	for (const invalid of ['{broken', 'null', '{"label":42}']) {
		values.set('draft', invalid);
		assert.equal(readDetectorChoices('draft', storage), null);
	}
});

test('unavailable storage and quota errors cannot interrupt editing, saving or discarding', () => {
	const denied = () => {
		throw new DOMException('Storage disabled', 'SecurityError');
	};
	const full = () => ({
		getItem: () => JSON.stringify(choices),
		setItem: () => {
			throw new DOMException('Full', 'QuotaExceededError');
		},
		removeItem: denied
	});
	assert.equal(readDetectorChoices('draft', denied), null);
	for (const storage of [denied, full]) {
		assert.doesNotThrow(() => writeDetectorChoices('draft', choices, storage));
		assert.doesNotThrow(() => writeDetectorChoices('draft', null, storage));
	}
});
