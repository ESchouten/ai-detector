import type { IncomingMessage } from 'node:http';

declare module 'node:http' {
	interface IncomingMessage {
		disconnectSignal?: AbortSignal;
	}
}

declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		interface Platform {
			req: IncomingMessage;
		}
	}
}

export {};
