import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, linkSync } from "node:fs";
import {
	copyFile,
	lstat,
	mkdir,
	open,
	readdir,
	readFile,
	rename,
	rm,
	stat,
	symlink,
	writeFile,
} from "node:fs/promises";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

/**
 * Knowledge-base model: one book is one SQLite knowledge base, and a subject is a
 * link to those bases rather than a copy of them.
 *
 *   <kbRoot>/_library/<kbId>/kb.sqlite     the book's knowledge base
 *   <kbRoot>/_library/<kbId>/book.json     title, source, pages
 *   <kbRoot>/_library/<kbId>/sources/<pdf> the original file, when added here
 *   <kbRoot>/<subjectKey>/subject.json     display name
 *   <kbRoot>/<subjectKey>/links.json       [{ kbId, addedAt }]
 *   <kbRoot>/<subjectKey>/kb_<kbId>.sqlite hard link to the library database
 *
 * The materialised link keeps the existing Python retriever working unchanged: it
 * still scans `<subject>/kb*.sqlite`. Linking rather than copying lets one book
 * belong to several subjects without duplicating gigabytes.
 */

const SUBJECT_KEY = /^[a-z0-9][a-z0-9_-]{1,40}$/;
const LIBRARY_DIR = "_library";
const BOOK_ID = /^[\w-]{1,64}$/;
type SubjectLink = { kbId: string; addedAt: string };

export class KbConflictError extends Error {}

const mutationState = globalThis as typeof globalThis & { qodexKbMutation?: Promise<void> };

function mutateKb<T>(operation: () => Promise<T>): Promise<T> {
	const result = (mutationState.qodexKbMutation ?? Promise.resolve()).then(operation);
	mutationState.qodexKbMutation = result.then(
		() => undefined,
		() => undefined,
	);
	return result;
}

export type KbEntry = {
	id: string;
	title: string;
	sourcePath: string;
	pages: number | null;
	chunks: number;
	indexed: number;
	bytes: number;
	createdAt: string;
	built: boolean;
	subjects: string[];
};

export type SubjectSummary = { key: string; name: string; createdAt: string; kbs: string[] };

export type BuildJob = {
	id: string;
	book: string;
	skill: "build-knowledge-base";
	status: "running" | "done" | "failed";
	message: string;
	startedAt: string;
	finishedAt?: string;
};

export function repoRoot(): string {
	return path.resolve(process.cwd(), "../../..");
}

export function kbRoot(): string {
	return path.resolve(process.env.QODEX_KB_ROOT || path.join(repoRoot(), "kb_library"));
}

function libraryDir(): string {
	return path.join(kbRoot(), LIBRARY_DIR);
}

function validKey(key: string): boolean {
	return SUBJECT_KEY.test(key);
}

async function readJson<T>(file: string): Promise<T | undefined> {
	try {
		return JSON.parse(await readFile(file, "utf8")) as T;
	} catch {
		return undefined;
	}
}

async function writeJson(file: string, value: unknown): Promise<void> {
	await mkdir(path.dirname(file), { recursive: true });
	await writeFile(file, JSON.stringify(value, null, 2), "utf8");
}

function dbFacts(
	file: string,
): { chunks: number; indexed: number; title: string; pages: number | null; source: string } | undefined {
	let db: DatabaseSync | undefined;
	try {
		db = new DatabaseSync(file, { readOnly: true });
		const chunks = Number((db.prepare("select count(*) as c from chunks").get() as { c: number }).c);
		const indexed = Number((db.prepare("select count(*) as c from chunks_fts").get() as { c: number }).c);
		const doc = db.prepare("select title, source_path, unit_count from documents order by rowid limit 1").get() as
			| { title?: string; source_path?: string; unit_count?: number }
			| undefined;
		return {
			chunks,
			indexed,
			title: String(doc?.title || "未命名"),
			pages: doc?.unit_count == null ? null : Number(doc.unit_count),
			source: String(doc?.source_path || ""),
		};
	} catch {
		return undefined;
	} finally {
		db?.close();
	}
}

async function subjectsOnDisk(): Promise<SubjectSummary[]> {
	const root = kbRoot();
	if (!existsSync(root)) return [];
	const subjects: SubjectSummary[] = [];
	for (const name of await readdir(root)) {
		if (name.startsWith("_")) continue; // _library and future private dirs
		const dir = path.join(root, name);
		if (!(await stat(dir).catch(() => undefined))?.isDirectory()) continue;
		const meta = await readJson<{ name?: string; createdAt?: string }>(path.join(dir, "subject.json"));
		const links = (await readJson<{ kbId: string }[]>(path.join(dir, "links.json"))) ?? [];
		subjects.push({
			key: name,
			name: meta?.name || name,
			createdAt: meta?.createdAt || "",
			kbs: links.map((l) => l.kbId),
		});
	}
	return subjects.sort((a, b) => a.key.localeCompare(b.key));
}

