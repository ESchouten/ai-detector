import assert from 'node:assert/strict';
import { test } from 'node:test';
import { error } from '@sveltejs/kit';
import { errorMessage } from '../src/lib/remote-errors.ts';

test('remote HttpError responses preserve actionable server guidance in the browser', () => {
	try {
		error(400, 'Check the camera power and network.');
	} catch (cause) {
		assert.equal(errorMessage(cause, 'Try again.'), 'Check the camera power and network.');
	}
	assert.equal(
		errorMessage(new Error('Network interrupted.'), 'Try again.'),
		'Network interrupted.'
	);
	assert.equal(errorMessage(null, 'Try again.'), 'Try again.');
});
