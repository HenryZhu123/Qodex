"use client";

import { Search, ShieldCheck, Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, array, badgeClass, type JsonObject, object, post, pretty, statusLabel, text } from "@/lib/workspace-api";
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
		[error, setError] = useState("");
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
							"帮我出一道题：先和我确认科目、考点、题量、分值和题型，再用 question_generation 的 author 出题，出完送 exam_checker 审校。生成题目只进入待审队列，不等于审校通过。",
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
			<PendingQuestions />
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
						题目 {text(state.question_id)} · v{text(state.version)}
					</h2>
					<p>
						审校：{statusLabel(object(state.review).status)} · 入库：{text(object(state.question_bank).status)}
					</p>
					<Report value={state} />
					{object(state.review).status === "NEEDS_REVISION" && (
						<p className="qx-note">
							审校服务只提供修改建议，不创建题目版本。AI 命题题由 Pi
							自主决定是否调用命题工具生成下一版本；上传文档题请修改源文件后重新上传。
						</p>
					)}
				</section>
			)}
			<GenerationPanel />
		</div>
	);
}

const GENERATION_OPERATIONS = [
	{
		key: "single",
		label: "单题命题 single（确定性模板）",
		example: true,
		hint: "固定考点（如 single_level_paging）+ 固定字段；项目自带示例，可直接提交，不调用模型。",
	},
	{
		key: "batch",
		label: "批量命题 batch（确定性模板）",
		example: true,
		hint: "显式 slots；项目自带示例，可直接提交，不调用模型。",
	},
	{
		key: "comprehensive",
		label: "综合应用题 comprehensive（确定性模板）",
		example: true,
		hint: "固定考点（分页 / 栈）；项目自带示例，可直接提交，不调用模型。",
	},
	{
		key: "author",
		label: "自然语言出题 author（需真实 brief）",
		example: false,
		hint: "字段：schema_version、request_id、brief、subject、syllabus_areas、question_type、total_score、requirements、evidence。会调用模型并计费。",
	},
	{
		key: "replenishment",
		label: "补题 replenishment（需组卷缺口单）",
		example: false,
		hint: "需要组卷服务返回的 replenishment_request（缺口单），没有静态示例；会调用模型并计费。",
	},
	{
		key: "revise",
		label: "修订 revise（需真实当前题目）",
		example: false,
		hint: "必须携带已生成题目的完整 current_question 和对应版本的反馈，不能用通用静态示例；会调用模型并计费。",
	},
] as const;

const PAID_GENERATION_OPERATIONS = new Set(["author", "replenishment", "revise"]);

