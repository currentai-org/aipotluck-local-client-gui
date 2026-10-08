import { describe, expect, it } from 'vitest';
import surface from '../../../conformance/upstream-surface.json';
import {
	MEASURE_BUDGET_SECONDS,
	SCORE_BANDS,
	localScoreExplainer,
	activeJob,
	canForceAdd,
	downloadProgress,
	elapsedSeconds,
	errorMessage,
	formatElapsed,
	jobHint,
	jobOutcome,
	jobStage,
	jobTitle,
	modelRow,
	splitModelId,
	type Job,
	type ModelEntry
} from './models';

const entry = (over: Partial<ModelEntry> = {}): ModelEntry => ({
	id: 'bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M',
	sized: true,
	ctx_size: 32768,
	cache_type_k: 'q8_0',
	cache_type_v: 'q8_0',
	score: null,
	stale: false,
	held_back: null,
	...over
});

const job = (over: Partial<Job> = {}): Job => ({
	id: 'j1',
	kind: 'pull',
	model: 'unsloth/Qwen3-4B-GGUF:Q4_K_M',
	state: 'running',
	created_at: '2026-10-07T20:00:00+00:00',
	started_at: '2026-10-07T20:00:05+00:00',
	finished_at: null,
	progress: [],
	result: null,
	error: null,
	error_code: null,
	...over
});
const said = (...messages: string[]) => messages.map((message) => ({ at: '2026-10-07T20:00:06+00:00', message }));

describe('the promise of "up to 3 minutes"', () => {
	it('is upstream’s own benchmark budget, as recorded in the conformance baseline', () => {
		expect(MEASURE_BUDGET_SECONDS).toBe(surface.gui_hooks.measure_budget_seconds);
	});
});

describe('the LocalScore explanation', () => {
	it('uses upstream’s own band thresholds, as recorded in the conformance baseline', () => {
		const b = surface.gui_hooks.localscore_bands;
		expect(SCORE_BANDS).toEqual({ fair: b.poor, good: b.good, excellent: b.excellent });
	});

	it('says, in plain words, that higher is better and where each band starts', () => {
		const t = localScoreExplainer();
		expect(t).toContain('Higher is better');
		expect(t).toContain('under 100 is poor');
		expect(t).toContain('over 1,000 is excellent');
	});
});

describe('modelRow', () => {
	it('splits the id into repo, owner and quant', () => {
		expect(splitModelId('bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M')).toEqual({
			owner: 'bartowski',
			repo: 'Qwen2.5-0.5B-Instruct-GGUF',
			quant: 'Q4_K_M'
		});
		expect(splitModelId('org/repo').quant).toBeNull();
	});

	it('a measured model shows its LocalScore, band and speed, like the CLI list', () => {
		const r = modelRow(entry({ score: { localscore: 1312.4, band: 'excellent', avg_gen_tps: 41.234 } }));
		expect(r.score).toBe('1,312 (excellent)');
		expect(r.facts).toEqual(['41.2 tok/s', '32K context']);
		expect(r.notes).toEqual([]);
	});

	it('an unmeasured model has no score and says how to get one', () => {
		const r = modelRow(entry());
		expect(r.score).toBeNull();
		expect(r.notes.map((n) => n.text)).toEqual(['Not measured yet; run a benchmark']);
	});

	it('a held back model is flagged with upstream’s reason and is not sent round the benchmark loop', () => {
		const r = modelRow(entry({ held_back: { quarantine_reason: 'ran out of memory 3 times' } }));
		expect(r.notes).toHaveLength(1);
		expect(r.notes[0].warn).toBe(true);
		expect(r.notes[0].text).toContain('ran out of memory 3 times');
	});

	it('a stale or low-confidence score says so; an unsized model says so', () => {
		const r = modelRow(
			entry({ sized: false, ctx_size: null, stale: true, score: { localscore: 90, band: 'poor', confidence: 'low' } })
		);
		expect(r.notes.map((n) => n.text)).toEqual([
			'Not sized for this computer yet',
			'Low confidence: this computer’s speed varied between runs',
			'Score is out of date; run a benchmark'
		]);
	});
});

