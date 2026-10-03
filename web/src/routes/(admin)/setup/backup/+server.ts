import type { RequestHandler } from './$types';
import { configuration } from '$lib/server/configuration';
import { backupSettings } from '$lib/server/settings-backup';
import { herd } from '$lib/server/herd';

export const GET: RequestHandler = ({ request }) => backupSettings(configuration, herd, request);
