import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { ConfigurationError } from '../configuration.ts';

const execute = promisify(execFile);
function folderPickerCommand(platform: NodeJS.Platform): [string, string[]] {
	// The title sits inside a quoted string in each script; a translation must not end it.
	const title = 'Choose your previous AI Detector folder'.replaceAll(/["`$\\]/g, '');
	if (platform === 'darwin')
		return [
			'osascript',
			[
				'-e',
				'try',
				'-e',
				/* @wc-ignore */ `POSIX path of (choose folder with prompt "${title}")`,
				'-e',
				'on error number -128',
				'-e',
				'return ""',
				'-e',
				'end try'
			]
		];
	if (platform === 'win32')
		return [
			'powershell.exe',
			[
				'-NoProfile',
				'-STA',
				'-Command',
				/* @wc-ignore */ `Add-Type -AssemblyName System.Windows.Forms; $picker = New-Object System.Windows.Forms.FolderBrowserDialog; $picker.Description = "${title}"; $picker.ShowNewFolderButton = $false; if ($picker.ShowDialog() -eq "OK") { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::WriteLine($picker.SelectedPath) }; $picker.Dispose()`
			]
		];
	return ['zenity', ['--file-selection', '--directory', `--title=${title}`]];
}

export async function chooseImportFolder(): Promise<string | null> {
	try {
		const [program, args] = folderPickerCommand(process.platform);
		const { stdout } = await execute(program, args, { timeout: 120000, windowsHide: true });
		return stdout.trim() || null;
	} catch (error) {
		if (process.platform === 'linux' && (error as { code?: number | string }).code === 1)
			return null;
		throw new ConfigurationError(
			'The folder chooser could not open. Use “Enter folder path” instead.'
		);
	}
}
