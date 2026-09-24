import { execFile, spawn } from "node:child_process";
import { createReadStream } from "node:fs";
import { unlink } from "node:fs/promises";
import { createInterface } from "node:readline";
import { promisify } from "node:util";
import type { ExtensionAPI, SessionInfo } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { type Component, Input, Key, matchesKey, type Theme, truncateToWidth, type TUI } from "@earendil-works/pi-tui";

const MAX_FILE_BYTES = 64 * 1024 * 1024;
const MAX_RESULTS = 100;
const SEARCH_CONCURRENCY = 6;
// Max session paths passed to a single ripgrep invocation, to stay well under
// the OS argument-length limit on very large histories.
const RG_PREFILTER_CHUNK = 800;

const execFileAsync = promisify(execFile);

/**
 * A term is safe for the ripgrep prefilter only if JSON string escaping can
 * never alter it. Pi stores conversation text as literal UTF-8, so normal
 * alphanumeric/CJK terms match the raw bytes verbatim. Terms containing quotes,
 * backslashes, angle brackets, ampersands, or control characters may appear
 * escaped (e.g. `\"`, `\u001b`, `\u003e`) in some entries, so we skip rg for
 * them and let the exact scan run over every session instead.
 */
function isRgSafeTerm(term: string): boolean {
	for (const ch of term) {
		const code = ch.codePointAt(0) ?? 0;
		if (code < 0x20) return false;
		if (ch === '"' || ch === "\\" || ch === "&" || ch === "<" || ch === ">") return false;
	}
	return true;
}

/** Files (from `paths`) whose raw bytes contain `term`, or null if rg is unusable. */
async function rgFilesForTerm(term: string, paths: readonly string[], signal?: AbortSignal): Promise<Set<string> | null> {
	const found = new Set<string>();
	for (let i = 0; i < paths.length; i += RG_PREFILTER_CHUNK) {
		if (signal?.aborted) return null;
		const chunk = paths.slice(i, i + RG_PREFILTER_CHUNK);
		try {
			const { stdout } = await execFileAsync(
				"rg",
				["-l", "--null", "-i", "-F", "-e", term, "--", ...chunk],
				{ maxBuffer: 256 * 1024 * 1024, signal },
			);
			for (const path of stdout.split("\0")) if (path) found.add(path);
		} catch (error) {
			// Exit code 1 means "no matches in this chunk", which is expected. Any
			// other failure (rg missing, exit 2, spawn error) means we cannot trust
			// rg, so signal a full-scan fallback by returning null.
			if ((error as { code?: unknown }).code === 1) continue;
			return null;
		}
	}
	return found;
}

/**
 * Intersection of files containing every term, or null if rg is unavailable so
 * the caller falls back to scanning all candidates. A sound superset of the
 * exact scan's accept condition (every term present somewhere in the session).
 */
async function rgCandidatePaths(terms: readonly string[], paths: readonly string[], signal?: AbortSignal): Promise<Set<string> | null> {
	let accumulator: Set<string> | null = null;
	for (const term of terms) {
		const matches = await rgFilesForTerm(term, paths, signal);
		if (matches === null) return null;
		if (accumulator === null) {
			accumulator = matches;
		} else {
			for (const path of accumulator) if (!matches.has(path)) accumulator.delete(path);
		}
		if (accumulator.size === 0) return accumulator;
	}
	return accumulator ?? new Set(paths);
}

export interface SessionSearchResult {
	session: SessionInfo;
	score: number;
	snippet: string;
	entryId?: string;
	entryLabel?: string;
	truncated: boolean;
}

interface SearchFragment {
	text: string;
	label: string;
	entryId?: string;
}

interface ParsedSearchArgs {
	query: string;
	scope: "all" | "current";
}

function normalize(text: string): string {
	return text.toLocaleLowerCase();
}

function compactPath(path: string, home = process.env.HOME ?? ""): string {
	return home && (path === home || path.startsWith(`${home}/`)) ? `~${path.slice(home.length)}` : path;
}

function stripDisplayMetadata(text: string): string {
	return text
		.replace(/<!-- pi:web-search(?:-(?:query(?:-count)?|source(?:-count)?))?:[^>]* -->/gi, "")
		.replace(/\n{3,}/g, "\n\n")
		.trim();
}

