/** Adding a camera must retain every camera that already uses this recipient. */
export function recipientCameraIds(
	cameras: { id: string; alerts: string[]; monitored: boolean }[],
	label: string,
	additionalCamera?: string | null
): string[] {
	return cameras
		.filter(
			(camera) =>
				camera.monitored && (camera.alerts.includes(label) || camera.id === additionalCamera)
		)
		.map((camera) => camera.id);
}
