// adapter-node serves HTTP but otherwise assumes HTTPS when reconstructing request URLs.
// Supply the transport through a private header, overwriting any client-supplied value.
// ORIGIN remains available for deployments behind a trusted HTTPS reverse proxy.
const protocolHeader = 'x-ai-detector-protocol';
process.env.PROTOCOL_HEADER = protocolHeader;
const { server } = await import('./build/index.js');

server.server.prependListener(
	'request',
	/** @param {import('node:http').IncomingMessage} request */ (request) => {
		request.headers[protocolHeader] = 'http';
	}
);
