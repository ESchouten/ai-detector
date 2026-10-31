import { ConfigurationError } from '../configuration.ts';
import { phoneAlarmUrl } from '../phone-alarm.ts';

/** Rings the phone like a detection does, so the person can hear whether it wakes them. */
export async function sendPhoneAlarmTest(topic: string): Promise<void> {
	let response: Response;
	try {
		response = await fetch(phoneAlarmUrl(topic), {
			method: 'POST',
			headers: { Title: 'AI Detector', Priority: 'urgent', Tags: 'rotating_light' },
			body: testMessage(),
			signal: AbortSignal.timeout(15_000)
		});
	} catch {
		throw new ConfigurationError(
			'Could not reach ntfy. Check the internet connection of this computer.'
		);
	}
	if (!response.ok)
		throw new ConfigurationError(
			`The ntfy server did not accept the test alarm (status ${response.status}).`
		);
}

function testMessage(): string {
	return 'Test alarm. This is how a detection sounds.';
}
