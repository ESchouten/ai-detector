/** One actual analyzed frame, with coordinates in the included image's pixels. */
export interface LivePreviewFrame {
	version: 1;
	runId: string;
	sourceKey: string;
	ruleId: string;
	ruleLabel: string;
	capturedAt: string;
	publishedAt: string;
	image: { width: number; height: number; jpeg: string };
	boxes: {
		x1: number;
		y1: number;
		x2: number;
		y2: number;
		label: string | null;
		confidence: number | null;
		trackId: number | null;
	}[];
}

export interface LivePreviewStatus {
	version: 1;
	state: 'waiting' | 'unavailable';
	message: string;
	ruleId?: string;
	ruleLabel?: string;
}
