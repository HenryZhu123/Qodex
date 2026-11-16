import { Type } from "typebox";
import type { ExtensionAPI } from "../../core/extensions/types.ts";

const operations = ["single", "batch", "replenishment", "comprehensive", "revise", "author"] as const;
type Operation = (typeof operations)[number];

const parameters = Type.Object({
	operation: Type.Union(
		[
			Type.Literal("single"),
			Type.Literal("batch"),
			Type.Literal("replenishment"),
			Type.Literal("comprehensive"),
			Type.Literal("revise"),
			Type.Literal("author"),
		],
		{
			description:
				"author for any natural-language, rough-topic, material-driven, or arbitrary-syllabus request; " +
				"single/comprehensive/batch/replenishment only for their fixed deterministic contracts; " +
				"revise for a versioned package returned by this service.",
		},
	),
	request: Type.Record(Type.String(), Type.Unknown(), {
		description:
			'Operation-specific request. author requires schema_version="0.1" and request_id, and accepts ' +
			"brief, seed, subject, syllabus_areas, question_type, total_score, requirements, evidence. " +
			"single/comprehensive/batch are deterministic template paths with fixed topics and fields; " +
			"revise requires current_question + feedback.",
	}),
});

const DETAIL_LIMIT = 500;

const AUTHOR_ALLOWED = new Set([
	"schema_version",
	"request_id",
	"brief",
	"seed",
	"subject",
	"syllabus_areas",
	"question_type",
	"total_score",
	"requirements",
	"evidence",
	"task_id",
]);
const AUTHOR_FIELDS =
	"schema_version、request_id、brief、seed、subject、syllabus_areas、question_type、total_score、requirements、evidence";
const SUBJECTS = new Set(["data_structures", "computer_organization", "operating_systems", "computer_networks"]);
const QUESTION_TYPES = new Set(["single_choice", "comprehensive"]);
// The authoring service resolves these IDs against the 408 syllabus. A Chinese
// chapter name is not a valid ID; listing them here keeps the model from guessing
// "ds.linear_list" and burning a retry on a validation error.
const SYLLABUS_AREAS = [
	"ds.foundations",
	"ds.linear",
	"ds.stack_queue_array",
	"ds.trees",
	"ds.graphs",
	"ds.search",
	"ds.sort",
	"co.system",
	"co.representation",
	"co.memory",
	"co.instructions",
	"co.cpu",
	"co.io",
	"os.foundations",
	"os.process",
	"os.memory",
	"os.files",
	"os.io",
	"cn.architecture",
	"cn.physical",
	"cn.link",
	"cn.network",
	"cn.transport",
	"cn.application",
];
const SYLLABUS_AREA_SET = new Set(SYLLABUS_AREAS);
const DETERMINISTIC_TOPICS = new Set([
	"single_level_paging",
	"stack_pop_sequence",
	"direct_mapped_cache",
	"ipv4_subnet_network_address",
	"tcp_message_boundaries",
]);
const AUTHORING_FIELDS = ["brief", "requirements", "syllabus_areas"];

// The authoring service expects syllabus slugs. Teaching requests say "数据结构",
// "计组", or "data_structure"; normalising here keeps the contract strict without
// making the model guess a spelling it cannot see in the tool schema.
const SUBJECT_ALIASES: Record<string, string> = {
	数据结构: "data_structures",
	data_structure: "data_structures",
	data_structures: "data_structures",
	计算机组成原理: "computer_organization",
	计算机组成: "computer_organization",
	计组: "computer_organization",
	computer_organization: "computer_organization",
	操作系统: "operating_systems",
	operating_system: "operating_systems",
	operating_systems: "operating_systems",
	计算机网络: "computer_networks",
	计网: "computer_networks",
	computer_network: "computer_networks",
	computer_networks: "computer_networks",
};

const REVISE_FEEDBACK_FIELDS = ["feedback_id", "question_id", "target_version", "part_id", "action", "comment"];
const REVISE_FEEDBACK_OPTIONAL = ["replacement"];

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
	return typeof value === "string" && value.trim().length > 0;
}

function detailText(value: unknown): string {
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value) ?? String(value);
	} catch {
		return String(value);
	}
}

