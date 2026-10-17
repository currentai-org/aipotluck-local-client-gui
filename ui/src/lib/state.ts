// Which screen to show, derived only from what upstream reports. Pure, so it is unit-tested.

export type Probe = {
	os: string;
	installed: boolean;
	logged_in: boolean;
	service_manager_usable: boolean;
	service_manager_detail: string;
	service: { state: string; detail: string } | null;
	layout: { install_root: string; config_dir: string; log_dir: string; state_dir: string };
	runtime_json_error: string | null;
};

export type AppState =
	| { ready: false; error?: string }
	| {
			ready: true;
			probe: Probe;
			service_healthy: boolean;
			hosted_by_gui: boolean;
			upstream_sha: string;
			busy: string | null;
			settings_url: string;
	  };

/** Upstream's GET /status, the fields this UI reads. Everything else is ignored, never rejected. */
export type Status = {
	logged_in?: boolean;
	llama_server?: {
		running?: boolean;
		healthy?: boolean;
		restart_count?: number;
		last_error?: string;
		error?: string;
	} | null;
	tunnel?: {
		running?: boolean;
		tunnel_connected?: boolean | null;
		restart_count?: number;
		last_error?: string;
	} | null;
	held_back_models?: Record<string, unknown> | unknown[];
	runtime_config?: { llama_cpp?: { tag?: string; asset_key?: string } };
};

export type Screen = 'starting' | 'broken' | 'setup' | 'pair' | 'running';

export function screenFor(app: AppState | null): Screen {
	if (!app) return 'starting';
	if (!app.ready) return app.error ? 'broken' : 'starting';
	if (app.busy === 'setup') return 'setup';
	if (!app.probe.installed) return 'setup';
	if (!app.probe.logged_in) return 'pair';
	return 'running';
}

export type Light = 'ok' | 'wait' | 'bad' | 'off';
export type Row = { label: string; light: Light; text: string };

/**
 * One line per moving part. "Running" and "connected" are different claims (upstream README:
 * newt retries forever and never exits on a failed connection), so the tunnel row reads
 * `tunnel_connected`, never just `running`.
 */
export function statusRows(app: AppState & { ready: true }, status: Status | null): Row[] {
	const rows: Row[] = [];
	rows.push(
		app.service_healthy
			? {
					label: 'Service',
					light: 'ok',
					text: app.hosted_by_gui ? 'Running while this window is open' : 'Running in the background'
				}
			: { label: 'Service', light: 'bad', text: 'Not responding' }
	);
	if (!status) return rows;

	const llama = status.llama_server;
	if (!status.logged_in) rows.push({ label: 'Inference server', light: 'off', text: 'Stopped until paired' });
	else if (!llama || llama.error) rows.push({ label: 'Inference server', light: 'bad', text: llama?.error ?? 'Not started' });
	else if (llama.healthy) rows.push({ label: 'Inference server', light: 'ok', text: 'Ready' });
	else if (llama.running) rows.push({ label: 'Inference server', light: 'wait', text: 'Starting…' });
	else rows.push({ label: 'Inference server', light: 'bad', text: llama.last_error || 'Not running' });

	const t = status.tunnel;
	if (!status.logged_in) rows.push({ label: 'Connection to AI Potluck', light: 'off', text: 'Not paired' });
	else if (!t || !t.running) rows.push({ label: 'Connection to AI Potluck', light: 'bad', text: t?.last_error || 'Not running' });
	else if (t.tunnel_connected === true) rows.push({ label: 'Connection to AI Potluck', light: 'ok', text: 'Connected' });
	else if (t.tunnel_connected === false)
		rows.push({ label: 'Connection to AI Potluck', light: 'bad', text: 'Can’t reach AI Potluck — retrying' });
	else rows.push({ label: 'Connection to AI Potluck', light: 'wait', text: 'Connecting…' });
	return rows;
}

/** The short names the combined status line uses for each component. */
const SHORT: Record<string, string> = {
	Service: 'Service',
	'Inference server': 'Inference server',
	'Connection to AI Potluck': 'Connection'
};
const SEVERITY: Record<Light, number> = { ok: 0, off: 1, wait: 1, bad: 2 };

export type Combined = {
	light: Light;
	/** One short line: "All running", or which component is behind the light and why. */
	text: string;
	/** Every component's own line, for a tooltip, so nothing the three rows said is lost. */
	detail: string;
};

/**
 * One light for all of `statusRows`: the worst component wins (red over yellow over green), and
 * the line under it names the component(s) responsible. A component that hasn't reported yet
 * (`off`) counts as yellow, never green -- an unknown is not an OK.
 */
export function combinedStatus(rows: Row[], hostedByGui = false): Combined {
	const detail = rows.map((r) => `${r.label}: ${r.text}`).join('\n');
	if (!rows.length) return { light: 'wait', text: 'Checking…', detail };
	const worst = Math.max(...rows.map((r) => SEVERITY[r.light]));
	if (worst === 0) {
		return { light: 'ok', text: hostedByGui ? 'All running · until this window closes' : 'All running', detail };
	}
	const light: Light = worst === 2 ? 'bad' : 'wait';
	const culprits = rows.filter((r) => SEVERITY[r.light] === worst);
	const names = culprits.map((r) => SHORT[r.label] ?? r.label);
	if (culprits.length === 1) {
		const t = culprits[0].text;
		return { light, text: `${names[0]}: ${t.charAt(0).toLowerCase()}${t.slice(1)}`, detail };
	}
	const list = names.length === 2 ? names.join(' and ') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
	return { light, text: `${list} ${light === 'bad' ? 'need attention' : 'starting…'}`, detail };
}

