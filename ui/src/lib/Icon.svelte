<script lang="ts">
	import { icons, type IconName } from '../design/icons';
	let { name, size = 16, label }: { name: IconName; size?: number; label?: string } = $props();
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="currentColor"
	role={label ? 'img' : undefined}
	aria-label={label}
	aria-hidden={label ? undefined : 'true'}
	class="icon"><path d={icons[name]} /></svg
>

<style>
	.icon {
		flex-shrink: 0;
	}
</style>