function truncateDetail(value: unknown): string {
	const text = detailText(value);
	return text.length > DETAIL_LIMIT ? `${text.slice(0, DETAIL_LIMIT - 1)}…` : text;
}

function describeHttpFailure(status: number, body: unknown, raw: string): string {
	const parts = [`HTTP ${status}`];
	if (typeof body === "object" && body !== null) {
		const record = body as Record<string, unknown>;
		for (const key of ["status", "detail", "message"]) {
			if (key in record) parts.push(`${key}: ${truncateDetail(record[key])}`);
		}
	}
	if (parts.length === 1 && raw.trim()) parts.push(truncateDetail(raw.trim()));
	return `INVALID_QUESTION_GENERATION_RESPONSE (${parts.join("; ")})`;
}

function isQuestionGenerationResult(
	value: unknown,
): value is { status: string; questions: unknown[] } & Record<string, unknown> {
	return (
		typeof value === "object" &&
		value !== null &&
		"status" in value &&
		typeof (value as Record<string, unknown>).status === "string" &&
		"questions" in value &&
		Array.isArray((value as Record<string, unknown>).questions)
	);
}

function invalidRequest(message: string, request: Record<string, unknown>) {
	const requestId = typeof request.request_id === "string" ? request.request_id : null;
	const payload = {
		schema_version: "0.1",
		request_id: requestId,
		status: "INVALID_REQUEST",
		questions: [],
		message,
	};
	return {
		content: [{ type: "text" as const, text: JSON.stringify(payload) }],
		details: payload,
		isError: true,
	};
}

function hasAuthoringConstraints(request: Record<string, unknown>): boolean {
	const constraints = request.constraints;
	return isRecord(constraints) && "authoring" in constraints;
}

/**
 * A natural-language request is an authoring request. The deterministic operations
 * have narrow, fixed contracts; when a caller sends authoring fields to one of them
 * we can return the correct route before spending a model call or a retry.
 */
function routeAuthoringFields(operation: Operation, request: Record<string, unknown>): string | undefined {
	if (operation === "author") return undefined;
	const present = AUTHORING_FIELDS.filter((field) => field in request);
	if (present.length === 0) return undefined;
	return (
		`operation=${operation} 收到 author 专用字段（${present.join("、")}）。` +
		"这是自然语言/材料驱动的命题请求，请改用 operation=author；" +
		"single/comprehensive/batch 是确定性模板入口，只接受固定 topic 与字段。"
	);
}

function routeMissingDeterministicFields(operation: Operation, request: Record<string, unknown>): string | undefined {
	if (operation === "author" || operation === "revise" || hasAuthoringConstraints(request)) return undefined;
	if (operation === "single" || operation === "comprehensive") {
		const topic = request.topic;
		if (typeof topic !== "string" || !DETERMINISTIC_TOPICS.has(topic)) {
			return (
				`operation=${operation} 只支持固定考点：single_level_paging、stack_pop_sequence、` +
				"direct_mapped_cache、ipv4_subnet_network_address、tcp_message_boundaries（且需匹配 subject/seed/evidence）。" +
				"任意考点或自然语言需求请改用 operation=author。"
			);
		}
	}
	if (operation === "batch" && !Array.isArray(request.slots)) {
		return (
			"operation=batch 需要显式 slots（每个槽位的 slot_id、count、score_per_question、subject、topic、question_type、difficulty）。" +
			"自然语言需求请改用 operation=author。"
		);
	}
	if (operation === "replenishment" && !isRecord(request.replenishment_request)) {
		return "operation=replenishment 需要组卷服务返回的 replenishment_request；自然语言需求请改用 operation=author。";
	}
	return undefined;
}

function withRequestDefaults(request: Record<string, unknown>): Record<string, unknown> {
	const normalized = { ...request };
	// The service requires both fields on every operation. Supplying the version and
	// minting an id here is the same adapter behaviour as task_id injection; it stops
	// a missing bookkeeping field from consuming one of the three failure retries.
	if (normalized.schema_version === undefined) normalized.schema_version = "0.1";
	if (!isText(normalized.request_id)) normalized.request_id = crypto.randomUUID();
	return normalized;
}

