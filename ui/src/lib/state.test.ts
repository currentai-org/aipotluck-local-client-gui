import { describe, expect, it } from 'vitest';
import {
	formatBytes,
	isModelId,
	normaliseModelId,
	planItems,
	planTotal,
	progressCaption,
	screenFor,
	statusRows,
	combinedStatus,
	type Row,
	type AppState,
	type InstallPlan,
	type Probe,
	BACKEND_INFO
} from './state';

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

describe('combinedStatus', () => {
	const ok = (label: string, text = 'fine'): Row => ({ label, light: 'ok', text });
	const all = (...over: Row[]): Row[] => {
		const base = [ok('Service', 'Running in the background'), ok('Inference server', 'Ready'), ok('Connection to AI Potluck', 'Connected')];
		return base.map((r) => over.find((o) => o.label === r.label) ?? r);
	};

	it('all three healthy is one green light, "All running"', () => {
		expect(combinedStatus(all())).toMatchObject({ light: 'ok', text: 'All running' });
	});

	it('one yellow component turns the light yellow and names it', () => {
		const c = combinedStatus(all({ label: 'Connection to AI Potluck', light: 'wait', text: 'Connecting…' }));
		expect(c).toMatchObject({ light: 'wait', text: 'Connection: connecting…' });
	});

	it('red beats yellow, and the line names the red one, not the yellow one', () => {
		const c = combinedStatus(
			all(
				{ label: 'Inference server', light: 'wait', text: 'Starting…' },
				{ label: 'Connection to AI Potluck', light: 'bad', text: 'Can’t reach AI Potluck — retrying' }
			)
		);
		expect(c.light).toBe('bad');
		expect(c.text).toBe('Connection: can’t reach AI Potluck — retrying');
	});

	it('several components at the worst level are all named, in one line', () => {
		const c = combinedStatus(
			all({ label: 'Service', light: 'bad', text: 'Not responding' }, { label: 'Inference server', light: 'bad', text: 'Not started' })
		);
		expect(c).toMatchObject({ light: 'bad', text: 'Service and Inference server need attention' });
		expect(c.text).not.toContain('\n');
	});

	it('a component that has not reported (off) never reads as green', () => {
		expect(combinedStatus(all({ label: 'Inference server', light: 'off', text: 'Stopped until paired' })).light).toBe('wait');
		expect(combinedStatus([]).light).toBe('wait');
	});

	it('keeps every component’s own line for the tooltip, so nothing the three rows said is lost', () => {
		const c = combinedStatus(all({ label: 'Connection to AI Potluck', light: 'bad', text: 'Can’t reach AI Potluck — retrying' }));
		expect(c.detail.split('\n')).toEqual([
			'Service: Running in the background',
			'Inference server: Ready',
			'Connection to AI Potluck: Can’t reach AI Potluck — retrying'
		]);
	});

	it('still says when the service only lives as long as the window', () => {
		expect(combinedStatus(all(), true).text).toMatch(/window closes/);
	});

	it('works end to end from what upstream reports', () => {
		const c = combinedStatus(
			statusRows(app({}, { hosted_by_gui: true }), {
				logged_in: true,
				llama_server: { running: true, healthy: true },
				tunnel: { running: true, tunnel_connected: false }
			}),
			true
		);
		expect(c).toMatchObject({ light: 'bad', text: 'Connection: can’t reach AI Potluck — retrying' });
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

const plan = (over: Partial<InstallPlan> = {}): InstallPlan => ({
	host: { os: 'linux', arch: 'x64', backend: 'cpu' },
	client: { bytes: 107_000_000, upstream_sha: '2ac25915bc15ab7f' },
	llama_cpp: {
		tag: 'b10989',
		asset_key: 'linux-x64-cpu',
		file: 'llama-b10989-bin-ubuntu-x64.tar.gz',
		bytes: 16_844_042,
		source_build: false
	},
	newt: { tag: '1.18.1', file: 'newt_linux_amd64', bytes: 39_305_900 },
	model: {
		id: 'bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M',
		is_default: true,
		default_id: 'bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M',
		bytes: 397_808_192,
		files: ['Qwen2.5-0.5B-Instruct-Q4_K_M.gguf']
	},
	...over
});

describe('formatBytes', () => {
	it('rounds like a person would say it, in decimal units', () => {
		expect(formatBytes(16_844_042)).toBe('17 MB');
		expect(formatBytes(397_808_192)).toBe('398 MB');
		expect(formatBytes(2_497_281_312)).toBe('2.5 GB');
		expect(formatBytes(2_000_000_000)).toBe('2 GB');
		expect(formatBytes(512)).toBe('512 B');
	});
});

describe('planItems', () => {
	const windowsCuda = (): InstallPlan => {
		const p = plan();
		p.host = { os: 'windows', arch: 'x64', backend: 'cuda' };
		p.llama_cpp = { ...p.llama_cpp, asset_key: 'windows-x64-cuda', file: 'llama-b10989-bin-win-cuda-12.4-x64.zip', bytes: 645_642_643 };
		p.backends = {
			auto: 'cuda',
			selected: 'cuda',
			options: [
				{ backend: 'cuda', available: true, bytes: 645_642_643 },
				{ backend: 'vulkan', available: true, bytes: 31_691_031 },
				{ backend: 'cpu', available: true, bytes: 18_428_704 }
			]
		};
		return p;
	};

	it('a Windows CUDA plan counts the CUDA runtime and points at the much smaller Vulkan build', () => {
		const llama = planItems(windowsCuda())[1];
		expect(llama.detail).toContain('CUDA build');
		expect(llama.bytes).toBe(645_642_643);
		expect(llama.note).toMatch(/CUDA runtime/);
		expect(llama.note).toMatch(/Vulkan is ~32 MB: choose it in Customize/);
	});

	it('a Vulkan or CPU plan makes no such suggestion', () => {
		const p = windowsCuda();
		p.host.backend = 'vulkan';
		p.llama_cpp = { ...p.llama_cpp, asset_key: 'windows-x64-vulkan', bytes: 31_691_031 };
		expect(planItems(p)[1].note).toBe('download; larger once unpacked');
		expect(planItems(plan())[1].note).toBe('download; larger once unpacked');
	});

	it('lists client, llama.cpp, newt and model, in install order, with their sizes', () => {
		const items = planItems(plan());
		expect(items.map((i) => i.name)).toEqual(['Client', 'llama.cpp', 'newt', 'Model (starter)']);
		expect(items.map((i) => i.bytes)).toEqual([107_000_000, 16_844_042, 39_305_900, 397_808_192]);
		expect(items[1].detail).toContain('CPU build');
		expect(items[3].detail).toBe('bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M');
	});

	it('a model whose size hugging face would not give is flagged, never shown as zero', () => {
		const p = plan();
		p.model = { ...p.model, id: 'nobody/nothing', is_default: false, bytes: null };
		const model = planItems(p)[3];
		expect(model.bytes).toBeNull();
		expect(model.warn).toBe(true);
		expect(planTotal(planItems(p)).partial).toBe(true);
	});

	it('a model being re-sized shows as pending under its own name, not the previous model’s', () => {
		const model = planItems(plan(), 'unsloth/Qwen3-4B-GGUF')[3];
		expect(model.pending).toBe(true);
		expect(model.detail).toBe('unsloth/Qwen3-4B-GGUF');
		expect(model.name).toBe('Model');
		expect(model.bytes).toBeNull();
		expect(model.warn).toBeFalsy();
	});

	it('going back to the default while re-sizing names the starter model', () => {
		const p = plan();
		p.model = { ...p.model, id: 'unsloth/Qwen3-4B-GGUF', is_default: false, bytes: 2_497_281_312 };
		const model = planItems(p, '')[3];
		expect(model.detail).toBe(p.model.default_id);
		expect(model.name).toBe('Model (starter)');
	});

	it('a source-build host never claims a download size for llama.cpp', () => {
		const p = plan();
		p.llama_cpp = { ...p.llama_cpp, source_build: true, bytes: 123 };
		expect(planItems(p)[1].bytes).toBeNull();
	});

	it('the total adds what was measured', () => {
		expect(planTotal(planItems(plan()))).toEqual({ bytes: 560_958_134, partial: false });
	});
});

describe('model id', () => {
	it('a pasted hugging face page url becomes its repo id', () => {
		expect(normaliseModelId(' https://huggingface.co/unsloth/Qwen3-4B-GGUF/tree/main?x=1 ')).toBe(
			'unsloth/Qwen3-4B-GGUF'
		);
		expect(normaliseModelId('  org/repo:Q8_0 ')).toBe('org/repo:Q8_0');
	});

	it('accepts owner/repo with an optional quant, the shape upstream takes', () => {
		expect(isModelId('bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M')).toBe(true);
		expect(isModelId('unsloth/Qwen3-4B-GGUF')).toBe(true);
	});

	it('nothing that could read as a flag or a path is accepted as a model id', () => {
		for (const bad of ['--system', '-x/y', 'org/--x', '../etc', 'org/../x', '/abs', 'org/a/b', 'org/r:Q4 x', 'org/r:', 'name', ''])
			expect(isModelId(bad), bad).toBe(false);
	});
});

describe('BACKEND_INFO', () => {
	it('has a one-sentence reason for each compute choice', () => {
		for (const [key, info] of Object.entries(BACKEND_INFO)) {
			expect(info.why, key).toMatch(/^[^.]+\.$/); // exactly one sentence
			expect(info.why.length, key).toBeLessThan(140);
		}
		expect(Object.keys(BACKEND_INFO)).toEqual(['cuda', 'vulkan', 'cpu']);
	});
});
