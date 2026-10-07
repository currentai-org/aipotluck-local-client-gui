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

/** Turn an upstream log line (`[LEVEL] logger.name: message`) into a short progress caption. */
export function progressCaption(line: string): string | null {
	const m = line.match(/^\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\] [\w.]+: (.*)$/);
	const msg = (m ? m[2] : line).trim();
	if (!msg || /^[=-]{10,}$/.test(msg)) return null;
	return msg.length > 140 ? msg.slice(0, 137) + '…' : msg;
}
