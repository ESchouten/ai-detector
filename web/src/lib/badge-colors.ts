/** Stable category colors; green, amber and red remain reserved for status. */
export function badgeHue(seed: string): number {
	const hues = [210, 260, 310, 180, 235, 285];
	let hash = 0;
	for (const character of seed.toLowerCase().replace(/[-_\s]+/g, ''))
		hash = (Math.imul(31, hash) + character.charCodeAt(0)) >>> 0;
	return hues[hash % hues.length];
}
