import * as v from 'valibot';

const legacyVerifier = v.looseObject({
	enabled: v.optional(v.boolean()),
	key: v.optional(v.nullable(v.string()))
});
const legacyConfiguration = v.looseObject({
	detectors: v.array(
		v.looseObject({
			vlm_enabled: v.optional(v.boolean()),
			vlm: v.optional(v.nullable(v.union([v.array(legacyVerifier), legacyVerifier])))
		})
	)
});

/** Upgrade saved preview settings once; new input still uses the strict canonical schema. */
export function upgradeVerificationKeys(input: unknown): unknown {
	const parsed = v.safeParse(legacyConfiguration, input);
	if (!parsed.success) return input;
	let changed = false;
	const detectors = parsed.output.detectors.map(({ vlm_enabled, vlm, ...detector }) => {
		if (vlm_enabled !== undefined) changed = true;
		const upgrade = ({ enabled, ...settings }: v.InferOutput<typeof legacyVerifier>) => {
			if (enabled !== undefined) changed = true;
			return vlm_enabled === false || enabled === false ? { ...settings, key: null } : settings;
		};
		return {
			...detector,
			...(vlm == null ? {} : { vlm: Array.isArray(vlm) ? vlm.map(upgrade) : upgrade(vlm) })
		};
	});
	return changed ? { ...parsed.output, detectors } : input;
}
