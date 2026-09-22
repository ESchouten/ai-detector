// adapter-node serves HTTP but otherwise assumes HTTPS when reconstructing request URLs.
// Supply the transport through a private header, overwriting any client-supplied value.
// ORIGIN remains available for deployments behind a trusted HTTPS reverse proxy.
const protocolHeader = 'x-ai-detector-protocol';
process.env.PROTOCOL_HEADER = protocolHeader;
const { server } = await import('./build/index.js');

server.server.prependListener(
	'request',
	/**
	 * @param {import('node:http').IncomingMessage} request
	 * @param {import('node:http').ServerResponse} response
	 */
	(request, response) => {
		request.headers[protocolHeader] = 'http';
		// The adapter's body signal stops tracking disconnects once the POST body is read.
		const controller = new AbortController();
		request.disconnectSignal = controller.signal;
		response.once('close', () => {
			if (!response.writableFinished) controller.abort();
		});
	}
);
