/**
 * A queue that runs operations one at a time, in the order they were given. A failed operation
 * rejects for its own caller only; the operations queued behind it still run.
 */
export function serialQueue(): <T>(operation: () => Promise<T>) => Promise<T> {
	let last: Promise<unknown> = Promise.resolve();
	return (operation) => {
		const result = last.then(operation);
		last = result.catch(() => undefined);
		return result;
	};
}
