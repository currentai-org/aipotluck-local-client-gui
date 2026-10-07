<script lang="ts">
	// Customize: choices for Set up, each one an upstream `install` flag. Nothing here touches the
	// machine; Save hands the choices back and the setup screen re-sizes the plan.
	import { untrack } from 'svelte';
	import Icon from './Icon.svelte';
	import { isModelId, normaliseModelId } from './state';

	let {
		modelHf,
		defaultModel,
		onsave,
		oncancel
	}: {
		/** The current override; '' means upstream's default. */
		modelHf: string;
		defaultModel: string;
		onsave: (modelHf: string) => void;
		oncancel: () => void;
	} = $props();

	// The page is mounted fresh each time it opens, so the draft starts from the saved value once.
	let draft = $state(untrack(() => modelHf));
	let error = $state<string | null>(null);

	function save() {
		const id = normaliseModelId(draft);
		if (id && !isModelId(id)) {
			error = 'That isn’t a Hugging Face model id. Use owner/repo, or owner/repo:QUANT.';
			return;
		}
		onsave(id === defaultModel ? '' : id);
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
	}
</style>
