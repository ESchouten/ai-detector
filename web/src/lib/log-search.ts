/** Keep each timestamped message and its traceback together when searching. */
export function searchLog(text: string, search: string): string {
	const query = search.trim().toLowerCase();
	if (!query) return text;
	return text
		.split(/(?=^\d{4}-\d{2}-\d{2}[T ])/m)
		.filter((entry) => entry.toLowerCase().includes(query))
		.join('\n');
}
