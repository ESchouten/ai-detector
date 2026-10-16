import { isHttpError, type RemoteQuery } from '@sveltejs/kit';

/** Remote commands throw SvelteKit HttpError; local failures use ordinary Error. */
export function errorMessage(cause: unknown, fallback: string): string {
	if (isHttpError(cause)) return cause.body.message;
	return cause instanceof Error ? cause.message : fallback;
}

/**
 * Fetches again what a change affected. A command sends back only the queries it accepts with
 * `.updates(...)`, and remote handlers here never import each other's queries, so pages refresh
 * them after the command instead.
 */
export async function refresh(...queries: RemoteQuery<unknown>[]): Promise<void> {
	await Promise.all(queries.map((query) => query.refresh()));
}
