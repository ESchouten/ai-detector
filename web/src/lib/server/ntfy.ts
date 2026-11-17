import { ConfigurationError } from '../configuration.ts';
import { phoneAlarmUrl } from '../phone-alarm.ts';

async function publish(topic: string, text: string, priority: 'urgent' | 'default') {
	const tags = priority === 'urgent' ? 'rotating_light' : 'video_camera';
	let response: Response;
	try {
		response = await fetch(phoneAlarmUrl(topic), {
			method: 'POST',
			headers: { Title: 'AI Detector', Priority: priority, Tags: tags },
			body: text,
			signal: AbortSignal.timeout(15_000)
		});
	} catch {
		throw new ConfigurationError(
			'Could not reach ntfy. Check the internet connection of this computer.'
		);
	}
	if (!response.ok)
		throw new ConfigurationError(
			`The ntfy server did not accept the message (status ${response.status}).`
		);
}

/** Rings the phone like a detection does, so the person can hear whether it wakes them. */
export function sendPhoneAlarmTest(topic: string): Promise<void> {
	return publish(topic, testMessage(), 'urgent');
}

/** A message of the application's own, such as a camera that is no longer watched: no alarm. */
export function sendNtfyNotice(topic: string, text: string): Promise<void> {
	return publish(topic, text, 'default');
}

function testMessage(): string {
	return 'Test alarm. This is how a detection sounds.';
}
