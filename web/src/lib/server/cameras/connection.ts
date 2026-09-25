import { ConfigurationError } from '../../configuration.ts';
import { sanitizeTextForLogs } from '../runtime-logs.ts';

export class CameraConnectionError extends ConfigurationError {}

export function cameraAddress(value: string): URL {
	try {
		const address = new URL(value.includes('://') ? value : `http://${value}`);
		if (!['http:', 'https:'].includes(address.protocol) || !address.hostname) throw new Error();
		if (address.username || address.password)
			throw new CameraConnectionError(
				'Enter the camera username and password in their separate fields.'
			);
		return address;
	} catch (cause) {
		if (cause instanceof CameraConnectionError) throw cause;
		throw new CameraConnectionError('Enter the camera’s address, for example 192.168.1.50.');
	}
}

export function cameraStream(value: string, username = '', password = ''): string {
	try {
		const source = new URL(value);
		if (!['rtsp:', 'rtsps:', 'http:', 'https:'].includes(source.protocol) || !source.hostname)
			throw new Error();
		if (username || password) {
			source.username = username;
			source.password = password;
		}
		return source.toString();
	} catch {
		throw new CameraConnectionError(
			'Enter a complete camera stream address starting with rtsp:// or http://.'
		);
	}
}

export function connectionFailure(cause: unknown): CameraConnectionError {
	const message = sanitizeTextForLogs(cause instanceof Error ? cause.message : String(cause));
	if (/ENOSPC|No space left on device|Disk quota exceeded/i.test(message))
		return new CameraConnectionError(
			'There is not enough space to save the test recording. Free some space on this computer and try again.'
		);
	if (
		/HTTP (?:401|403)\b|unauthori[sz]ed|notauthori[sz]ed|authentication failed|authorization failed/i.test(
			message
		)
	)
		return new CameraConnectionError(
			'The camera rejected the login. Check its username and password, then try again.'
		);
	if (
		/ECONNREFUSED|ENOTFOUND|EHOSTUNREACH|ENETUNREACH|ETIMEDOUT|timed? ?out|timeout|connection refused/i.test(
			message
		)
	)
		return new CameraConnectionError(
			'The camera did not respond. Check its power, network connection and address, then try again.'
		);
	if (
		/Invalid data found|does not contain any stream|matches no streams|unsupported codec|decoder.*not found|Could not find codec parameters/i.test(
			message
		)
	)
		return new CameraConnectionError(
			'The camera did not provide a supported video stream. Try another channel or ask your camera installer for its stream address.'
		);
	return new CameraConnectionError(
		'Could not connect to this camera. Check that local camera access is enabled, or enter its stream URL manually.'
	);
}

export function cameraStorageFailure(cause: unknown): CameraConnectionError | undefined {
	const code = (cause as NodeJS.ErrnoException).code;
	if (code === 'ENOSPC' || code === 'EDQUOT') return connectionFailure('No space left on device');
	if (['EACCES', 'EPERM', 'ENOTDIR', 'EROFS'].includes(code ?? ''))
		return new CameraConnectionError(
			'The test recording could not be saved. Check that AI Detector’s data folder is writable, or repair the installation.'
		);
	return undefined;
}
