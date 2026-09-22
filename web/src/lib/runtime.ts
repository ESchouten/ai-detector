export type RuntimeMode = 'auto' | 'native' | 'docker';
export type RuntimePhase = 'stopped' | 'checking' | 'starting' | 'running' | 'stopping' | 'failed';

export interface RuntimeStatus {
	managed: boolean;
	mode: RuntimeMode;
	selected: 'native' | 'docker' | null;
	phase: RuntimePhase;
	message: string;
	helpUrl?: string;
	logs: string;
	dataDirectory: string;
}
