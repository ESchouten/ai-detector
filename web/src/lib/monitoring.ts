import { plural } from './format.ts';
import type { RuntimeStatus } from './runtime.ts';

export type StatusTone = 'ok' | 'busy' | 'warn' | 'bad' | 'idle';
export type MonitoringAction = 'start' | 'retry' | 'cancel' | 'pause';

export interface MonitoringSummary {
	tone: StatusTone;
	/** The state in two or three words, for navigation and headings. */
	label: string;
	/** One sentence saying what the state means or what to do next. */
	detail: string;
	/** Worth interrupting every page for: detection is not protecting the cameras. */
	attention: boolean;
	action: MonitoringAction | null;
}

type Runtime = Pick<
	RuntimeStatus,
	'managed' | 'phase' | 'readiness' | 'message' | 'preparation' | 'cameras' | 'issues'
>;

/** Cameras that are analysed and recorded right now. */
function monitoredCount(runtime: Pick<RuntimeStatus, 'cameras'>): number {
	return runtime.cameras.filter(
		(camera) => camera.state === 'monitoring' && !camera.error && !camera.recordingError
	).length;
}

function problem(runtime: Runtime): string {
	const offline = runtime.cameras.filter((camera) => camera.state === 'offline').length;
	if (offline) return plural(offline, ['# camera offline.', '# cameras offline.']);
	const camera = runtime.cameras.find((camera) => camera.recordingError || camera.error);
	if (camera) return `${camera.label}: ${camera.recordingError ?? camera.error}`;
	return runtime.issues?.[0] ?? runtime.message;
}

/** States in which the detector's own progress says nothing useful. */
function unavailable(
	runtime: Runtime,
	{ stale, configured }: { stale: boolean; configured: boolean }
): MonitoringSummary | undefined {
	if (stale)
		return {
			tone: 'warn',
			label: 'Connection lost',
			detail: 'This page has not heard from AI Detector. Reopen the app if it does not reconnect.',
			attention: true,
			action: null
		};
	if (!configured)
		return {
			tone: 'idle',
			label: 'Live view only',
			detail: 'Add a detector to start monitoring your cameras.',
			attention: false,
			action: null
		};
	if (!runtime.managed)
		return {
			tone: 'idle',
			label: 'Runs separately',
			detail: 'Detection is started and stopped outside this app, so its status is not shown here.',
			attention: false,
			action: null
		};
}

/** The process is not running, or is on its way up or down. */
function lifecycle(runtime: Runtime): MonitoringSummary | undefined {
	if (runtime.phase === 'stopping')
		return {
			tone: 'busy',
			label: 'Stopping…',
			detail: runtime.message,
			attention: false,
			action: null
		};
	if (runtime.phase === 'failed' || runtime.readiness === 'failed')
		return {
			tone: 'bad',
			label: 'Monitoring stopped',
			detail: runtime.message,
			attention: true,
			action: 'retry'
		};
	if (runtime.phase === 'checking' || runtime.phase === 'starting')
		return {
			tone: 'busy',
			label: 'Starting…',
			detail: runtime.preparation ?? runtime.message,
			attention: false,
			action: runtime.phase === 'checking' ? 'cancel' : null
		};
	if (runtime.phase === 'stopped')
		return {
			tone: 'warn',
			label: 'Paused',
			detail: 'Nothing is detected or recorded while monitoring is paused.',
			attention: true,
			action: 'start'
		};
}

/** One reading of the detector's state, shared by navigation, banners and the status page. */
export function monitoringSummary(
	runtime: Runtime,
	scope: { stale: boolean; configured: boolean }
): MonitoringSummary {
	const special = unavailable(runtime, scope) ?? lifecycle(runtime);
	if (special) return special;
	if (runtime.readiness === 'degraded')
		return {
			tone: 'warn',
			label: 'Needs attention',
			detail: problem(runtime),
			attention: true,
			action: 'pause'
		};
	if (runtime.readiness === 'monitoring')
		return {
			tone: 'ok',
			label: 'Monitoring',
			detail: plural(monitoredCount(runtime), ['Watching # camera.', 'Watching # cameras.']),
			attention: false,
			action: 'pause'
		};
	return {
		tone: 'busy',
		label: runtime.readiness === 'connecting' ? 'Connecting cameras…' : 'Preparing…',
		detail: runtime.preparation ?? runtime.message,
		attention: false,
		action: 'pause'
	};
}
