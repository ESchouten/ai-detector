import { openDashboard, reportFailure } from './browser.ts';
import { connectDesktopHost } from './host.ts';
import { DesktopInstance } from './instance.ts';
import { advertiseDashboard } from './network.ts';
import { dataDirectory } from './paths.ts';

type Handler = (request: Request, server: Bun.Server<undefined>) => Response | Promise<Response>;

/** Bind before initializing SvelteKit: only the port owner may start monitoring. */
export async function startDesktop(initialize: () => Promise<Handler>): Promise<void> {
	if (process.argv.includes('--background')) process.env.OPEN_BROWSER = 'false';
	process.env.AIDETECTOR_DATA_DIR = dataDirectory(true);
	const instance = new DesktopInstance(process.env.AIDETECTOR_DATA_DIR);
	const port = Number(process.env.PORT ?? 8765);
	const browserUrl = `http://127.0.0.1:${port}/`;
	if (process.argv.includes('--quit')) process.exit((await instance.existing(port, true)) ? 0 : 1);
	let handler: Handler | undefined;
	let closeHost: (() => void) | undefined;
	let closeDiscovery: (() => void) | undefined;
	let shutdown: Promise<void> | undefined;
	let server: Bun.Server<undefined>;

	async function drain(): Promise<void> {
		try {
			await Promise.all(
				process
					.rawListeners('sveltekit:shutdown')
					.map((listener) => listener.call(process, 'SIGTERM'))
			);
		} finally {
			closeDiscovery?.();
			await server.stop(true);
			closeHost?.();
			process.removeListener('SIGTERM', quit);
			process.removeListener('SIGINT', quit);
		}
	}

	function quit(): void {
		shutdown ??= drain().catch(async (error: Error) => {
			await reportFailure(`AI Detector could not finish shutting down. ${error.message}`);
			console.error('Application shutdown failed:', error);
			process.exitCode = 1;
		});
	}

	try {
		server = Bun.serve({
			port,
			hostname: process.env.HOST || '127.0.0.1',
			idleTimeout: Number(process.env.BUN_IDLE_TIMEOUT ?? 255),
			fetch(request, owner) {
				if (!handler) return new Response('Starting AI Detector…', { status: 503 });
				return instance.respond(request, quit) ?? handler(request, owner);
			},
			error(error) {
				console.error(error);
				return Response.json({ message: 'Something went wrong' }, { status: 500 });
			}
		});
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'EADDRINUSE' && (await instance.existing(port))) {
			openDashboard(browserUrl);
			return;
		}
		await reportFailure(
			`AI Detector cannot open its dashboard on port ${port}. Another application may be using that port. Close the other application and reopen AI Detector.`
		);
		throw error;
	}
	instance.publish(server.port!);
	process.once('exit', () => instance.remove());
	try {
		handler = await initialize();
	} catch (error) {
		await reportFailure(`AI Detector could not start. ${(error as Error).message}`);
		await drain();
		throw error;
	}
	process.on('SIGTERM', quit);
	process.on('SIGINT', quit);
	if (process.env.AIDETECTOR_DESKTOP_HOST === '1')
		closeHost = connectDesktopHost(process.stdin, process.stdout, quit);
	if (process.env.HOST === '0.0.0.0') closeDiscovery = advertiseDashboard(server.port!);
	console.info(`AI Detector is ready at ${browserUrl}`);
	openDashboard(browserUrl);
}
