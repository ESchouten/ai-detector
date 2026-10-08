import { resolve } from '$app/paths';
import { checkCameraRecording } from '../camera-check';
import { errorMessage } from '../remote-errors';
import { finishSetup, getSetupStatus } from '../remote/camera-setup.remote';
import { getCameras, saveCamera } from '../remote/camera.remote';

export type SetupCamera = Awaited<ReturnType<typeof getSetupStatus>>[number];

/** Picture and recording-location checks for saved cameras, one camera at a time. */
export class SetupVerifier {
	cameras = $state<SetupCamera[]>([]);
	/** The camera being checked right now, if any. */
	checking = $state('');
	errors = $state<Record<string, string>>({});
	connectionLost = $state(false);
	lastCheckedAt = $state(Date.now());
	#controller = new AbortController();
	/** A picture check also records the clip that the recording check needs. */
	#checks: Record<string, string> = {};

	constructor(cameras: SetupCamera[]) {
		this.cameras = cameras;
	}

	get stopped(): boolean {
		return this.#controller.signal.aborted;
	}
	/** Every camera passed its checks and, when monitored, is being processed. */
	get ready(): boolean {
		return (
			this.cameras.length > 0 &&
			this.cameras.every(
				(camera) => camera.readyToFinish && (!camera.monitored || camera.monitoring)
			)
		);
	}
	get finished(): boolean {
		return this.cameras.length > 0 && this.cameras.every((camera) => camera.completedAt);
	}
	get failed(): boolean {
		return Object.keys(this.errors).length > 0;
	}

	needsCheck(camera: SetupCamera): boolean {
		return (
			!camera.pictureVerifiedAt || (camera.archiveDestinations > 0 && !camera.archiveVerifiedAt)
		);
	}

	async refresh(): Promise<void> {
		await getSetupStatus().refresh();
		this.cameras = await getSetupStatus();
		this.connectionLost = false;
		this.lastCheckedAt = Date.now();
	}

	/** Refresh every two seconds and run outstanding checks until stopped. */
	start(tick: () => void | Promise<void>): () => void {
		let timer: ReturnType<typeof setTimeout>;
		const poll = async () => {
			try {
				await this.refresh();
				if (this.stopped) return;
				await tick();
				if (!this.checking) void this.check();
			} catch {
				this.connectionLost = true;
			}
			if (!this.stopped) timer = setTimeout(poll, 2000);
		};
		void poll();
		return () => {
			this.#controller.abort();
			clearTimeout(timer);
		};
	}

	async check(
		ids = this.cameras
			.filter((camera) => this.needsCheck(camera) && !this.errors[camera.id])
			.map((camera) => camera.id)
	): Promise<void> {
		for (const id of ids) {
			if (this.stopped) return;
			this.checking = id;
			delete this.errors[id];
			try {
				let camera = this.cameras.find((item) => item.id === id);
				if (camera && !camera.pictureVerifiedAt) {
					await this.#checkPicture(id);
					await this.refresh();
					camera = this.cameras.find((item) => item.id === id);
				}
				if (camera && camera.archiveDestinations > 0 && !camera.archiveVerifiedAt)
					await this.#checkRecording(id);
				await this.refresh();
			} catch (cause) {
				if (this.stopped) return;
				this.errors[id] = errorMessage(cause, 'This camera could not be checked. Try again.');
			}
		}
		this.checking = '';
	}

	retry(id: string): void {
		void this.check([id]);
	}

	async finish(): Promise<void> {
		await finishSetup().updates(getSetupStatus(), getCameras());
		this.cameras = await getSetupStatus();
	}

	/** Imported cameras have never shown a picture here; connect once to confirm they work. */
	async #checkPicture(id: string): Promise<void> {
		const camera = (await getCameras()).find((item) => item.id === id);
		if (!camera) return;
		const check = await checkCameraRecording(
			camera.source,
			this.#controller.signal,
			resolve('/camera-checks')
		);
		await saveCamera({
			id,
			label: camera.label,
			source: check.source,
			mode: 'keep',
			checkId: check.checkId
		}).updates(getCameras());
		this.#checks[id] = check.checkId;
	}

	async #checkRecording(id: string): Promise<void> {
		const checkId = this.#checks[id];
		delete this.#checks[id];
		const response = await fetch(resolve(`/cameras/${id}/archive-check`), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(checkId ? { checkId } : {}),
			signal: this.#controller.signal
		});
		if (response.status >= 500) throw new Error('The recording check could not finish. Try again.');
		const result = await response.json();
		if (!response.ok) throw new Error(result.message);
	}
}
