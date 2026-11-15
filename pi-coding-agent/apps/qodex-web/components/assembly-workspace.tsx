"use client";

import { ArrowLeft, Download, FileText, Plus, RefreshCw, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
	api,
	array,
	badgeClass,
	historyUrl,
	type JsonObject,
	object,
	post,
	pretty,
	statusLabel,
	text,
	validateQuotas,
} from "@/lib/workspace-api";

export function Report({ value }: { value: unknown }) {
	return (
		<details className="qx-report">
			<summary>查看完整报告 / 来源信息</summary>
			<pre>{pretty(value)}</pre>
		</details>
	);
}

export function AssemblyForm({ openHistory }: { openHistory: (id?: string) => void }) {
	const [subject, setSubject] = useState("数据结构");
	const [name, setName] = useState("章节练习");
	const [count, setCount] = useState(3);
	const [points, setPoints] = useState(2);
	const [topics, setTopics] = useState([
		{ id: "linear", name: "线性表顺序存储", count: 1 },
		{ id: "tree", name: "二叉树遍历", count: 1 },
		{ id: "forest", name: "森林与二叉树的转换", count: 1 },
	]);
	const [diff, setDiff] = useState([1, 2, 0]);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [result, setResult] = useState<JsonObject>();
	const [bank, setBank] = useState<JsonObject[]>([]);
	const [bankMessage, setBankMessage] = useState("");
	const [decisions, setDecisions] = useState("[]");
	const validation = validateQuotas(count, points, topics, diff);
	async function inspectBank() {
		setBankMessage("正在读取正式题库…");
		try {
			const data = await api(
				`checker/v1/question-bank/search?limit=100&question_type=single_choice&subject=${encodeURIComponent(subject)}`,
			);
			setBank(array(data.questions).map(object));
			setBankMessage(
				`已读取 ${array(data.questions).length} 道题（最多 100 道）。这些是检索结果，能否入选仍由后端核验版本、分值和完整性。`,
			);
		} catch (e) {
			setBankMessage(e instanceof Error ? e.message : "题库读取失败");
		}
	}
	async function submit() {
		if (busy || validation) return;
		setError("");
		setResult(undefined);
		let parsed: unknown;
		try {
			parsed = JSON.parse(decisions);
			if (!Array.isArray(parsed)) throw new Error("复核决定必须是 JSON 数组");
		} catch {
			setError("复核决定须为有效 JSON 数组。不提交复核时保留 []。");
			return;
		}
		setBusy(true);
		try {
			const data = await post("assembly/v1/exam-assembly/assemble", {
				schema_version: "1.0",
				request_id: `${subject} · ${name.trim() || "章节练习"} · ${crypto.randomUUID().slice(0, 8)}`,
				subject,
				question_count: count,
				total_score: count * points,
				question_type_counts: { single_choice: count },
				question_type_scores: { single_choice: points },
				knowledge_point_counts: Object.fromEntries(topics.map((t) => [t.name.trim(), t.count])),
				difficulty_counts: { easy: diff[0], medium: diff[1], hard: diff[2] },
				export_pdf: false,
				similarity_decisions: parsed,
			});
			setResult(data);
			const stored = object(data.history);
			if (stored.status === "STORED" && typeof stored.exam_id === "string") openHistory(stored.exam_id);
		} catch (e) {
			setError(e instanceof Error ? e.message : "组卷失败。请先查看历史，确认是否已执行，不要自动重复提交。");
		} finally {
			setBusy(false);
		}
	}
	const knowledge = [
		...new Set(bank.flatMap((q) => array(object(object(q.question_json).metadata).knowledge_points).map(text))),
	];
	return (
		<div className="qx-page">
			<div className="qx-pagehead">
				<div>
					<div className="qx-eyebrow">EXAM ASSEMBLY</div>
					<h1>智能组卷</h1>
					<p>设定需求，从已审校题库中选出合适的题目。</p>
				</div>
				<button type="button" className="qx-btn" onClick={() => openHistory()}>
					<RefreshCw size={15} />
					查看历史
				</button>
			</div>
			<div className="qx-steps">
				① 配置需求 <span>—</span> ② 选题与校验 <span>—</span> ③ 预览与导出
			</div>
			<div className="qx-buildgrid">
				<div>
					<section className="qx-formsection">
						<h2>
							<small>01</small>基本信息
						</h2>
						<div className="qx-fields">
							<label className="qx-full">
								试卷名称
								<input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
							</label>
							<label>
								科目
								<input list="subjects" value={subject} onChange={(e) => setSubject(e.target.value)} />
								<datalist id="subjects">
									{["数据结构", "计算机网络", "操作系统", "计算机组成原理"].map((s) => (
										<option key={s}>{s}</option>
									))}
								</datalist>
							</label>
							<label>
								题型
								<input value="单项选择（当前支持）" readOnly />
							</label>
							<label>
								题目数量
								<input
									type="number"
									min="1"
									max="100"
									value={count}
									onChange={(e) => setCount(Number(e.target.value))}
								/>
							</label>
							<label>
								每题分值
								<input type="number" min="1" value={points} onChange={(e) => setPoints(Number(e.target.value))} />
							</label>
						</div>
						<p className="qx-note">分值必须与题库原题分值一致，不会自动改分。试卷名称保存在本次请求标识中。</p>
					</section>
					<section className="qx-formsection">
						<div className="qx-between">
							<h2>
								<small>02</small>知识点配额
							</h2>
							<button type="button" className="qx-link" onClick={inspectBank}>
								读取题库知识点
							</button>
						</div>
						{bankMessage && <output className="qx-note">{bankMessage}</output>}
						<datalist id="knowledge">
							{knowledge.map((k) => (
								<option key={k}>{k}</option>
							))}
						</datalist>
						{topics.map((t, i) => (
							<div className="qx-topicrow" key={t.id}>
								<input
									aria-label={`知识点 ${i + 1}`}
									list="knowledge"
									value={t.name}
									onChange={(e) => setTopics(topics.map((v, j) => (j === i ? { ...v, name: e.target.value } : v)))}
								/>
								<input
									aria-label={`知识点 ${i + 1} 题数`}
									type="number"
									min="0"
									value={t.count}
									onChange={(e) =>
										setTopics(topics.map((v, j) => (j === i ? { ...v, count: Number(e.target.value) } : v)))
									}
								/>
								<button
									type="button"
									aria-label={`移除知识点 ${i + 1}`}
									className="qx-iconbtn"
									onClick={() => setTopics(topics.filter((_, j) => j !== i))}
								>
									<Trash2 size={15} />
								</button>
							</div>
						))}
						<button
							type="button"
							className="qx-link"
							onClick={() => setTopics([...topics, { id: crypto.randomUUID(), name: "", count: 0 }])}
						>
							<Plus size={14} />
							添加知识点
						</button>
					</section>
					<section className="qx-formsection">
						<h2>
							<small>03</small>难度分布
						</h2>
						<div className="qx-fields qx-three">
							{["简单", "中等", "困难"].map((d, i) => (
								<label key={d}>
									{d}
									<input
										type="number"
										min="0"
										value={diff[i]}
										onChange={(e) => setDiff(diff.map((v, j) => (i === j ? Number(e.target.value) : v)))}
									/>
								</label>
							))}
						</div>
					</section>
					<details className="qx-report">
						<summary>教师相似题复核决定（高级）</summary>
						<p className="qx-note">
							仅在已查看完整题目并人工确认后使用。需与具体 pair_id、内容哈希和版本绑定；后端验证，不自动生成结论。
						</p>
						<textarea
							aria-label="相似题复核决定"
							value={decisions}
							onChange={(e) => setDecisions(e.target.value)}
							rows={5}
						/>
					</details>
				</div>
				<aside className="qx-summary">
					<h2>这份试卷</h2>
					<p>生成前，先确认你的需求</p>
					<div className="qx-totals">
						<b>
							{count}
							<small>题</small>
						</b>
						<b>
							{count * points}
							<small>分</small>
						</b>
					</div>
					<dl>
						<div>
							<dt>科目</dt>
							<dd>{subject}</dd>
						</div>
						<div>
							<dt>题型</dt>
							<dd>单项选择</dd>
						</div>
						<div>
							<dt>知识点配额</dt>
							<dd>
								{topics.reduce((n, t) => n + t.count, 0)} / {count}
							</dd>
						</div>
						<div>
							<dt>难度配额</dt>
							<dd>
								{diff.reduce((a, b) => a + b, 0)} / {count}
							</dd>
						</div>
					</dl>
					<hr />
					<p>
						<ShieldCheck size={15} />
						仅从正式题库取题，核验 PASS 审校与来源版本。
					</p>
					<p>题库不足时报告缺口，不重复选题，也不降低要求。</p>
					{validation && <div className="qx-error">{validation}</div>}
					<button
						type="button"
						className="qx-btn primary"
						disabled={busy || !!validation || !subject.trim()}
						onClick={submit}
					>
						<Sparkles size={16} />
						{busy ? "正在组卷与保存…" : "开始组卷"}
					</button>
					<p className="qx-note">先生成 HTML；可在预览中打印为 PDF。提交后不自动重试。</p>
				</aside>
			</div>
			{error && (
				<div className="qx-error" role="alert">
					{error}
				</div>
			)}
			{result && (
				<section className="qx-result">
					<h2>{statusLabel(result.status)}</h2>
					{object(result.history).status !== "STORED" && (
						<p className="qx-error">历史未保存：请检查数据库配置。完整返回见下方报告。</p>
					)}
					<Report value={result} />
				</section>
			)}
		</div>
	);
}