export async function listLibrary(): Promise<KbEntry[]> {
	const dir = libraryDir();
	if (!existsSync(dir)) return [];
	const subjects = await subjectsOnDisk();
	const entries: KbEntry[] = [];
	for (const id of await readdir(dir)) {
		const kbDir = path.join(dir, id);
		const dbPath = path.join(kbDir, "kb.sqlite");
		if (!existsSync(dbPath)) continue;
		const meta = await readJson<{ title?: string; sourcePath?: string; createdAt?: string; pages?: number }>(
			path.join(kbDir, "book.json"),
		);
		const facts = dbFacts(dbPath);
		const info = await stat(dbPath).catch(() => undefined);
		entries.push({
			id,
			title: meta?.title || facts?.title || id,
			sourcePath: meta?.sourcePath || facts?.source || "",
			pages: meta?.pages ?? facts?.pages ?? null,
			chunks: facts?.chunks ?? 0,
			indexed: facts?.indexed ?? 0,
			bytes: info?.size ?? 0,
			createdAt: meta?.createdAt || "",
			built: !!facts,
			subjects: subjects.filter((s) => s.kbs.includes(id)).map((s) => s.key),
		});
	}
	return entries.sort((a, b) => (a.createdAt < b.createdAt ? -1 : 1));
}

export async function listSubjects(): Promise<{ root: string; subjects: SubjectSummary[]; library: KbEntry[] }> {
	return { root: kbRoot(), subjects: await subjectsOnDisk(), library: await listLibrary() };
}

export async function createSubject(key: string, name: string): Promise<{ key: string }> {
	return mutateKb(async () => {
		if (!validKey(key)) throw new Error("专业标识只能包含小写字母、数字、下划线和短横线（2–41 位）。");
		if (!name.trim()) throw new Error("专业名称不能为空。");
		const dir = path.join(kbRoot(), key);
		if (existsSync(dir)) throw new Error(`专业 ${key} 已存在。`);
		await writeJson(path.join(dir, "subject.json"), { key, name: name.trim(), createdAt: new Date().toISOString() });
		await writeJson(path.join(dir, "links.json"), []);
		return { key };
	});
}

export async function subjectDetail(key: string): Promise<{ subject: SubjectSummary; kbs: KbEntry[] }> {
	if (!validKey(key)) throw new Error("专业标识不合法。");
	const subject = (await subjectsOnDisk()).find((s) => s.key === key);
	if (!subject) throw new Error(`专业 ${key} 不存在。`);
	const library = await listLibrary();
	return { subject, kbs: library.filter((kb) => subject.kbs.includes(kb.id)) };
}

/** Materialise the link as a hard link so the Python retriever sees kb_<id>.sqlite. */
async function materialise(subjectKey: string, kbId: string): Promise<void> {
	const source = path.join(libraryDir(), kbId, "kb.sqlite");
	const target = path.join(kbRoot(), subjectKey, `kb_${kbId}.sqlite`);
	if (existsSync(target)) return;
	try {
		linkSync(source, target);
	} catch {
		try {
			await symlink(source, target);
		} catch {
			await copyFile(source, target);
		}
	}
}

async function subjectLinks(dir: string): Promise<SubjectLink[]> {
	try {
		const links: SubjectLink[] = JSON.parse(await readFile(path.join(dir, "links.json"), "utf8"));
		if (!Array.isArray(links) || !links.every((link) => link && typeof link.kbId === "string")) {
			throw new Error("专业关联记录格式无效。");
		}
		return links;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
		throw error;
	}
}

async function subjectDirectory(key: string): Promise<string> {
	if (!validKey(key)) throw new Error("专业标识不合法。");
	const dir = path.join(kbRoot(), key);
	if (!(await lstat(dir).catch(() => undefined))?.isDirectory()) throw new Error("专业不存在。");
	return dir;
}

async function removeLink(dir: string, kbId: string, links: SubjectLink[]) {
	await rm(path.join(dir, `kb_${kbId}.sqlite`), { force: true });
	if (links.some((link) => link.kbId === kbId)) {
		await writeJson(
			path.join(dir, "links.json"),
			links.filter((link) => link.kbId !== kbId),
		);
	}
}

