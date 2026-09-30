# Optional Telegram bot creation service

The desktop app works without this service: users can reuse a saved bot or paste a BotFather token. This separately deployed service removes token copying for new bots. It never receives camera images, recordings, detector settings or existing bot credentials.

## Deploy

1. Create a dedicated manager bot in BotFather and enable **Bot Management Mode** in the BotFather Mini App.
2. Host one instance behind an HTTPS reverse proxy. Build from this directory with `docker build -t ai-detector-telegram-manager .`.
3. Set `TELEGRAM_MANAGER_TOKEN`, a random `TELEGRAM_WEBHOOK_SECRET`, and `PUBLIC_URL` (the HTTPS origin). `PORT` defaults to 8080. Supply secrets through the hosting provider, never in an image or desktop build.
4. Start the container. It registers `/webhook` with Telegram. Forward POST requests, limit `/sessions` creation at the proxy (for example 5/minute per client), and disable request-body logging. The app server, not the browser, makes requests; no CORS access is needed.
5. Set `AI_DETECTOR_TELEGRAM_MANAGER_URL` to that HTTPS origin in AI Detector's environment. With no URL, the creation button is hidden.

Sessions are kept only in memory, capped at 100, and expire after ten minutes. Use one replica; restarts require creating a new link. `/poll` requires a random 256-bit session secret separate from the Telegram start code. Tokens are returned only to that installation and forgotten when it acknowledges or the session expires. The manager bot remains able to manage the created bots through Telegram; operate it as a credential-bearing service.

The user opens the manager link, creates a bot in Telegram, and keeps the suggested username. The service checks the initiating Telegram user and that exact username before fetching a token. AI Detector then uses the ordinary local chat-selection and delivery-confirmation flow. Existing bots and bots created with a different username can still be connected by pasting their token.

Before enabling this in a release, run a real Telegram smoke test using the deployed manager: create, cancel, expiry, phone connection, group connection, channel connection. Unit tests mock Telegram and cannot verify BotFather's account settings.

Official API: [managed bots](https://core.telegram.org/bots/features#managed-bots), [requesting bot creation](https://core.telegram.org/bots/api#keyboardbuttonrequestmanagedbot).
