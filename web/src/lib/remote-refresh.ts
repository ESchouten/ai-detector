import type { RemoteQuery } from '@sveltejs/kit';

/**
 * Fetches again what a change affected. A command's `.updates(...)` asks the server to send it
 * back, which SvelteKit now only does for queries the command itself accepts; remote handlers here
 * never import each other's queries, so pages refresh them after the command instead.
 */
export async function refresh(...queries: RemoteQuery<unknown>[]): Promise<void> {
	await Promise.all(queries.map((query) => query.refresh()));
}
