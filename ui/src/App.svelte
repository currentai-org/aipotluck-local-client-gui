<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from './lib/Icon.svelte';
	import SetupSettings from './lib/SetupSettings.svelte';
	import { api, onRuntimeReady, onTaskDone, onTaskLog, type PairingPreview } from './lib/api';
	import {
		formatBytes,
		planItems,
		planTotal,
		progressCaption,
		screenFor,
		statusRows,
		type AppState,
		type InstallPlan,
		type Status
	} from './lib/state';

	let app = $state<AppState | null>(null);
	let status = $state<Status | null>(null);
	let log = $state<string[]>([]);
	let caption = $state<string | null>(null);
	let taskError = $state<string | null>(null);
	let clip = $state<PairingPreview | null>(null);
	let pasted = $state('');
	let showPaste = $state(false);
	let logEl: HTMLPreElement | undefined = $state();

	// Set up's plan: what it will install and how big. `modelHf` is the Customize override ('' =
	// upstream's default); `planFor` is the override the current plan was sized for.
	let modelHf = $state('');
	let customizing = $state(false);
	let plan = $state<InstallPlan | null>(null);
	let planFor = $state<string | null>(null);
	let planError = $state<string | null>(null);
	let planSeq = 0;

	const screen = $derived(screenFor(app));
	const busy = $derived(app && app.ready ? app.busy : null);
	const rows = $derived(app && app.ready ? statusRows(app, status) : []);
	const planPending = $derived(planFor !== modelHf);
	const items = $derived(plan ? planItems(plan, planPending) : []);
	const total = $derived(planTotal(items));

	async function loadPlan() {
		const seq = ++planSeq;
		const want = modelHf;
		planError = null;
		try {
			const p = await api.installPlan(want);
			if (seq !== planSeq) return; // a newer choice superseded this one
			plan = p;
			planFor = want;
		} catch (e) {
			if (seq !== planSeq) return;
			planError = String(e);
			planFor = want;
		}
	}

	function saveSettings(next: string) {
		customizing = false;
		if (next === modelHf) return;
		modelHf = next;
		loadPlan();
	}

	async function refresh() {
		try {
			app = await api.appState();
		} catch (e) {
			app = { ready: false, error: String(e) };
		}
		status = app.ready && app.service_healthy ? await api.status() : null;
		if (screen === 'setup' && app.ready && plan === null && planFor === null && planSeq === 0) loadPlan();
		if (screen === 'pair') clip = await api.clipboardPairing().catch(() => null);
	}

	async function run(fn: () => Promise<void>) {
		taskError = null;
		log = [];
		caption = null;
		try {
			await fn();
		} catch (e) {
			taskError = String(e);
		}
		await refresh();
	}

	onMount(() => {
		const unsubs = [
			onRuntimeReady(refresh),
			onTaskLog((e) => {
				log = [...log.slice(-400), e.line];
				const c = progressCaption(e.line);
				if (c) caption = c;
				queueMicrotask(() => logEl?.scrollTo({ top: logEl.scrollHeight }));
			}),
			onTaskDone(async (e) => {
				if (!e.ok) taskError = `That didn’t finish (exit code ${e.code}). The details are in the log below.`;
				else if (e.task === 'pair') pasted = '';
				await refresh();
			})
		];
		// Coming back from the browser with the code copied is the moment to notice it.
		const onFocus = () => refresh();
		window.addEventListener('focus', onFocus);
		refresh();
		const timer = setInterval(refresh, 3000);
		return () => {
			clearInterval(timer);
			window.removeEventListener('focus', onFocus);
			unsubs.forEach((u) => u.then((f) => f()));
		};
	});
</script>

<header class="topbar" data-surface="chrome">
	<span class="mark"><Icon name="computer-line" size={18} /></span>
	<span class="name">AI Potluck · Local client</span>
</header>

