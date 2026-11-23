/** Generated from config/metadata.schema.json. Run pnpm schema:generate; do not edit. */

export type Timestamp = string;
export type EventId = string | null;
export type Camera = string | null;
export type Validated = boolean | null;
export type Confidence = number;
export type Detections = number;
export type Start = string;
export type End = string;
export type Duration = number;
export type X1 = number;
export type Y1 = number;
export type X2 = number;
export type Y2 = number;
export type ValidationError = string | null;
export type Individuals = IndividualMetadata[] | null;
export type Track = number;
export type Label = string;
export type Sighting = string;
export type Name = string | null;
export type Name1 = string;
export type Score = number;
export type Candidates = CandidateMetadata[];
export type IndividualsError = string | null;
export type Validated1 = boolean;
export type Source = 'web' | 'telegram';
export type ReviewedAt = string;

export interface EventMetadata {
	timestamp: Timestamp;
	event_id?: EventId;
	camera?: Camera;
	validated: Validated;
	confidence: Confidence;
	confidences: Confidences;
	detections: Detections;
	start: Start;
	end: End;
	duration: Duration;
	crop?: CropMetadata | null;
	validation_error?: ValidationError;
	individuals?: Individuals;
	individuals_error?: IndividualsError;
	review?: ManualReview | null;
}
export interface Confidences {
	[k: string]: number;
}
export interface CropMetadata {
	x1: X1;
	y1: Y1;
	x2: X2;
	y2: Y2;
	[k: string]: unknown;
}
/**
 * A tracked object of the event and the named individuals it resembles most.
 */
export interface IndividualMetadata {
	track: Track;
	label: Label;
	sighting: Sighting;
	name: Name;
	candidates: Candidates;
}
export interface CandidateMetadata {
	name: Name1;
	score: Score;
}
/**
 * A person's verdict on the event, from the web application or Telegram.
 */
export interface ManualReview {
	validated: Validated1;
	source: Source;
	reviewed_at: ReviewedAt;
}
