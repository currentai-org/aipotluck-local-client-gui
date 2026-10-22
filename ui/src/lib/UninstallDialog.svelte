<script lang="ts">
	// Uninstall confirmation. A native <dialog> opened modally: focus is trapped, Escape cancels,
	// and the page behind is inert. Nothing happens until Confirm.
	import { onMount } from 'svelte';
	import Icon from './Icon.svelte';
	import { api } from './api';
	import { uninstallSummary } from './state';

	let {
		onconfirm,
		oncancel,
		running
	}: {
		onconfirm: (choice: { removeCli: boolean; removeModels: boolean }) => void;
		oncancel: () => void;
		running: boolean;
	} = $props();

	let dialog: HTMLDialogElement | undefined = $state();
	let removeCli = $state(true);
	let removeModels = $state(false);
	let note = $state<string | null>(null);

	const summary = $derived(uninstallSummary(removeCli, removeModels));

	onMount(() => {
		dialog?.showModal();
		api.uninstallInfo().then((i) => (note = i.note)).catch(() => {});
	});
</script>

<dialog
	bind:this={dialog}
	aria-labelledby="uninstall-title"
	aria-describedby="uninstall-summary"
	oncancel={(e) => {
		e.preventDefault();
		if (!running) oncancel();
	}}
>
	<form
		method="dialog"
		class="stack"
		onsubmit={(e) => {
			e.preventDefault();
			onconfirm({ removeCli, removeModels });
		}}
	>
		<h2 id="uninstall-title">Uninstall AI Potluck?</h2>

		<fieldset class="options" disabled={running}>
			<legend class="label">Remove</legend>
			<label class="option locked">
				<input type="checkbox" checked disabled />
				<span class="box" aria-hidden="true"><Icon name="check-line" size={14} /></span>
				<span>GUI files</span>
			</label>
			<label class="option">
				<input type="checkbox" bind:checked={removeCli} />
				<span class="box" aria-hidden="true"><Icon name="check-line" size={14} /></span>
				<span>CLI files</span>
			</label>
			<label class="option">
				<input type="checkbox" bind:checked={removeModels} />
				<span class="box" aria-hidden="true"><Icon name="check-line" size={14} /></span>
				<span>Model cache</span>
			</label>
		</fieldset>

		<p id="uninstall-summary" class="small">{summary}</p>
		{#if note}<p class="small">{note}</p>{/if}

		{#if running}
			<div class="stack">
				<div class="progress" aria-label="Uninstalling"></div>
				<p class="small">Uninstalling… the app closes when it’s done.</p>
			</div>
		{:else}
			<div class="row actions">
				<button type="submit" class="btn confirm"><Icon name="delete-bin-line" /> Confirm</button>
				<button type="button" class="btn secondary" onclick={oncancel}>Cancel</button>
			</div>
		{/if}
	</form>
</dialog>

<style>
	/* Alpha DS Alert Dialog: Background 3, Border 2, sharp, popover shadow, overlay scrim. */
	dialog {
		width: min(28rem, calc(100vw - 2rem));
		box-sizing: border-box;
		padding: var(--ds-space-6);
		background: var(--ds-bg-3);
		color: var(--ds-fg-1);
		border: var(--ds-border-hairline) solid var(--ds-line-2);
		border-radius: var(--ds-radius-sharp);
		box-shadow: var(--ds-shadow-popover);
	}
	dialog::backdrop {
		background: var(--ds-overlay);
	}
	h2 {
		margin: 0;
	}
	.options {
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
	.option {
		display: flex;
		align-items: center;
		gap: var(--ds-space-2);
		cursor: pointer;
	}
	.option.locked {
		cursor: default;
		color: var(--ds-fg-2);
	}
	/* Alpha DS Checkbox: 16px sharp square, Border 3 on Background 2; checked fills Fg 1 with a
	   Surface-coloured check. The real input stays for keyboard and screen readers. */
	.option input {
		position: absolute;
		opacity: 0;
		width: 1px;
		height: 1px;
		margin: 0;
	}
	.box {
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
		color: transparent;
		transition:
			border-color var(--ds-duration-fast),
			background-color var(--ds-duration-fast);
	}
	.option:hover .box {
		border-color: var(--ds-fg-2);
	}
	.option input:checked + .box {
		background: var(--ds-fg-1);
		border-color: var(--ds-fg-1);
		color: var(--ds-surface);
	}
	.option input:disabled + .box {
		opacity: 0.4;
	}
	.option input:focus-visible + .box {
		outline: 2px solid var(--ds-focus);
		outline-offset: 2px;
	}
	.actions {
		justify-content: flex-start;
	}
	/* Requested red: Accent 2 on the edge, label and icon -- never as a fill (the design system
	   keeps Accent to marks, not surfaces). */
	.btn.confirm {
		background: var(--ds-surface-raised);
		border-color: var(--ds-accent-2);
		color: var(--ds-accent-2-text);
	}
	.btn.confirm :global(svg) {
		color: var(--ds-accent-2);
	}
	.btn.confirm:hover {
		background-image: linear-gradient(var(--ds-tint-hover), var(--ds-tint-hover));
	}
</style>