function normalizeSubject(request: Record<string, unknown>): Record<string, unknown> {
	if (typeof request.subject !== "string") return request;
	const alias = SUBJECT_ALIASES[request.subject.trim()];
	return alias ? { ...request, subject: alias } : request;
}

function normalizeAuthorRequest(request: Record<string, unknown>): Record<string, unknown> {
	const normalized = normalizeSubject(withRequestDefaults(request));
	// One requirement is unambiguous; wrapping it keeps the service contract strict
	// without forcing the model to learn another JSON shape.
	if (typeof normalized.requirements === "string") {
		normalized.requirements = [normalized.requirements];
	}
	return normalized;
}

function authorRequestError(request: Record<string, unknown>): string | undefined {
	const unknown = Object.keys(request).filter((key) => !AUTHOR_ALLOWED.has(key));
	if (unknown.length > 0) {
		return `author 不接受字段 ${unknown.join("、")}。允许的字段：${AUTHOR_FIELDS}。`;
	}
	if (request.schema_version !== "0.1") {
		return 'author.schema_version 必须是 "0.1"。';
	}
	if (!isText(request.request_id) || request.request_id.length > 200) {
		return "author.request_id 必须是非空字符串（≤200 字）。";
	}
	if (request.brief !== undefined && (!isText(request.brief) || request.brief.length > 2000)) {
		return "author.brief 必须是非空字符串（≤2000 字）。";
	}
	if (request.subject !== undefined) {
		const subject = request.subject;
		if (typeof subject !== "string" || !SUBJECTS.has(subject)) {
			return `author.subject 必须是 ${[...SUBJECTS].join(" / ")}；收到 ${detailText(subject)}。中文科目名会自动映射。`;
		}
	}
	if (request.syllabus_areas !== undefined) {
		const areas = request.syllabus_areas;
		if (!Array.isArray(areas) || areas.length === 0 || !areas.every((area) => isText(area))) {
			return "author.syllabus_areas 必须是非空章节 ID 字符串数组。";
		}
		const unknownAreas = areas.filter((area) => !SYLLABUS_AREA_SET.has(area));
		if (unknownAreas.length > 0) {
			return (
				`author.syllabus_areas 必须是章节 ID，不能写中文名：${unknownAreas.join("、")}。` +
				`合法值：${SYLLABUS_AREAS.join(", ")}。`
			);
		}
	}
	if (request.question_type !== undefined) {
		const questionType = request.question_type;
		if (typeof questionType !== "string" || !QUESTION_TYPES.has(questionType)) {
			return "author.question_type 必须是 single_choice 或 comprehensive。";
		}
	}
	if (request.total_score !== undefined) {
		const score = request.total_score;
		if (request.question_type !== "comprehensive") {
			return "author.total_score 仅用于综合题；单选题不要传 total_score。";
		}
		if (typeof score !== "number" || !Number.isInteger(score) || score < 2 || score > 30) {
			return "author.total_score 必须是 2–30 的整数（仅综合题）。";
		}
	}
	if (request.requirements !== undefined) {
		const requirements = request.requirements;
		if (
			!Array.isArray(requirements) ||
			requirements.length < 1 ||
			requirements.length > 8 ||
			!requirements.every((item) => isText(item) && item.length <= 1000)
		) {
			return "author.requirements 必须是 1–8 条非空字符串（每条 ≤1000 字），不要传对象。";
		}
	}
	if (request.seed !== undefined) {
		const seed = request.seed;
		if (typeof seed !== "number" || !Number.isInteger(seed) || seed < 0 || seed > 2 ** 32 - 1) {
			return "author.seed 必须是 0–4294967295 的整数。";
		}
	}
	if (request.evidence !== undefined && !Array.isArray(request.evidence)) {
		return "author.evidence 必须是材料数组。";
	}
	return undefined;
}

