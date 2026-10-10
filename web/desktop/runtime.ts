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
	const port = Number(process.env.PORT ?? 80);
	const host = process.env.HOST || '0.0.0.0';
	const browserUrl = new URL(`http://127.0.0.1:${port}/`).href;
	if (process.argv.includes('--quit')) process.exit((await instance.existing(port, true)) ? 0 : 1);
	let handler: Handler | undefined;
	let closeHost: (() => void) | undefined;
	let closeDiscovery: (() => Promise<void>) | undefined;
	let shutdown: Promise<void> | undefined;
	let server: Bun.Server<undefined>;
	const terminate = () => quit('SIGTERM');
	const interrupt = () => quit('SIGINT');

	async function drain(reason: string): Promise<void> {
		try {
			await Promise.all(
				process.rawListeners('sveltekit:shutdown').map((listener) => listener.call(process, reason))
			);
		} finally {
			await closeDiscovery?.();
			await server.stop(true);
			closeHost?.();
			process.removeListener('SIGTERM', terminate);
			process.removeListener('SIGINT', interrupt);
		}
	}

	function quit(reason = 'Application shutdown'): void {
		const intentional = reason !== 'SIGTERM' && reason !== 'SIGINT';
		if (intentional && !shutdown) console.error('AI_DETECTOR_STOPPING');
		shutdown ??= (async () => {
			let success = false;
			try {
				await drain(reason);
				success = true;
			} catch (error) {
				await reportFailure(
					`AI Detector could not finish shutting down. ${(error as Error).message}`
				);
				console.error('Application shutdown failed:', error);
				process.exitCode = 1;
			} finally {
				if (intentional) instance.completeShutdown(success);
			}
		})();
	}

	try {
		server = Bun.serve({
			port,
			hostname: host,
			idleTimeout: Number(process.env.BUN_IDLE_TIMEOUT ?? 255),
			fetch(request, owner) {
				if (!handler) return new Response('Starting AI Detector…', { status: 503 });
				return (
					instance.respond(request, () => quit('Authenticated desktop quit request')) ??
					handler(request, owner)
				);
			},
			error(error) {
				console.error(error);
				return Response.json({ message: 'Something went wrong' }, { status: 500 });
			}
		});
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'EADDRINUSE' && (await instance.existing(port))) {
			openDashboard(browserUrl);
			if (process.env.AIDETECTOR_DESKTOP_HOST === '1') await attachDesktopHost(instance, port);
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
		await drain('Application startup failed');
		throw error;
	}
	process.on('SIGTERM', terminate);
	process.on('SIGINT', interrupt);
	if (process.env.AIDETECTOR_DESKTOP_HOST === '1')
		closeHost = connectDesktopHost(process.stdin, process.stdout, quit, () => {
			for (const listener of process.rawListeners('aidetector:launcher-disconnected'))
				listener.call(process);
		});
	if (host === '0.0.0.0') closeDiscovery = advertiseDashboard(server.port!);
	console.info(`AI Detector is ready at ${browserUrl}`);
	openDashboard(browserUrl);
}

/** A reopened native menu controls the existing server through its authenticated endpoint. */
async function attachDesktopHost(instance: DesktopInstance, port: number): Promise<void> {
	const finished = new AbortController();
	let shutdown: Promise<void> | undefined;
	const close = connectDesktopHost(
		process.stdin,
		process.stdout,
		() => {
			console.error('AI_DETECTOR_STOPPING');
			shutdown ??= (async () => {
				if (!(await instance.existing(port, true))) {
					await reportFailure('AI Detector could not finish shutting down. Please try again.');
					process.exitCode = 1;
				}
			})();
			finished.abort();
		},
		() => finished.abort()
	);
	try {
		const result = await instance.waitForShutdown(finished.signal);
		if (result !== undefined) console.error('AI_DETECTOR_STOPPING');
		if (result !== true) {
			await reportFailure(
				result === false
					? 'AI Detector could not finish shutting down.'
					: 'The AI Detector background process stopped unexpectedly.'
			);
			process.exitCode = 1;
		}
	} catch (error) {
		if (!finished.signal.aborted) throw error;
	} finally {
		try {
			await shutdown;
		} finally {
			close();
		}
	}
}
