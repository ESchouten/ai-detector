export type SetupStep = 'cameras' | 'detectors' | 'finish';

export function setupStep(
	requested: string | null,
	cameraCount: number,
	detectorCount: number
): SetupStep {
	if (!cameraCount) return 'cameras';
	if (requested === 'cameras' || requested === 'detectors' || requested === 'finish')
		return requested;
	return detectorCount ? 'finish' : 'detectors';
}