function reviseRequestError(request: Record<string, unknown>): string | undefined {
	const current = request.current_question;
	if (!isRecord(current)) {
		return "revise 需要 current_question（服务返回的完整题包，含 question_id/version/metadata/generator）。";
	}
	if (!isText(current.question_id)) {
		return "revise.current_question.question_id 缺失。";
	}
	if (typeof current.version !== "number" || !Number.isInteger(current.version) || current.version < 1) {
		return "revise.current_question.version 必须是正整数。";
	}
	const feedback = request.feedback;
	if (!isRecord(feedback)) {
		return `revise.feedback 必须是对象，包含 ${REVISE_FEEDBACK_FIELDS.join("、")}。`;
	}
	const unknown = Object.keys(feedback).filter(
		(key) => !REVISE_FEEDBACK_FIELDS.includes(key) && !REVISE_FEEDBACK_OPTIONAL.includes(key),
	);
	if (unknown.length > 0) {
		return `revise.feedback 不接受字段 ${unknown.join("、")}；允许：${[...REVISE_FEEDBACK_FIELDS, ...REVISE_FEEDBACK_OPTIONAL].join("、")}。`;
	}
	const missing = REVISE_FEEDBACK_FIELDS.filter((key) => key !== "target_version" && !isText(feedback[key]));
	const targetVersion = feedback.target_version;
	const targetVersionValid =
		typeof targetVersion === "number" && Number.isInteger(targetVersion) && targetVersion >= 1;
	if (missing.length > 0 || !targetVersionValid) {
		return (
			`revise.feedback 缺少或为空：${[...missing, ...(targetVersionValid ? [] : ["target_version"])].join("、")}。` +
			"通用创作题的 action 必须是 repair；分页综合题还需要 action=replace 与 replacement。" +
			"target_version 必须是正整数，且等于 current_question.version。"
		);
	}
	if (feedback.question_id !== current.question_id) {
		return "revise.feedback.question_id 必须与 current_question.question_id 一致。";
	}
	if (typeof feedback.target_version === "number" && feedback.target_version !== current.version) {
		return `revise.feedback.target_version 是 v${feedback.target_version}，current_question 是 v${current.version}。`;
	}
	return undefined;
}

function prepareRequest(
	operation: Operation,
	request: Record<string, unknown>,
): { request: Record<string, unknown> } | { error: string } {
	if (!isRecord(request)) {
		return { error: "request 必须是 JSON 对象。" };
	}
	if (operation === "author") {
		const normalized = normalizeAuthorRequest(request);
		const error = authorRequestError(normalized);
		return error === undefined ? { request: normalized } : { error };
	}
	const normalized = normalizeSubject(withRequestDefaults(request));
	const routingError =
		routeAuthoringFields(operation, normalized) ?? routeMissingDeterministicFields(operation, normalized);
	if (routingError !== undefined) return { error: routingError };
	if (operation === "revise") {
		const feedback = normalized.feedback;
		if (isRecord(feedback)) {
			// The review reports an `errors` array; revision feedback is about one
			// targeted repair, so keep the review's evidence but do not forward the
			// array as an unknown feedback field.
			const cleaned = { ...feedback };
			delete cleaned.errors;
			normalized.feedback = cleaned;
		}
		const error = reviseRequestError(normalized);
		if (error !== undefined) return { error };
	}
	return { request: normalized };
}