export function linkKb(subjectKey: string, kbId: string): Promise<{ linked: string }> {
	return mutateKb(async () => {
		const dir = await subjectDirectory(subjectKey);
		if (!BOOK_ID.test(kbId)) throw new Error("知识库标识不合法。");
		if (!existsSync(path.join(libraryDir(), kbId, "kb.sqlite"))) throw new Error("书库里没有这个知识库。");
		const links = await subjectLinks(dir);
		await materialise(subjectKey, kbId);
		if (!links.some((link) => link.kbId === kbId)) {
			links.push({ kbId, addedAt: new Date().toISOString() });
			await writeJson(path.join(dir, "links.json"), links);
		}
		return { linked: kbId };
	});
}

export function unlinkKb(subjectKey: string, kbId: string): Promise<{ unlinked: string }> {
	return mutateKb(async () => {
		const dir = await subjectDirectory(subjectKey);
		if (!BOOK_ID.test(kbId)) throw new Error("知识库标识不合法。");
		await removeLink(dir, kbId, await subjectLinks(dir));
		return { unlinked: kbId };
	});
}

async function deleteDirectory(dir: string) {
	const trash = path.join(kbRoot(), "_trash");
	await mkdir(trash, { recursive: true });
	if (!(await lstat(trash)).isDirectory()) throw new Error("知识库清理目录无效。");
	const pending = path.join(trash, randomUUID());
	await rename(dir, pending);
	await rm(pending, { recursive: true, force: true }).catch(() => {
		throw new Error("条目已移出知识库，但本地文件仍被占用，未完全清理。");
	});
}

export function deleteSubject(key: string): Promise<{ deleted: string }> {
	return mutateKb(async () => {
		const dir = await subjectDirectory(key);
		const entries = await readdir(dir);
		if ((await subjectLinks(dir)).length || entries.some((entry) => /^kb.*\.sqlite$/i.test(entry))) {
			throw new KbConflictError("该专业仍有关联书籍，请先取消全部链接。");
		}
		if (entries.some((entry) => entry !== "subject.json" && entry !== "links.json")) {
			throw new KbConflictError("该专业目录还有其他本地文件，无法删除。");
		}
		await deleteDirectory(dir);
		return { deleted: key };
	});
}

export function deleteBook(kbId: string, expectedSubjects: string[]): Promise<{ deleted: string }> {
	return mutateKb(async () => {
		if (!BOOK_ID.test(kbId)) throw new Error("知识库标识不合法。");
		const library = libraryDir();
		if (!(await lstat(library).catch(() => undefined))?.isDirectory()) throw new Error("书库目录无效。");
		const book = path.join(library, kbId);
		if (!(await lstat(book).catch(() => undefined))?.isDirectory() || !existsSync(path.join(book, "kb.sqlite"))) {
			throw new Error("书库里没有这个知识库。");
		}
		const linked: { key: string; dir: string; links: SubjectLink[] }[] = [];
		for (const entry of await readdir(kbRoot(), { withFileTypes: true })) {
			if (!entry.isDirectory() || !validKey(entry.name)) continue;
			const dir = path.join(kbRoot(), entry.name);
			const links = await subjectLinks(dir);
			if (links.some((link) => link.kbId === kbId) || existsSync(path.join(dir, `kb_${kbId}.sqlite`))) {
				linked.push({ key: entry.name, dir, links });
			}
		}
		const expected = new Set(expectedSubjects);
		if (linked.length !== expected.size || linked.some(({ key }) => !expected.has(key))) {
			throw new KbConflictError("这本书的关联专业已变更，请刷新后重新确认删除。");
		}
		for (const { dir, links } of linked) await removeLink(dir, kbId, links);
		await deleteDirectory(book);
		return { deleted: kbId };
	});
}

export async function registerExisting(subjectKey: string, sourceDb: string): Promise<{ kbId: string }> {
	const source = path.resolve(sourceDb.trim());
	if (!(await stat(source).catch(() => undefined))?.isFile()) throw new Error("找不到该数据库文件。");
	const facts = dbFacts(source);
	if (!facts) throw new Error("这个文件不是知识库数据库（缺少 chunks/documents 表）。");
	const kbId = `kb_${Date.now().toString(36)}`;
	const kbDir = path.join(libraryDir(), kbId);
	await mkdir(kbDir, { recursive: true });
	await copyFile(source, path.join(kbDir, "kb.sqlite"));
	await writeJson(path.join(kbDir, "book.json"), {
		id: kbId,
		title: facts.title,
		sourcePath: facts.source || source,
		pages: facts.pages,
		createdAt: new Date().toISOString(),
	});
	await linkKb(subjectKey, kbId);
	return { kbId };
}

