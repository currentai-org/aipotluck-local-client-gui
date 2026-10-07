import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Tauri expects a fixed dev port and must not clear its terminal output.
export default defineConfig({
	plugins: [svelte()],
	clearScreen: false,
	server: { port: 1420, strictPort: true, host: '127.0.0.1' },
	build: { target: 'es2021', outDir: 'dist', emptyOutDir: true },
	test: { environment: 'node', include: ['src/**/*.test.ts'] }
});
