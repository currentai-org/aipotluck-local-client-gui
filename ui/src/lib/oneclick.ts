// One-click pairing, as the UI sees it: what upstream's `cli login` (no credential flags) prints
// while it waits, read back out of the task log. Pure functions, so they're unit-tested here and the
// screen just renders them.
//
// What upstream prints (aipotluck/installer/cli.py `_one_click_credentials`):
//     Pair this device with your AI Potluck account.
//     Opened this link in your browser. If nothing appeared, open it yourself on any device ...
//     (or: Open this link in a browser on any device where you're signed in to AI Potluck:)
//
//         https://www.aipotluck.org/chat/local-inference/pair?id=<pairing id>&name=<host>
//
//     Waiting for you to approve it there (Ctrl-C to cancel)...
// and at the end one of: "Paired as '<label>'.", "Logged in. ...", "Pairing cancelled; nothing was
// changed.", or an [ERROR] line carrying upstream's own reason (404 = server without one-click).
//
// The pairing id in the URL is the poll's only credential (pairing.py), so the full URL is shown
// to the person (they may need to open it elsewhere) but never logged by the GUI anywhere else.

const PAIR_PATH = '/chat/local-inference/pair?';

/** The pairing link upstream printed, if this line is it. Only ever an http(s) URL to the pair page. */
export function pairingLink(line: string): string | null {
	const t = line.trim();
	if (!t.includes(PAIR_PATH)) return null;
	try {
		const u = new URL(t);
		if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
		if (!u.pathname.endsWith('/chat/local-inference/pair') || !u.searchParams.get('id')) return null;
		return u.toString();
	} catch {
		return null;
	}
}

/** The newest pairing link in a task log, or null before upstream has printed one. */
export function latestPairingLink(log: string[]): string | null {
	for (let i = log.length - 1; i >= 0; i--) {
		const link = pairingLink(log[i]);
		if (link) return link;
	}
	return null;
}

/** Upstream said it handed the link to a browser (vs. no browser available: show the link first). */
export function browserOpened(log: string[]): boolean {
	return log.some((l) => l.startsWith('Opened this link in your browser'));
}

/** The server a pairing link points at, for showing which server this is (scheme://host[:port]). */
export function serverOf(link: string): string {
	try {
		return new URL(link).origin;
	} catch {
		return '';
	}
}

/** Upstream's own reason a pairing stopped, from its [ERROR] lines; the most specific one wins. */
export function pairingFailure(log: string[]): string | null {
	const errors = log
		.map((l) => l.match(/^\[ERROR\] [\w.]+: (.*)$/)?.[1]?.trim())
		.filter((m): m is string => !!m);
	if (!errors.length) return null;
	return errors[errors.length - 1];
}

export function pairingCancelled(log: string[]): boolean {
	return log.some((l) => /Pairing cancelled; nothing was changed/.test(l));
}

/** Server without one-click pairing (HTTP 404): the manual paste is the way through. */
export function oneClickUnavailable(log: string[]): boolean {
	return log.some((l) => /doesn't offer one-click pairing/.test(l));
}
