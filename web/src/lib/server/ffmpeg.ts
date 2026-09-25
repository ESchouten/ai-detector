import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { promisify } from 'node:util';
import ffmpegStatic from 'ffmpeg-static';

export { sanitizeSourceForLogs, sanitizeTextForLogs } from './runtime-logs.ts';

const execute = promisify(execFile);
let cachedPath: string | undefined;
let pendingPath: Promise<string | null> | undefined;

export const getExecutableName = () => (process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg');
export const isRtspSource = (source: string) => /^rtsps?:\/\//i.test(source.trim());

export function getRtspInputArgs(source: string): string[] {
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

async function extractBundledFfmpeg(): Promise<string | null> {
	// The executable adapter embeds static/_internal/ffmpeg as a Bun file asset.
	// Read those trusted bytes locally; request headers never choose executable content.
	const bun = (globalThis as typeof globalThis & { Bun?: { embeddedFiles: File[] } }).Bun;
	const suffix = process.platform === 'win32' ? '.exe' : '.';
	const asset = bun?.embeddedFiles.find(
		(file) => /^ffmpeg-[a-z0-9]+\.(?:exe)?$/.test(file.name) && file.name.endsWith(suffix)
	);
	if (!asset) return null;
	const target = path.join(tmpdir(), 'ai-detector-web', 'bin', asset.name);
	if (existsSync(target)) return target;
	await mkdir(path.dirname(target), { recursive: true });
	const pending = `${target}.${randomUUID()}.tmp`;
	try {
		await writeFile(pending, new Uint8Array(await asset.arrayBuffer()), { mode: 0o755 });
		await rename(pending, target);
	} finally {
		await rm(pending, { force: true });
	}
	return target;
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
	return (await extractBundledFfmpeg()) ?? ((await canRun('ffmpeg')) ? 'ffmpeg' : null);
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