export default function questionGenerationExtension(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "question_generation",
		label: "Question generation",
		description:
			"Generate or revise 408 questions. Use operation=author for ANY natural-language, rough-topic, " +
			"material-driven, or arbitrary-syllabus request; it plans the topic and returns a versioned package. " +
			"single/comprehensive/batch/replenishment are deterministic template paths with fixed topics and " +
			"fields, not a general-purpose entry. This is the only tool allowed to create a new question version.",
		promptSnippet: "Generate or revise 408 questions and submit them for review",
		promptGuidelines: [
			"Routing: if the user names a topic in prose, asks for any 408 question, or supplies material, use author. Use single only with a fixed topic and exact fields from its contract; use comprehensive only for the fixed paging/stack templates; use batch only with explicit slots; use replenishment only with an assembly v1.0 plan.",
			'author fields: schema_version="0.1" and request_id are required. Optional: brief (≤2000 chars), seed, subject (data_structures | computer_organization | operating_systems | computer_networks), syllabus_areas, question_type (single_choice | comprehensive), total_score (comprehensive only, 2–30), requirements (1–8 strings), evidence (≤16 items). Unknown fields are rejected before any model call.',
			"Chinese subject names such as 数据结构/计组/操作系统/计网 are normalised to the four IDs; prefer the English IDs. syllabus_areas must be IDs: ds.foundations, ds.linear, ds.stack_queue_array, ds.trees, ds.graphs, ds.search, ds.sort, co.system, co.representation, co.memory, co.instructions, co.cpu, co.io, os.foundations, os.process, os.memory, os.files, os.io, cn.architecture, cn.physical, cn.link, cn.network, cn.transport, cn.application.",
			"single requires topic one of single_level_paging, stack_pop_sequence, direct_mapped_cache, ipv4_subnet_network_address, tcp_message_boundaries, plus seed and evidence rules. Any other topic must use author.",
			"revise requires the exact current_question package and feedback {feedback_id, question_id, target_version, part_id, action, comment}; general authoring uses action=repair, paging comprehensive uses action=replace plus replacement. Do not review or revise a version you did not receive from the service.",
			"When exam_checker returns NEEDS_REVISION, inspect its structured errors and autonomously decide whether a revision is warranted. Set feedback.feedback_id to exam_checker's review_id. Do not ask exam_checker to edit a question.",
			"Do not create an unbounded loop. Review at most v1, v2, and v3 for one question; if v3 is rejected, report that the autonomous attempt failed.",
			"Treat queued versions as pending independent review. The student_view is the student-facing content; keep instructor_view, pedagogy, self_check, generator, and authoring_report separate.",
			"For evidence-grounded reasoning questions, set request.constraints.authoring to {objective: analyze|diagnose|transfer|design, focus?: string}. This uses the configured model; batches support at most two authored items. Omit authoring for the deterministic generator.",
		],
		parameters,
		async execute(_id, { operation, request }, signal) {
			const prepared = prepareRequest(operation, request as Record<string, unknown>);
			if ("error" in prepared) {
				return invalidRequest(prepared.error, request as Record<string, unknown>);
			}
			const currentQuestion = prepared.request.current_question;
			const currentTaskId =
				operation === "revise" && isRecord(currentQuestion) && isText(currentQuestion.task_id)
					? currentQuestion.task_id
					: undefined;
			const requestWithTask = {
				...prepared.request,
				task_id:
					typeof prepared.request.task_id === "string"
						? prepared.request.task_id
						: (currentTaskId ?? crypto.randomUUID()),
			};
			const base = (process.env.QUESTION_GENERATION_SERVICE_URL || "http://127.0.0.1:8093").replace(/\/+$/, "");
			const defaultTimeout = operation === "batch" || operation === "replenishment" ? 1_200_000 : 600_000;
			let response: Response;
			try {
				const configuredTimeout = Number(process.env.QUESTION_GENERATION_TIMEOUT_MS || defaultTimeout);
				if (!Number.isInteger(configuredTimeout) || configuredTimeout < 1_000 || configuredTimeout > 1_800_000) {
					throw new Error("INVALID_QUESTION_GENERATION_TIMEOUT");
				}
				const timeout = AbortSignal.timeout(configuredTimeout);
				response = await fetch(`${base}/v1/question-generation/${operation}`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(requestWithTask),
					signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
				});
			} catch (error) {
				if (signal?.aborted) throw error;
				throw new Error("QUESTION_GENERATION_UNAVAILABLE");
			}
			let raw: string;
			try {
				raw = await response.text();
			} catch (error) {
				if (signal?.aborted) throw error;
				throw new Error("INVALID_QUESTION_GENERATION_RESPONSE");
			}
			let result: unknown;
			try {
				result = JSON.parse(raw);
			} catch {
				result = undefined;
			}
			if (!isQuestionGenerationResult(result)) {
				if (!response.ok) throw new Error(describeHttpFailure(response.status, result, raw));
				throw new Error(`INVALID_QUESTION_GENERATION_RESPONSE (${response.status})`);
			}
			return {
				content: [{ type: "text", text: JSON.stringify(result) }],
				details: result,
			};
		},
	});
}