export function HistoryList({ active, open }: { active: boolean; open: (id: string) => void }) {
	const [rows, setRows] = useState<JsonObject[]>([]),
		[offset, setOffset] = useState(0),
		[busy, setBusy] = useState(false),
		[error, setError] = useState("");
	const [search, setSearch] = useState(""),
		[status, setStatus] = useState("");
	const [refresh, setRefresh] = useState(0);
	// biome-ignore lint/correctness/useExhaustiveDependencies: refresh deliberately reloads the same page after a new attempt.
	useEffect(() => {
		if (!active) return;
		const abort = new AbortController();
		setBusy(true);
		setError("");
		api(`assembly/v1/exam-assembly/history?limit=20&offset=${offset}`, { signal: abort.signal })
			.then((data) => setRows(array(data.exams).map(object)))
			.catch((e) => {
				if (!abort.signal.aborted) setError(String(e.message));
			})
			.finally(() => {
				if (!abort.signal.aborted) setBusy(false);
			});
		return () => abort.abort();
	}, [active, offset, refresh]);
	const filtered = rows.filter(
		(r) =>
			(!status || r.status === status) &&
			`${r.request_id} ${r.subject} ${r.exam_id}`.toLowerCase().includes(search.toLowerCase()),
	);
	return (
		<div className="qx-page">
			<div className="qx-pagehead">
				<div>
					<div className="qx-eyebrow">YOUR EXAM LIBRARY</div>
					<h1>组卷历史</h1>
					<p>每一次组卷，都有迹可循。</p>
				</div>
				<a className="qx-btn primary" href="#assembly">
					<Plus size={15} />
					新建组卷
				</a>
			</div>
			<div className="qx-filters">
				<input
					aria-label="搜索本页历史"
					placeholder="搜索本页名称、学科或编号"
					value={search}
					onChange={(e) => setSearch(e.target.value)}
				/>
				<select aria-label="筛选本页状态" value={status} onChange={(e) => setStatus(e.target.value)}>
					<option value="">本页全部状态</option>
					{["STRUCTURAL_PASS", "NEEDS_QUESTIONS", "UNRESOLVED", "INVALID_REQUEST", "TOOL_ERROR"].map((s) => (
						<option key={s} value={s}>
							{statusLabel(s)}
						</option>
					))}
				</select>
				<button type="button" className="qx-btn" disabled={busy} onClick={() => setRefresh((n) => n + 1)}>
					<RefreshCw size={14} />
					刷新
				</button>
			</div>
			{error && (
				<p className="qx-error" role="alert">
					{error}
				</p>
			)}
			<div className="qx-tablewrap">
				<table className="qx-table">
					<thead>
						<tr>
							<th>试卷 / 组卷需求</th>
							<th>创建时间</th>
							<th>请求题数 / 总分</th>
							<th>状态</th>
							<th>操作</th>
						</tr>
					</thead>
					<tbody>
						{filtered.map((r) => (
							<tr key={text(r.exam_id)}>
								<td>
									<button type="button" className="qx-titlelink" onClick={() => open(text(r.exam_id))}>
										{text(r.request_id)}
									</button>
									<small>
										{text(r.subject)} · {text(r.exam_id).slice(0, 8)}
									</small>
								</td>
								<td>{new Date(text(r.created_at)).toLocaleString("zh-CN")}</td>
								<td>
									{text(r.requested_question_count)} 题 / {text(r.requested_total_score)} 分
								</td>
								<td>
									<span className={`qx-badge ${badgeClass(r.status)}`}>{statusLabel(r.status)}</span>
								</td>
								<td>
									<button type="button" className="qx-link" onClick={() => open(text(r.exam_id))}>
										{r.status === "STRUCTURAL_PASS" ? "查看试卷" : "查看报告"}
									</button>
								</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
			{busy && <p className="qx-empty">正在读取历史…</p>}
			{!busy && !filtered.length && (
				<p className="qx-empty">{error ? "暂时无法读取历史，请检查服务状态。" : "暂无符合条件的记录。"}</p>
			)}
			<div className="qx-between qx-pagination">
				<span>本页 {rows.length} 条 · 按生成时间倒序 · 筛选仅作用于本页</span>
				<div className="qx-actions">
					<button
						type="button"
						className="qx-btn"
						disabled={offset === 0 || busy}
						onClick={() => setOffset((n) => Math.max(0, n - 20))}
					>
						上一页
					</button>
					<span>{offset / 20 + 1}</span>
					<button
						type="button"
						className="qx-btn"
						disabled={rows.length < 20 || busy}
						onClick={() => setOffset((n) => n + 20)}
					>
						下一页
					</button>
				</div>
			</div>
			<p className="qx-note">历史保存当次题目与答案快照。后续修改题库，不影响已保存试卷；失败记录中的题数是请求值。</p>
		</div>
	);
}

export function HistoryDetail({ id }: { id: string }) {
	const [detail, setDetail] = useState<JsonObject>(),
		[error, setError] = useState(""),
		[tab, setTab] = useState("student"),
		[retry, setRetry] = useState(0);
	// biome-ignore lint/correctness/useExhaustiveDependencies: retry deliberately re-reads the same immutable snapshot after a network error.
	useEffect(() => {
		const abort = new AbortController();
		setDetail(undefined);
		setError("");
		setTab("student");
		api(historyUrl(id), { signal: abort.signal })
			.then(setDetail)
			.catch((e) => {
				if (!abort.signal.aborted) setError(e.message);
			});
		return () => abort.abort();
	}, [id, retry]);
	const request = object(detail?.request),
		success = detail?.status === "STRUCTURAL_PASS";
	return (
		<div className="qx-page">
			<a className="qx-back" href="#history">
				<ArrowLeft size={14} />
				返回组卷历史
			</a>
			{error && (
				<div className="qx-error" role="alert">
					{error}
					<button type="button" className="qx-btn" onClick={() => setRetry((n) => n + 1)}>
						重新读取
					</button>
				</div>
			)}
			{!detail && !error && <p>正在读取试卷快照…</p>}
			{detail && (
				<>
					<div className="qx-pagehead">
						<div>
							<h1>{text(request.request_id) || text(request.subject) || "组卷记录"}</h1>
							<p>
								{new Date(text(detail.created_at)).toLocaleString("zh-CN")} ·{" "}
								<span className={`qx-badge ${badgeClass(detail.status)}`}>{statusLabel(detail.status)}</span>
							</p>
						</div>
						{success && (
							<div className="qx-actions">
								<a className="qx-btn" href={`/api/services/${historyUrl(id, "/student.html")}?download=1`}>
									<Download size={14} />
									学生卷 HTML
								</a>
								<a className="qx-btn primary" href={`/api/services/${historyUrl(id, "/answer.html")}?download=1`}>
									<Download size={14} />
									答案卷 HTML
								</a>
							</div>
						)}
					</div>
					{success ? (
						<div className="qx-detailgrid">
							<section className="qx-preview">
								<div className="qx-previewbar">
									<div className="qx-actions">
										<button
											type="button"
											className={`qx-btn ${tab === "student" ? "selected" : ""}`}
											onClick={() => setTab("student")}
										>
											<FileText size={14} />
											学生试卷
										</button>
										<button
											type="button"
											className={`qx-btn ${tab === "answer" ? "selected" : ""}`}
											onClick={() => setTab("answer")}
										>
											<ShieldCheck size={14} />
											答案与解析
										</button>
									</div>
									<a
										target="_blank"
										rel="noreferrer"
										className="qx-link"
										href={`/api/services/${historyUrl(id, tab === "student" ? "/student.html" : "/answer.html")}`}
									>
										打开 / 打印 PDF
									</a>
								</div>
								<iframe
									key={`${id}-${tab}`}
									title={tab === "student" ? "学生试卷预览" : "教师答案预览"}
									sandbox=""
									src={`/api/services/${historyUrl(id, tab === "student" ? "/student.html" : "/answer.html")}`}
								/>
							</section>
							<aside className="qx-detailinfo">
								<h2>试卷信息</h2>
								<dl>
									<div>
										<dt>学科</dt>
										<dd>{text(request.subject)}</dd>
									</div>
									<div>
										<dt>题数 / 总分</dt>
										<dd>
											{text(request.question_count)} 题 / {text(request.total_score)} 分
										</dd>
									</div>
									<div>
										<dt>保存方式</dt>
										<dd>数据库快照</dd>
									</div>
								</dl>
								<hr />
								<h2>知识点配额</h2>
								{Object.entries(object(request.knowledge_point_counts)).map(([k, v]) => (
									<div className="qx-between" key={k}>
										<span>{k}</span>
										<span>{text(v)} 题</span>
									</div>
								))}
								<div className="qx-callout">
									<ShieldCheck size={18} />
									<h3>结构检查通过</h3>
									<p>题数、分值、配额与版本等由后端检查。字面相似筛查不代表语义质量认证，内容仍需教师确认。</p>
								</div>
							</aside>
						</div>
					) : (
						<div className="qx-callout">
							<h2>{statusLabel(detail.status)} · 未生成完整试卷</h2>
							<p>{text(detail.message) || "请查看实际检查报告。学生卷和答案卷均不可下载。"}</p>
							{array(detail.deficits).length > 0 && <pre>{pretty(detail.deficits)}</pre>}
							{array(detail.errors).map((v) => (
								<p key={pretty(v)}>{typeof v === "string" ? v : pretty(v)}</p>
							))}
							<a className="qx-btn" href="#assembly">
								调整需求，重新组卷
							</a>
						</div>
					)}
					<Report value={{ ...detail, note: "本详情不包含教师答案；答案仅在独立预览中读取。" }} />
				</>
			)}
		</div>
	);
}
