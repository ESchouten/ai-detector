import type { RequestHandler } from './$types';
import { configuration } from '$lib/server/configuration';
import { backupSettings } from '$lib/server/settings-backup';

export const GET: RequestHandler = ({ request }) => backupSettings(configuration, request);