function compactText(text: string, limit: number): string {
	const normalized = stripDisplayMetadata(text).replace(/\s+/g, " ").trim();
	return normalized.length > limit ? `${normalized.slice(0, limit - 1)}…` : normalized;
}

function contentText(content: any): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const item of content) {
		if (typeof item?.text === "string") parts.push(stripDisplayMetadata(item.text));
		if (typeof item?.thinking === "string") parts.push(stripDisplayMetadata(item.thinking));
		if (item?.type === "toolCall") {
			let args = "";
			try { args = JSON.stringify(item.arguments ?? {}); } catch { args = String(item.arguments ?? ""); }
			parts.push(`${item.name ?? "tool"} ${args}`);
		}
		if (item?.type === "image") parts.push("[image]");
	}
	return parts.join("\n");
}

function entryFragments(entry: any): SearchFragment[] {
	if (entry?.type === "session") return [{ text: `${entry.id ?? ""}\n${entry.cwd ?? ""}`, label: "session header" }];
	if (entry?.type === "session_info") return [{ text: String(entry.name ?? ""), label: "session title", entryId: entry.id }];
	if (entry?.type === "compaction") return [{ text: String(entry.summary ?? ""), label: "compaction summary", entryId: entry.id }];
	if (entry?.type === "branch_summary") return [{ text: String(entry.summary ?? ""), label: "branch summary", entryId: entry.id }];
	if (entry?.type === "custom_message") return [{ text: contentText(entry.content), label: `custom message ${entry.customType ?? ""}`.trim(), entryId: entry.id }];
	if (entry?.type !== "message") return [];

	const message = entry.message ?? {};
	const fragments: SearchFragment[] = [];
	const text = contentText(message.content);
	if (text) {
		const label = message.role === "toolResult"
			? `${message.toolName ?? "tool"} result`
			: `${message.role ?? "message"} message`;
		fragments.push({ text, label, entryId: entry.id });
	}
	if (typeof message.errorMessage === "string") fragments.push({ text: message.errorMessage, label: "assistant error", entryId: entry.id });
	if (message.role === "toolResult" && message.toolName) fragments.push({ text: String(message.toolName), label: `${message.toolName} result`, entryId: entry.id });
	return fragments;
}

function queryTerms(query: string): string[] {
	return [...new Set(normalize(query).split(/\s+/).filter(Boolean))];
}

function countOccurrences(haystack: string, needle: string): number {
	if (!needle) return 0;
	let count = 0;
	let offset = 0;
	while ((offset = haystack.indexOf(needle, offset)) >= 0) {
		count += 1;
		offset += Math.max(1, needle.length);
	}
	return count;
}

export function scoreSearchText(text: string, query: string): { score: number; matchedTerms: Set<string> } {
	const haystack = normalize(text);
	const phrase = normalize(query.trim());
	const terms = queryTerms(query);
	const matchedTerms = new Set<string>();
	let score = countOccurrences(haystack, phrase) * 20;
	for (const term of terms) {
		const count = countOccurrences(haystack, term);
		if (count > 0) {
			matchedTerms.add(term);
			score += Math.min(10, count);
		}
	}
	return { score, matchedTerms };
}

function snippetAround(text: string, query: string, radius = 110): string {
	const compact = text.replace(/\s+/g, " ").trim();
	if (!compact) return "(empty match)";
	const lower = normalize(compact);
	const phrase = normalize(query.trim());
	let index = lower.indexOf(phrase);
	if (index < 0) {
		for (const term of queryTerms(query)) {
			index = lower.indexOf(term);
			if (index >= 0) break;
		}
	}
	if (index < 0) return compactText(compact, radius * 2);
	const start = Math.max(0, index - radius);
	const end = Math.min(compact.length, index + Math.max(phrase.length, 1) + radius);
	return `${start > 0 ? "…" : ""}${compact.slice(start, end)}${end < compact.length ? "…" : ""}`;
}

