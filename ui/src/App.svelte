<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from './lib/Icon.svelte';
	import Models from './lib/Models.svelte';
	import SetupSettings from './lib/SetupSettings.svelte';
	import ServerOverride from './lib/ServerOverride.svelte';
	import {
		browserOpened,
		latestPairingLink,
		oneClickUnavailable,
		pairingCancelled,
		pairingFailure,
		serverOf
	} from './lib/oneclick';
	import UninstallDialog from './lib/UninstallDialog.svelte';
	import { api, onRuntimeReady, onTaskDone, onTaskLog, type PairingPreview } from './lib/api';
	import {
		formatBytes,
		planItems,
		planTotal,
		progressCaption,
		screenFor,
		statusRows,
		combinedStatus,
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
	// Which pairing ran last, so the log is read the right way: 'oneclick' prints a link and waits.
	let pairMode = $state<'oneclick' | 'paste' | null>(null);
	let copied = $state(false);
	let logEl: HTMLPreElement | undefined = $state();
	let uninstalling = $state(false);

	// Set up's plan: what it will install and how big. `modelHf` and `backend` are the Customize
	// overrides ('' = upstream's default model / auto-detected compute); `planFor` is the pair the
	// current plan was sized for.
	let modelHf = $state('');
	let backend = $state('');
	const choiceKey = $derived(`${backend}|${modelHf}`);
	let customizing = $state(false);
	let plan = $state<InstallPlan | null>(null);
	let planFor = $state<string | null>(null);
	let planError = $state<string | null>(null);
	let planSeq = 0;

	const screen = $derived(screenFor(app));
	const busy = $derived(app && app.ready ? app.busy : null);
	const rows = $derived(app && app.ready ? statusRows(app, status) : []);
	const summary = $derived(combinedStatus(rows, !!(app && app.ready && app.hosted_by_gui)));
	const planPending = $derived(planFor !== choiceKey);
	const modelPending = $derived(planPending && planFor !== null && planFor.split('|').slice(1).join('|') !== modelHf);
	const items = $derived(
		plan
			? planItems(plan, modelPending ? modelHf : null).map((i) =>
					i.name === 'llama.cpp' && planPending ? { ...i, bytes: null, pending: true } : i
				)
			: []
	);
	const total = $derived(planTotal(items));
	const waiting = $derived(busy === 'pair' && pairMode === 'oneclick');
	const link = $derived(pairMode === 'oneclick' ? latestPairingLink(log) : null);
	const opened = $derived(browserOpened(log));
	const noOneClick = $derived(pairMode === 'oneclick' && !waiting && oneClickUnavailable(log));
	const cancelled = $derived(pairMode === 'oneclick' && !waiting && pairingCancelled(log));
	const override = $derived(app && app.ready ? (app.server_url_override ?? null) : null);

	function pairOneClick() {
		pairMode = 'oneclick';
		showPaste = false;
		copied = false;
		run(api.pairOneClick);
	}

	function pairPasted(text?: string) {
		pairMode = 'paste';
		run(() => api.pair(text));
	}

	async function copyLink() {
		if (!link) return;
		try {
			await navigator.clipboard.writeText(link);
			copied = true;
		} catch {
			copied = false;
		}
	}

	async function loadPlan() {
		const seq = ++planSeq;
		const want = choiceKey;
		const [wantBackend, wantModel] = [backend, modelHf];
		planError = null;
		try {
			const p = await api.installPlan(wantModel, wantBackend);
			if (seq !== planSeq) return; // a newer choice superseded this one
			plan = p;
			planFor = want;
		} catch (e) {
			if (seq !== planSeq) return;
			planError = String(e);
			planFor = want;
		}
	}

	function saveSettings(next: { modelHf: string; backend: string }) {
		customizing = false;
		if (next.modelHf === modelHf && next.backend === backend) return;
		modelHf = next.modelHf;
		backend = next.backend;
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
				if (e.task === 'uninstall' && !e.ok) uninstalling = false;
				if (e.task === 'pair' && pairMode === 'oneclick' && !e.ok) {
					// Upstream's own reason (timed out, server refused, ...) beats an exit code; a cancel
					// the person asked for isn't an error at all.
					taskError = pairingCancelled(log) ? null : (pairingFailure(log) ?? `Pairing didn’t finish (exit code ${e.code}).`);
				} else if (!e.ok) taskError = `That didn’t finish (exit code ${e.code}). The details are in the log below.`;
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
			{backend}
			backends={plan?.backends ?? null}
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
				<button class="btn primary" onclick={() => run(() => api.setupDevice(modelHf, backend))}>
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
			<p>Approve this computer in your browser, signed in to your AI Potluck account. That’s it.</p>
		</div>

		{#if waiting}
			<div class="card" data-surface="2" aria-live="polite">
				<p class="label">Waiting for your approval</p>
				{#if link}
					<p class="small">
						{opened ? 'We opened this link in your browser.' : 'Open this link in a browser where you’re signed in to AI Potluck.'}
						It works on any device, and expires in 10 minutes.
					</p>
					<p class="small mono pair-link" title={link}>{serverOf(link)}/chat/local-inference/pair</p>
					<div class="row">
						<button class="btn secondary" onclick={() => link && api.openUrl(link).catch((e) => (taskError = String(e)))}>
							<Icon name="external-link-line" /> {opened ? 'Open it again' : 'Open in browser'}
						</button>
						<button class="btn ghost" onclick={copyLink}>
							<Icon name={copied ? 'check-line' : 'clipboard-line'} /> {copied ? 'Copied' : 'Copy link'}
						</button>
					</div>
				{:else}
					<p class="small">{caption ?? 'Getting a pairing link…'}</p>
				{/if}
				<div class="progress" aria-label="Waiting for approval"></div>
				<button class="btn ghost" onclick={() => api.cancelPairing().catch((e) => (taskError = String(e)))}>
					<Icon name="close-line" /> Cancel
				</button>
			</div>
		{:else if busy === 'pair'}
			<div class="stack">
				<div class="progress" aria-label="Pairing"></div>
				<p class="small">{caption ?? 'Pairing…'}</p>
			</div>
		{:else}
			{#if clip}
				<!-- The code is already on the clipboard (copied from Settings): one click either way. -->
				<div class="card" data-surface="2">
					<p class="label">Pairing code found on your clipboard</p>
					<p class="small mono">{clip.tunnel_endpoint}</p>
					<button class="btn primary block" disabled={!!busy} onclick={() => pairPasted()}>
						<Icon name="link" /> Pair with this code
					</button>
				</div>
			{/if}
			<button class={clip ? 'btn secondary block' : 'btn primary block'} disabled={!!busy} onclick={pairOneClick}>
				<Icon name="link" /> Pair in your browser
			</button>
			{#if cancelled}
				<p class="small">Pairing cancelled. Nothing was changed.</p>
			{/if}
			{#if noOneClick}
				<p class="small">This server doesn’t offer one-click pairing. Paste the code from its Settings page instead.</p>
			{/if}
			{#if !clip}
				<div>
					<button class="btn ghost" aria-expanded={showPaste || noOneClick} onclick={() => (showPaste = !showPaste)}>
						<Icon name="clipboard-line" /> Paste the code instead
					</button>
				</div>
			{/if}
			{#if (showPaste || noOneClick) && !clip}
				<div class="stack">
					<p class="small">
						On aipotluck.org, open <span class="mono">Settings → Local Inference</span>, choose
						<em>Add a managed server</em>, click <em>Pair</em>, then <em>Copy</em>.
						<button class="link-inline" onclick={() => api.openSettingsPage().catch((e) => (taskError = String(e)))}>Open it</button>
					</p>
					<textarea
						class="paste"
						placeholder="Paste the pairing code here"
						bind:value={pasted}
						autocomplete="off"
						spellcheck="false"
					></textarea>
					<button class="btn secondary pair-pasted" disabled={!pasted.trim() || !!busy} onclick={() => pairPasted(pasted)}>
						<Icon name="link" /> Pair
					</button>
				</div>
			{/if}
		{/if}
	{:else if screen === 'running' && app?.ready}
		<div class="stack">
			<p class="label">This computer</p>
			<h1>Sharing with AI Potluck</h1>
		</div>
		<div class="card status" title={summary.detail} data-detail={summary.detail} role="status" aria-label={`Status: ${summary.text}`}>
			<div class="status-row">
				<span class="light {summary.light}" aria-hidden="true"></span>
				<span class="status-label">Status</span>
				<span class="status-text one-line">{summary.text}</span>
			</div>
		</div>
		<Models serviceHealthy={app.service_healthy} disabled={!!busy} />
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
		<span class="footer-text">aipotluck-local-client {app.upstream_sha.slice(0, 7)}{app.hosted_by_gui ? ' · hosted by this window' : ''}</span>
		<ServerOverride {override} disabled={busy === 'pair'} onchange={refresh} />
		<button class="btn ghost uninstall" disabled={!!busy} onclick={() => (uninstalling = true)}>
			<Icon name="delete-bin-line" size={14} /> Uninstall
		</button>
	{/if}
</footer>

{#if uninstalling}
	<UninstallDialog
		running={busy === 'uninstall'}
		oncancel={() => (uninstalling = false)}
		onconfirm={({ removeCli, removeModels }) => {
			taskError = null;
			log = [];
			api.uninstall(removeCli, removeModels).catch((e) => {
				taskError = String(e);
				uninstalling = false;
			});
			refresh();
		}}
	/>
{/if}
