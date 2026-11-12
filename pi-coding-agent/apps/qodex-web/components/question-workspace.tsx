"use client";

import { Search, ShieldCheck, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { api, array, type JsonObject, object, post, pretty, statusLabel, text } from "@/lib/workspace-api";
import { Report } from "./assembly-workspace";

export function QuestionBank() {
	const [subject, setSubject] = useState(""),
		[keyword, setKeyword] = useState(""),
		[difficulty, setDifficulty] = useState("");
	const [rows, setRows] = useState<JsonObject[]>([]),
		[error, setError] = useState(""),
		[busy, setBusy] = useState(false),
		[loaded, setLoaded] = useState(false);
	async function search() {
		setBusy(true);
		setError("");
		try {
			const query = new URLSearchParams({ limit: "100" });
			if (subject) query.set("subject", subject);
			if (keyword) query.set("keyword", keyword);
			if (difficulty) query.set("difficulty", difficulty);
			const data = await api(`checker/v1/question-bank/search?${query}`);
			setRows(array(data.questions).map(object));
			setLoaded(true);
		} catch (e) {
			setError(e instanceof Error ? e.message : "题库读取失败");
		} finally {
			setBusy(false);
		}
	}
	return (
		<div className="qx-page">
			<div className="qx-pagehead">
				<div>
					<div className="qx-eyebrow">REVIEWED QUESTION BANK</div>
					<h1>正式题库</h1>
					<p>检索已入库的题目，查看题面、答案和来源版本。</p>
				</div>
				<a className="qx-btn primary" href="#assembly">
					前往组卷
				</a>
			</div>
			<form
				className="qx-filters"
				onSubmit={(e) => {
					e.preventDefault();
					void search();
				}}
			>
				<input
					aria-label="题库学科"
					placeholder="学科（留空为全部）"
					value={subject}
					onChange={(e) => setSubject(e.target.value)}
				/>
				<input
					aria-label="题库关键词"
					placeholder="题干关键词"
					value={keyword}
					onChange={(e) => setKeyword(e.target.value)}
				/>
				<select aria-label="题库难度" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
					<option value="">全部难度</option>
					<option value="easy">简单</option>
					<option value="medium">中等</option>
					<option value="hard">困难</option>
				</select>
				<button className="qx-btn primary" disabled={busy} type="submit">
					<Search size={15} />
					{busy ? "查询中…" : "查询题库"}
				</button>
			</form>
			{error && (
				<p className="qx-error" role="alert">
					{error}
				</p>
			)}
			{loaded && (
				<p className="qx-note">
					本次返回 {rows.length} 条（最多 100 条，非题库总数）。教师工作区包含答案，请勿直接分发本页给学生。
				</p>
			)}
			{!loaded && <div className="qx-empty">选择检索条件，查询你的本地 PostgreSQL 题库。</div>}
			{loaded && !rows.length && <p className="qx-empty">没有符合条件的已入库题目。启动服务并不会自动生成题库数据。</p>}
			{rows.map((r, i) => {
				const payload = object(r.question_json),
					q = object(payload.question),
					meta = object(payload.metadata);
				return (
					<article className="qx-bankitem" key={text(r.record_id)}>
						<div className="qx-between">
							<h2>
								{i + 1}. {text(q.question_text)}
							</h2>
							<span className="qx-badge green">正式题库</span>
						</div>
						<p className="qx-note">
							{text(q.subject)} · {text(meta.difficulty)} · {array(meta.knowledge_points).map(text).join(" / ")} ·{" "}
							{text(q.points)} 分
						</p>
						<div className="qx-options">
							{array(q.options).map((v) => (
								<p key={text(v)}>{text(v)}</p>
							))}
						</div>
						<details>
							<summary>教师答案与解析</summary>
							{!text(q.answer_text).trim() && (
								<p className="qx-error">这道题尚无答案。即使审校通过，组卷服务也不会选用；请先按来源补全并重审。</p>
							)}
							<p>答案：{text(q.answer_text)}</p>
							<p>{text(q.explanation)}</p>
						</details>
						<Report value={r} />
					</article>
				);
			})}
		</div>
	);
}

export function CheckerWorkspace({ prompt }: { prompt: (text: string) => void }) {
	const [kb, setKb] = useState<string[]>([]);
	useEffect(() => {
		const abort = new AbortController();
		fetch("/api/workspace/status", { signal: abort.signal })
			.then(async (response) => {
				if (response.ok) setKb(array(object(await response.json()).knowledge_base_subjects).map(text));
			})
			.catch(() => {});
		return () => abort.abort();
	}, []);
	const [file, setFile] = useState<File>(),
		[documentId, setDocumentId] = useState("");
	const [result, setResult] = useState<JsonObject>(),
		[state, setState] = useState<JsonObject>();
	const [busy, setBusy] = useState(false),
		[error, setError] = useState(""),
		[instruction, setInstruction] = useState("");
	async function run(action: () => Promise<JsonObject>, kind: "document" | "state" = "document") {
		if (busy) return;
		setBusy(true);
		setError("");
		try {
			const data = await action();
			if (kind === "state") setState(data);
			else {
				setResult(data);
				setState(undefined);
			}
			if (data.document_id) setDocumentId(text(data.document_id));
		} catch (e) {
			setError(e instanceof Error ? e.message : "请求失败");
		} finally {
			setBusy(false);
		}
	}
	async function upload() {
		if (!file) return;
		if (file.size > 10 * 1024 * 1024) {
			setError("文件超过 10 MB，请先拆分。原服务的 MinerU 上传上限为 10 MB。");
			return;
		}
		const data = new FormData();
		data.append("file", file);
		await run(() => api("checker/v1/exam-checker/documents/parse", { method: "POST", body: data }));
	}
	const documentPath = `checker/v1/exam-checker/documents/${encodeURIComponent(documentId)}`;
	const questions: JsonObject[] = result?.nodes
		? Object.values(object(result.nodes))
				.map(object)
				.filter((q) => q.type === "question")
				.map((q) => ({ ...q, question_id: q.id }))
		: array(result?.questions).map(object);
	return (
		<div className="qx-page">
			<div className="qx-pagehead">
				<div>
					<div className="qx-eyebrow">QUESTION WORKFLOW</div>
					<h1>命题与审校</h1>
					<p>从现有试卷准备题目，或让 Pi 帮你完成命题与修订。</p>
				</div>
				<button
					type="button"
					className="qx-btn"
					onClick={() =>
						prompt(
							"请介绍 question_generation 的 single、batch、comprehensive、revise 操作，并先确认我的命题需求。生成题目只进入待审队列，不等于审校通过。",
						)
					}
				>
					进入 Pi 命题对话
				</button>
			</div>
			<div className="qx-callout">
				命题待审队列尚未自动送审。只有同一题目版本审校通过并成功入库，才可用于组卷。解析、审校及 AI
				修订可能调用你的模型与 MinerU 服务。
				<p>
					{kb.length
						? `检测到知识库索引：${kb.join("、")}`
						: "未检测到知识库运行索引，当前不能验证知识库增强审校。可在本地配置 EXAM_CHECKER_KB_DIR 后重启。"}
				</p>
			</div>
			<section className="qx-formsection">
				<h2>上传试卷</h2>
				<div className="qx-upload">
					<Upload size={27} />
					<div>
						<strong>选择 PDF、DOC 或 DOCX</strong>
						<p className="qx-note">最多 10 MB。只解析一次，随后可按文档编号继续审校。</p>
					</div>
					<input
						aria-label="上传试卷文件"
						type="file"
						accept=".pdf,.doc,.docx"
						disabled={busy}
						onChange={(e) => setFile(e.target.files?.[0])}
					/>
					<button type="button" className="qx-btn primary" disabled={!file || busy} onClick={upload}>
						{busy ? "处理中，请勿重复提交…" : "解析试卷"}
					</button>
				</div>
			</section>
			<section className="qx-formsection">
				<h2>继续处理已有文档</h2>
				<div className="qx-filters">
					<input
						aria-label="文档编号"
						placeholder="document_id"
						value={documentId}
						disabled={busy}
						onChange={(e) => {
							setDocumentId(e.target.value);
							setState(undefined);
							setResult(undefined);
						}}
					/>
					<button
						type="button"
						className="qx-btn"
						disabled={busy || !documentId.trim()}
						onClick={() => run(() => api(documentPath))}
					>
						加载文档
					</button>
					<button
						type="button"
						className="qx-btn primary"
						disabled={busy || !documentId.trim()}
						onClick={() => run(() => post(`${documentPath}/review`, {}))}
					>
						<ShieldCheck size={14} />
						整卷审校
					</button>
				</div>
			</section>
			{error && (
				<p className="qx-error" role="alert">
					{error} 操作可能已经执行，请保留文档编号检查状态后再决定是否重试。
				</p>
			)}
			{busy && <output className="qx-note">等待上游处理。请保持页面打开；不会自动重试或重复提交。</output>}
			{result && (
				<section className="qx-result">
					<div className="qx-between">
						<h2>文档结果</h2>
						<span className="qx-badge">{statusLabel(result.status) || "已解析"}</span>
					</div>
					<p className="qx-note">
						文档编号：{documentId} · 返回题目数：{questions.length}
					</p>
					{questions.map((q, i) => {
						const questionId = text(q.question_id);
						return (
							<div className="qx-topicrow" key={questionId || pretty(q)}>
								<span>
									题目 {text(q.question_number) || i + 1} · {questionId}
								</span>
								<span className="qx-badge">{statusLabel(object(q.review).status) || "查看状态"}</span>
								<button
									type="button"
									className="qx-link"
									disabled={busy}
									onClick={() =>
										run(() => api(`${documentPath}/questions/${encodeURIComponent(questionId)}/state`), "state")
									}
								>
									查看版本与审校
								</button>
								<button
									type="button"
									className="qx-link"
									disabled={busy}
									onClick={() =>
										run(async () => {
											await post(`${documentPath}/questions/${encodeURIComponent(questionId)}/review`, {});
											return api(`${documentPath}/questions/${encodeURIComponent(questionId)}/state`);
										}, "state")
									}
								>
									单题审校
								</button>
							</div>
						);
					})}
					<Report value={result} />
				</section>
			)}
			{state && (
				<section className="qx-result">
					<h2>
						题目 {text(state.question_id)} · v{text(state.version_number)}
					</h2>
					<p>
						审校：{statusLabel(object(state.review).status)} · 入库：{text(object(state.question_bank).status)}
					</p>
					<Report value={state} />
					<label className="qx-field">
						修订要求
						<textarea
							rows={3}
							value={instruction}
							onChange={(e) => setInstruction(e.target.value)}
							placeholder="先查看报告，再说明需要修改的内容"
						/>
					</label>
					<button
						type="button"
						className="qx-btn"
						disabled={busy || !instruction.trim()}
						onClick={() =>
							run(async () => {
								await post(`${documentPath}/questions/${encodeURIComponent(text(state.question_id))}/revise`, {
									base_version_id: state.question_version_id,
									user_instruction: instruction,
								});
								return api(`${documentPath}/questions/${encodeURIComponent(text(state.question_id))}/state`);
							}, "state")
						}
					>
						按当前版本进行 AI 修订与重审
					</button>
				</section>
			)}
			<GenerationPanel />
		</div>
	);
}

function GenerationPanel() {
	const [operation, setOperation] = useState("single"),
		[payload, setPayload] = useState(""),
		[result, setResult] = useState<JsonObject>(),
		[error, setError] = useState(""),
		[busy, setBusy] = useState(false);
	async function example() {
		try {
			const r = await fetch(`/examples/generation-${operation}.json`);
			if (!r.ok) throw Error("请使用 Pi 准备该操作的合法请求 JSON。");
			setPayload(pretty(await r.json()));
			setError("");
		} catch (e) {
			setError(e instanceof Error ? e.message : "示例加载失败");
		}
	}
	async function generate() {
		if (busy) return;
		setError("");
		let data: unknown;
		try {
			data = JSON.parse(payload);
			if (!data || Array.isArray(data) || typeof data !== "object") throw Error();
		} catch {
			setError("请填入合法的请求 JSON 对象。");
			return;
		}
		setBusy(true);
		setResult(undefined);
		try {
			setResult(await post(`generation/v1/question-generation/${operation}`, data));
		} catch (e) {
			setError(e instanceof Error ? e.message : "命题请求失败");
		} finally {
			setBusy(false);
		}
	}
	return (
		<details className="qx-report qx-generation">
			<summary>自主命题 · 直接调用服务（完整 JSON 请求）</summary>
			<p className="qx-note">支持现有单题、批量、综合题和修订服务。成功结果写入命题待审队列，不会自动成为正式题库。</p>
			<div className="qx-filters">
				<select
					aria-label="命题操作"
					value={operation}
					disabled={busy}
					onChange={(e) => {
						setOperation(e.target.value);
						setPayload("");
					}}
				>
					<option value="single">单题命题</option>
					<option value="batch">批量命题</option>
					<option value="comprehensive">综合应用题</option>
					<option value="revise">修订综合题</option>
				</select>
				<button type="button" className="qx-btn" disabled={busy} onClick={example}>
					加载项目请求示例
				</button>
			</div>
			<textarea
				aria-label="命题请求 JSON"
				rows={12}
				value={payload}
				disabled={busy}
				onChange={(e) => setPayload(e.target.value)}
			/>
			<button type="button" className="qx-btn primary" disabled={busy || !payload.trim()} onClick={generate}>
				{busy ? "命题与入队中…" : "提交命题"}
			</button>
			{error && (
				<p className="qx-error" role="alert">
					{error}
				</p>
			)}
			{result && <Report value={result} />}
		</details>
	);
}
