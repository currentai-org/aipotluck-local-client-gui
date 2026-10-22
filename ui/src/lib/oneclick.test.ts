import { describe, expect, it } from 'vitest';
import {
	browserOpened,
	latestPairingLink,
	oneClickUnavailable,
	pairingCancelled,
	pairingFailure,
	pairingLink,
	serverOf
} from './oneclick';

// Lines exactly as upstream's `cli login` (one-click) prints them, at the pinned commit.
const ID = 'Xk2_9aQ-wt3hL0v8bYc1nR5sE7uJ4mZ6dF0gH2jK8pA';
const LINK = `https://www.aipotluck.org/chat/local-inference/pair?id=${ID}&name=pi5`;
const opened = [
	'[INFO] aipotluck.cli: newt binary: /home/u/.local/share/aipotluck/newt/1.18.1/newt_linux_arm64',
	'Pair this device with your AI Potluck account.',
	'Opened this link in your browser. If nothing appeared, open it yourself on any device',
	"where you're signed in to AI Potluck:",
	'',
	`    ${LINK}`,
	'',
	'Waiting for you to approve it there (Ctrl-C to cancel)...'
];

describe('the pairing link upstream prints', () => {
	it('is picked out of the log, indented as upstream prints it', () => {
		expect(latestPairingLink(opened)).toBe(LINK);
		expect(browserOpened(opened)).toBe(true);
	});

	it('is not there yet before upstream prints it', () => {
		expect(latestPairingLink(opened.slice(0, 2))).toBeNull();
	});

	it('when no browser could open, upstream says so and the link is the way through', () => {
		const headless = ['Open this link in a browser on any device where you’re signed in to AI Potluck:', `    ${LINK}`];
		expect(latestPairingLink(headless)).toBe(LINK);
		expect(browserOpened(headless)).toBe(false);
	});

	it('never mistakes some other URL in the log for the pairing link', () => {
		expect(pairingLink('    https://www.aipotluck.org/chat/settings/local-inference')).toBeNull();
		expect(pairingLink('[INFO] downloading https://github.com/fosrl/newt/releases/download/1.18.1/newt_linux_arm64')).toBeNull();
		expect(pairingLink('javascript:alert(1)//chat/local-inference/pair?id=x')).toBeNull();
		expect(pairingLink('https://www.aipotluck.org/chat/local-inference/pair?name=pi5')).toBeNull(); // no id
	});

	it('names the server it points at, including a dev server’s port', () => {
		expect(serverOf(LINK)).toBe('https://www.aipotluck.org');
		expect(serverOf(`http://localhost:5173/chat/local-inference/pair?id=${ID}`)).toBe('http://localhost:5173');
	});
});

describe('how a pairing ended', () => {
	it('reports upstream’s own reason, not a generic failure', () => {
		const log = [...opened, "[ERROR] aipotluck.cli: Timed out after 10 minutes waiting for the pairing to be approved in the browser. Run `login` again to get a new link."];
		expect(pairingFailure(log)).toMatch(/^Timed out after 10 minutes/);
		expect(pairingFailure(opened)).toBeNull();
	});

	it('recognises a server without one-click pairing, so the paste fallback can be offered', () => {
		const log = ["[ERROR] aipotluck.cli: https://develop.aipotluck.org doesn't offer one-click pairing (HTTP 404): it may predate it, or have it switched off. Pair manually instead: copy the JSON from Settings -> Local Inference and run `login --credentials-file <file>`."];
		expect(oneClickUnavailable(log)).toBe(true);
		expect(oneClickUnavailable(opened)).toBe(false);
	});

	it('recognises a cancel as a cancel, not an error', () => {
		const log = [...opened, '', '[ERROR] aipotluck.cli: Pairing cancelled; nothing was changed.'];
		expect(pairingCancelled(log)).toBe(true);
	});
});
