import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import type { RuntimeMode } from '../runtime.ts';

const execute = promisify(execFile);
export const DOCKER_HELP = 'https://docs.docker.com/desktop/setup/install/windows-install/';
export const NVIDIA_HELP =
	'https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html';

export class SetupError extends Error {
	readonly helpUrl?: string;
	constructor(message: string, helpUrl?: string) {
		super(message);
		this.helpUrl = helpUrl;
	}
}

export function chooseRuntime(mode: RuntimeMode): 'native' | 'docker' {
	return mode === 'docker' ? 'docker' : 'native';
}

export async function checkDocker(platform: string, signal?: AbortSignal): Promise<void> {
	const help = platform === 'win32' ? DOCKER_HELP : NVIDIA_HELP;
	try {
		const { stdout } = await execute('docker', ['info', '--format', '{{.OSType}}'], {
			timeout: 15000,
			windowsHide: true,
			signal,
			killSignal: 'SIGKILL'
		});
		if (stdout.trim() === 'linux') return;
	} catch {
		signal?.throwIfAborted();
		throw new SetupError(
			'Install or open Docker, then try again. Docker must be running on this computer.',
			help
		);
	}
	throw new SetupError('Switch Docker to Linux containers, then try again.', help);
}

export function dockerArguments(
	image: string,
	directory: string,
	name: string,
	platform: string,
	user?: string
): string[] {
	const args = ['run', '--rm', '--interactive', '--name', name, '--gpus', 'all', '--init'];
	if (platform === 'linux' && user) args.push('--user', user);
	args.push('--env', 'HOME=/tmp', '--env', 'YOLO_CONFIG_DIR=/tmp/ultralytics');
	args.push(
		'--volume',
		`${directory}:/data`,
		image,
		'python3',
		'-m',
		'aidetector',
		'--control-stdin',
		'--status-json'
	);
	return args;
}
