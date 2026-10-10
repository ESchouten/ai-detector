import { DetectionArchive } from './archive.ts';
import { DETECTIONS_DIR } from './application-paths.ts';

export const recordings = new DetectionArchive(DETECTIONS_DIR);
