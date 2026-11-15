"use client";

import { BookPlus, Database, Link2, Plus, RefreshCw, Search, Unlink, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

type Kb = {
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
type Subject = { key: string; name: string; createdAt: string; kbs: string[] };
type Payload = { root: string; subjects: Subject[]; library: Kb[] };

const PAGE_SIZE = 8;

async function kb<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(path, { ...init, cache: "no-store" });
	const data: unknown = await response.json();
	if (!response.ok) {
		const body = data as { error?: string };
		throw new Error(body.error || `请求失败 ${response.status}`);
	}
	return data as T;
}

const post = (value: unknown): RequestInit => ({
	method: "POST",
	headers: { "content-type": "application/json" },
	body: JSON.stringify(value),
});

export function KnowledgeBase() {
	const [payload, setPayload] = useState<Payload>({ root: "", subjects: [], library: [] });
	const [query, setQuery] = useState("");
	const [applied, setApplied] = useState("");
	const [page, setPage] = useState(1);
	const [selected, setSelected] = useState("");
	const [creating, setCreating] = useState(false);
	const [key, setKey] = useState("");
	const [name, setName] = useState("");
	const [pdfPath, setPdfPath] = useState("");
	const [dbPath, setDbPath] = useState("");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [notice, setNotice] = useState("");

	const load = useCallback(async () => {
		try {
			const data = await kb<Payload>("/api/kb/subjects");
			setPayload(data);
			setError("");
		} catch (e) {
			setError(e instanceof Error ? e.message : "读取知识库失败");
		}
	}, []);

	useEffect(() => {
		void load();
	}, [load]);

	const run = async (action: () => Promise<string>) => {
		setBusy(true);
		setError("");
		setNotice("");
		try {
			setNotice(await action());
			await load();
		} catch (e) {
			setError(e instanceof Error ? e.message : "操作失败");
		} finally {
			setBusy(false);
		}
	};

	const booksOf = useCallback(
		(subject: Subject) => payload.library.filter((item) => subject.kbs.includes(item.id)),
		[payload.library],
	);

	// Fuzzy match on subject name, identifier, or any book title inside it.
	const filtered = useMemo(() => {
		const needle = applied.trim().toLowerCase();
		if (!needle) return payload.subjects;
		return payload.subjects.filter((subject) => {
			if (subject.name.toLowerCase().includes(needle) || subject.key.toLowerCase().includes(needle)) return true;
			return booksOf(subject).some((book) => book.title.toLowerCase().includes(needle));
		});
	}, [applied, payload.subjects, booksOf]);

	const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
	const current = Math.min(page, pages);
	const visible = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

	function search() {
		const value = query.trim();
		setApplied(value);
		setPage(1);
		if (!value) {
			setSelected("");
			return;
		}
		const needle = value.toLowerCase();
		const hits = payload.subjects.filter(
			(subject) =>
				subject.name.toLowerCase().includes(needle) ||
				subject.key.toLowerCase().includes(needle) ||
				booksOf(subject).some((book) => book.title.toLowerCase().includes(needle)),
		);
		// A single hit is the "locate to that subject" case.
		if (hits.length === 1) setSelected(hits[0].key);
	}

	const selectedSubject = payload.subjects.find((s) => s.key === selected);
	const linked = selectedSubject ? booksOf(selectedSubject) : [];
	const available = payload.library.filter((item) => !selected?.length || !selectedSubject?.kbs.includes(item.id));

	return (
		<div className="qx-page">
			<header className="qx-pagehead qx-kb-head">
				<p className="qx-eyebrow">KNOWLEDGE BASE</p>
				<h1>知识库</h1>
			</header>

			<div className="qx-kb-toolbar">
				<form
					className="qx-kb-search"
					onSubmit={(event) => {
						event.preventDefault();
						search();
					}}
				>
					<input
						value={query}
						onChange={(e) => setQuery(e.target.value)}
						placeholder="搜索书籍、专业或标识"
						aria-label="搜索知识库"
					/>
					<button type="submit" className="qx-btn">
						<Search size={15} />
						查询
					</button>
				</form>
				<div className="qx-actions">
					<button type="button" className="qx-btn" aria-label="刷新" onClick={() => void load()}>
						<RefreshCw size={15} />
					</button>
					<button type="button" className="qx-btn primary" onClick={() => setCreating((v) => !v)}>
						{creating ? <X size={15} /> : <Plus size={15} />}
						新建知识库
					</button>
				</div>
			</div>

			{error && <p className="qx-error">{error}</p>}
			{notice && <p className="qx-note">{notice}</p>}

			{creating && (
				<section className="qx-kb-card">
					<h2>
						<Plus size={16} /> 新建知识库
					</h2>
					<form
						className="qx-kb-form"
						onSubmit={(event) => {
							event.preventDefault();
							void run(async () => {
								await kb("/api/kb/subjects", post({ key: key.trim(), name: name.trim() }));
								const created = name.trim();
								setKey("");
								setName("");
								setCreating(false);
								return `知识库 ${created} 已创建`;
							});
						}}
					>
						<label>
							专业标识
							<input
								value={key}
								onChange={(e) => setKey(e.target.value)}
								placeholder="clinical_medicine"
								pattern="[a-z0-9][a-z0-9_-]{1,40}"
								required
							/>
						</label>
						<label>
							专业名称
							<input value={name} onChange={(e) => setName(e.target.value)} placeholder="临床医学" required />
						</label>
						<button type="submit" className="qx-btn primary" disabled={busy}>
							<Plus size={15} />
							创建
						</button>
					</form>
					<p className="qx-note">标识同时是目录名，会被检索用到；只能用小写字母、数字、下划线和短横线。</p>
				</section>
			)}

			<section className="qx-kb-card">
				<h2>
					<Database size={16} /> 知识库（{filtered.length}）
				</h2>
				<p className="qx-note">一个专业挂载若干本书的 SQLite 知识库；同一本书可以被多个专业链接。</p>

				{payload.subjects.length === 0 ? (
					<div className="qx-kb-empty">
						<p>暂无知识库</p>
						<button type="button" className="qx-btn primary" onClick={() => setCreating(true)}>
							<Plus size={15} />
							添加知识库
						</button>
					</div>
				) : filtered.length === 0 ? (
					<div className="qx-kb-empty">
						<p>没有匹配「{applied}」的知识库</p>
					</div>
				) : (
					<>
						<div className="qx-kb-grid">
							{visible.map((subject) => {
								const books = booksOf(subject);
								return (
									<button
										key={subject.key}
										type="button"
										className={`qx-kb-item ${subject.key === selected ? "is-active" : ""}`}
										onClick={() => setSelected(subject.key)}
									>
										<strong>{subject.name}</strong>
										<span className="qx-kb-key">{subject.key}</span>
										<span className="qx-kb-books">
											书籍：{books.length === 0 ? "无" : books.map((book) => book.title).join("、")}
										</span>
									</button>
								);
							})}
						</div>
						<div className="qx-kb-pager">
							<button type="button" className="qx-btn" disabled={current <= 1} onClick={() => setPage(current - 1)}>
								上一页
							</button>
							<span>
								第 {current} / {pages} 页
							</span>
							<button type="button" className="qx-btn" disabled={current >= pages} onClick={() => setPage(current + 1)}>
								下一页
							</button>
						</div>
					</>
				)}
			</section>

			{selectedSubject && (
				<section className="qx-kb-card">
					<h2>
						<Database size={16} /> {selectedSubject.name}
					</h2>
					<p className="qx-note">
						标识 {selectedSubject.key}　·　{linked.length} 个知识库　·　
						{linked.reduce((sum, item) => sum + item.chunks, 0)} 个块
					</p>

					{linked.length === 0 ? (
						<p className="qx-note">该专业还没有知识库。可在下方「添加书籍」或从书库链接。</p>
					) : (
						<table className="qx-table">
							<thead>
								<tr>
									<th>书名</th>
									<th>页数</th>
									<th>块数</th>
									<th>入索引</th>
									<th />
								</tr>
							</thead>
							<tbody>
								{linked.map((item) => (
									<tr key={item.id}>
										<td>{item.title}</td>
										<td>{item.pages ?? "—"}</td>
										<td>{item.chunks}</td>
										<td>{item.indexed}</td>
										<td>
											<button
												type="button"
												className="qx-link"
												onClick={() =>
													void run(async () => {
														await kb(`/api/kb/subjects/${selectedSubject.key}/links?kbId=${item.id}`, {
															method: "DELETE",
														});
														return `已从 ${selectedSubject.name} 移除《${item.title}》`;
													})
												}
											>
												<Unlink size={13} /> 取消链接
											</button>
										</td>
									</tr>
								))}
							</tbody>
						</table>
					)}

					<h3>添加书籍</h3>
					<form
						className="qx-kb-form"
						onSubmit={(event) => {
							event.preventDefault();
							void run(async () => {
								await kb("/api/kb/books", post({ subjectKey: selectedSubject.key, path: pdfPath.trim() }));
								setPdfPath("");
								return "已加入构建队列，约 1 分钟后刷新可见";
							});
						}}
					>
						<label className="qx-kb-wide">
							PDF / DOCX 绝对路径
							<input
								value={pdfPath}
								onChange={(e) => setPdfPath(e.target.value)}
								placeholder="D:\books\生物化学与分子生物学（第10版）.pdf"
							/>
						</label>
						<button type="submit" className="qx-btn primary" disabled={busy}>
							<BookPlus size={15} />
							解析并建库
						</button>
					</form>

					<form
						className="qx-kb-form"
						onSubmit={(event) => {
							event.preventDefault();
							void run(async () => {
								await kb("/api/kb/books", post({ subjectKey: selectedSubject.key, sqlitePath: dbPath.trim() }));
								setDbPath("");
								return "已登记现有知识库并链接到该专业";
							});
						}}
					>
						<label className="qx-kb-wide">
							现有知识库 .sqlite 路径
							<input
								value={dbPath}
								onChange={(e) => setDbPath(e.target.value)}
								placeholder="D:\Code\hku\LLM\kb_review\books\biochemistry\kb.sqlite"
							/>
						</label>
						<button type="submit" className="qx-btn" disabled={busy}>
							<Link2 size={15} />
							登记并链接
						</button>
					</form>

					{available.length > 0 && (
						<>
							<h3>从书库链接</h3>
							<table className="qx-table">
								<thead>
									<tr>
										<th>书名</th>
										<th>块数</th>
										<th>所属专业</th>
										<th />
									</tr>
								</thead>
								<tbody>
									{available.map((item) => (
										<tr key={item.id}>
											<td>{item.title}</td>
											<td>{item.chunks}</td>
											<td>
												{item.subjects.length === 0 ? (
													<small>未链接</small>
												) : (
													item.subjects.map((subjectKey) => <code key={subjectKey}>{subjectKey} </code>)
												)}
											</td>
											<td>
												<button
													type="button"
													className="qx-link"
													onClick={() =>
														void run(async () => {
															await kb(`/api/kb/subjects/${selectedSubject.key}/links`, post({ kbId: item.id }));
															return `已链接《${item.title}》`;
														})
													}
												>
													<Link2 size={13} /> 链接
												</button>
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</>
					)}
				</section>
			)}
		</div>
	);
}
