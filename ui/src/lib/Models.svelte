<script lang="ts">
	// The models section of the running screen: upstream's list / pull / remove / benchmark, all
	// through its own HTTP API (GET/POST/DELETE /models, POST /models/benchmark, GET /jobs). Slow
	// work is an upstream job; this shows its progress and never runs anything itself.
	import { onMount } from 'svelte';
	import Icon from './Icon.svelte';
	import { api } from './api';
	import { isModelId, normaliseModelId } from './state';
	import {
		MEASURE_BUDGET_SECONDS,
		activeJob,
		canForceAdd,
		elapsedSeconds,
		errorMessage,
		formatElapsed,
		jobHint,
		jobOutcome,
		jobStage,
		jobTitle,
		modelName,
		modelRow,
		type Job,
		type ModelListing,
		type Note
	} from './models';

	let { serviceHealthy, disabled = false }: { serviceHealthy: boolean; disabled?: boolean } = $props();

	let listing = $state<ModelListing | null>(null);
	let listError = $state<string | null>(null);
	let job = $state<Job | null>(null);
	let outcome = $state<Note | null>(null);
	let now = $state(Date.now());
	let sizes = $state<Record<string, number | null>>({});

	let addValue = $state('');
	let addError = $state<string | null>(null);
	let forceable = $state<string | null>(null); // the model upstream refused as too large
	let sending = $state(false);

	let confirming = $state<string | null>(null);
	let deleting = $state<string | null>(null);
	let deleteError = $state<string | null>(null);

	const rows = $derived(listing ? listing.models.map(modelRow) : []);
	const count = $derived(listing?.models.length ?? 0);
	const locked = $derived(disabled || !!job || sending || !!deleting);
	const stage = $derived(job ? jobStage(job, count) : '');
	const hint = $derived(job ? jobHint(job, { downloadBytes: job.model ? sizes[job.model] : null, modelCount: count }) : '');

	async function loadModels() {
		try {
			const r = await api.service<ModelListing>('GET', '/models');
			if (r.status === 200) {
				listing = r.body;
				listError = null;
			} else listError = errorMessage(r.body, `The service couldn’t list models (HTTP ${r.status}).`);
		} catch (e) {
			listError = String(e);
		}
	}

	function sizeFor(model: string | null) {
		if (!model || model in sizes) return;
		sizes[model] = null;
		api.modelSize(model).then((m) => (sizes[model] = m.bytes)).catch(() => {});
	}

	/** Follow the newest unfinished job, wherever it was started; note how it ended once it's done. */
	async function loadJobs() {
		let jobs: Job[] = [];
		try {
			const r = await api.service<{ jobs: Job[] }>('GET', '/jobs');
			if (r.status !== 200) return;
			jobs = r.body.jobs;
		} catch {
			return;
		}
		const previous = job;
		job = activeJob(jobs);
		if (job?.kind === 'pull') sizeFor(job.model);
		if (previous && (!job || job.id !== previous.id)) {
			const finished = jobs.find((j) => j.id === previous.id);
			// List first, so the outcome line never sits above a list that doesn't reflect it yet.
			await loadModels();
			if (finished) outcome = jobOutcome(finished);
		}
	}

	async function submit(path: '/models' | '/models/benchmark', body: Record<string, unknown>) {
		sending = true;
		outcome = null;
		try {
			const r = await api.service<{ job: Job }>('POST', path, body);
			if (r.status === 202) {
				job = r.body.job;
				if (job.kind === 'pull') sizeFor(job.model);
				return true;
			}
			if (canForceAdd(r.body)) forceable = String(body.model);
			addError = errorMessage(r.body, `The service refused that (HTTP ${r.status}).`);
		} catch (e) {
			addError = String(e);
		} finally {
			sending = false;
		}
		return false;
	}

	async function add(allowOversized = false) {
		addError = null;
		forceable = null;
		const id = normaliseModelId(addValue);
		if (!isModelId(id)) {
			addError = 'That isn’t a Hugging Face model id. Use owner/repo, or owner/repo:QUANT.';
			return;
		}
		const body: Record<string, unknown> = { model: id };
		if (allowOversized) body.allow_oversized = true;
		if (await submit('/models', body)) addValue = '';
	}

	async function remove(id: string) {
		deleting = id;
		deleteError = null;
		try {
			const r = await api.service('DELETE', `/models?model=${encodeURIComponent(id)}`);
			if (r.status === 200) outcome = { text: `Removed ${modelName(id)}.` };
			else deleteError = errorMessage(r.body, `Couldn’t remove it (HTTP ${r.status}).`);
		} catch (e) {
			deleteError = String(e);
		} finally {
			deleting = null;
			confirming = null;
			await loadModels();
		}
	}

	onMount(() => {
		loadModels();
		loadJobs();
		// Quick while a job runs (its stage and the clock move); slow otherwise, just to notice a job
		// started from the CLI or aipotluck.org.
		let ticks = 0;
		const timer = setInterval(() => {
			now = Date.now();
			ticks++;
			if (job ? ticks % 2 === 0 : ticks % 5 === 0) loadJobs();
			if (!job && ticks % 15 === 0) loadModels();
		}, 1000);
		return () => clearInterval(timer);
	});

	$effect(() => {
		if (serviceHealthy && listing === null) loadModels();
	});
