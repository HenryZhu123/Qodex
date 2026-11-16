"use client";

import { FileText, History, Plus, Sparkles } from "lucide-react";
import { useState } from "react";
import { type PaperGroup, paperRequest, preset408 } from "@/lib/paper-plan";
import { type JsonObject, object, post, pretty, statusLabel } from "@/lib/workspace-api";
import styles from "./mixed-paper-form.module.css";

export function MixedPaperForm({ openHistory }: { openHistory: (id?: string) => void }) {
	const [groups, setGroups] = useState<PaperGroup[]>([
		{
			id: "first",
			subject: "数据结构",
			question_type: "single_choice",
			count: 1,
			score: 2,
			partScores: "",
			knowledgePoint: "",
			difficulty: "",
		},
	]);
	const [name, setName] = useState("自定义练习卷");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [result, setResult] = useState<JsonObject>();
	const [decisions, setDecisions] = useState("[]");
	const [semanticReview, setSemanticReview] = useState(false);
	const [semanticCalls, setSemanticCalls] = useState(8);
	const invalidSemanticBudget =
		semanticReview && (!Number.isInteger(semanticCalls) || semanticCalls < 0 || semanticCalls > 100);
	function update(id: string, change: Partial<PaperGroup>) {
		setGroups((rows) => rows.map((r) => (r.id === id ? { ...r, ...change } : r)));
	}
	let validation = "";
	let preview: ReturnType<typeof paperRequest> | undefined;
	try {
		preview = paperRequest(groups, name, "预览");
	} catch (e) {
		validation = e instanceof Error ? e.message : "配置无效";
	}
	if (invalidSemanticBudget) validation = "语义复核请求上限须为0至100的整数。";
	async function submit(selectedGroups = groups) {
		if (busy) return;
		setError("");
		setResult(undefined);
		setBusy(true);
		try {
			const supplied: unknown = JSON.parse(decisions);
			if (!Array.isArray(supplied)) throw new Error("人工复核决定须为JSON数组。");
			const response = await post("assembly/v1/exam-assembly/assemble", {
				...paperRequest(selectedGroups, name, crypto.randomUUID().slice(0, 8)),
				similarity_decisions: supplied,
				semantic_review: semanticReview,
				semantic_max_calls: semanticReview ? semanticCalls : 8,
			});
			setResult(response);
			const saved = object(response.history);
			if (saved.status === "STORED" && typeof saved.exam_id === "string") openHistory(saved.exam_id);
		} catch (e) {
			setError(e instanceof Error ? e.message : "组卷失败，请查看历史后再决定是否重试。");
		} finally {
			setBusy(false);
		}
	}
	return (
		<div className={`qx-page ${styles.page}`}>
			<div className="qx-pagehead">
				<div>
					<div className="qx-eyebrow">MIXED PAPER</div>
					<h1>多学科整卷</h1>
					<p>自由搭配学科与题型，从已审校题库生成试卷和独立答案。</p>
				</div>
				<button type="button" className="qx-btn" onClick={() => openHistory()}>
					<History size={14} aria-hidden="true" />
					组卷历史
				</button>
			</div>
			<section className={styles.nameSection}>
				<label className={styles.nameField}>
					试卷名称
					<input disabled={busy} value={name} onChange={(e) => setName(e.target.value)} />
				</label>
			</section>
			<section className={styles.template} aria-label="408快捷组卷">
				<div className={styles.templateIcon}>
					<FileText size={22} aria-hidden="true" />
				</div>
				<div className={styles.templateCopy}>
					<h2>408 标准整卷</h2>
					<p>
						40 道单选 <span>＋</span> 7 道综合 <span>·</span> 四学科 <span>·</span> 150 分
					</p>
					<small>使用预设分值直接选题；题量不足会返回缺题报告。</small>
				</div>
				<div className={styles.templateActions}>
					<button type="button" className="qx-btn" disabled={busy} onClick={() => setGroups(preset408())}>
						编辑此结构
					</button>
					<button
						type="button"
						className="qx-btn primary"
						disabled={busy || !name.trim() || invalidSemanticBudget}
						onClick={() => submit(preset408())}
					>
						<Sparkles size={14} aria-hidden="true" />
						一键生成整卷
					</button>
				</div>
			</section>
			<section className={styles.customHeader}>
				<div>
					<h2>自定义试卷结构</h2>
					<p>按下列顺序选题；总分与小问分值须与题库原题匹配。</p>
				</div>
				<button
					type="button"
					className="qx-btn"
					disabled={busy}
					onClick={() =>
						setGroups([
							...groups,
							{
								id: crypto.randomUUID(),
								subject: "数据结构",
								question_type: "comprehensive",
								count: 1,
								score: 10,
								partScores: "",
								knowledgePoint: "",
								difficulty: "",
							},
						])
					}
				>
					<Plus size={14} aria-hidden="true" />
					添加题目组
				</button>
			</section>
			<div className={`qx-tablewrap ${styles.tableWrap}`}>
				<table className="qx-table">
					<thead>
						<tr>
							{["顺序", "学科", "题型", "题数", "每题总分", "小问分值", "知识点", "难度", "操作"].map((s) => (
								<th key={s}>{s}</th>
							))}
						</tr>
					</thead>
					<tbody>
						{groups.map((g, i) => (
							<tr key={g.id}>
								<td>{i + 1}</td>
								<td>
									<select
										aria-label={`第${i + 1}组学科`}
										value={g.subject}
										onChange={(e) => update(g.id, { subject: e.target.value })}
									>
										{["数据结构", "计算机组成原理", "操作系统", "计算机网络"].map((s) => (
											<option key={s}>{s}</option>
										))}
									</select>
								</td>
								<td>
									<select
										aria-label={`第${i + 1}组题型`}
										value={g.question_type}
										onChange={(e) =>
											update(g.id, {
												question_type: e.target.value === "single_choice" ? "single_choice" : "comprehensive",
												partScores: "",
											})
										}
									>
										<option value="single_choice">单项选择</option>
										<option value="comprehensive">综合应用</option>
									</select>
								</td>
								<td>
									<input
										aria-label={`第${i + 1}组题数`}
										type="number"
										min="1"
										max="100"
										value={g.count}
										onChange={(e) => update(g.id, { count: Number(e.target.value) })}
									/>
								</td>
								<td>
									<input
										aria-label={`第${i + 1}组分值`}
										type="number"
										min="1"
										max="150"
										value={g.score}
										onChange={(e) => update(g.id, { score: Number(e.target.value) })}
									/>
								</td>
								<td>
									<input
										aria-label={`第${i + 1}组小问分值`}
										placeholder="如3,7"
										disabled={g.question_type === "single_choice"}
										value={g.partScores}
										onChange={(e) => update(g.id, { partScores: e.target.value })}
									/>
								</td>
								<td>
									<input
										aria-label={`第${i + 1}组知识点`}
										placeholder="不限"
										value={g.knowledgePoint}
										onChange={(e) => update(g.id, { knowledgePoint: e.target.value })}
									/>
								</td>
								<td>
									<select
										aria-label={`第${i + 1}组难度`}
										value={g.difficulty}
										onChange={(e) => update(g.id, { difficulty: e.target.value })}
									>
										<option value="">不限</option>
										<option value="easy">简单</option>
										<option value="medium">中等</option>
										<option value="hard">困难</option>
									</select>
								</td>
								<td>
									<button
										type="button"
										className="qx-link"
										disabled={busy || i === 0}
										onClick={() =>
											setGroups((rows) => {
												const next = [...rows];
												[next[i - 1], next[i]] = [next[i], next[i - 1]];
												return next;
											})
										}
									>
										上移
									</button>
									<button
										type="button"
										className="qx-link"
										disabled={busy}
										onClick={() => setGroups(groups.filter((r) => r.id !== g.id))}
									>
										移除
									</button>
								</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
			<p className="qx-note">知识点、难度与小问分值留空时不限。综合题小问分值用逗号分隔，如 2,2,2,4。</p>
			<details className="qx-report">
				<summary>语义重复复核（可选）</summary>
				<label className="qx-actions">
					<input
						type="checkbox"
						checked={semanticReview}
						disabled={busy}
						onChange={(e) => setSemanticReview(e.target.checked)}
					/>
					复核所有入选题对，确认重复后尝试同要求换题
				</label>
				<p>包含材料和综合题小问。需要教师结论或服务端启用模型；未完成复核不出卷。模型复核可能产生API费用。</p>
				<label className="qx-actions">
					本次模型请求上限
					<input
						aria-label="语义复核模型请求上限"
						type="number"
						min="0"
						max="100"
						value={semanticCalls}
						disabled={busy || !semanticReview}
						onChange={(e) => setSemanticCalls(Number(e.target.value))}
					/>
				</label>
				<p>实际还受服务端上限约束；每次最多复核4对，换题后仅复核新题对。预算不足时保留报告，不自动追加。</p>
			</details>
			<details className="qx-report">
				<summary>教师相似题复核决定</summary>
				<p>仅填写教师确认的原始决定；不提交时保留 []。</p>
				<textarea
					aria-label="整卷人工复核决定"
					rows={5}
					value={decisions}
					onChange={(e) => setDecisions(e.target.value)}
				/>
			</details>
			<section className={styles.submitBar}>
				<div>
					<h2>
						{preview?.question_count ?? 0} 题 <span>·</span> {preview?.total_score ?? 0} 分
					</h2>
					<p>生成学生卷与独立答案，保存至组卷历史。</p>
				</div>
				<button type="button" className="qx-btn primary" disabled={busy || !!validation} onClick={() => submit()}>
					{busy ? "正在选题与保存…" : "按自定义结构生成"}
				</button>
			</section>
			{validation && <p className="qx-error">{validation}</p>}
			{error && (
				<p role="alert" className="qx-error">
					{error}
				</p>
			)}
			{result && (
				<section className="qx-result">
					<h2>{statusLabel(result.status)}</h2>
					<pre>{pretty(result)}</pre>
				</section>
			)}
		</div>
	);
}
