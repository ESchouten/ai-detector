import { createServer } from 'node:http';
import { DesktopInstance } from '../instance.ts';

/** Answers the instance's control requests over HTTP, as the desktop runtime does. */
export function instanceServer(instance: DesktopInstance, quit: () => void) {
	return createServer(async (request, response) => {
		const result =
			instance.respond(
				new Request(`http://localhost${request.url}`, {
					method: request.method,
					headers: request.headers as Record<string, string>
				}),
				quit
			) ?? new Response(null, { status: 404 });
		response.writeHead(result.status, Object.fromEntries(result.headers));
		response.end(await result.text());
	});
}

// Run by itself, it is the owner process a test asks to quit.
if (import.meta.main) {
	const instance = new DesktopInstance(process.env.TEST_DATA!);
	const server = instanceServer(instance, () => {
		// The real runtime also keeps the owner process alive after HTTP closes
		// while accepted detections finish validation and export.
		server.close();
		setTimeout(() => process.disconnect(), 250);
	});
	server.listen(0, '127.0.0.1', () => {
		const port = (server.address() as { port: number }).port;
		instance.publish(port);
		process.send!({ port });
	});
	process.once('exit', () => {
		instance.completeShutdown(process.env.FAIL_SHUTDOWN !== 'true');
		instance.remove();
	});
}
