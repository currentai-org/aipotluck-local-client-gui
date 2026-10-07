// The only way the UI reaches the machine: Tauri commands implemented in src-tauri/src/lib.rs.
import { invoke } from '@tauri-apps/api/core';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import type { AppState, Status } from './state';

export type ServiceResponse<T = unknown> = { status: number; body: T };
export type PairingPreview = { tunnel_id: string; tunnel_endpoint: string };
export type TaskLine = { task: string; line: string };
export type TaskDone = { task: string; code: number; ok: boolean };

export const api = {
	appState: () => invoke<AppState>('app_state'),
	setupDevice: () => invoke<void>('setup_device'),
	clipboardPairing: () => invoke<PairingPreview | null>('clipboard_pairing'),
	pair: (pasted?: string) => invoke<void>('pair', { pasted: pasted ?? null }),
	unpair: () => invoke<void>('unpair'),
	openSettingsPage: () => invoke<void>('open_settings_page'),
	service: <T = unknown>(method: 'GET' | 'POST' | 'DELETE', path: string, body?: unknown) =>
		invoke<ServiceResponse<T>>('service_call', { method, path, body: body ?? null }),
	status: async (): Promise<Status | null> => {
		try {
			const r = await api.service<Status>('GET', '/status');
			return r.status === 200 ? r.body : null;
		} catch {
			return null;
		}
	}
};

export function onTaskLog(cb: (e: TaskLine) => void): Promise<UnlistenFn> {
	return listen<TaskLine>('task-log', (e) => cb(e.payload));
}
export function onTaskDone(cb: (e: TaskDone) => void): Promise<UnlistenFn> {
	return listen<TaskDone>('task-done', (e) => cb(e.payload));
}
export function onRuntimeReady(cb: () => void): Promise<UnlistenFn> {
	return listen('runtime-ready', () => cb());
}