/** Turn an upstream log line (`[LEVEL] logger.name: message`) into a short progress caption. */
export function progressCaption(line: string): string | null {
	const m = line.match(/^\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\] [\w.]+: (.*)$/);
	const msg = (m ? m[2] : line).trim();
	if (!msg || /^[=-]{10,}$/.test(msg)) return null;
	return msg.length > 140 ? msg.slice(0, 137) + '…' : msg;
}

/** What Set up would install (src-tauri `install_plan`, sidecar/gui_plan.py). Sizes are bytes or null (unknown). */
export type InstallPlan = {
	host: { os: string; arch: string; backend: string };
	client: { bytes: number; upstream_sha: string };
	llama_cpp: {
		tag: string | null;
		asset_key: string | null;
		file: string | null;
		bytes: number | null;
		source_build: boolean;
		reason?: string;
		error?: string;
	};
	newt: { tag: string | null; file: string | null; bytes: number | null; error?: string };
	model: { id: string; is_default: boolean; default_id: string; bytes: number | null; files: string[] };
};

/** Decimal units, like Hugging Face and GitHub show them, rounded the way a person would say it. */
export function formatBytes(bytes: number): string {
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	let v = bytes;
	let i = 0;
	while (v >= 1000 && i < units.length - 1) {
		v /= 1000;
		i++;
	}
	const shown = v >= 10 || i === 0 ? Math.round(v).toString() : v.toFixed(1).replace(/\.0$/, '');
	return `${shown} ${units[i]}`;
}

export type PlanItem = {
	name: string;
	detail: string;
	/** null: couldn't be measured; `pending`: being measured right now. */
	bytes: number | null;
	pending?: boolean;
	note?: string;
	warn?: boolean;
};

const BACKEND_NAMES: Record<string, string> = { cpu: 'CPU', cuda: 'CUDA', vulkan: 'Vulkan', rocm: 'ROCm' };

/**
 * One line per thing Set up puts on this computer, in the order it happens. `pendingModel` is the
 * model just chosen in Customize while it is being sized ('' = back to the default): its row names
 * that model and reads "Checking…", never the previous model's name or size.
 */
export function planItems(plan: InstallPlan, pendingModel: string | null = null): PlanItem[] {
	const modelPending = pendingModel !== null;
	const llama = plan.llama_cpp;
	const backend = llama.asset_key ? llama.asset_key.split('-').slice(-1)[0] : plan.host.backend;
	const llamaItem: PlanItem = {
		name: 'llama.cpp',
		detail: `Inference server · ${llama.tag ?? '?'} · ${BACKEND_NAMES[backend] ?? backend} build`,
		bytes: llama.bytes,
		note: 'download; larger once unpacked'
	};
	if (llama.source_build) {
		llamaItem.bytes = null;
		llamaItem.note = 'built from source on this computer';
	} else if (llama.error) {
		llamaItem.note = llama.error;
		llamaItem.warn = true;
	}
	const newtItem: PlanItem = {
		name: 'newt',
		detail: `Tunnel to AI Potluck · ${plan.newt.tag ?? '?'}`,
		bytes: plan.newt.bytes,
		note: 'downloaded when you pair'
	};
	if (plan.newt.error) {
		newtItem.note = plan.newt.error;
		newtItem.warn = true;
	}
	const modelId = modelPending ? pendingModel || plan.model.default_id : plan.model.id;
	const modelItem: PlanItem = {
		name: modelId === plan.model.default_id ? 'Model (starter)' : 'Model',
		detail: modelId,
		bytes: modelPending ? null : plan.model.bytes,
		pending: modelPending
	};
	if (!modelPending && plan.model.bytes === null) {
		modelItem.note = 'couldn’t read its size from Hugging Face; check the name, or Set up may fail';
		modelItem.warn = true;
	}
	return [
		{
			name: 'Client',
			detail: `aipotluck-local-client ${plan.client.upstream_sha.slice(0, 7)} and its Python runtime`,
			bytes: plan.client.bytes
		},
		llamaItem,
		newtItem,
		modelItem
	];
}

/** Sum of what could be measured, and whether anything couldn't. */
export function planTotal(items: PlanItem[]): { bytes: number; partial: boolean } {
	return {
		bytes: items.reduce((n, i) => n + (i.bytes ?? 0), 0),
		partial: items.some((i) => i.bytes === null)
	};
}

const HF_URL = /^https?:\/\/(?:www\.)?huggingface\.co\//i;

/**
 * What a person typed or pasted into the model field, as `owner/repo[:quant]`: trimmed, and a
 * pasted huggingface.co page URL reduced to its repo. Empty means "use the default".
 */
export function normaliseModelId(raw: string): string {
	let s = raw.trim();
	if (HF_URL.test(s)) s = s.replace(HF_URL, '').split(/[?#]/)[0].split('/').slice(0, 2).join('/');
	return s;
}

const PART = '[A-Za-z0-9](?:[A-Za-z0-9._-]{0,95})';
const MODEL_ID = new RegExp(`^${PART}/${PART}(?::[A-Za-z0-9._-]{1,64})?$`);

/**
 * Same shape src-tauri/src/model_id.rs enforces (which is the real boundary; this is only so the
 * settings page can say so before it closes).
 */
export function isModelId(id: string): boolean {
	return MODEL_ID.test(id) && !/--|\.\./.test(id.split(':')[0]);
}
