// The models section: upstream's GET /models listing and its jobs (POST /models, POST
// /models/benchmark), turned into what the screen shows. Pure, so it is unit-tested; every fact
// comes from upstream's JSON, nothing is computed about the device here.

import { formatBytes } from './state';

/**
 * Upstream's per-model benchmark budget (aipotluck/installer/model_perf.py PROBE_BUDGET_SECONDS),
 * quoted to the user as "up to N min". models.test.ts holds it to the conformance baseline, so an
 * upstream change shows up as a failing test, not a wrong promise.
 */
export const MEASURE_BUDGET_SECONDS = 180;

export type Score = {
	localscore: number;
	band?: string;
	avg_prompt_tps?: number;
	avg_gen_tps?: number;
	avg_ttft_ms?: number;
	confidence?: string;
	observed_spread?: number;
};

export type ModelEntry = {
	id: string;
	sized: boolean;
	ctx_size: number | null;
	cache_type_k?: string | null;
	cache_type_v?: string | null;
	score: Score | null;
	stale: boolean;
	held_back: { quarantine_reason?: string } | null;
};

export type ModelListing = {
	models: ModelEntry[];
	engine?: { tag?: string; localscore_note?: string };
};

export type JobState = 'queued' | 'running' | 'succeeded' | 'failed';

export type Job = {
	id: string;
	kind: string;
	model: string | null;
	state: JobState;
	created_at: string;
	started_at: string | null;
	finished_at: string | null;
	progress: { at: string; message: string }[];
	/** A pull's latest byte count while it downloads; total_bytes is null until llama.cpp knows it. */
	download?: { received_bytes: number; total_bytes: number | null; updated_at: string } | null;
	result: Record<string, unknown> | null;
	error: string | null;
	error_code: string | null;
};

/** Upstream's error body, `{"error": {"code", "message", ...}}`. */
export type ServiceError = {
	error: { code: string; message: string; retry_with?: Record<string, unknown> };
};

/** `owner/repo:QUANT` → its parts, for a two-line row. */
export function splitModelId(id: string): { owner: string; repo: string; quant: string | null } {
	const [path, quant] = id.split(':', 2);
	const slash = path.indexOf('/');
	return {
		owner: slash >= 0 ? path.slice(0, slash) : '',
		repo: slash >= 0 ? path.slice(slash + 1) : path,
		quant: quant || null
	};
}

/** How a single model is named in a sentence: its repo, plus the quant (two quants of one repo are common). */
export function modelName(id: string): string {
	const { repo, quant } = splitModelId(id);
	return quant ? `${repo} ${quant}` : repo;
}

export type Note = { text: string; warn?: boolean };
export type ModelRow = {
	id: string;
	repo: string;
	owner: string;
	quant: string | null;
	/** LocalScore, formatted, or null when not measured. */
	score: string | null;
	facts: string[];
	notes: Note[];
};

function contextLabel(ctx: number): string {
	return ctx >= 1024 && ctx % 1024 === 0 ? `${ctx / 1024}K context` : `${ctx.toLocaleString('en-US')} context`;
}

/**
 * One row per model, carrying what the CLI's `list` prints: the score, its band and generation
 * speed, and the same notes (held back, not sized, not measured, stale, low confidence).
 */
export function modelRow(m: ModelEntry): ModelRow {
	const { owner, repo, quant } = splitModelId(m.id);
	const facts: string[] = [];
	const notes: Note[] = [];
	if (m.held_back) {
		notes.push({
			text: `Held back: ${m.held_back.quarantine_reason ?? 'it kept running out of memory'}. It can still be picked in chat; remove it if it isn’t needed.`,
			warn: true
		});
	}
	if (!m.sized) notes.push({ text: 'Not sized for this computer yet' });
	const s = m.score;
	if (s) {
		if (s.band) facts.push(s.band);
		if (typeof s.avg_gen_tps === 'number') facts.push(`${s.avg_gen_tps.toFixed(1)} tok/s`);
		if (s.confidence === 'low') notes.push({ text: 'Low confidence: this computer’s speed varied between runs' });
		if (m.stale) notes.push({ text: 'Score is out of date; run a benchmark', warn: true });
	} else if (!m.held_back) {
		// Not for a held-back model: measuring is usually what held it back (the CLI says the same).
		notes.push({ text: 'Not measured yet; run a benchmark' });
	}
	if (m.ctx_size) facts.push(contextLabel(m.ctx_size));
	return {
		id: m.id,
		repo,
		owner,
		quant,
		score: s ? Math.round(s.localscore).toLocaleString('en-US') : null,
		facts,
		notes
	};
}

/** The job to show progress for: the newest one not yet finished. `/jobs` is newest first. */
export function activeJob(jobs: Job[]): Job | null {
	return jobs.find((j) => j.state === 'queued' || j.state === 'running') ?? null;
}

export function jobTitle(job: Job): string {
	const name = job.model ? modelName(job.model) : null;
	if (job.kind === 'pull') return `Adding ${name ?? 'a model'}`;
	if (job.kind === 'benchmark') return name ? `Benchmarking ${name}` : 'Benchmarking every model';
	return `${job.kind}${name ? ` ${name}` : ''}`;
}

const STAGES: [RegExp, string][] = [
	[/^downloading /, 'Downloading'],
	[/^re-sizing /, 'Re-sizing for this computer'],
	[/^sizing /, 'Sizing for this computer'],
	[/^checking .* can serve a turn/, 'Checking it can serve a turn'],
	[/^screening /, 'Screening'],
	[/^measuring /, 'Measuring speed']
];