describe('jobs', () => {
	it('the job shown is the newest unfinished one', () => {
		const done = job({ id: 'old', state: 'succeeded' });
		const queued = job({ id: 'q', state: 'queued' });
		expect(activeJob([queued, done])?.id).toBe('q');
		expect(activeJob([done])).toBeNull();
	});

	it('titles name the model', () => {
		expect(jobTitle(job())).toBe('Adding Qwen3-4B-GGUF Q4_K_M');
		expect(jobTitle(job({ kind: 'benchmark', model: null }))).toBe('Benchmarking every model');
	});

	it('the stage is upstream’s latest progress message, in words', () => {
		expect(jobStage(job({ state: 'queued' }))).toContain('Waiting');
		expect(jobStage(job())).toBe('Starting');
		expect(jobStage(job({ progress: said('downloading unsloth/Qwen3-4B-GGUF:Q4_K_M') }))).toBe('Downloading');
		expect(jobStage(job({ progress: said('downloading x/y', 'sizing x/y') }))).toBe('Sizing for this computer');
		expect(jobStage(job({ progress: said('something new upstream says') }))).toBe('something new upstream says');
	});

	it('a benchmark of every model says which one it is on, and how far through', () => {
		const j = job({
			kind: 'benchmark',
			model: null,
			progress: said('re-sizing a/one:Q4', 'measuring a/one:Q4', 're-sizing b/two:Q8', 'measuring b/two:Q8')
		});
		expect(jobStage(j, 3)).toBe('Measuring speed · two Q8 (2 of 3)');
	});

	it('the hint quotes the download size and upstream’s measuring budget', () => {
		expect(jobHint(job(), { downloadBytes: 2_497_281_312 })).toMatch(/^~2\.5 GB download, then a moment to size it/);
		expect(jobHint(job())).not.toContain('measure');
		expect(jobHint(job({ kind: 'benchmark', model: null }), { modelCount: 3 })).toBe(
			'Up to 3 min per model, so up to about 9 min for all 3.'
		);
	});

	it('a download shows bytes received against upstream’s total, or the expected size until it knows', () => {
		const at = '2026-10-07T20:00:09+00:00';
		const downloading = (received: number, total: number | null) =>
			job({ progress: said('downloading unsloth/Qwen3-4B-GGUF:Q4_K_M'), download: { received_bytes: received, total_bytes: total, updated_at: at } });
		expect(downloadProgress(downloading(1_200_000_000, 2_497_281_312))).toEqual({
			fraction: 1_200_000_000 / 2_497_281_312,
			text: '1.2 GB of 2.5 GB (48%)'
		});
		expect(downloadProgress(downloading(500_000_000, null), 2_000_000_000)?.text).toBe('500 MB of 2 GB (25%)');
		expect(downloadProgress(downloading(500_000_000, null))).toEqual({ fraction: null, text: '500 MB so far' });
	});

	it('no download bar once the pull has moved on to sizing, or for a benchmark', () => {
		const d = { received_bytes: 10, total_bytes: 10, updated_at: '' };
		expect(downloadProgress(job({ progress: said('downloading x/y', 'sizing x/y'), download: d }))).toBeNull();
		expect(downloadProgress(job({ kind: 'benchmark', progress: said('downloading x/y'), download: d }))).toBeNull();
		expect(downloadProgress(job({ progress: said('downloading x/y') }))).toBeNull();
	});

	it('elapsed time counts from when upstream started the job', () => {
		const now = Date.parse('2026-10-07T20:02:10+00:00');
		expect(elapsedSeconds(job(), now)).toBe(125);
		expect(formatElapsed(125)).toBe('2:05');
		expect(formatElapsed(3)).toBe('0:03');
	});

	it('outcomes: added with a score, rejected by upstream, failed', () => {
		expect(jobOutcome(job({ state: 'succeeded', result: { score: { localscore: 312.2 } } })).text).toBe(
			'Added Qwen3-4B-GGUF Q4_K_M, LocalScore 312.'
		);
		expect(jobOutcome(job({ state: 'succeeded', result: { score: null } })).text).toBe(
			'Added Qwen3-4B-GGUF Q4_K_M. Run a benchmark to see how fast it is here.'
		);
		const rejected = jobOutcome(
			job({ state: 'succeeded', result: { rejected: true, rejection: 'a turn would take 4 minutes', removed: true } })
		);
		expect(rejected.warn).toBe(true);
		expect(rejected.text).toContain('a turn would take 4 minutes');
		expect(jobOutcome(job({ state: 'failed', error: 'download failed: 404' }))).toEqual({
			text: 'download failed: 404',
			warn: true
		});
	});

	it('a benchmark that upstream declined to measure says why', () => {
		const busy = 'This machine is still busy, so a measurement would describe the contention rather than the model. Try again when it’s idle.';
		const out = jobOutcome(
			job({
				kind: 'benchmark',
				model: null,
				state: 'succeeded',
				result: {
					results: [
						{ model: 'a/one-GGUF:Q8_0', measured: false, measurement_skipped: busy },
						{ model: 'a/two-GGUF:Q4', measured: false, measurement_skipped: busy }
					]
				}
			})
		);
		expect(out.warn).toBe(true);
		expect(out.text).toBe(`Measured 0 of 2. one-GGUF Q8_0: ${busy}`);
		expect(
			jobOutcome(job({ kind: 'benchmark', model: null, state: 'succeeded', result: { results: [{ measured: true }, { measured: true }] } }))
				.text
		).toBe('Benchmark finished for all 2 models.');
	});

	it('only an oversized refusal offers "add anyway"', () => {
		const tooBig = { error: { code: 'too_large_for_device', message: '39.6GB of weights…', retry_with: { allow_oversized: true } } };
		expect(canForceAdd(tooBig)).toBe(true);
		expect(canForceAdd({ error: { code: 'bad_request', message: 'x' } })).toBe(false);
		expect(errorMessage(tooBig, 'fallback')).toBe('39.6GB of weights…');
		expect(errorMessage(null, 'fallback')).toBe('fallback');
	});
});