/** Add a PDF (or DOCX/TXT) and build its knowledge base with the skill pipeline. */
export async function addBook(subjectKey: string, sourcePath: string): Promise<{ kbId: string; job: BuildJob }> {
	const source = path.resolve(sourcePath.trim());
	const info = await stat(source).catch(() => undefined);
	if (!info?.isFile()) throw new Error("找不到该文件，请填写本机绝对路径。");
	return prepareBuild(subjectKey, path.basename(source), source, (book) => copyFile(source, book));
}

/** Add a book uploaded from the browser: the bytes are written straight into the library. */
export async function addBookFromFile(
	subjectKey: string,
	fileName: string,
	data: Buffer,
): Promise<{ kbId: string; job: BuildJob; file: string }> {
	const name = path.win32.basename(fileName);
	const result = await prepareBuild(subjectKey, name, name, (book) => writeFile(book, data));
	return { ...result, file: name };
}

async function prepareBuild(
	subjectKey: string,
	name: string,
	sourcePath: string,
	save: (book: string) => Promise<void>,
): Promise<{ kbId: string; job: BuildJob }> {
	if (!/\.(pdf|docx|doc|txt|md)$/i.test(name)) throw new Error("只接受 PDF、DOC、DOCX、TXT、MD。");
	if (subjectKey) await subjectDirectory(subjectKey);
	const script = path.join(
		repoRoot(),
		"research-assets",
		"skills",
		"build-knowledge-base",
		"scripts",
		"kb_pipeline.py",
	);
	if (!existsSync(script)) throw new Error("未安装 build-knowledge-base skill。");
	const kbId = `kb_${randomUUID()}`;
	const kbDir = path.join(libraryDir(), kbId);
	await mkdir(path.join(kbDir, "sources"), { recursive: true });
	const book = path.join(kbDir, "sources", name);
	await save(book);
	await writeJson(path.join(kbDir, "book.json"), {
		id: kbId,
		title: path.basename(name, path.extname(name)),
		sourcePath,
		createdAt: new Date().toISOString(),
	});
	const job = await startBuild(kbId, book, script, subjectKey);
	return { kbId, job };
}

export async function getBuildJob(kbId: string, jobId: string): Promise<BuildJob | undefined> {
	if (!/^kb_[a-f0-9-]{36}$/.test(kbId) || !/^[a-f0-9-]{36}$/.test(jobId)) return undefined;
	return readJson<BuildJob>(path.join(libraryDir(), kbId, "jobs", `${jobId}.json`));
}

async function startBuild(kbId: string, book: string, script: string, subjectKey: string): Promise<BuildJob> {
	const kbDir = path.join(libraryDir(), kbId);
	const id = randomUUID();
	const job: BuildJob = {
		id,
		book: path.basename(book),
		skill: "build-knowledge-base",
		status: "running",
		message: "解析入库中",
		startedAt: new Date().toISOString(),
	};
	const jobsDir = path.join(kbDir, "jobs");
	const jobFile = path.join(jobsDir, `${id}.json`);
	await writeJson(jobFile, job);
	const log = await open(path.join(jobsDir, `${id}.log`), "a");
	const args = [script, "run", "--input", book, "--out", kbDir, "--stop-after", "ingest", "--ocr", "off"];
	const child = spawn(process.env.QODEX_PYTHON || "python", args, {
		cwd: repoRoot(),
		stdio: ["ignore", log.fd, log.fd],
		windowsHide: true,
	});
	let launchError: Error | undefined;
	child.once("error", (error) => {
		launchError = error;
	});
	child.once("close", (code) => {
		void (async () => {
			let status: BuildJob["status"] = "failed";
			let message: string;
			if (launchError) {
				message = `无法启动构建进程：${launchError.message}`;
			} else if (code !== 0) {
				const state = await readJson<{ phase?: string }>(path.join(kbDir, "run_state.json"));
				message =
					state?.phase === "blocked_integrity"
						? "原文抽样未通过完整性检查，请查看 integrity_report.md。"
						: `构建失败，请查看任务日志（退出码 ${code}）。`;
			} else {
				status = "done";
				message = "解析入库完成";
				if (subjectKey) {
					try {
						await linkKb(subjectKey, kbId);
					} catch {
						message = "已入库，未能自动链接到所选专业。";
					}
				}
			}
			await writeJson(`${jobFile}.tmp`, { ...job, status, message, finishedAt: new Date().toISOString() });
			await rename(`${jobFile}.tmp`, jobFile);
		})().catch((error: unknown) => console.error("Could not save knowledge-base build status", error));
	});
	await log.close();
	return job;
}