/**
 * What the job is doing now, in words, from upstream's latest progress message. A benchmark of
 * every model also says which one it is on, counted from upstream's "re-sizing" step per model.
 */
export function jobStage(job: Job, modelCount = 0): string {
	if (job.state === 'queued') return 'Waiting for the job ahead of it to finish';
	const last = job.progress[job.progress.length - 1]?.message;
	if (!last) return 'Starting';
	const match = STAGES.find(([re]) => re.test(last));
	let stage = match ? match[1] : last;
	if (job.kind === 'benchmark' && !job.model) {
		const done = job.progress.filter((p) => p.message.startsWith('re-sizing ')).length;
		const current = last.split(' ').pop();
		const name = current?.includes('/') ? modelName(current) : null;
		if (name) stage += ` · ${name}`;
		if (modelCount > 1 && done) stage += ` (${Math.min(done, modelCount)} of ${modelCount})`;
	}
	return stage;
}

function minutes(seconds: number): string {
	return `${Math.max(1, Math.round(seconds / 60))} min`;
}

/** How long it may take, said once, so a quiet progress bar doesn't read as stuck. */
export function jobHint(job: Job, opts: { downloadBytes?: number | null; modelCount?: number } = {}): string {
	const measure = minutes(MEASURE_BUDGET_SECONDS);
	if (job.kind === 'pull') {
		// A pull downloads and sizes; measuring is Benchmark's job (upstream 928b822).
		const size = opts.downloadBytes ? `~${formatBytes(opts.downloadBytes)} download` : 'Download';
		return `${size}, then a moment to size it for this computer. A large model can take a while to download.`;
	}
	if (job.kind === 'benchmark') {
		const n = job.model ? 1 : (opts.modelCount ?? 0);
		return n > 1
			? `Up to ${measure} per model, so up to about ${minutes(MEASURE_BUDGET_SECONDS * n)} for all ${n}.`
			: `Up to ${measure}.`;
	}
	return '';
}

/**
 * How far a pull's download has got, from upstream's byte count: `fraction` (0-1) once the total
 * is known, and words for beside the bar. Null when nothing is downloading, including after the
 * download, when the job has moved on to sizing.
 */
export function downloadProgress(job: Job, expectedBytes?: number | null): { fraction: number | null; text: string } | null {
	const d = job.download;
	if (job.kind !== 'pull' || !d || !jobStage(job).startsWith('Downloading')) return null;
	const total = d.total_bytes ?? expectedBytes ?? null;
	if (!total) return { fraction: null, text: `${formatBytes(d.received_bytes)} so far` };
	const fraction = Math.min(1, d.received_bytes / total);
	return { fraction, text: `${formatBytes(d.received_bytes)} of ${formatBytes(total)} (${Math.floor(fraction * 100)}%)` };
}

/** Seconds since the job started (or was queued), from upstream's own timestamps. */
export function elapsedSeconds(job: Job, nowMs: number): number {
	const since = Date.parse(job.started_at ?? job.created_at);
	return Number.isNaN(since) ? 0 : Math.max(0, Math.floor((nowMs - since) / 1000));
}

export function formatElapsed(seconds: number): string {
	const m = Math.floor(seconds / 60);
	const s = seconds % 60;
	return `${m}:${s.toString().padStart(2, '0')}`;
}

/** What a finished job amounts to, in a sentence, for the line left behind once it's done. */
export function jobOutcome(job: Job): Note {
	const name = job.model ? modelName(job.model) : null;
	if (job.state === 'failed') return { text: job.error ?? 'It didn’t finish.', warn: true };
	const r = job.result ?? {};
	if (job.kind === 'pull') {
		if (r.rejected) {
			const removed = r.removed ? ' It has been removed.' : r.removal_note ? ` ${r.removal_note}` : '';
			return { text: `${name} can’t serve a conversation on this computer: ${r.rejection}.${removed}`, warn: true };
		}
		const score = (r.score as Score | null | undefined)?.localscore;
		return {
			text:
				typeof score === 'number'
					? `Added ${name}, LocalScore ${Math.round(score).toLocaleString('en-US')}.`
					: `Added ${name}. Run a benchmark to see how fast it is here.`
		};
	}
	if (job.kind === 'benchmark') {
		type Measured = { model?: string; measured?: boolean; measurement_skipped?: string; rejection?: string };
		const results = (r.results as Measured[] | undefined) ?? [];
		const unmeasured = results.filter((x) => !x.measured);
		if (!results.length) return { text: 'There were no models to benchmark.' };
		if (!unmeasured.length)
			return { text: `Benchmark finished for ${results.length === 1 ? (name ?? '1 model') : `all ${results.length} models`}.` };
		// Upstream says why, per model (a busy machine, a model that won't load); pass the first on.
		const first = unmeasured[0];
		const why = first.measurement_skipped ?? first.rejection;
		const who = first.model ? modelName(first.model) : null;
		return {
			text: `Measured ${results.length - unmeasured.length} of ${results.length}.${why ? ` ${who ? `${who}: ` : ''}${why}` : ''}`,
			warn: true
		};
	}
	return { text: 'Done.' };
}

/** Upstream refused an Add before downloading because the weights won't fit; the user may insist. */
export function canForceAdd(body: unknown): boolean {
	return (body as ServiceError | null)?.error?.code === 'too_large_for_device';
}

export function errorMessage(body: unknown, fallback: string): string {
	const e = (body as ServiceError | null)?.error;
	return e?.message ?? (typeof body === 'string' && body ? body : fallback);
}
