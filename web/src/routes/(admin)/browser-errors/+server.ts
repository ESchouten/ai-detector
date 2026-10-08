import type { RequestHandler } from '@sveltejs/kit';
import * as v from 'valibot';
import { webLog } from '$lib/server/web-log';

const report = v.object({
	message: v.pipe(v.string(), v.maxLength(1000)),
	stack: v.optional(v.pipe(v.string(), v.maxLength(6000)), ''),
	page: v.pipe(v.string(), v.maxLength(300))
});
/** A page that keeps failing must not fill the log. */
const PER_MINUTE = 20;
let minute = 0;
let written = 0;

// What goes wrong in the browser is invisible to the server; pages report it here so a
// diagnostics download shows it.
export const POST: RequestHandler = async ({ request, url }) => {
	if (request.headers.get('origin') !== url.origin) return new Response(null, { status: 403 });
	const input = v.safeParse(report, await request.json().catch(() => null));
	if (!input.success) return new Response(null, { status: 400 });
	const now = Math.floor(Date.now() / 60000);
	if (now !== minute) [minute, written] = [now, 0];
	if (written++ < PER_MINUTE) {
		const { message, stack, page } = input.output;
		webLog.warn(/* @wc-ignore */ `Browser error on ${page}: ${message}\n${stack}`);
	}
	return new Response(null, { status: 204 });
};
