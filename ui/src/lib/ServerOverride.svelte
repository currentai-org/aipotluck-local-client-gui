<script lang="ts">
	// The hidden pairing-server override, for testing against develop or a local dev server.
	//
	// Deliberately near-invisible while unused: a small mark in the footer, in the hairline colour,
	// that only reads as a control on hover/focus (it is still a real, keyboard-reachable button
	// with an accessible name). Once an override is SET it stops hiding: the footer names the
	// server, so nobody pairs a production machine to develop without noticing.
	//
	// Validation is upstream's: `set_pairing_server` asks upstream's own resolve_server_url, the
	// same check `cli login --server-url` makes, and shows its message if it refuses.
	import Icon from './Icon.svelte';
	import { api, type PairingServer } from './api';

	let { override = null, disabled = false, onchange }: { override?: string | null; disabled?: boolean; onchange?: () => void } =
		$props();

	let open = $state(false);
	let info = $state<PairingServer | null>(null);
	let value = $state('');
	let error = $state<string | null>(null);
	let saving = $state(false);

	function hostOf(url: string): string {
		try {
			return new URL(url).host;
		} catch {
			return url;
		}
	}

	async function show() {
		open = true;
		error = null;
		try {
			info = await api.pairingServer();
			value = info.override ?? '';
		} catch (e) {
			error = String(e);
		}
	}

	async function save(next: string | null) {
		saving = true;
		error = null;
		try {
			info = await api.setPairingServer(next);
			value = info.override ?? '';
			open = false;
			onchange?.();
		} catch (e) {
			error = String(e);
		} finally {
			saving = false;
		}
	}
</script>

<span class="server-override">
	{#if override}
		<button class="active" title={`Pairing server (testing override): ${override}`} onclick={show} {disabled}>
			pairing with {hostOf(override)}
		</button>
	{:else}
		<button class="quiet" aria-label="Pairing server" title="Pairing server" onclick={show} {disabled}>
			<Icon name="settings-3-line" size={12} />
		</button>
	{/if}
</span>

{#if open}
	<div class="card override-panel" data-surface="2" role="dialog" aria-label="Pairing server">
		<p class="label">Pairing server</p>
		<p class="small">
			For testing only. One-click pairing talks to
			<span class="mono">{info?.default ?? 'aipotluck.org'}</span> unless this is set.
		</p>
		<form
			class="override-form"
			onsubmit={(e) => {
				e.preventDefault();
				save(value);
			}}
		>
			<input
				class="input mono"
				type="url"
				placeholder={info?.default ?? 'https://www.aipotluck.org'}
				aria-label="Pairing server URL"
				bind:value
				oninput={() => (error = null)}
				aria-invalid={!!error}
				autocomplete="off"
				spellcheck="false"
			/>
			<button type="submit" class="btn secondary" disabled={saving || !value.trim()}>
				<Icon name="check-line" /> Use
			</button>
		</form>
		{#if error}
			<div class="error" role="alert"><Icon name="error-warning-line" /><span>{error}</span></div>
		{/if}
		<div class="row">
			{#if info?.override}
				<button class="btn ghost" disabled={saving} onclick={() => save(null)}>
					<Icon name="refresh-line" /> Back to {info.default}
				</button>
			{/if}
			<button class="btn ghost" onclick={() => (open = false)}>
				<Icon name="close-line" /> Close
			</button>
		</div>
	</div>
{/if}

<style>
	.server-override {
		margin-left: auto;
		flex-shrink: 0;
		max-width: 50%;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	.server-override button {
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		cursor: pointer;
	}
	/* Hidden in plain sight: hairline colour, no border, no fill, until it is pointed at. */
	.quiet {
		display: inline-flex;
		align-items: center;
		color: var(--ds-line-2);
		opacity: 0.6;
	}
	.quiet:hover,
	.quiet:focus-visible {
		color: var(--ds-fg-3);
		opacity: 1;
	}
	/* An override in effect is never subtle. */
	.active {
		color: var(--ds-accent-2-text);
		text-decoration: underline dotted;
	}
	.override-panel {
		position: fixed;
		left: var(--ds-space-6);
		right: var(--ds-space-6);
		bottom: calc(var(--ds-space-8) + var(--ds-space-4));
		max-width: 512px;
		margin: 0 auto;
		box-shadow: var(--ds-shadow-popover);
	}
	.override-form {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--ds-space-2);
	}
</style>
