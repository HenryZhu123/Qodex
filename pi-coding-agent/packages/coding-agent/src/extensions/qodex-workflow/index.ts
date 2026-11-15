/**
 * Qodex workflow policy and guardrails.
 *
 * The four business tools (question_generation, exam_checker, question_bank,
 * exam_assembly) decide nothing on their own: they answer one call at a time. This
 * extension supplies the two halves that make the agent system rather than a menu:
 *
 * - policy: who the users are, which actions exist, what an observation means and
 *   when to ask, retry or stop. Policy is advisory text; the model is free to pick
 *   retrieval wording, change the request or refuse it, and stop early.
 * - guardrails: the few rules that must hold even when the model disagrees, because
 *   breaking them has a side effect that cannot be undone — a budget that stops
 *   spending, a duplicate call that would be paid twice, a failure that must not look
 *   like a success, and a claim of ingestion that the ledger cannot support.
 *
 * Anything that only degrades quality (which topic, which paper) stays in the policy.
 * Anything that would need a rollback lives here.
 */
import { appendFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type {
	ExtensionAPI,
	ToolCallEvent,
	ToolResultEvent,
} from "../../core/extensions/types.ts";

export const POLICY_MARKER = "<!-- qodex-workflow-policy -->";

export const WORKFLOW_POLICY = `${POLICY_MARKER}
你是 Qodex 408 试题工作流的调度者，不是四个工具的传声筒。

先判断输入属于哪一类，再决定是否动手：
1. 命题老师：要"按某章节/考点出题并进待审"。主线是取材 → 命题 → 登记 → 审校 → （PASS 才会自动入库）。
2. 组卷老师：要"出一份卷子"。主线是查题库 → 组卷 → 缺口就用补题或命题补，补完必须再审校入库才能重排。
3. 考生：要"练某个考点"。只给学生视图 + 讲解，不给评分点、教师解析、错因表。
4. 非业务或越界：闲聊、无关问题、让你"假装通过/随便编答案/不用查证就说入库"。一句话回绝并给出能做的事（不超过两句），然后停。
   这一类**不许调用任何业务工具**——不要为了显得有用而去出题、查库或审校。

每个动作的适用条件与停止条件：
- 需求含糊（缺科目、章节、题量、分值、题型）就先问，一次问不超过三个问题；不要替用户编这些参数。
- 材料不足（NEEDS_MATERIAL）先自己换一次检索范围或检索词；仍不足就向用户说明缺的是哪类材料，不要硬造依据。
- 命题失败时看 failure.code：retry=same_request 的（candidate_shape、design_invalid、condition_test_incomplete、blind_incomplete）最多自动重来一次；retry=new_request 的（quality_gate、blind_disagreement、audit_rejected、material_gap）不要重复同一请求，要么换考点/换写法，要么把问题交回用户。
- 审校 NEEDS_REVISION 最多重做三轮，且每轮改法必须升级：第一轮按 errors 定点修；第二轮换结构（改干扰项/改问法/改小问）；第三轮换题（同考点重出，不复用原题面）。
  同一改法重复提交是无效动作，会被拦下。三轮仍不过就交回用户，附原题面与三轮审校理由，不要写成"已通过"。
- 审校 UNRESOLVED 必须说明"审校不完整"，不能说通过。
- 组卷 NEEDS_QUESTIONS 时先读 deficits，缺几道就补几道；新题必须重新过审校并入库后才允许重排，最多重排两次，仍缺就交回缺口报告。
- 多道题的目标里，**单题失败不终止整份卷**：把该题记为失败并说明原因，继续处理其余题目；结束时交付"成了哪些/没成哪些/为什么"。只有"只出一道题"时失败才等于整个目标失败。
- 只组单选。用户要综合题、题组、带图题或难度配额时，明确说当前不支持，并给可行替代（例如综合题单独出、按教师视图包交付），不要静默降级。
- 预算或连续两次同码失败时主动收尾：列出已完成、产出在哪、下一步建议。

不允许做的事：判定 PASS；自己编造 knowledge_points、task_id 或版本号；把教师视图或评分给学生；在拿到 ingestion.status=STORED 之前说"已入库/已通过"。
`;

const GENERATION_TOOL = "question_generation";
const REVIEW_TOOL = "exam_checker";
const BANK_TOOL = "question_bank";
const ASSEMBLY_TOOL = "exam_assembly";
const DOMAIN_TOOLS = new Set([GENERATION_TOOL, REVIEW_TOOL, BANK_TOOL, ASSEMBLY_TOOL]);
const DEFAULT_TRACE_DIR = ".local/qodex-traces";

type Bucket = "generation" | "review" | "assembly";

export interface WorkflowLimits {
	generation: number;
	review: number;
	assembly: number;
	wallClockMs: number;
	/** Failed (rejected) calls allowed before the run must stop and hand back. */
	failures: number;
}

const DEFAULT_LIMITS: WorkflowLimits = {
	// One item may take one draft plus three review-driven rewrites, so a small paper
	// needs well over six calls; the wall clock and the failure cap stop runaways.
	generation: 12,
	review: 12,
	assembly: 3,
	wallClockMs: 45 * 60_000,
	failures: 3,
};

function positiveInteger(value: string | undefined, fallback: number): number {
	if (!value) return fallback;
	const parsed = Number(value);
	return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function resolveLimits(env: Record<string, string | undefined>): WorkflowLimits {
	return {
		generation: positiveInteger(env.QODEX_MAX_GENERATION_CALLS, DEFAULT_LIMITS.generation),
		review: positiveInteger(env.QODEX_MAX_REVIEW_CALLS, DEFAULT_LIMITS.review),
		assembly: positiveInteger(env.QODEX_MAX_ASSEMBLY_CALLS, DEFAULT_LIMITS.assembly),
		wallClockMs: positiveInteger(env.QODEX_MAX_WALL_CLOCK_MS, DEFAULT_LIMITS.wallClockMs),
		failures: positiveInteger(env.QODEX_MAX_FAILED_CALLS, DEFAULT_LIMITS.failures),
	};
}

export function policyEnabled(env: Record<string, string | undefined>): boolean {
	const flag = (env.QODEX_WORKFLOW_POLICY ?? "").toLowerCase();
	return flag !== "0" && flag !== "off" && flag !== "false";
}

function bucketOf(toolName: string): Bucket | undefined {
	if (toolName === GENERATION_TOOL) return "generation";
	if (toolName === REVIEW_TOOL) return "review";
	if (toolName === ASSEMBLY_TOOL) return "assembly";
	return undefined;
}

/** Deterministic JSON so two identical calls always digest the same. */
function canonical(value: unknown): string {
	if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
	if (value && typeof value === "object") {
		const entries = Object.entries(value as Record<string, unknown>)
			.filter(([, item]) => item !== undefined)
			.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
			.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`);
		return `{${entries.join(",")}}`;
	}
	return JSON.stringify(value ?? null);
}

export function callDigest(toolName: string, input: unknown): string {
	return createHash("sha256").update(`${toolName}\n${canonical(input)}`).digest("hex").slice(0, 32);
}

export interface Observation {
	ok: boolean;
	code?: string;
	status?: string;
	retry?: string;
	needs?: string | null;
	next: string[];
	artifact?: Record<string, string>;
	/** Bounded evidence for the next move: why it failed, not the whole payload. */
	detail?: string;
	errors?: string[];
}

const FAILURE_STATUSES = new Set([
	"SELF_CHECK_FAILED",
	"MODEL_UNAVAILABLE",
	"NEEDS_MATERIAL",
	"SERVER_BUSY",
	"QUEUE_UNAVAILABLE",
	"QUEUE_VERSION_CONFLICT",
	"HARNESS_ERROR",
	"INVALID_REQUEST",
	"UNRESOLVED",
	"NEEDS_REVISION",
	"TOOL_ERROR",
]);

function hintFor(status: string | undefined, code: string | undefined): string[] {
	if (code === "material_gap" || status === "NEEDS_MATERIAL") {
		return ["换一次检索范围或检索词", "仍不足则向用户说明缺失的材料类型，不要编造依据"];
	}
	if (code === "audit_rejected" || status === "NEEDS_REVISION") {
		return ["用审校给出的 errors 修订一次（revise_question）", "第二轮仍不过就停下并如实报告"];
	}
	if (status === "UNRESOLVED") {
		return ["审校不完整，必须说明未通过而非通过", "重试一次 review_question，或交回用户"];
	}
	if (status === "NEEDS_QUESTIONS") {
		return ["读 deficits 后补题，新题须审校入库后再重排一次"];
	}
	if (code === "quality_gate" || code === "blind_disagreement") {
		return ["不要重发同一请求：换考点或改写要求后再生成"];
	}
	if (status === "INVALID_REQUEST") {
		return ["按返回的 errors 修正请求参数；不支持的能力要明确告知用户"];
	}
	if (status && FAILURE_STATUSES.has(status)) {
		return ["如实报告失败状态，不要当成成功"];
	}
	return [];
}

function firstText(content: ToolResultEvent["content"]): string | undefined {
	for (const part of content) {
		if (part.type === "text" && typeof part.text === "string") return part.text;
	}
	return undefined;
}

function parsePayload(text: string | undefined): Record<string, unknown> | undefined {
	if (!text || !text.trim().startsWith("{")) return undefined;
	try {
		const parsed: unknown = JSON.parse(text);
		return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : undefined;
	} catch {
		return undefined;
	}
}

function clip(value: unknown, limit = 240): string | undefined {
	if (typeof value !== "string" || !value.trim()) return undefined;
	const text = value.trim();
	return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function stringField(source: Record<string, unknown> | undefined, key: string): string | undefined {
	const value = source?.[key];
	return typeof value === "string" ? value : undefined;
}

function nested(source: Record<string, unknown> | undefined, key: string): Record<string, unknown> | undefined {
	const value = source?.[key];
	return value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
}

/** Turn a raw service payload into the observation the model needs for its next move. */
export function observe(toolName: string, payload: Record<string, unknown> | undefined): Observation {
	if (payload && typeof payload.error === "string") {
		return { ok: false, code: payload.error, next: hintFor(undefined, undefined) };
	}
	if (toolName === GENERATION_TOOL) {
		const status = stringField(payload, "status");
		const failure = nested(payload, "failure");
		const code = stringField(failure, "code");
		const retry = stringField(failure, "retry");
		const questions = Array.isArray(payload?.questions) ? payload.questions.length : 0;
		const ok = status === "GENERATED";
		const next = ok ? [] : hintFor(status, code);
		const observation: Observation = { ok, next };
		if (status) observation.status = status;
		if (code) observation.code = code;
		if (retry) observation.retry = retry;
		if (failure && "needs" in failure) {
			const needs = failure.needs;
			observation.needs = typeof needs === "string" ? needs : null;
		}
		if (ok && questions > 0) observation.artifact = { questions: String(questions) };
		if (!ok) {
			const report = nested(payload, "authoring_report");
			observation.detail = clip(payload && payload.message) ?? clip(report && report.stage);
		}
		return observation;
	}
	if (toolName === REVIEW_TOOL) {
		const status =
			stringField(payload, "status") ?? stringField(nested(payload, "review"), "status");
		const ingestion = nested(payload, "ingestion");
		const observation: Observation = {
			ok: status === "PASS",
			next: status === "PASS" ? [] : hintFor(status, undefined),
		};
		if (typeof status === "string") observation.status = status;
		const artifact: Record<string, string> = {};
		const taskId = stringField(payload, "task_id");
		if (taskId) artifact.task_id = taskId;
		const documentId = stringField(payload, "document_id");
		if (documentId) artifact.document_id = documentId;
		const questionId = stringField(payload, "question_id");
		if (questionId) artifact.question_id = questionId;
		if (typeof payload?.version === "number") artifact.version = String(payload.version);
		if (ingestion && typeof ingestion.status === "string") artifact.ingestion = ingestion.status;
		if (Object.keys(artifact).length > 0) observation.artifact = artifact;
		if (!observation.ok) {
			// The Pi tool returns a compact, flat review result; the raw HTTP payload nests
			// the same evidence under review.summary. Accept both so the observation keeps
			// working whichever shape reaches the hook.
			const summary = nested(nested(payload, "review"), "summary");
			const rawErrors =
				summary && Array.isArray(summary.errors)
					? summary.errors
					: Array.isArray(payload?.errors)
						? payload.errors
						: [];
			const types = rawErrors
				.map((item) => (item && typeof item === "object" ? (item as Record<string, unknown>).error_type : undefined))
				.filter((item): item is string => typeof item === "string");
			if (types.length > 0) observation.errors = types.slice(0, 6);
			const unresolved =
				summary && Array.isArray(summary.unresolved_checks)
					? summary.unresolved_checks
					: Array.isArray(payload?.unresolved_checks)
						? payload.unresolved_checks
						: [];
			if (unresolved.length > 0) observation.detail = `unresolved_checks=${unresolved.length}`;
		}
		return observation;
	}
	if (toolName === ASSEMBLY_TOOL) {
		const status = stringField(payload, "status");
		const deficits = Array.isArray(payload?.deficits) ? payload.deficits : [];
		const observation: Observation = {
			ok: status === "STRUCTURAL_PASS",
			next: hintFor(status, undefined),
		};
		if (status) observation.status = status;
		if (deficits.length > 0) observation.artifact = { deficits: String(deficits.length) };
		if (!observation.ok) {
			const errors = payload && Array.isArray(payload.errors) ? payload.errors : [];
			const first = errors.find((item) => typeof item === "string");
			observation.detail = clip(first) ?? clip(payload && payload.message);
		}
		const artifacts = nested(payload, "artifacts");
		if (artifacts) {
			const paths = Object.entries(artifacts)
				.filter(([, value]) => typeof value === "string")
				.map(([key]) => key);
			if (paths.length > 0) observation.artifact = { ...observation.artifact, files: paths.join(",") };
		}
		return observation;
	}
	if (toolName === BANK_TOOL) {
		const questions = Array.isArray(payload?.questions) ? payload.questions.length : undefined;
		return { ok: true, next: [], ...(questions === undefined ? {} : { artifact: { questions: String(questions) } }) };
	}
	return { ok: true, next: [] };
}

// Quoted text is the agent talking about the words, not asserting a result: it explains
// the rule as `看到 ingestion.status=STORED 才说"已入库"`. Strip quotes before matching,
// then require an unquoted completion claim.
function claimOfIngestion(text: string): boolean {
	const unquoted = text.replace(/"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|'[^']*'/g, " ");
	return /((?<![从把])已入库|已通过审校|审校通过|已经入库|accepted into the bank)/i.test(unquoted);
}

function messageText(message: AgentMessage): string {
	if (message.role !== "assistant") return "";
	return message.content
		.filter((part) => part.type === "text")
		.map((part) => (part as { text: string }).text)
		.join("\n");
}

export default function qodexWorkflowExtension(pi: ExtensionAPI): void {
	const startedAt = Date.now();
	const counts: Record<Bucket, number> = { generation: 0, review: 0, assembly: 0 };
	const completed = new Map<string, Observation>();
	const rollback = new Map<string, Observation>();
	const traceDir = process.env.QODEX_TRACE_DIR ?? DEFAULT_TRACE_DIR;
	const traceFile = join(traceDir, `workflow-${startedAt.toString(36)}.jsonl`);
	let ingestionVerified = false;
	let policyAttached = false;
	let domainCalls = 0;
	let failedCalls = 0;
	let lastDomainTool = "";

	const trace = async (event: string, fields: Record<string, unknown> = {}): Promise<void> => {
		try {
			await mkdir(traceDir, { recursive: true });
			await appendFile(traceFile, `${JSON.stringify({ ts: new Date().toISOString(), event, ...fields })}\n`);
		} catch {
			// Tracing must never block a tool call.
		}
	};

	pi.on("session_start", async (event) => {
		await trace("session_start", { reason: event.reason, trace: traceFile });
	});

	pi.on("before_agent_start", async (event) => {
		// The trace is the operator's window into a live session: what the user typed,
		// which tool ran, what came back. Prompt text is capped so a pasted paper cannot
		// bloat the log.
		await trace("user_prompt", { prompt: event.prompt.slice(0, 2000), length: event.prompt.length });
		if (!policyEnabled(process.env)) return undefined;
		policyAttached = true;
		if (event.systemPrompt.includes(POLICY_MARKER)) return undefined;
		return { systemPrompt: `${event.systemPrompt}\n\n${WORKFLOW_POLICY}` };
	});

	pi.on("tool_call", async (event: ToolCallEvent) => {
		if (!DOMAIN_TOOLS.has(event.toolName)) return undefined;
		const limits = resolveLimits(process.env);
		const bucket = bucketOf(event.toolName);
		const digest = callDigest(event.toolName, event.input);

		if (bucket && counts[bucket] >= limits[bucket]) {
			await trace("blocked", { tool: event.toolName, reason: "BUDGET", bucket, digest });
			return {
				block: true,
				reason:
					`BUDGET_EXHAUSTED: ${bucket} 已用 ${counts[bucket]}/${limits[bucket]} 次。` +
					"停止新调用，向用户报告已完成的部分、产出位置与下一步建议。",
			};
		}
		if (Date.now() - startedAt > limits.wallClockMs) {
			await trace("blocked", { tool: event.toolName, reason: "WALL_CLOCK", digest });
			return {
				block: true,
				reason: "BUDGET_EXHAUSTED: 本轮墙钟已超出预算。停止新调用并向用户报告当前结果。",
			};
		}
		const prior = completed.get(digest);
		if (prior) {
			await trace("blocked", { tool: event.toolName, reason: "DUPLICATE", digest });
			return {
				block: true,
				reason:
					"DUPLICATE_CALL: 相同参数的调用已经成功执行过，结果在上面那条观察里。" +
					"不要重复付费；需要不同结果请改参数或换考点。",
			};
		}
		domainCalls += 1;
		lastDomainTool = event.toolName;
		if (failedCalls >= limits.failures) {
			await trace("blocked", { tool: event.toolName, reason: "REPEATED_FAILURES", digest });
			return {
				block: true,
				reason:
					`REPEATED_FAILURES: 本轮已连续失败 ${failedCalls} 次。停止新调用，把失败原文与请求体交回用户，` +
					"不要继续试参数。",
			};
		}
		await trace("tool_call", {
			tool: event.toolName,
			digest,
			counts: { ...counts },
			operation: stringField(event.input as Record<string, unknown>, "operation"),
		});
		return undefined;
	});

	pi.on("tool_result", async (event: ToolResultEvent) => {
		if (!DOMAIN_TOOLS.has(event.toolName)) return undefined;
		const payload = parsePayload(firstText(event.content));
		const observation = observe(event.toolName, payload);
		const digest = callDigest(event.toolName, event.input);
		const bucket = bucketOf(event.toolName);
		if (observation.ok) {
			completed.set(digest, observation);
			rollback.delete(digest);
			// Only successful work consumes the per-tool budget, so one malformed request
			// cannot end the session; repeated failures are bounded separately below.
			if (bucket) counts[bucket] += 1;
		} else {
			rollback.set(digest, observation);
			failedCalls += 1;
		}
		if (observation.artifact?.ingestion === "STORED" || observation.status === "PASS") {
			ingestionVerified = observation.artifact?.ingestion === "STORED";
		}
		await trace("tool_result", {
			tool: event.toolName,
			digest,
			ok: observation.ok,
			status: observation.status,
			code: observation.code,
			artifact: observation.artifact,
		});
		if (!payload) return undefined;
		return {
			content: [{ type: "text", text: JSON.stringify({ observation }) }],
			isError: !observation.ok,
		};
	});

	pi.on("message_end", async (event) => {
		if (event.message.role !== "assistant") return undefined;
		const text = messageText(event.message);
		if (!text || !claimOfIngestion(text)) return undefined;
		if (ingestionVerified) return undefined;
		// Nothing was executed, so the sentence can only be about capabilities; and a
		// read-only bank query cannot have produced an ingestion receipt either.
		if (domainCalls === 0) return undefined;
		if (lastDomainTool !== REVIEW_TOOL && lastDomainTool !== GENERATION_TOOL) return undefined;
		const correction =
			"\n\n[护栏] 本轮没有拿到 ingestion.status=STORED 的回执，因此上面的“已入库/已通过”不成立；" +
			"请改成“自检通过 / 待审校”或“审校未完成”。";
		await trace("claim_blocked", { chars: text.length });
		return {
			message: {
				...event.message,
				content: [...event.message.content, { type: "text", text: correction }],
			},
		};
	});

	pi.registerCommand("qodex", {
		description: "显示 Qodex 工作流的三类意图、预算使用和 trace 位置",
		handler: async (_args, ctx) => {
			const limits = resolveLimits(process.env);
			const lines = [
				"Qodex 工作流（先说清你是谁要什么，再动手）",
				"1) 出题：'数据结构 图 单选 2 道进待审'",
				"2) 组卷：'数据结构 10 题各 2 分，简单 3 中 5 难 2'",
				"3) 练题：'我想练循环队列'（只看学生视图）",
				`预算：命题 ${counts.generation}/${limits.generation}，审校 ${counts.review}/${limits.review}，` +
					`组卷 ${counts.assembly}/${limits.assembly}；policy=${policyAttached ? "已注入" : "未注入"}`,
				`trace：${traceFile}`,
			];
			ctx.ui.notify(lines.join("\n"));
		},
	});
}
