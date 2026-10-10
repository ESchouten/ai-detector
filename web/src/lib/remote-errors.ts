import { isHttpError } from '@sveltejs/kit';

/** Remote commands throw SvelteKit HttpError; local failures use ordinary Error. */
export function errorMessage(cause: unknown, fallback: string): string {
	if (isHttpError(cause)) return cause.body.message;
	return cause instanceof Error ? cause.message : fallback;
}
