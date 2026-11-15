import { spawn } from "node:child_process";
import { closeSync, existsSync, linkSync, openSync } from "node:fs";
import { copyFile, mkdir, readdir, readFile, rm, stat, symlink, writeFile } from "node:fs/promises";
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
	status: string;
	message: string;
	startedAt: string;
	finishedAt?: string;
};

export function repoRoot(): string {
	return path.resolve(process.cwd(), "../../..");
}

export function kbRoot(): string {
	return path.resolve(process.env.QODEX_KB_ROOT || path.join(repoRoot(), "knowledge-base"));
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
	if (!validKey(key)) throw new Error("专业标识只能包含小写字母、数字、下划线和短横线（2–41 位）。");
	if (!name.trim()) throw new Error("专业名称不能为空。");
	const dir = path.join(kbRoot(), key);
	if (existsSync(dir)) throw new Error(`专业 ${key} 已存在。`);
	await writeJson(path.join(dir, "subject.json"), { key, name: name.trim(), createdAt: new Date().toISOString() });
	await writeJson(path.join(dir, "links.json"), []);
	return { key };
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

export async function linkKb(subjectKey: string, kbId: string): Promise<{ linked: string }> {
	if (!validKey(subjectKey)) throw new Error("专业标识不合法。");
	if (!/^[\w-]{1,64}$/.test(kbId)) throw new Error("知识库标识不合法。");
	if (!existsSync(path.join(libraryDir(), kbId, "kb.sqlite"))) throw new Error("书库里没有这个知识库。");
	const dir = path.join(kbRoot(), subjectKey);
	if (!existsSync(dir)) throw new Error(`专业 ${subjectKey} 不存在。`);
	const linksFile = path.join(dir, "links.json");
	const links = (await readJson<{ kbId: string; addedAt: string }[]>(linksFile)) ?? [];
	if (!links.some((l) => l.kbId === kbId)) {
		links.push({ kbId, addedAt: new Date().toISOString() });
		await writeJson(linksFile, links);
	}
	await materialise(subjectKey, kbId);
	return { linked: kbId };
}

export async function unlinkKb(subjectKey: string, kbId: string): Promise<{ unlinked: string }> {
	if (!validKey(subjectKey)) throw new Error("专业标识不合法。");
	const dir = path.join(kbRoot(), subjectKey);
	const linksFile = path.join(dir, "links.json");
	const links = (await readJson<{ kbId: string }[]>(linksFile)) ?? [];
	await writeJson(
		linksFile,
		links.filter((l) => l.kbId !== kbId),
	);
	await rm(path.join(dir, `kb_${kbId}.sqlite`), { force: true });
	return { unlinked: kbId };
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
	if (!validKey(subjectKey)) throw new Error("专业标识不合法。");
	const source = path.resolve(sourcePath.trim());
	const info = await stat(source).catch(() => undefined);
	if (!info?.isFile()) throw new Error("找不到该文件，请填写本机绝对路径。");
	if (!/\.(pdf|docx|doc|txt|md)$/i.test(source)) throw new Error("只接受 PDF、DOC、DOCX、TXT、MD。");
	const kbId = `kb_${Date.now().toString(36)}`;
	const kbDir = path.join(libraryDir(), kbId);
	await mkdir(path.join(kbDir, "sources"), { recursive: true });
	const book = path.join(kbDir, "sources", path.basename(source));
	await copyFile(source, book);
	await writeJson(path.join(kbDir, "book.json"), {
		id: kbId,
		title: path.basename(source, path.extname(source)),
		sourcePath: source,
		createdAt: new Date().toISOString(),
	});
	const job = startBuild(kbDir, book);
	await linkKb(subjectKey, kbId);
	return { kbId, job };
}

function startBuild(kbDir: string, book: string): BuildJob {
	const id = Date.now().toString(36);
	const job: BuildJob = {
		id,
		book: path.basename(book),
		status: "running",
		message: "解析入库中",
		startedAt: new Date().toISOString(),
	};
	const jobsDir = path.join(kbDir, "jobs");
	void mkdir(jobsDir, { recursive: true }).then(() => writeJson(path.join(jobsDir, `${id}.json`), job));

	// File descriptor, not a stream: a stream has no fd yet at spawn time, and a
	// pipe would dead-lock once its buffer fills.
	const fd = openSync(path.join(jobsDir, `${id}.log`), "a");
	const args = [
		path.join(repoRoot(), "research-assets", "skills", "build-knowledge-base", "scripts", "kb_pipeline.py"),
		"run",
		"--input",
		book,
		"--out",
		kbDir,
		"--stop-after",
		"ingest",
		"--ocr",
		"off",
	];
	const child = spawn(process.env.QODEX_PYTHON || "python", args, {
		cwd: repoRoot(),
		stdio: ["ignore", fd, fd],
		windowsHide: true,
	});
	const settle = (status: string, message: string) => {
		closeSync(fd);
		void writeJson(path.join(jobsDir, `${id}.json`), { ...job, status, message, finishedAt: new Date().toISOString() });
	};
	child.on("error", (error) => settle("failed", `无法启动构建进程：${error.message}`));
	child.on("exit", (code) =>
		settle(code === 0 ? "done" : "failed", code === 0 ? "解析入库完成" : `构建失败，退出码 ${code}`),
	);
	return job;
}
