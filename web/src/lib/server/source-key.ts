import { createHash } from 'node:crypto';
import path from 'node:path';

/**
 * The detector's name for a camera in status records and live pictures: the SHA-256 of its
 * source, with a local file resolved against the settings folder. It follows the source, unlike
 * a camera's saved id, which survives a changed address.
 */
export function sourceKey(source: string, settingsDirectory: string): string {
	const resolved = /^(?:[a-z]+:\/\/|\d+$)/i.test(source)
		? source
		: path.resolve(settingsDirectory, source);
	return createHash('sha256').update(resolved).digest('hex');
}
