import { execFile } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { connect } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createSecureContext, rootCertificates, TLSSocket } from 'node:tls';
import { promisify } from 'node:util';

export const PHONE = 111;
export const GROUP = -1001234567890;
const TELEGRAM = 'api.telegram.org';

const chats = {
	[PHONE]: { id: PHONE, type: 'private', first_name: 'Erik' },
	[GROUP]: { id: GROUP, type: 'supergroup', title: 'Barn group' }
};
const farmer = { id: PHONE, is_bot: false, first_name: 'Erik' };

/** A certificate authority for this test only, and Telegram's name signed by it. */
async function certificates(directory) {
	const openssl = (...args) => promisify(execFile)('openssl', args, { cwd: directory });
	const subject = (name) => ['-nodes', '-newkey', 'rsa:2048', '-subj', `/CN=${name}`];
	await openssl(
		'req',
		'-x509',
		...subject('AI Detector test'),
		'-keyout',
		'ca.key',
		'-out',
		'ca.pem'
	);
	await openssl('req', ...subject(TELEGRAM), '-keyout', 'telegram.key', '-out', 'telegram.csr');
	await writeFile(path.join(directory, 'names.cnf'), `subjectAltName=DNS:${TELEGRAM}\n`);
	await openssl(
		'x509',
		'-req',
		'-in',
		'telegram.csr',
		'-CA',
		'ca.pem',
		'-CAkey',
		'ca.key',
		'-CAcreateserial',
		'-extfile',
		'names.cnf',
		'-out',
		'telegram.pem'
	);
	const authority = path.join(directory, 'ca.pem');
	// The detector checks Telegram against this, and every other site against the usual roots.
	const bundle = path.join(directory, 'bundle.pem');
	await writeFile(bundle, [await readFile(authority, 'utf8'), ...rootCertificates].join('\n'));
	return {
		authority,
		bundle,
		context: createSecureContext({
			key: await readFile(path.join(directory, 'telegram.key')),
			cert: await readFile(path.join(directory, 'telegram.pem'))
		})
	};
}

async function fields(request, body) {
	const type = request.headers['content-type'] ?? '';
	if (!body.length) return {};
	if (type.includes('json')) return JSON.parse(body.toString());
	const form = await new Request('http://telegram.test/', {
		method: 'POST',
		headers: { 'content-type': type },
		body
	}).formData();
	return Object.fromEntries(
		[...form].map(([name, value]) => [
			name,
			typeof value === 'string' ? value : { file: value.name, type: value.type, size: value.size }
		])
	);
}

/**
 * Telegram's Bot API, answered on this computer: nothing reaches Telegram. The application and
 * its detector find it through a local HTTPS proxy that passes every other site through. It also
 * plays the farmer in Telegram: /start with the pairing code, then the confirmation button.
 */
export async function fakeTelegram(t) {
	const directory = await mkdtemp(path.join(tmpdir(), 'fake-telegram-'));
	t.after(() => rm(directory, { recursive: true, force: true }));
	const { authority, bundle, context } = await certificates(directory);
	const calls = [];
	const updates = new Map();
	let pairing = '';
	let updateId = 0;
	let messageId = 0;
	const queue = (token, update) =>
		updates.set(token, [...(updates.get(token) ?? []), { update_id: ++updateId, ...update }]);

	async function answer(method, token, payload) {
		if (method === 'getMe')
			return { id: 999, is_bot: true, first_name: 'Farm Bot', username: 'farm_test_bot' };
		if (method === 'getWebhookInfo') return { url: '', pending_update_count: 0 };
		if (method === 'getUpdates') {
			const offset = Number(payload.offset ?? 0);
			const pending = () => (updates.get(token) ?? []).filter((item) => item.update_id >= offset);
			if (!pending().length) await new Promise((resolve) => setTimeout(resolve, 500));
			return pending();
		}
		if (!method.startsWith('send')) return true;
		const message = { message_id: ++messageId, date: 0, chat: chats[payload.chat_id] };
		const markup =
			typeof payload.reply_markup === 'string'
				? JSON.parse(payload.reply_markup)
				: payload.reply_markup;
		if (markup?.inline_keyboard?.flat().some((button) => button.callback_data === pairing))
			queue(token, {
				callback_query: {
					id: `pressed-${message.message_id}`,
					from: farmer,
					data: pairing,
					message: { ...message, reply_markup: markup }
				}
			});
		return message;
	}

	const api = createServer(async (request, response) => {
		const chunks = [];
		for await (const chunk of request) chunks.push(chunk);
		const [, bot, method] = new URL(request.url, `https://${TELEGRAM}`).pathname.split('/');
		const token = bot.slice('bot'.length);
		const payload = await fields(request, Buffer.concat(chunks));
		calls.push({ method, token, payload });
		response.writeHead(200, { 'content-type': 'application/json' });
		response.end(JSON.stringify({ ok: true, result: await answer(method, token, payload) }));
	});
	// Tunnels outlive their HTTP connection; they are closed here rather than waited for.
	const tunnels = new Set();
	const proxy = createServer();
	proxy.on('connect', (request, socket, head) => {
		const [host, port] = request.url.split(':');
		tunnels.add(socket);
		socket.on('close', () => tunnels.delete(socket));
		socket.on('error', () => socket.destroy());
		socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
		if (host === TELEGRAM) {
			api.emit('connection', new TLSSocket(socket, { isServer: true, secureContext: context }));
			return;
		}
		const upstream = connect(Number(port), host, () => {
			upstream.write(head);
			socket.pipe(upstream).pipe(socket);
		});
		upstream.on('error', () => socket.destroy());
		socket.on('close', () => upstream.destroy());
	});
	proxy.listen(0, '127.0.0.1');
	await once(proxy, 'listening');
	t.after(() => {
		for (const socket of tunnels) socket.destroy();
		proxy.close();
	});
	return {
		calls,
		/** For the application and the detector it starts. */
		env: {
			HTTPS_PROXY: `http://127.0.0.1:${proxy.address().port}`,
			NODE_USE_ENV_PROXY: '1',
			NODE_EXTRA_CA_CERTS: authority,
			REQUESTS_CA_BUNDLE: bundle
		},
		/** The farmer opens the pairing link in Telegram, which sends the bot /start with its code. */
		start(token, code) {
			pairing = code;
			queue(token, {
				message: {
					message_id: ++messageId,
					date: 0,
					chat: chats[PHONE],
					from: farmer,
					text: `/start ${code}`
				}
			});
		}
	};
}
