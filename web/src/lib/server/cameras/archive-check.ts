import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import { copyFile, lstat, mkdir, realpath, rm } from 'node:fs/promises';
import path from 'node:path';
import { promisify } from 'node:util';
import { isArchiveSegment } from '../archive.ts';
import { CameraConnectionError, cameraStorageFailure } from './connection.ts';

const execute = promisify(execFile);

async function childDirectory(parent: string, name: string): Promise<string> {
	const directory = path.join(parent, name);
	try {
		await mkdir(directory, { mode: 0o700 });
	} catch (cause) {
		if ((cause as NodeJS.ErrnoException).code !== 'EEXIST') throw cause;
	}
	if (!(await lstat(directory)).isDirectory())
		throw new CameraConnectionError(
			'The recording location contains a file or linked folder. Choose a regular recording folder before testing it.'
		);
	return directory;
}

/** Exercise the configured archive filesystem without inventing a detection event. */
export async function verifyCameraArchive(
	directory: string,
	cameraId: string,
	sourceClip: string,
	categories: string[],
	executable: string,
	signal?: AbortSignal
): Promise<void> {
	if (
		!isArchiveSegment(cameraId) ||
		categories.some(
			(category) =>
				category !== '' &&
				(!isArchiveSegment(category) || category.includes(':') || /^\.+$/.test(category))
		)
	)
		throw new CameraConnectionError(
			'The recording location is invalid. Check the camera settings.'
		);
	try {
		const root = await childDirectory(await realpath(directory), 'detections');
		for (const category of new Set(categories)) {
			signal?.throwIfAborted();
			const destination = category ? await childDirectory(root, category) : root;
			// A temporary file never appears as an archive category or event, even after a crash.
			const clip = path.join(destination, `.setup-test-${cameraId}-${randomUUID()}.mp4`);
			await copyFile(sourceClip, clip, constants.COPYFILE_EXCL);
			try {
				try {
					await execute(
						executable,
						[
							'-hide_banner',
							'-loglevel',
							'error',
							'-nostdin',
							'-xerror',
							'-i',
							clip,
							'-map',
							'0:v:0',
							'-an',
							'-f',
							'null',
							'-'
						],
						{
							timeout: 10000,
							killSignal: 'SIGKILL',
							maxBuffer: 64 * 1024,
							windowsHide: true,
							signal
						}
					);
				} catch (cause) {
					signal?.throwIfAborted();
					throw new CameraConnectionError(
						(cause as NodeJS.ErrnoException).code === 'ENOENT'
							? 'The camera software is missing. Repair or reinstall AI Detector and try again.'
							: 'The test recording was saved but could not be played. Check the camera picture and try again.'
					);
				}
			} finally {
				await rm(clip, { force: true });
			}
		}
	} catch (cause) {
		signal?.throwIfAborted();
		if ((cause as NodeJS.ErrnoException).code === 'ENOENT')
			throw new CameraConnectionError(
				'The camera test recording is no longer available. Check its picture again.'
			);
		throw cameraStorageFailure(cause) ?? cause;
	}
}
