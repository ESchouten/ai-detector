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
	return sanitizeParameters(text)
		.replace(/(pairing code:\s*)\d{6}/gi, '$1***')
		.replace(/\bbot\d+:[A-Za-z0-9_-]+/g, 'bot***')
		.replace(/\b[a-z][a-z0-9+.-]*:\/\/[^\s\r\n]+/gi, (source) => sanitizeSourceForLogs(source));
}
