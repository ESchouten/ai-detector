import { createServer } from 'node:http';
import { DesktopInstance } from '../instance.ts';
const instance = new DesktopInstance(process.env.TEST_DATA!);
const server = createServer(async (request, response) => {
	const result = instance.respond(
		new Request(`http://localhost${request.url}`, {
			method: request.method,
			headers: request.headers as Record<string, string>
		}),
		() => {
			// The real runtime also keeps the owner process alive after HTTP closes
			// while accepted detections finish validation and export.
			server.close();
			setTimeout(() => process.disconnect(), 250);
		}
	)!;
	response.writeHead(result.status, Object.fromEntries(result.headers));
	response.end(await result.text());
});
server.listen(0, '127.0.0.1', () => {
	const port = (server.address() as { port: number }).port;
	instance.publish(port);
	process.send!({ port });
});
process.once('exit', () => instance.remove());
