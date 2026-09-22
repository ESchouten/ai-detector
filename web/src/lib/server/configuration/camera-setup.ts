import { createHash } from 'node:crypto';
import { ConfigurationError, sameTelegram } from '../../configuration.ts';
import type { Configuration, DetectorConfig } from '../../schema.ts';

function completionSignature(source: string, rules: DetectorConfig[]): string {
	return createHash('sha256')
		.update(JSON.stringify([source, rules]))
		.digest('hex');
}

export function cameraArchiveSelection(document: Configuration, id: string) {
	const camera = document.app.streams.find((item) => item.id === id);
	if (!camera) throw new ConfigurationError('This camera no longer exists.');
	const rules = document.config.detectors.filter((rule) =>
		rule.detection.source.includes(camera.source)
	);
	const categories = [
		...new Set(
			rules.flatMap((rule) =>
				(rule.exporters?.disk ?? []).map(
					(value) => (value as { directory?: string | null }).directory ?? ''
				)
			)
		)
	].sort();
	const signature = createHash('sha256')
		.update(JSON.stringify([camera.source, categories]))
		.digest('hex');
	return { camera, rules, categories, signature };
}

export function cameraSetupStatus(document: Configuration, id: string) {
	const { camera, rules, categories, signature } = cameraArchiveSelection(document, id);
	const alerts = document.app.telegrams
		.filter((channel) =>
			rules.some((rule) => rule.exporters?.telegram?.some((item) => sameTelegram(item, channel)))
		)
		.map((channel) => channel.label);
	const archiveVerifiedAt =
		camera.setup?.archiveSignature === signature ? camera.setup.archiveVerifiedAt : undefined;
	const pictureVerifiedAt = camera.setup?.pictureVerifiedAt;
	const alertsSkipped = camera.setup?.alerts === 'skipped';
	const monitored = rules.length > 0;
	const readyToFinish =
		!!pictureVerifiedAt &&
		(!monitored ||
			((!categories.length || !!archiveVerifiedAt) && (alerts.length > 0 || alertsSkipped)));
	return {
		id,
		label: camera.label ?? 'Camera',
		monitored,
		pictureVerifiedAt,
		archiveVerifiedAt,
		archiveDestinations: categories.length,
		alerts,
		alertsSkipped,
		completedAt:
			readyToFinish &&
			camera.setup?.completionSignature === completionSignature(camera.source, rules)
				? camera.setup.completedAt
				: undefined,
		readyToFinish
	};
}

export function recordArchiveCheck(
	document: Configuration,
	id: string,
	signature: string,
	verifiedAt: string
): void {
	const selected = cameraArchiveSelection(document, id);
	if (selected.signature !== signature)
		throw new ConfigurationError(
			'Camera settings changed during the recording check. Check the recording location again.'
		);
	selected.camera.setup = {
		...selected.camera.setup,
		archiveSignature: signature,
		archiveVerifiedAt: verifiedAt
	};
}

export function skipCameraAlerts(document: Configuration, id: string): void {
	const { camera } = cameraArchiveSelection(document, id);
	camera.setup = { ...camera.setup, alerts: 'skipped' };
}

export function finishCameraSetup(document: Configuration, id: string, monitoring: boolean): void {
	const status = cameraSetupStatus(document, id);
	if (!status.readyToFinish)
		throw new ConfigurationError(
			'Confirm the picture, check the recording location and choose whether to connect alerts before finishing.'
		);
	if (status.monitored && !monitoring)
		throw new ConfigurationError(
			'Monitoring has not been verified yet. Start monitoring and wait for the camera to process pictures before finishing.'
		);
	const { camera, rules } = cameraArchiveSelection(document, id);
	camera.setup = {
		...camera.setup,
		completedAt: new Date().toISOString(),
		completionSignature: completionSignature(camera.source, rules)
	};
}
