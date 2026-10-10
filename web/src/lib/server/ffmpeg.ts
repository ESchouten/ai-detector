import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';
import ffmpegStatic from 'ffmpeg-static';

export { sanitizeSourceForLogs, sanitizeTextForLogs } from './runtime-logs.ts';

const execute = promisify(execFile);
let cachedPath: string | undefined;
let pendingPath: Promise<string | null> | undefined;

const getExecutableName = () => (process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg');
const isRtspSource = (source: string) => /^rtsps?:\/\//i.test(source.trim());

function getRtspInputArgs(source: string): string[] {
	return [
		'-rtsp_transport',
		'tcp',
		'-timeout',
		'10000000',
		'-threads',
		'1',
		'-analyzeduration',
		'1000000',
		'-probesize',
		'1000000',
		'-i',
		source
	];
}

export function getCameraInputArgs(source: string): string[] {
	return isRtspSource(source)
		? getRtspInputArgs(source)
		: ['-rw_timeout', '10000000', '-i', source];
}

async function canRun(command: string): Promise<boolean> {
	try {
		await execute(command, ['-version'], {
			timeout: 5000,
			killSignal: 'SIGKILL',
			windowsHide: true
		});
		return true;
	} catch {
		return false;
	}
}

async function resolveFfmpegPath(): Promise<string | null> {
	const configured = process.env.FFMPEG_PATH?.trim();
	if (configured && (existsSync(configured) || (await canRun(configured)))) return configured;
	if (typeof ffmpegStatic === 'string' && existsSync(ffmpegStatic)) return ffmpegStatic;
	const name = getExecutableName();
	for (const candidate of [
		path.resolve(path.dirname(process.execPath), name),
		path.resolve(path.dirname(process.execPath), 'bin', name),
		path.resolve(process.cwd(), name),
		path.resolve(process.cwd(), 'bin', name)
	]) {
		if (existsSync(candidate)) return candidate;
	}
	return (await canRun('ffmpeg')) ? 'ffmpeg' : null;
}

export async function getFfmpegPathWithFallback(): Promise<string | null> {
	if (cachedPath) return cachedPath;
	pendingPath ??= resolveFfmpegPath().finally(() => {
		pendingPath = undefined;
	});
	const result = await pendingPath;
	if (result) cachedPath = result;
	return result;
}
