import path from 'node:path';
import { BoundedLog } from './bounded-log.ts';

export { readLogTail } from './bounded-log.ts';

export class DetectorLog extends BoundedLog {
	constructor(directory: string) {
		super(path.join(directory, 'logs', 'application.log'));
	}

	async resume(): Promise<void> {
		await this.restore();
		this.append(`${new Date().toISOString()} Resuming monitoring after application startup\n`);
	}

	begin(): void {
		this.clear();
		this.append(`${new Date().toISOString()} Starting monitoring\n`);
	}
}
