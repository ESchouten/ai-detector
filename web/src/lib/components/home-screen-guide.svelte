<script lang="ts">
	import { asset } from '$app/paths';
	import { page } from '$app/state';
	import type { PWAInstallElement } from '@khmyznikov/pwa-install';

	// A phone has no button for this that a page may press, so the person is shown the way. The
	// steps come from pwa-install, which follows what each phone and browser shows and speaks the
	// phone's own language. It is fetched when someone asks for the steps.
	let element: PWAInstallElement;

	export async function show(): Promise<void> {
		await import('@khmyznikov/pwa-install');
		// It first works out what this device can do, and has done so once it has drawn itself.
		await element.updateComplete;
		// Over plain HTTP Android installs nothing and its Install button would do nothing, so
		// show the steps for adding the page by hand, as for a browser that cannot install.
		if (element.isAndroid && !isSecureContext) element.isAndroidFallback = true;
		element.showDialog(true);
	}
</script>

<pwa-install
	bind:this={element}
	manual-apple
	manual-chrome
	manual-how-to
	disable-install-description
	description={page.url.host}
	manifest-url={asset('/manifest.webmanifest')}
></pwa-install>
