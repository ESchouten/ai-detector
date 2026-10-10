import { json, type RequestHandler } from '@sveltejs/kit';
import * as v from 'valibot';
import { connectCamera, CameraConnectionError } from '$lib/server/cameras';

const checkInput = v.object({ source: v.pipe(v.string(), v.trim(), v.minLength(1)) });

export const POST: RequestHandler = async ({ request }) => {
	try {
		const input = v.safeParse(checkInput, await request.json());
		if (!input.success)
			return json(
				{ message: 'Choose a camera stream before checking its picture.' },
				{ status: 400 }
			);
		const result = await connectCamera(input.output.source, request.signal);
		return json(result, { headers: { 'Cache-Control': 'no-store' } });
	} catch (cause) {
		if (request.signal.aborted) return new Response(null, { status: 499 });
		if (cause instanceof CameraConnectionError)
			return json({ message: cause.message }, { status: 400 });
		if (cause instanceof SyntaxError)
			return json(
				{ message: 'The camera check request was not valid. Please try again.' },
				{ status: 400 }
			);
		throw cause;
	}
};
