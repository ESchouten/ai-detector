import type { Component } from 'svelte';
import { resolve } from '$app/paths';
import BellIcon from '@lucide/svelte/icons/bell';
import BracesIcon from '@lucide/svelte/icons/braces';
import CctvIcon from '@lucide/svelte/icons/cctv';
import FilmIcon from '@lucide/svelte/icons/film';
import HardDriveIcon from '@lucide/svelte/icons/hard-drive';
import ScanSearchIcon from '@lucide/svelte/icons/scan-search';
import ScrollTextIcon from '@lucide/svelte/icons/scroll-text';
import SettingsIcon from '@lucide/svelte/icons/settings';
import SmartphoneIcon from '@lucide/svelte/icons/smartphone';
import SparklesIcon from '@lucide/svelte/icons/sparkles';

export interface NavItem {
	title: string;
	href: string;
	icon: Component;
	/** Lit for every page of its area rather than only its own address. */
	area?: 'settings';
	/** Shown where there is room to explain the destination. */
	description?: string;
}

// The lists are functions so their titles are written in the language of each request.

/** What people open every day. */
export function mainNavigation(): NavItem[] {
	return [
		{ title: 'Recordings', href: resolve('/detections'), icon: FilmIcon },
		{ title: 'Cameras', href: resolve('/streams'), icon: CctvIcon },
		{ title: 'Detectors', href: resolve('/detectors'), icon: ScanSearchIcon }
	];
}

/** What people set once and return to occasionally. */
export function settingsNavigation(): NavItem[] {
	return [
		{
			title: 'Alerts',
			href: resolve('/notifications'),
			icon: BellIcon,
			description: 'Who gets a Telegram message when something is detected.'
		},
		{
			title: 'Validator',
			href: resolve('/validator'),
			icon: SparklesIcon,
			description: 'Let AI double-check detections before an alert is sent.'
		},
		{
			title: 'Devices',
			href: resolve('/devices'),
			icon: SmartphoneIcon,
			description: 'Phones and computers that can open this dashboard.'
		},
		{
			title: 'Storage',
			href: resolve('/storage'),
			icon: HardDriveIcon,
			description: 'Free space and old recordings.'
		},
		{
			title: 'Advanced',
			href: resolve('/advanced'),
			icon: BracesIcon,
			description: 'Edit thresholds, prompts and the detection engine as JSON.'
		}
	];
}

export function logsNavigation(): NavItem {
	return {
		title: 'Logs',
		href: resolve('/logs'),
		icon: ScrollTextIcon,
		description: 'Recent activity and a diagnostics download for support.'
	};
}

export function settingsHome(): NavItem {
	return { title: 'Settings', href: resolve('/settings'), icon: SettingsIcon, area: 'settings' };
}

export const REPOSITORY_URL = 'https://github.com/ESchouten/ai-detector';

export function isActive(item: NavItem, pathname: string): boolean {
	return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

/** The phone's fourth tab stands for every settings and support page. */
export function isSettingsArea(pathname: string): boolean {
	return [settingsHome(), ...settingsNavigation(), logsNavigation()].some((item) =>
		isActive(item, pathname)
	);
}
