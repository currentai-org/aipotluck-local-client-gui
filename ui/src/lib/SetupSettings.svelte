<script lang="ts">
	// Customize: choices for Set up, each one an upstream `install` flag. Nothing here touches the
	// machine; Save hands the choices back and the setup screen re-sizes the plan.
	import { untrack } from 'svelte';
	import Icon from './Icon.svelte';
	import { BACKEND_INFO, isModelId, normaliseModelId, type BackendChoice, type InstallPlan } from './state';
	import { formatBytes } from './state';

	let {
		modelHf,
		backend,
		defaultModel,
		backends,
		onsave,
		oncancel
	}: {
		/** The current override; '' means upstream's default. */
		modelHf: string;
		/** The compute override; '' means auto-detect. */
		backend: string;
		defaultModel: string;
		/** The compute picker's options (empty on macOS, which has no picker). */
		backends: InstallPlan['backends'] | null;
		onsave: (choice: { modelHf: string; backend: string }) => void;
		oncancel: () => void;
	} = $props();

	// The page is mounted fresh each time it opens, so the drafts start from the saved values once.
	let draft = $state(untrack(() => modelHf));
	let backendDraft = $state<string>(untrack(() => backend || backends?.auto || ''));
	let error = $state<string | null>(null);

	const options = $derived(backends?.options ?? []);

	function save() {
		const id = normaliseModelId(draft);
		if (id && !isModelId(id)) {
			error = 'That isn’t a Hugging Face model id. Use owner/repo, or owner/repo:QUANT.';
			return;
		}
		// Picking what auto-detect would pick anyway is no override: a later re-detect still applies.
		const b = backendDraft === backends?.auto ? '' : backendDraft;
		onsave({ modelHf: id === defaultModel ? '' : id, backend: b });
	}
</script>

<div class="stack">
	<p class="label">Customize set up</p>
	<h1>Settings</h1>
</div>

<form
	class="stack"
	onsubmit={(e) => {
		e.preventDefault();
		save();
	}}
>
	{#if options.length}
		<fieldset class="field">
			<legend class="label">Compute</legend>
			<div class="choices" role="radiogroup" aria-label="Compute">
				{#each options as opt (opt.backend)}
					{@const info = BACKEND_INFO[opt.backend as BackendChoice]}
					<label class="choice" class:disabled={!opt.available && opt.backend !== backends?.auto}>
						<input
							type="radio"
							name="backend"
							value={opt.backend}
							bind:group={backendDraft}
							disabled={!opt.available && opt.backend !== backends?.auto}
						/>
						<span class="radio" aria-hidden="true"></span>
						<span class="choice-name">{info.name}</span>
						{#if opt.backend === backends?.auto}<span class="tag mono">detected</span>{/if}
						<span class="choice-size small mono">
							{#if !opt.available}{opt.backend === backends?.auto ? 'built here' : 'not available'}{:else if opt.bytes !== null}~{formatBytes(opt.bytes)}{:else}—{/if}
						</span>
					</label>
				{/each}
			</div>
			{#if backendDraft && BACKEND_INFO[backendDraft as BackendChoice]}
				<p class="small" aria-live="polite">{BACKEND_INFO[backendDraft as BackendChoice].why}</p>
			{/if}
		</fieldset>
	{/if}

	<div class="field">
		<label class="label" for="model-hf">Model</label>
		<input
			id="model-hf"
			class="input mono"
			type="text"
			placeholder={defaultModel}
			bind:value={draft}
			oninput={() => (error = null)}
			aria-invalid={!!error}
			autocomplete="off"
			autocapitalize="off"
			spellcheck="false"
		/>
		<p class="small">
			A Hugging Face GGUF repo, optionally with a quantization: <span class="mono">owner/repo</span> or
			<span class="mono">owner/repo:Q4_K_M</span>. Leave empty for the small starter model. You can add more
			models later.
		</p>
		{#if error}
			<div class="error" role="alert"><Icon name="error-warning-line" /><span>{error}</span></div>
		{/if}
		{#if draft.trim()}
			<div>
				<button type="button" class="btn ghost" onclick={() => ((draft = ''), (error = null))}>
					<Icon name="refresh-line" /> Use the starter model
				</button>
			</div>
		{/if}
	</div>

	<div class="row">
		<button type="submit" class="btn primary"><Icon name="check-line" /> Save changes</button>
		<button type="button" class="btn secondary" onclick={oncancel}>
			<Icon name="arrow-left-line" /> Cancel
		</button>
	</div>
</form>

<style>
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--ds-space-2);
		margin: 0;
		padding: 0;
		border: 0;
		min-width: 0;
	}
	legend {
		padding: 0;
		margin-bottom: var(--ds-space-2);
	}
	.choices {
		display: flex;
		flex-direction: column;
		gap: var(--ds-space-2);
	}
	.choice {
		display: flex;
		align-items: center;
		gap: var(--ds-space-2);
		cursor: pointer;
	}
	.choice.disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	/* Alpha DS Radio (components/radio): a 16px square on Background 2 with a Border 3 edge, Fg 2 on
	   hover, Fg 1 when checked, and an 8px Fg 1 mark inside. The real input stays for keyboard and
	   screen readers, visually hidden. */
	.choice input {
		position: absolute;
		opacity: 0;
		width: 1px;
		height: 1px;
		margin: 0;
	}
	.radio {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: 16px;
		height: 16px;
		box-sizing: border-box;
		background: var(--ds-bg-2);
		border: var(--ds-border-hairline) solid var(--ds-line-3);
		border-radius: var(--ds-radius-sharp);
		transition: border-color var(--ds-duration-fast);
	}
	.choice:hover .radio {
		border-color: var(--ds-fg-2);
	}
	.choice input:checked + .radio {
		border-color: var(--ds-fg-1);
	}
	.choice input:checked + .radio::after {
		content: '';
		width: 8px;
		height: 8px;
		background: var(--ds-fg-1);
		border-radius: max(0px, calc(var(--ds-radius-sharp) - 4px));
	}
	.choice input:focus-visible + .radio {
		outline: 2px solid var(--ds-focus);
		outline-offset: 2px;
	}
	.choice-name {
		color: var(--ds-fg-1);
	}
	.choice-size {
		margin-left: auto;
		color: var(--ds-fg-2);
	}
	.tag {
		padding: 0 var(--ds-space-1);
		font-size: var(--ds-text-micro);
		color: var(--ds-fg-2);
		border: var(--ds-border-hairline) solid var(--ds-line-2);
		border-radius: var(--ds-radius-sharp);
	}
</style>
