export class SetupError extends Error {
	readonly helpUrl?: string;
	constructor(message: string, helpUrl?: string) {
		super(message);
		this.helpUrl = helpUrl;
	}
}
