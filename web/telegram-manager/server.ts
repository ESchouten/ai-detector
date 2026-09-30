import { createServer } from 'node:http';
import { Bot, webhookCallback } from 'grammy';
import { BotCreationSessions } from './service.ts';

const { TELEGRAM_MANAGER_TOKEN, TELEGRAM_WEBHOOK_SECRET, PUBLIC_URL, PORT = '8080' } = process.env;
if (!TELEGRAM_MANAGER_TOKEN || !TELEGRAM_WEBHOOK_SECRET || !PUBLIC_URL?.startsWith('https://')) {
	throw new Error('Set TELEGRAM_MANAGER_TOKEN, TELEGRAM_WEBHOOK_SECRET and an HTTPS PUBLIC_URL.');
}
const bot = new Bot(TELEGRAM_MANAGER_TOKEN);
await bot.init();
const sessions = new BotCreationSessions(bot.botInfo.username);
bot.chatType('private').command('start', (ctx) => sessions.start(ctx.match, ctx.from.id, bot.api));
bot
	.chatType('private')
	.on('message:managed_bot_created', (ctx) =>
		sessions.created(ctx.from.id, ctx.message.managed_bot_created.bot, bot.api)
	);
const webhook = webhookCallback(bot, 'http', { secretToken: TELEGRAM_WEBHOOK_SECRET });
const server = createServer(async (request, response) => {
	response.setHeader('Cache-Control', 'no-store');
	response.setHeader('Content-Type', 'application/json');
	if (request.method === 'POST' && request.url === '/webhook') {
		try {
			await webhook(request, response);
		} catch {
			if (!response.headersSent) response.writeHead(503).end('{"error":"Retry webhook"}');
		}
		return;
	}
	if (request.method !== 'POST' || !['/sessions', '/poll', '/cancel'].includes(request.url ?? '')) {
		response.writeHead(404).end('{}');
		return;
	}
	try {
		let body = '';
		for await (const chunk of request) {
			body += chunk;
			if (Buffer.byteLength(body) > 1024) {
				response.writeHead(413).end('{}');
				return;
			}
		}
		const input: unknown = JSON.parse(body || '{}');
		if (request.url === '/sessions') {
			response.end(JSON.stringify(sessions.begin()));
			return;
		}
		if (!input || typeof input !== 'object' || !('id' in input) || typeof input.id !== 'string') {
			response.writeHead(400).end('{}');
			return;
		}
		if (request.url === '/cancel') {
			sessions.cancel(input.id);
			response.end('{}');
		} else response.end(JSON.stringify(sessions.poll(input.id)));
	} catch {
		response
			.writeHead(409)
			.end('{"error":"This connection expired or the service is busy. Start again."}');
	}
});
server.requestTimeout = 15000;
server.listen(Number(PORT), '0.0.0.0');
await bot.api.setWebhook(new URL('/webhook', PUBLIC_URL).href, {
	secret_token: TELEGRAM_WEBHOOK_SECRET,
	allowed_updates: ['message']
});
console.info('Telegram manager ready');
