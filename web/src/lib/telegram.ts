export interface TelegramRecipient {
	id: string;
	name: string;
}

export interface TelegramPairing {
	id: string;
	bot: { name: string; username: string };
	url: string;
	expiresAt: number;
	qrDataUrl: string;
}

export type TelegramPairingState =
	| { state: 'waiting' }
	| { state: 'matched'; chat: TelegramRecipient };
