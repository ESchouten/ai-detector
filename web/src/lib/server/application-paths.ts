import { dev } from '$app/environment';
import path from 'node:path';
import { dataDirectory } from '../../../desktop/paths.ts';

declare const __AI_DETECTOR_WEB_TARGET__: string;

export const EXECUTABLE_DIRECTORY = path.dirname(process.execPath);
export const PACKAGED = !dev && __AI_DETECTOR_WEB_TARGET__ !== 'node';

export const DATA_DIRECTORY = dataDirectory(PACKAGED);
export const CONFIG_PATH = path.join(DATA_DIRECTORY, 'config.json');
export const APP_CONFIG_PATH = path.join(DATA_DIRECTORY, 'app.json');
export const DETECTIONS_DIR = path.join(DATA_DIRECTORY, 'detections');
