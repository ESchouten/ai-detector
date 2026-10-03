import type { RuntimeStatus } from './runtime.ts';

type Monitoring = Pick<RuntimeStatus, 'managed' | 'phase' | 'readiness' | 'identification'>;

/** Explain the next useful action without mistaking missing photos for missing setup. */
export function herdEmptyState(configured: boolean, runtime: Monitoring, stale: boolean) {
	if (!configured)
		return {
			title: 'Start recognizing your cows',
			description:
				'Add a Cow Identity detector and choose a camera where cows are clearly separated. Start monitoring to collect photos you can name.'
		};
	if (!runtime.managed || stale)
		return {
			title: 'Waiting for monitoring status',
			description:
				'Your identity detector is saved. Open AI Detector on the monitoring computer to check its status.'
		};
	if (runtime.phase === 'stopped')
		return {
			title: 'Ready to collect cow photos',
			description: 'Your identity detector is saved. Start monitoring above to collect photos.'
		};
	if (runtime.phase === 'stopping')
		return {
			title: 'Monitoring is stopping',
			description: 'Start monitoring again when you want to collect more cow photos.'
		};
	if (runtime.phase === 'failed')
		return {
			title: 'Monitoring needs attention',
			description:
				'Your identity detector is saved. Check the monitoring details above to see what needs attention.'
		};
	const identification = runtime.identification ?? [];
	if (identification.some((identity) => identity.state === 'failed'))
		return {
			title: 'Cow identification needs attention',
			description:
				'Camera detection can continue, but an identity detector cannot currently suggest names. Check its message above and open Logs for details.'
		};
	if (runtime.readiness === 'degraded')
		return {
			title: 'Monitoring needs attention',
			description:
				'Your identity detector is saved. Check the monitoring details above to see what needs attention.'
		};
	if (
		['checking', 'starting'].includes(runtime.phase) ||
		['preparing', 'connecting'].includes(runtime.readiness)
	)
		return {
			title: 'Getting ready to collect photos',
			description:
				'Monitoring is starting. Preparation and camera connection progress appear above; the first start can take longer.'
		};
	if (identification.some((identity) => identity.state === 'preparing'))
		return {
			title: 'Preparing cow identification',
			description:
				'Photos can still be collected while the model and confirmed examples are prepared. Each identity detector shows its progress above.'
		};
	if (identification.length && identification.every((identity) => identity.state === 'collecting'))
		return {
			title: 'Collecting your first cow photos',
			description:
				'Keep a clear view of separated cows and refresh photos. Name at least two cows before the app can suggest matches.'
		};
	return {
		title: 'Waiting for clear cow photos',
		description:
			'Keep monitoring running with a clear view of separated cows. Small, overlapping or partly hidden cows are skipped. Refresh photos to check for new examples.'
	};
}