</script>

<section class="stack" aria-label="Models">
	<div class="models-head">
		<p class="label">Models</p>
		{#if listing}<p class="label">{count} installed</p>{/if}
	</div>

	<div class="card models">
		{#if listing && listError}
			<div class="error" role="alert"><Icon name="error-warning-line" /><span>Couldn’t refresh the list: {listError}</span></div>
		{/if}
		{#if listing && rows.length}
			<div class="model-cols label" aria-hidden="true"><span>Model</span><span>LocalScore</span><span></span></div>
			{#each rows as row (row.id)}
				<div class="model" class:dim={deleting === row.id}>
					<div class="model-line">
						<span class="model-name">
							{row.repo}{#if row.quant}<span class="quant mono">{row.quant}</span>{/if}
						</span>
						<span class="model-score mono">{row.score ?? '—'}</span>
						<button
							class="btn destructive icon"
							aria-label={`Remove ${row.id}`}
							title="Remove"
							disabled={locked}
							onclick={() => (confirming = confirming === row.id ? null : row.id)}
						>
							<Icon name="delete-bin-line" />
						</button>
					</div>
					<p class="model-meta small mono">{[row.owner, ...row.facts].filter(Boolean).join(' · ')}</p>
					{#each row.notes as n (n.text)}
						<p class="model-note small" class:warn={n.warn}>
							{#if n.warn}<Icon name="error-warning-line" size={14} />{/if}{n.text}
						</p>
					{/each}
					{#if confirming === row.id}
						<div class="confirm">
							<p class="small">Delete {modelName(row.id)} and its downloaded weights from this computer?</p>
							<div class="row">
								<button class="btn destructive" disabled={!!deleting} onclick={() => remove(row.id)}>
									<Icon name="delete-bin-line" /> Delete
								</button>
								<button class="btn secondary" onclick={() => (confirming = null)}>
									<Icon name="close-line" /> Keep
								</button>
							</div>
						</div>
					{/if}
				</div>
			{/each}
		{:else if listing}
			<p class="small">No models yet. Add one below.</p>
		{:else if listError}
			<div class="error"><Icon name="error-warning-line" /><span>{listError}</span></div>
		{:else if serviceHealthy}
			<div class="progress" aria-label="Loading models"></div>
		{:else}
			<p class="small">Models are listed once the service is running.</p>
		{/if}
	</div>
	{#if deleteError}
		<div class="error" role="alert"><Icon name="error-warning-line" /><span>{deleteError}</span></div>
	{/if}
	{#if listing?.engine?.localscore_note && rows.some((r) => r.score)}
		<p class="small faint">{listing.engine.localscore_note}</p>
	{/if}

	{#if job}
		<div class="card job" data-surface="2" aria-live="polite">
			<div class="job-line">
				<span class="status-label">{jobTitle(job)}</span>
				<span class="mono small">{formatElapsed(elapsedSeconds(job, now))}</span>
			</div>
			<div class="progress" aria-label={stage}></div>
			<p class="small">{stage}</p>
			<p class="small faint">{hint}</p>
			{#if job.progress.length}
				<details>
					<summary>Details</summary>
					<pre class="log">{job.progress.map((p) => `${p.at.slice(11, 19)}  ${p.message}`).join('\n')}</pre>
				</details>
			{/if}
		</div>
	{:else if outcome}
		<p class="model-note small" class:warn={outcome.warn} class:positive={!outcome.warn} role="status">
			<Icon name={outcome.warn ? 'error-warning-line' : 'checkbox-circle-fill'} size={14} />{outcome.text}
		</p>
	{/if}

	<form
		class="add"
		onsubmit={(e) => {
			e.preventDefault();
			add();
		}}
	>
		<input
			id="add-model"
			class="input mono"
			type="text"
			placeholder="owner/repo:QUANT from Hugging Face"
			aria-label="Model to add"
			bind:value={addValue}
			oninput={() => ((addError = null), (forceable = null))}
			aria-invalid={!!addError}
			autocomplete="off"
			autocapitalize="off"
			spellcheck="false"
		/>
		<button type="submit" class="btn secondary" disabled={locked || !addValue.trim()}>
			<Icon name="add-line" /> Add
		</button>
	</form>
	{#if addError}
		<div class="error" role="alert"><Icon name="error-warning-line" /><span>{addError}</span></div>
		{#if forceable && forceable === normaliseModelId(addValue)}
			<div>
				<button class="btn secondary" disabled={locked} onclick={() => add(true)}>
					<Icon name="download-2-line" /> Download anyway
				</button>
			</div>
		{/if}
	{/if}

	<div class="row">
		<button
			class="btn secondary"
			disabled={locked || !count}
			onclick={() => {
				addError = null;
				submit('/models/benchmark', {});
			}}
		>
			<Icon name="dashboard-3-line" /> Benchmark
		</button>
		<p class="small faint">
			{#if job}Available once the job above finishes.{:else}Measures every model, up to {Math.round(MEASURE_BUDGET_SECONDS / 60)} min each.{/if}
		</p>
	</div>
</section>

<style>
	.models-head {
		display: flex;
		justify-content: space-between;
	}
	.models {
		gap: var(--ds-space-4);
	}
	.model-cols,
	.model-line {
		display: grid;
		grid-template-columns: 1fr auto var(--ds-control-sm);
		gap: var(--ds-space-3);
		align-items: center;
	}
	.model {
		display: flex;
		flex-direction: column;
		gap: var(--ds-space-1);
		padding-top: var(--ds-space-3);
		border-top: var(--ds-border-hairline) solid var(--ds-line-2);
	}
	.model-cols + .model {
		border-top: none;
		padding-top: 0;
	}
	.model.dim {
		opacity: 0.4;
	}
	.model-name {
		color: var(--ds-fg-1);
		overflow-wrap: anywhere;
	}
	.quant {
		margin-left: var(--ds-space-2);
		padding: 0 var(--ds-space-1);
		font-size: var(--ds-text-micro);
		color: var(--ds-fg-2);
		border: var(--ds-border-hairline) solid var(--ds-line-2);
		border-radius: var(--ds-radius-sharp);
		white-space: nowrap;
	}
	.model-score {
		color: var(--ds-fg-1);
		font-size: var(--ds-text-small);
	}
	.model-meta {
		color: var(--ds-fg-2);
	}
	.model-note {
		display: flex;
		gap: var(--ds-space-1);
		align-items: flex-start;
		color: var(--ds-fg-3);
	}
	.model-note.warn {
		color: var(--ds-fg-1);
	}
	.model-note.warn :global(svg) {
		color: var(--ds-accent-2-text);
		margin-top: 2px;
	}
	.model-note.positive :global(svg) {
		color: var(--ds-positive-text);
		margin-top: 2px;
	}
	.confirm {
		display: flex;
		flex-direction: column;
		gap: var(--ds-space-2);
		margin-top: var(--ds-space-2);
	}
	.btn.icon {
		height: var(--ds-control-sm);
		width: var(--ds-control-sm);
		padding: 0;
		justify-content: center;
	}
	.job {
		gap: var(--ds-space-2);
	}
	.job-line {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}
	.faint {
		color: var(--ds-fg-3);
	}
	.add {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--ds-space-2);
	}
	.add .input {
		height: var(--ds-control-lg);
	}
</style>
