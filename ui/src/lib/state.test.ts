import { describe, expect, it } from 'vitest';
import { progressCaption, screenFor, statusRows, type AppState, type Probe } from './state';

const probe = (over: Partial<Probe> = {}): Probe => ({
	os: 'linux',
	installed: true,
	logged_in: true,
	service_manager_usable: true,
	service_manager_detail: '',
	service: { state: 'running', detail: '' },
	layout: { install_root: '/i', config_dir: '/c', log_dir: '/l', state_dir: '/s' },
	runtime_json_error: null,
	...over
});
const app = (over: Partial<Probe> = {}, rest: Record<string, unknown> = {}) =>
	({
		ready: true,
		probe: probe(over),
		service_healthy: true,
		hosted_by_gui: false,
		upstream_sha: 'abc',
		busy: null,
		settings_url: 'https://x',
		...rest
	}) as AppState & { ready: true };

describe('screenFor', () => {
	it('a fresh machine lands on setup, a set-up one on pair, a paired one on running', () => {
		expect(screenFor(app({ installed: false, logged_in: false }))).toBe('setup');
		expect(screenFor(app({ installed: true, logged_in: false }))).toBe('pair');
		expect(screenFor(app())).toBe('running');
	});
	it('stays on setup while the installer runs, even once runtime.json appears mid-install', () => {
		expect(screenFor(app({ installed: true, logged_in: false }, { busy: 'setup' }))).toBe('setup');
	});
	it('a runtime that failed to unpack is shown as broken, not as still starting', () => {
		expect(screenFor({ ready: false, error: 'corrupt' })).toBe('broken');
		expect(screenFor({ ready: false })).toBe('starting');
	});
});

describe('statusRows', () => {
	it('a running newt that has not connected is reported as a problem, never as connected', () => {
		const rows = statusRows(app(), {
			logged_in: true,
			llama_server: { running: true, healthy: true },
			tunnel: { running: true, tunnel_connected: false }
		});
		const tunnel = rows.find((r) => r.label.startsWith('Connection'))!;
		expect(tunnel.light).toBe('bad');
	});
	it('no signal yet from newt is "connecting", not a failure', () => {
		const rows = statusRows(app(), {
			logged_in: true,
			llama_server: { running: true, healthy: true },
			tunnel: { running: true, tunnel_connected: null }
		});
		expect(rows.find((r) => r.label.startsWith('Connection'))!.light).toBe('wait');
	});
	it('says the service only lives as long as the window when the GUI is hosting it', () => {
		expect(statusRows(app({}, { hosted_by_gui: true }), null)[0].text).toMatch(/window is open/);
	});
});

describe('progressCaption', () => {
	it('strips upstream log prefixes and drops banner rules', () => {
		expect(progressCaption('[INFO] aipotluck.installer: Resolved asset: linux-x64-cpu (x.tar.gz)')).toBe(
			'Resolved asset: linux-x64-cpu (x.tar.gz)'
		);
		expect(progressCaption('=========================')).toBeNull();
	});
});