<main>
	{#if screen === 'starting'}
		<div class="stack">
			<p class="label">Starting</p>
			<div class="progress" aria-label="Preparing"></div>
			<p class="small">Preparing the bundled runtime. This only takes a moment the first time.</p>
		</div>
	{:else if screen === 'broken' && app && !app.ready}
		<div class="stack">
			<p class="label">Something’s wrong</p>
			<h1>This app couldn’t start its runtime</h1>
			<div class="error"><Icon name="error-warning-line" /><span class="mono">{app.error}</span></div>
			<p class="small">Reinstalling the app usually fixes this.</p>
		</div>
	{:else if screen === 'setup' && app?.ready && customizing && busy !== 'setup'}
		<SetupSettings
			{modelHf}
			defaultModel={plan?.model.default_id ?? ''}
			onsave={saveSettings}
			oncancel={() => (customizing = false)}
		/>
	{:else if screen === 'setup' && app?.ready}
		<div class="stack">
			<p class="label">Step 1 of 2</p>
			<h1>Set up this computer</h1>
			<p>
				Installs these for this computer’s hardware. Nothing is shared until you pair it with your AI
				Potluck account.
			</p>
		</div>
		<div class="card" aria-label="What will be installed">
			{#if plan}
				<ul class="plan">
					{#each items as item (item.name)}
						<li class="plan-item">
							<span class="plan-name">{item.name}</span>
							<span class="plan-size mono">
								{#if item.pending}Checking…{:else if item.bytes !== null}~{formatBytes(item.bytes)}{:else}—{/if}
							</span>
							<span class="plan-detail small">{item.detail}</span>
							{#if item.note && !item.pending}
								<span class="plan-note small" class:warn={item.warn}>
									{#if item.warn}<Icon name="error-warning-line" size={14} />{/if}{item.note}
								</span>
							{/if}
						</li>
					{/each}
				</ul>
				<div class="plan-item plan-total">
					<span class="plan-name">Total</span>
					<span class="plan-size mono">
						{planPending ? 'Checking…' : `~${formatBytes(total.bytes)}${total.partial ? ' +' : ''}`}
					</span>
				</div>
			{:else if planError}
				<div class="error"><Icon name="error-warning-line" /><span>Couldn’t work out what will be installed: {planError}</span></div>
			{:else}
				<div class="progress" aria-label="Checking what will be installed"></div>
				<p class="small">Checking what this computer needs…</p>
			{/if}
		</div>
		{#if planError && plan}
			<div class="error" role="alert"><Icon name="error-warning-line" /><span>{planError}</span></div>
		{/if}
		{#if busy === 'setup'}
			<div class="stack">
				<div class="progress" aria-label="Setting up"></div>
				<p class="small">{caption ?? 'Starting…'}</p>
			</div>
		{:else}
			<div class="setup-actions">
				<button class="btn primary" onclick={() => run(() => api.setupDevice(modelHf))}>
					<Icon name="download-2-line" /> Set up
				</button>
				<button class="btn secondary" disabled={!plan} onclick={() => (customizing = true)}>
					<Icon name="settings-3-line" /> Customize
				</button>
			</div>
		{/if}
		{#if !app.probe.service_manager_usable}
			<p class="small">
				This computer doesn’t have a background service manager available, so the server will run
				only while this window is open.
			</p>
			<details>
				<summary>Why</summary>
				<p class="small mono">{app.probe.service_manager_detail}</p>
			</details>
		{/if}
	{:else if screen === 'pair' && app?.ready}
		<div class="stack">
			<p class="label">Step 2 of 2</p>
			<h1>Pair with AI Potluck</h1>
			<p>
				On aipotluck.org, open <span class="mono small">Settings → Local Inference</span>, choose
				<em>Add a managed server</em>, click <em>Pair</em>, then <em>Copy</em>. Come back here.
			</p>
		</div>

		{#if clip}
			<div class="card" data-surface="2">
				<p class="label">Pairing code found on your clipboard</p>
				<p class="small mono">{clip.tunnel_endpoint}</p>
				<button class="btn primary block" disabled={!!busy} onclick={() => run(() => api.pair())}>
					<Icon name="link" /> Pair this computer
				</button>
			</div>
		{:else}
			<div class="row">
				<button class="btn secondary" onclick={() => api.openSettingsPage().catch((e) => (taskError = String(e)))}>
					<Icon name="external-link-line" /> Open aipotluck.org
				</button>
				<button class="btn ghost" onclick={() => (showPaste = !showPaste)}>
					<Icon name="clipboard-line" /> Paste instead
				</button>
			</div>
			<p class="small">Waiting for the pairing code… this screen picks it up as soon as it’s copied.</p>
		{/if}

		{#if showPaste}
			<div class="stack">
				<textarea
					class="paste"
					placeholder="Paste the pairing code here"
					bind:value={pasted}
					autocomplete="off"
					spellcheck="false"
				></textarea>
				<button class="btn secondary" disabled={!pasted.trim() || !!busy} onclick={() => run(() => api.pair(pasted))}>
					<Icon name="link" /> Pair
				</button>
			</div>
		{/if}

		{#if busy === 'pair'}
			<div class="stack">
				<div class="progress" aria-label="Pairing"></div>
				<p class="small">{caption ?? 'Pairing…'}</p>
			</div>
		{/if}
	{:else if screen === 'running' && app?.ready}
		<div class="stack">
			<p class="label">This computer</p>
			<h1>Sharing with AI Potluck</h1>
		</div>
		<div class="card">
			{#each rows as r (r.label)}
				<div class="status-row">
					<span class="light {r.light}" aria-hidden="true"></span>
					<span class="status-label">{r.label}</span>
					<span class="status-text">{r.text}</span>
				</div>
			{/each}
		</div>
		{#if status?.runtime_config?.llama_cpp?.tag}
			<p class="small mono">
				llama.cpp {status.runtime_config.llama_cpp.tag} · {status.runtime_config.llama_cpp.asset_key}
			</p>
		{/if}
		<div class="row">
			<button class="btn secondary" onclick={() => api.openSettingsPage().catch((e) => (taskError = String(e)))}>
				<Icon name="external-link-line" /> Manage on aipotluck.org
			</button>
			<button class="btn destructive" disabled={!!busy} onclick={() => run(api.unpair)}>
				<Icon name="logout-box-r-line" /> Unpair
			</button>
		</div>
	{/if}

	{#if taskError}
		<div class="error" role="alert"><Icon name="error-warning-line" /><span>{taskError}</span></div>
	{/if}

	{#if log.length}
		<details open={!!taskError}>
			<summary>Details</summary>
			<pre class="log" bind:this={logEl}>{log.join('\n')}</pre>
		</details>
	{/if}
</main>

<footer>
	{#if app?.ready}
		aipotluck-local-client {app.upstream_sha.slice(0, 7)}{app.hosted_by_gui ? ' · hosted by this window' : ''}
	{/if}
</footer>
