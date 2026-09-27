export interface ImportSummary {
	id: string;
	source: string;
	destination: string;
	cameras: number;
	detectors: number;
	recordings: number;
	bytes: number;
	recordingBytes: number;
	notes: string[];
}

export interface ImportStatus {
	phase: 'idle' | 'ready' | 'copying' | 'complete' | 'failed';
	summary?: ImportSummary;
	copiedBytes: number;
	totalBytes: number;
	message?: string;
	keepRecordings?: boolean;
	canRestart?: boolean;
}
