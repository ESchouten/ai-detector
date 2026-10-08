/**
 * Whether a device has a home screen that does not hold the application yet: a phone or tablet,
 * until the application is opened from the home screen. An iPad presents itself as a Mac, except
 * that it has a touch screen.
 */
export function lacksHomeScreenIcon(device: {
	userAgent: string;
	maxTouchPoints: number;
	standalone: boolean;
}): boolean {
	if (device.standalone) return false;
	return (
		/iPhone|iPad|iPod|Android/.test(device.userAgent) ||
		(/Macintosh/.test(device.userAgent) && device.maxTouchPoints > 1)
	);
}

/** The same for the device this page is open on. */
export function deviceLacksHomeScreenIcon(): boolean {
	return lacksHomeScreenIcon({
		userAgent: navigator.userAgent,
		maxTouchPoints: navigator.maxTouchPoints,
		standalone:
			matchMedia('(display-mode: standalone)').matches ||
			(navigator as Navigator & { standalone?: boolean }).standalone === true
	});
}

/**
 * Whether the home screen of this device can only hold a link to the page: Android makes a web
 * page an app over HTTPS only, and a link opens in the browser as before.
 */
export function holdsOnlyShortcut(device: { userAgent: string; secure: boolean }): boolean {
	return /Android/.test(device.userAgent) && !device.secure;
}

/** The same for the device this page is open on. */
export function deviceHoldsOnlyShortcut(): boolean {
	return holdsOnlyShortcut({ userAgent: navigator.userAgent, secure: isSecureContext });
}
