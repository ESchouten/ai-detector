import { errorMessage } from './remote-errors.ts';
import type {
	TelegramPairing as TelegramPairingSession,
	TelegramRecipient,
	TelegramPairingState as PairingResult
} from './telegram.ts';
export type TelegramPairingState =
	| { state: 'idle' | 'starting' }
	| { state: 'waiting'; session: TelegramPairingSession }
	| { state: 'matched'; chat: TelegramRecipient; bot: TelegramPairingSession['bot'] }
	| { state: 'failed'; message: string };

interface PairingApi {
	begin(input: { token: string }): Promise<TelegramPairingSession>;
	poll(input: { id: string }): Promise<PairingResult>;
	cancel(input: { id: string }): Promise<unknown>;
}

/** One local pairing attempt; abandoning it also retires late responses and server sessions. */
export class TelegramPairing {
	private api: PairingApi;
	private changed: (state: TelegramPairingState) => void;
	private generation = 0;
	private session: TelegramPairingSession | undefined;
	private timer: ReturnType<typeof setTimeout> | undefined;
	private cancelling: Promise<unknown> = Promise.resolve();

	constructor(api: PairingApi, changed: (state: TelegramPairingState) => void) {
		this.api = api;
		this.changed = changed;
	}

	async start(token: string): Promise<void> {
		this.cancel();
		const generation = this.generation;
		this.changed({ state: 'starting' });
		try {
			await this.cancelling;
			if (generation !== this.generation) return;
			const session = await this.api.begin({ token });
			if (generation !== this.generation) {
				await this.api.cancel({ id: session.id });
				return;
			}
			this.session = session;
			this.changed({ state: 'waiting', session });
			this.schedule(generation);
		} catch (cause) {
			if (generation === this.generation) this.fail(cause);
		}
	}

	cancel(): Promise<unknown> {
		this.generation++;
		clearTimeout(this.timer);
		this.release();
		this.changed({ state: 'idle' });
		return this.cancelling;
	}

	private release(): void {
		const session = this.session;
		this.session = undefined;
		if (session) {
			// Navigation can outlive the connection; the server also expires abandoned sessions.
			this.cancelling = this.api.cancel({ id: session.id }).catch(() => undefined);
		}
	}

	private schedule(generation: number): void {
		this.timer = setTimeout(() => void this.poll(generation), 2000);
	}

	private async poll(generation: number): Promise<void> {
		const session = this.session;
		if (!session || generation !== this.generation) return;
		if (Date.now() >= session.expiresAt) {
			this.fail(new Error('This connection link expired. Choose Connect my bot to try again.'));
			return;
		}
		try {
			const result = await this.api.poll({ id: session.id });
			if (generation !== this.generation) return;
			if (result.state === 'matched') {
				this.release();
				this.changed({ state: 'matched', chat: result.chat, bot: session.bot });
			} else this.schedule(generation);
		} catch (cause) {
			if (generation === this.generation) this.fail(cause);
		}
	}

	private fail(cause: unknown): void {
		this.release();
		this.changed({
			state: 'failed',
			message: errorMessage(cause, 'Telegram could not connect. Try again.')
		});
	}
}