function GenerationPanel() {
	const [operation, setOperation] = useState("single"),
		[payload, setPayload] = useState(""),
		[result, setResult] = useState<JsonObject>(),
		[error, setError] = useState(""),
		[busy, setBusy] = useState(false);
	const selected = GENERATION_OPERATIONS.find((item) => item.key === operation) ?? GENERATION_OPERATIONS[0];
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
		if (
			PAID_GENERATION_OPERATIONS.has(operation) &&
			!window.confirm(`operation=${operation} 会调用模型并产生费用，确定提交？`)
		)
			return;
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
			<summary>命题接口自测（测试 / 展示用，非教师入口）</summary>
			<p className="qx-note">
				这里直接向 8093 发完整 JSON 请求，只用于验证接口本身；教师日常出题请用对话或上面的待审题目面板。
				结果只写入命题待审队列，不会自动成为正式题库。
			</p>
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
					{GENERATION_OPERATIONS.map((item) => (
						<option key={item.key} value={item.key}>
							{item.label}
						</option>
					))}
				</select>
				<button type="button" className="qx-btn" disabled={busy || !selected.example} onClick={example}>
					{selected.example ? "加载项目请求示例" : "该操作没有静态示例"}
				</button>
			</div>
			<p className="qx-note">{selected.hint}</p>
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

/**
 * The review queue is where a generated question waits before it can reach the
 * bank. Listing it is read-only; only the per-row review button spends a model
 * call, and it asks first. The list omits answers on purpose: the teacher view
 * comes from the review state, one question at a time.
 */
function PendingQuestions() {
	const [rows, setRows] = useState<JsonObject[]>([]),
		[total, setTotal] = useState(0),
		[limit, setLimit] = useState(20),
		[loaded, setLoaded] = useState(false),
		[error, setError] = useState(""),
		[busy, setBusy] = useState(""),
		[state, setState] = useState<JsonObject>(),
		[outcomes, setOutcomes] = useState<Record<string, JsonObject>>({});

	const load = useCallback(
		async (next = limit) => {
			setBusy("list");
			setError("");
			try {
				const data = await api(`generation/v1/question-generation/pending?limit=${next}`);
				setRows(array(data.questions).map(object));
				setTotal(Number(data.total) || 0);
				setLoaded(true);
			} catch (e) {
				setError(e instanceof Error ? e.message : "待审题目读取失败");
			} finally {
				setBusy("");
			}
		},
		[limit],
	);

	useEffect(() => {
		void load();
	}, [load]);

	const questionPath = (row: JsonObject) =>
		`checker/v1/exam-checker/tasks/${encodeURIComponent(text(row.task_id))}/questions/${encodeURIComponent(text(row.question_id))}`;

	async function showState(row: JsonObject) {
		if (busy) return;
		setBusy(text(row.question_id));
		setError("");
		try {
			setState(await api(`${questionPath(row)}/state`));
		} catch (e) {
			setError(e instanceof Error ? e.message : "状态读取失败");
		} finally {
			setBusy("");
		}
	}

	async function review(row: JsonObject) {
		if (busy) return;
		const version = Number(row.version) || 1;
		const questionId = text(row.question_id);
		const confirmed = window.confirm(
			`审校会调用模型并产生费用。\n\n${questionId} v${version}\n\n同一版本重复审校复用同一幂等键，不会重复计费。确定现在审校？`,
		);
		if (!confirmed) return;
		setBusy(questionId);
		setError("");
		try {
			// One key per version: re-clicking returns the stored review instead of paying again,
			// while a revised version produces a new key and therefore a real second review.
			const reviewed = await post(`${questionPath(row)}/review`, {
				version,
				idempotency_key: `web:${text(row.task_id)}:${questionId}:v${version}`,
			});
			setOutcomes((previous) => ({ ...previous, [questionId]: object(reviewed.review) }));
			setState(await api(`${questionPath(row)}/state`));
		} catch (e) {
			setError(e instanceof Error ? e.message : "审校失败");
		} finally {
			setBusy("");
		}
	}

	return (
		<section className="qx-formsection">
			<div className="qx-between">
				<h2>待审题目</h2>
				<div className="qx-actions">
					<select
						aria-label="待审题展示条数"
						value={limit}
						disabled={!!busy}
						onChange={(e) => {
							const next = Number(e.target.value);
							setLimit(next);
							void load(next);
						}}
					>
						<option value={20}>最近 20 道</option>
						<option value={50}>最近 50 道</option>
						<option value={100}>最近 100 道</option>
					</select>
					<button type="button" className="qx-btn" disabled={!!busy} onClick={() => void load()}>
						{busy === "list" ? "读取中…" : "刷新"}
					</button>
				</div>
			</div>
			<p className="qx-note">
				命题结果先进入这里；审校 PASS 后自动入库。列表只读、不调用模型；只有点「送审校」才会产生一次模型调用。
			</p>
			{loaded && (
				<p className="qx-note">
					待审 {total} 道，本次显示 {rows.length} 道（只列未作废的当前版本）。
				</p>
			)}
			{error && (
				<p className="qx-error" role="alert">
					{error}
				</p>
			)}
			{loaded && !rows.length && (
				<p className="qx-empty">待审队列是空的。出题后（对话或上面的自测面板）会出现在这里。</p>
			)}
			{rows.map((row) => {
				const questionId = text(row.question_id);
				const status = text(object(outcomes[questionId]).status);
				return (
					<article className="qx-bankitem" key={`${text(row.task_id)}:${questionId}:${text(row.version)}`}>
						<div className="qx-between">
							<h2>{text(row.stem) || "（该版本没有学生题面）"}</h2>
							<span className={`qx-badge ${badgeClass(status)}`}>{status ? statusLabel(status) : "待审校"}</span>
						</div>
						<p className="qx-note">
							{text(row.subject) || "未标科目"} · {text(row.topic) || "未标考点"} · v{text(row.version)} ·{" "}
							{text(row.queued_at).replace("T", " ").slice(0, 19)} · {text(row.question_type)}
						</p>
						<div className="qx-options">
							{array(row.options).map((option) => (
								<p key={text(object(option).id)}>
									{text(object(option).id)}. {text(object(option).text)}
								</p>
							))}
						</div>
						<div className="qx-actions">
							<button type="button" className="qx-link" disabled={!!busy} onClick={() => void showState(row)}>
								查看版本与审校
							</button>
							<button type="button" className="qx-btn primary" disabled={!!busy} onClick={() => void review(row)}>
								<ShieldCheck size={14} />
								{busy === questionId ? "审校中…" : "送审校"}
							</button>
						</div>
						{status === "NEEDS_REVISION" && (
							<p className="qx-note">
								审校只给修改建议，不改题目。AI 出的题由 Pi
								在对话里按版本决定是否修订；上传文档的题请改源文件后重新上传。
							</p>
						)}
					</article>
				);
			})}
			{state && (
				<section className="qx-result">
					<div className="qx-between">
						<h2>
							题目 {text(state.question_id)} · v{text(state.version)}
						</h2>
						<span className={`qx-badge ${badgeClass(object(state.review).status)}`}>
							{statusLabel(object(state.review).status) || "未审校"}
						</span>
					</div>
					<p className="qx-note">
						审校：{statusLabel(object(state.review).status) || "未审校"} · 入库：
						{statusLabel(object(state.question_bank).status) || "未知"}
						{object(state.question_bank).record_id ? ` · record ${text(object(state.question_bank).record_id)}` : ""}
					</p>
					<Report value={state} />
				</section>
			)}
		</section>
	);
}