export function parseSessionSearchArgs(args: string): ParsedSearchArgs {
	const tokens = args.trim().match(/(?:[^\s"]+|"[^"]*")+/g)?.map((token) => token.replace(/^"|"$/g, "")) ?? [];
	let scope: ParsedSearchArgs["scope"] = "all";
	const query: string[] = [];
	for (const token of tokens) {
		if (token === "--current" || token === "--project") scope = "current";
		else if (token === "--all") scope = "all";
		else query.push(token);
	}
	return { query: query.join(" ").trim(), scope };
}

export async function scanSession(session: SessionInfo, query: string, signal?: AbortSignal): Promise<SessionSearchResult | undefined> {
	const terms = queryTerms(query);
	const foundTerms = new Set<string>();
	let score = 0;
	let bestScore = -1;
	let bestFragment: SearchFragment | undefined;
	let consumedBytes = 0;
	let truncated = false;

	const metadataFragments: SearchFragment[] = [
		{ text: session.name ?? "", label: "session title" },
		{ text: session.cwd, label: "working directory" },
		{ text: session.id, label: "session id" },
		{ text: session.firstMessage, label: "first user message" },
	];
	for (const fragment of metadataFragments) {
		const result = scoreSearchText(fragment.text, query);
		for (const term of result.matchedTerms) foundTerms.add(term);
		const weighted = result.score * (fragment.label === "session title" ? 4 : fragment.label === "first user message" ? 2 : 1);
		score += weighted;
		if (weighted > bestScore) {
			bestScore = weighted;
			bestFragment = fragment;
		}
	}

	try {
		const stream = createReadStream(session.path, { encoding: "utf8" });
		const reader = createInterface({ input: stream, crlfDelay: Infinity });
		for await (const line of reader) {
			if (signal?.aborted) {
				reader.close();
				return undefined;
			}
			consumedBytes += Buffer.byteLength(line, "utf8") + 1;
			if (consumedBytes > MAX_FILE_BYTES) {
				truncated = true;
				break;
			}
			let entry: any;
			try { entry = JSON.parse(line); } catch { continue; }
			for (const fragment of entryFragments(entry)) {
				const result = scoreSearchText(fragment.text, query);
				if (result.score <= 0) continue;
				for (const term of result.matchedTerms) foundTerms.add(term);
				const weighted = result.score + (fragment.label.includes("error") ? 5 : fragment.label.includes("tool") || fragment.label.includes("result") ? 2 : 0);
				score += weighted;
				if (weighted > bestScore) {
					bestScore = weighted;
					bestFragment = fragment;
				}
			}
		}
	} catch {
		return undefined;
	}

	if (terms.some((term) => !foundTerms.has(term)) || !bestFragment) return undefined;
	return {
		session,
		score,
		snippet: snippetAround(bestFragment.text, query),
		entryId: bestFragment.entryId,
		entryLabel: bestFragment.label,
		truncated,
	};
}

async function mapConcurrent<T, U>(items: readonly T[], concurrency: number, fn: (item: T, index: number) => Promise<U>): Promise<U[]> {
	const results = new Array<U>(items.length);
	let next = 0;
	const workers = Array.from({ length: Math.max(1, Math.min(concurrency, items.length || 1)) }, async () => {
		while (true) {
			const index = next++;
			if (index >= items.length) return;
			results[index] = await fn(items[index], index);
		}
	});
	await Promise.all(workers);
	return results;
}

async function copyText(text: string): Promise<boolean> {
	if (process.platform !== "darwin") return false;
	return new Promise<boolean>((resolve) => {
		const child = spawn("pbcopy", [], { stdio: ["pipe", "ignore", "ignore"] });
		child.on("error", () => resolve(false));
		child.on("close", (code) => resolve(code === 0));
		child.stdin.end(text);
	});
}

function resultLabel(session: SessionInfo): string {
	const date = session.modified.toISOString().slice(0, 10);
	const title = compactText(session.name || session.firstMessage || session.id, 70);
	const location = compactText(compactPath(session.cwd), 42);
	return `${date} · ${title} · ${location} · ${session.id.slice(0, 8)}`;
}

function resultDetails(result: SessionSearchResult): string {
	return [
		result.session.name ? `Title: ${result.session.name}` : undefined,
		`Session: ${result.session.id}`,
		`Project: ${compactPath(result.session.cwd)}`,
		`Modified: ${result.session.modified.toLocaleString()}`,
		`Match: ${result.entryLabel ?? "session metadata"}${result.truncated ? " · file scan capped at 64 MiB" : ""}`,
		"",
		result.snippet,
	].filter((line) => line !== undefined).join("\n");
}

const RESULT_WINDOW = 10;
const SEARCH_DEBOUNCE_MS = 140;

/**
 * Core search used by both the live picker and the non-TUI fallback: ripgrep
 * prefilter (escape-guarded) narrows candidates, then the exact per-entry scan
 * ranks them. Abortable via `signal` so stale searches stop promptly.
 */
async function runSessionSearch(
	query: string,
	sessions: readonly SessionInfo[],
	opts: { signal?: AbortSignal; onProgress?: (completed: number, total: number) => void } = {},
): Promise<SessionSearchResult[]> {
	const { signal, onProgress } = opts;
	const terms = queryTerms(query);
	if (terms.length === 0) return [];

	let scanTargets: readonly SessionInfo[] = sessions;
	if (terms.every(isRgSafeTerm)) {
		const rgPaths = await rgCandidatePaths(terms, sessions.map((session) => session.path), signal);
		if (rgPaths) scanTargets = sessions.filter((session) => rgPaths.has(session.path));
	}
	if (signal?.aborted) return [];

	let completed = 0;
	const total = scanTargets.length;
	const scanned = await mapConcurrent(scanTargets, SEARCH_CONCURRENCY, async (session) => {
		const result = await scanSession(session, query, signal);
		completed += 1;
		onProgress?.(completed, total);
		return result;
	});
	if (signal?.aborted) return [];
	return scanned
		.filter((result): result is SessionSearchResult => Boolean(result))
		.sort((a, b) => b.score - a.score || b.session.modified.getTime() - a.session.modified.getTime())
		.slice(0, MAX_RESULTS);
}

/** Non-TUI fallback: prompt once, search, and show a static selector. */
async function searchAndSelectFallback(
	ctx: any,
	candidates: readonly SessionInfo[],
	parsed: ParsedSearchArgs,
): Promise<SessionSearchResult | null> {
	let query = parsed.query;
	if (!query) {
		const input = await ctx.ui.input("Search Pi sessions", "keywords, optionally --current");
		query = parseSessionSearchArgs(input ?? "").query;
	}
	if (!query) return null;
	ctx.ui.setStatus("session-search", ctx.ui.theme.fg("accent", "searching sessions…"));
	const results = await runSessionSearch(query, candidates, {
		onProgress: (done, total) => {
			if (done % 8 === 0 || done === total) {
				ctx.ui.setStatus("session-search", ctx.ui.theme.fg("accent", `searching ${done}/${total}…`));
			}
		},
	});
	ctx.ui.setStatus("session-search", undefined);
	if (results.length === 0) {
		ctx.ui.notify(`No ${parsed.scope === "current" ? "current-project " : ""}sessions matched “${query}”.`, "info");
		return null;
	}
	const choices = results.map((result) => resultLabel(result.session));
	const selectedLabel = await ctx.ui.select(`Session matches for “${query}” (${results.length})`, choices);
	if (!selectedLabel) return null;
	return results[choices.indexOf(selectedLabel)] ?? null;
}

/** A ranked row in the live picker. Snippet/entryId are resolved lazily. */
interface RankedResult {
	session: SessionInfo;
	score: number;
	/** undefined = not scanned yet; null = scanned, no entry-level match. */
	enriched?: SessionSearchResult | null;
}

/**
 * Per-file match counts for one term via `rg --count-matches` (~20ms across the
 * whole corpus). Returns null when rg is unavailable/fails so callers fall back
 * to the exact scan.
 */
async function rgCountsForTerm(
	term: string,
	paths: readonly string[],
	signal?: AbortSignal,
): Promise<Map<string, number> | null> {
	const counts = new Map<string, number>();
	for (let i = 0; i < paths.length; i += RG_PREFILTER_CHUNK) {
		if (signal?.aborted) return null;
		const chunk = paths.slice(i, i + RG_PREFILTER_CHUNK);
		try {
			const { stdout } = await execFileAsync(
				"rg",
				["--count-matches", "--null", "-i", "-F", "-e", term, "--", ...chunk],
				{ maxBuffer: 64 * 1024 * 1024, signal },
			);
			for (const line of stdout.split("\n")) {
				const sep = line.indexOf("\0");
				if (sep <= 0) continue;
				counts.set(line.slice(0, sep), Number(line.slice(sep + 1)) || 0);
			}
		} catch (error) {
			if ((error as { code?: unknown }).code === 1) continue; // no matches in chunk
			return null;
		}
	}
	return counts;
}

/**
 * Search + rank entirely in rg: every term must appear (AND), score = summed
 * raw hit count. Byte-level counting is a sound superset of the exact scorer
 * (never drops a content match); ranking tracks it closely in practice, and the
 * exact snippet/entry is resolved lazily for the selected row only.
 */
async function rgRankSessions(
	terms: readonly string[],
	sessions: readonly SessionInfo[],
	signal?: AbortSignal,
): Promise<RankedResult[] | null> {
	const byPath = new Map(sessions.map((session) => [session.path, session]));
	let scores: Map<string, number> | undefined;
	for (const term of terms) {
		const candidates = scores ? [...scores.keys()] : [...byPath.keys()];
		if (candidates.length === 0) break;
		const counts = await rgCountsForTerm(term, candidates, signal);
		if (!counts) return null;
		if (!scores) {
			scores = counts;
		} else {
			for (const [path, prev] of scores) {
				const count = counts.get(path);
				if (!count) scores.delete(path);
				else scores.set(path, prev + count);
			}
		}
	}
	if (!scores) return [];
	const ranked: RankedResult[] = [];
	for (const [path, score] of scores) {
		const session = byPath.get(path);
		if (session && score > 0) ranked.push({ session, score });
	}
	return ranked
		.sort((a, b) => b.score - a.score || b.session.modified.getTime() - a.session.modified.getTime())
		.slice(0, MAX_RESULTS);
}

/**
 * Live, incremental session-search picker. rg does search + ranking in one pass
 * per keystroke (debounced, abortable); labels come from in-memory SessionInfo;
 * only the selected row's file is parsed (lazily) for its snippet/entry.
 */
class LiveSessionSearchComponent implements Component {
	private readonly input = new Input();
	private results: RankedResult[] = [];
	private selectedIndex = 0;
	private activeQuery = "";
	private finished = false;
	private status: string;
	private lastQuery: string;
	private searchToken = 0;
	private abort: AbortController | undefined;
	private debounceTimer: ReturnType<typeof setTimeout> | undefined;

	constructor(
		private readonly tui: TUI,
		private readonly theme: Theme,
		private readonly sessions: readonly SessionInfo[],
		parsed: ParsedSearchArgs,
		private readonly onDone: (result: SessionSearchResult | null) => void,
	) {
		this.input.focused = true;
		this.input.setValue(parsed.query);
		this.lastQuery = parsed.query;
		this.status = parsed.query.trim() ? "searching…" : "type to search";
		if (parsed.query.trim()) void this.runSearch();
	}

	private scheduleSearch(): void {
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
		this.debounceTimer = setTimeout(() => {
			this.debounceTimer = undefined;
			void this.runSearch();
		}, SEARCH_DEBOUNCE_MS);
	}

	private async runSearch(): Promise<void> {
		const token = ++this.searchToken;
		this.abort?.abort();
		const controller = new AbortController();
		this.abort = controller;

		const query = this.input.getValue().trim();
		if (!query) {
			this.results = [];
			this.selectedIndex = 0;
			this.status = "type to search";
			this.tui.requestRender();
			return;
		}

		this.activeQuery = query;
		this.status = "searching…";
		this.tui.requestRender();
		let ranked: RankedResult[] = [];
		try {
			const terms = queryTerms(query);
			let rg: RankedResult[] | null = null;
			if (terms.length > 0 && terms.every(isRgSafeTerm)) {
				rg = await rgRankSessions(terms, this.sessions, controller.signal);
			}
			if (rg) {
				ranked = rg;
			} else {
				// Escape-unsafe term or rg unavailable: exact scan (slow but sound).
				const exact = await runSessionSearch(query, this.sessions, {
					signal: controller.signal,
					onProgress: (done, total) => {
						if (token !== this.searchToken) return;
						if (done % 16 === 0 || done === total) {
							this.status = `searching ${done}/${total}…`;
							this.tui.requestRender();
						}
					},
				});
				ranked = exact.map((result) => ({ session: result.session, score: result.score, enriched: result }));
			}
		} catch {
			ranked = [];
		}
		if (token !== this.searchToken) return; // superseded by a newer keystroke
		this.results = ranked;
		this.selectedIndex = 0;
		this.status = ranked.length === 0 ? "no matches" : `${ranked.length} match${ranked.length === 1 ? "" : "es"}`;
		this.tui.requestRender();
		void this.ensureEnriched(token, 0);
	}

	handleInput(data: string): void {
		if (matchesKey(data, Key.up)) {
			if (this.results.length > 0) {
				this.selectedIndex = this.selectedIndex === 0 ? this.results.length - 1 : this.selectedIndex - 1;
				void this.ensureEnriched(this.searchToken, this.selectedIndex);
				this.tui.requestRender();
			}
			return;
		}
		if (matchesKey(data, Key.down)) {
			if (this.results.length > 0) {
				this.selectedIndex = this.selectedIndex === this.results.length - 1 ? 0 : this.selectedIndex + 1;
				void this.ensureEnriched(this.searchToken, this.selectedIndex);
				this.tui.requestRender();
			}
			return;
		}
		if (matchesKey(data, Key.enter)) {
			if (this.results[this.selectedIndex]) void this.finishSelected();
			return;
		}
		if (matchesKey(data, Key.escape) || matchesKey(data, Key.ctrl("c"))) {
			this.finish(null);
			return;
		}
		// Everything else edits the query box.
		this.input.handleInput(data);
		const value = this.input.getValue();
		if (value !== this.lastQuery) {
			this.lastQuery = value;
			this.scheduleSearch();
		}
	}

	/** Parse just this row's file for its exact snippet/entryId, once. */
	private async ensureEnriched(token: number, index: number): Promise<void> {
		const item = this.results[index];
		if (!item || item.enriched !== undefined) return;
		const scanned = await scanSession(item.session, this.activeQuery);
		if (token !== this.searchToken) return;
		item.enriched = scanned ?? null;
		this.tui.requestRender();
	}

	private async finishSelected(): Promise<void> {
		const item = this.results[this.selectedIndex];
		if (!item) return;
		await this.ensureEnriched(this.searchToken, this.selectedIndex);
		this.finish(
			item.enriched ?? {
				session: item.session,
				score: item.score,
				snippet: compactText(item.session.firstMessage || item.session.name || item.session.id, 200),
				truncated: false,
			},
		);
	}

	private finish(result: SessionSearchResult | null): void {
		if (this.finished) return;
		this.finished = true;
		this.dispose();
		this.onDone(result);
	}

	dispose(): void {
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
		this.debounceTimer = undefined;
		this.abort?.abort();
	}

	invalidate(): void {}

	render(width: number): string[] {
		const dim = (s: string) => this.theme.fg("dim", s);
		const accent = (s: string) => this.theme.fg("accent", s);
		const lines: string[] = [];
		lines.push(dim("Search sessions  ·  ↑↓ move · enter open · esc cancel"));
		lines.push(...this.input.render(width));
		lines.push(dim(this.status));

		if (this.results.length > 0) {
			const half = Math.floor(RESULT_WINDOW / 2);
			const start = Math.max(0, Math.min(this.selectedIndex - half, this.results.length - RESULT_WINDOW));
			const end = Math.min(start + RESULT_WINDOW, this.results.length);
			for (let i = start; i < end; i++) {
				const isSelected = i === this.selectedIndex;
				const label = truncateToWidth(resultLabel(this.results[i].session), Math.max(1, width - 2), "");
				lines.push(isSelected ? accent(`→ ${label}`) : `  ${dim(label)}`);
			}
			if (start > 0 || end < this.results.length) {
				lines.push(dim(`  (${this.selectedIndex + 1}/${this.results.length})`));
			}
			const selected = this.results[this.selectedIndex];
			const snippet = selected
				? selected.enriched === undefined
					? "…"
					: (selected.enriched?.snippet ?? selected.session.firstMessage ?? "")
				: "";
			if (snippet) {
				lines.push("");
				lines.push(dim(truncateToWidth(snippet.replace(/\s+/g, " ").trim(), Math.max(1, width - 2), "")));
			}
		}
		return lines;
	}
}

export default function (pi: ExtensionAPI) {
	pi.registerCommand("session-search", {
		description: "Search user, assistant, tool, error, and compaction text across Pi sessions",
		handler: async (args, ctx) => {
			const parsed = parseSessionSearchArgs(args);

			// ctx.switchSession() tears down the current session runtime and
			// invalidates this ctx (and ctx.ui). Once a switch happens, the
			// finally block must not touch the stale ctx, so flag it.
			let switched = false;
			try {
				const sessions = await SessionManager.listAll();
				const candidates = parsed.scope === "current"
					? sessions.filter((session) => session.cwd === ctx.cwd)
					: sessions;

				// Live incremental picker in the TUI; static prompt+select fallback
				// elsewhere. The live component runs the (rg-prefiltered) search itself,
				// debounced per keystroke and cancelling stale in-flight scans.
				const selected = ctx.mode === "tui"
					? await ctx.ui.custom<SessionSearchResult | null>((tui, theme, _kb, done) =>
							new LiveSessionSearchComponent(tui, theme, candidates, parsed, done),
						)
					: await searchAndSelectFallback(ctx, candidates, parsed);
				if (!selected) return;
				const action = await ctx.ui.select(resultDetails(selected), [
					"Resume this session",
					"Fork through the matching entry",
					"Copy matching excerpt",
					"Put excerpt in editor",
					"Cancel",
				]);
				if (!action || action === "Cancel") return;
				if (action === "Resume this session") {
					const result = await ctx.switchSession(selected.session.path, {
						withSession: async (replacementCtx: any) => replacementCtx.ui.notify(`Resumed ${selected.session.name || selected.session.id.slice(0, 8)}.`, "info"),
					});
					if (result.cancelled) {
						ctx.ui.notify("Session switch was canceled.", "warning");
						return;
					}
					switched = true;
					return;
				}
				if (action === "Fork through the matching entry") {
					const source = SessionManager.open(selected.session.path);
					const targetId = selected.entryId && source.getEntry(selected.entryId) ? selected.entryId : source.getLeafId();
					if (!targetId) {
						ctx.ui.notify("The matching session has no forkable entry.", "warning");
						return;
					}
					const forkPath = source.createBranchedSession(targetId);
					if (!forkPath) {
						ctx.ui.notify("Could not create a persisted session fork.", "error");
						return;
					}
					const result = await ctx.switchSession(forkPath, {
						withSession: async (replacementCtx: any) => replacementCtx.ui.notify(`Forked search match from ${selected.session.id.slice(0, 8)}.`, "info"),
					});
					if (result.cancelled) {
						const removed = await unlink(forkPath).then(() => true, () => false);
						ctx.ui.notify(
							removed ? "Fork switch was canceled; the unused fork was removed." : `Fork switch was canceled; unused fork remains at ${forkPath}.`,
							"warning",
						);
						return;
					}
					switched = true;
					return;
				}
				if (action === "Copy matching excerpt") {
					if (await copyText(selected.snippet)) ctx.ui.notify("Matching excerpt copied.", "info");
					else {
						ctx.ui.setEditorText(selected.snippet);
						ctx.ui.notify("Clipboard backend unavailable; excerpt placed in the editor.", "warning");
					}
					return;
				}
				ctx.ui.setEditorText(selected.snippet);
			} finally {
				// Only clear the status on the live ctx. After a switch, the old
				// ctx is stale and the new session owns its own UI state.
				if (!switched) ctx.ui.setStatus("session-search", undefined);
			}
		},
	});
}
