function sanitizeParameters(text: string): string {
	return text.replace(
		/((?:^|[?&;/])(?:user(?:name)?|pass(?:word)?|pwd|token|key|api_key)=)([^&;\s]+)/gi,
		'$1***'
	);
}

export function sanitizeSourceForLogs(source: string): string {
	const sanitized = sanitizeParameters(source);

	try {
		const url = new URL(sanitized);
		url.username = url.username ? '***' : '';
		url.password = url.password ? '***' : '';
		return url.toString();
	} catch {
		return sanitized;
	}
}

export function sanitizeTextForLogs(text: string): string {
	return sanitizeParameters(text).replace(/[a-z][a-z0-9+.-]*:\/\/[^\s\r\n]+/gi, (source) =>
		sanitizeSourceForLogs(source)
	);
}
