import { Type } from "typebox";
import type { ExtensionAPI } from "../../core/extensions/types.ts";

export const assemblyParameters = Type.Object(
	{
		schema_version: Type.Optional(Type.Union([Type.Literal("1.0"), Type.Literal("2.0")])),
		request_id: Type.String({ minLength: 1, maxLength: 200 }),
		subject: Type.String({ minLength: 1 }),
		question_count: Type.Integer({ minimum: 1, maximum: 100 }),
		total_score: Type.Integer({ minimum: 1 }),
		question_type_counts: Type.Optional(
			Type.Record(Type.String(), Type.Integer({ minimum: 0 }), {
				description:
					"Question count per type; sum equals question_count. Currently only single_choice is supported.",
			}),
		),
		question_type_scores: Type.Optional(
			Type.Record(Type.String(), Type.Integer({ minimum: 1 }), {
				description:
					"Per-question score for each type. Same keys as question_type_counts; sum(count * score) equals total_score.",
			}),
		),
		knowledge_point_counts: Type.Optional(
			Type.Record(Type.String(), Type.Integer({ minimum: 0 }), {
				description:
					"Exact bank knowledge-point labels. Each question fills one topic quota even with multiple labels.",
			}),
		),
		difficulty_counts: Type.Optional(
			Type.Object(
				{
					easy: Type.Integer({ minimum: 0 }),
					medium: Type.Integer({ minimum: 0 }),
					hard: Type.Integer({ minimum: 0 }),
				},
				{ additionalProperties: false },
			),
		),
		slots: Type.Optional(
			Type.Array(
				Type.Object(
					{
						subject: Type.String({ minLength: 1 }),
						question_type: Type.Union([Type.Literal("single_choice"), Type.Literal("comprehensive")]),
						score: Type.Integer({ minimum: 1, maximum: 150 }),
						knowledge_point: Type.Optional(Type.String({ minLength: 1 })),
						difficulty: Type.Optional(
							Type.Union([Type.Literal("easy"), Type.Literal("medium"), Type.Literal("hard")]),
						),
						part_scores: Type.Optional(Type.Array(Type.Integer({ minimum: 1 }), { maxItems: 20 })),
					},
					{ additionalProperties: false },
				),
				{ minItems: 1, maxItems: 100 },
			),
		),
		max_repair_rounds: Type.Optional(Type.Integer({ minimum: 0, maximum: 10 })),
		semantic_review: Type.Optional(Type.Boolean()),
		semantic_max_calls: Type.Optional(Type.Integer({ minimum: 0, maximum: 100 })),
		similarity_search_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 128 })),
		export_pdf: Type.Optional(Type.Boolean()),
		similarity_decisions: Type.Optional(
			Type.Array(
				Type.Object(
					{
						pair_id: Type.String({ pattern: "^[0-9a-f]{24}$" }),
						question_ids: Type.Array(Type.String(), { minItems: 2, maxItems: 2 }),
						content_hashes: Type.Array(Type.String({ pattern: "^[0-9a-f]{64}$" }), { minItems: 2, maxItems: 2 }),
						source: Type.Literal("human"),
						reviewer: Type.String({ minLength: 1 }),
						verdict: Type.Union([
							Type.Literal("DISTINCT"),
							Type.Literal("DUPLICATE"),
							Type.Literal("UNRESOLVED"),
						]),
						reason: Type.String({ minLength: 1 }),
					},
					{ additionalProperties: false },
				),
				{ maxItems: 5000 },
			),
		),
	},
	{ additionalProperties: false },
);

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

// The authoring tools use 408 syllabus IDs; the question bank and assembly use
// Chinese subject labels. Normalising here keeps one vocabulary at the boundary
// instead of making the model guess which spelling a slot needs.
const SUBJECT_ALIASES: Record<string, string> = {
	data_structures: "数据结构",
	data_structure: "数据结构",
	数据结构: "数据结构",
	computer_organization: "计算机组成原理",
	计算机组成原理: "计算机组成原理",
	operating_systems: "操作系统",
	operating_system: "操作系统",
	操作系统: "操作系统",
	computer_networks: "计算机网络",
	computer_network: "计算机网络",
	计算机网络: "计算机网络",
};

function bankSubject(value: unknown): unknown {
	return typeof value === "string" ? (SUBJECT_ALIASES[value.trim()] ?? value) : value;
}

function withBankSubjects(params: Record<string, unknown>): Record<string, unknown> {
	const copy = { ...params };
	copy.subject = bankSubject(copy.subject);
	if (Array.isArray(copy.slots)) {
		copy.slots = copy.slots.map((slot) => (isRecord(slot) ? { ...slot, subject: bankSubject(slot.subject) } : slot));
	}
	return copy;
}

export default function examAssemblyExtension(pi: ExtensionAPI): void {
	pi.registerTool<typeof assemblyParameters, { result: Record<string, unknown> }>({
		name: "exam_assembly",
		label: "exam assembly",
		description:
			"Assemble single-choice or mixed-subject comprehensive papers from the accepted PostgreSQL Question Bank API. Verifies current PASS and source versions. Returns separate student exam, teacher answers and report paths. No mock fallback or arbitrary SQL.",
		promptSnippet: "Assemble exams from accepted bank questions or report missing requirements",
		promptGuidelines: [
			"V2 semantic_review=true requests all selected pairs (including materials and subquestions) be reviewed. Model review is disabled server-side by default and may incur API costs when enabled; obtain explicit user approval and a semantic_max_calls budget before requesting model review. Confirmed duplicates trigger bounded replacement without changing scores or quotas. Budget exhaustion, uncertain verdicts and search limits never mean semantic pass. Model findings are not human review; never fabricate source=human decisions. V1 does not accept semantic_review or semantic budget fields.",
			"Preserve all user quotas. Do not invent questions, answers, bank labels or successful results. For v2, omitted topic/difficulty/part_scores means unrestricted; do not invent exact quotas the user did not request.",
			"For v1 use question_type_counts, question_type_scores and knowledge_point_counts. Each quota dimension sums to question_count; sum(type count * type score) equals total_score. Each question fills one knowledge-point quota.",
			"Only STRUCTURAL_PASS means assembly completed. NEEDS_QUESTIONS reports shortages, INVALID_REQUEST requires correcting quotas, UNRESOLVED is inconclusive, TOOL_ERROR means failure. Never report those statuses as success.",
			"The production tool uses real accepted bank entries only. Do not load development JSON, fabricate PASS reviews or use -e to load the old development extension.",
			"For mixed subjects, comprehensive questions or different scores use schema_version=2.0 and ordered slots, each with subject, question_type, score and optional knowledge_point/difficulty/part_scores. Slots count and score sum must match question_count/total_score. Do not send legacy quota maps or max_repair_rounds with v2. Put 40 choice slots before comprehensive slots for a 408-style paper. Scores must match originals; never rescale. v2 exports HTML (export_pdf=false), printable as PDF. Bad records are skipped and reported. Old comprehensive snapshots lacking structured parts/grading require a new authored version and independent review; never overwrite an immutable version.",
			"Return the separate student/answer artifact paths. Structural checks do not certify semantic uniqueness or absence of cross-question clues.",
			"UNRESOLVED with similarity_review.status=NEEDS_REVIEW requires human review. Return the teacher-only review packet and decisions template paths. Never invent a human reviewer, reason or verdict. Only forward explicit human decisions with their original question IDs and content hashes; changed content invalidates old decisions.",
			"On NEEDS_QUESTIONS, return deficits and the replenishment_request artifact when present. V2 deficits identify unfilled ordered slots in one partial assignment. Joint deficits are a proposed completion, not unique mandatory cells. Do not add them to marginal deficits or claim a minimum unless minimum_count_proven is true. Newly supplied questions must independently pass review and enter the bank before reassembly.",
		],
		parameters: assemblyParameters,
		executionMode: "sequential",
		async execute(_toolCallId, params, signal) {
			let httpStatus: number | undefined;
			try {
				const seconds = Number(process.env.EXAM_ASSEMBLY_TIMEOUT_SECONDS ?? "180");
				if (!Number.isFinite(seconds) || seconds <= 0 || seconds > 3600) {
					throw new Error("Invalid EXAM_ASSEMBLY_TIMEOUT_SECONDS");
				}
				const timeout = AbortSignal.timeout(Math.ceil(seconds * 1000));
				const payload = withBankSubjects(params as Record<string, unknown>);
				const response = await fetch(
					`${(process.env.EXAM_ASSEMBLY_SERVICE_URL || "http://127.0.0.1:8092").replace(/\/$/, "")}/v1/exam-assembly/assemble`,
					{
						method: "POST",
						headers: { "content-type": "application/json" },
						body: JSON.stringify(payload),
						signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
					},
				);
				httpStatus = response.status;
				const text = await response.text();
				let body: unknown;
				try {
					body = JSON.parse(text);
				} catch {
					body = { detail: text.slice(0, 2000) };
				}
				const statuses = ["STRUCTURAL_PASS", "NEEDS_QUESTIONS", "INVALID_REQUEST", "UNRESOLVED", "TOOL_ERROR"];
				const valid = isRecord(body) && typeof body.status === "string" && statuses.includes(body.status);
				const validSuccess =
					isRecord(body) &&
					(body.status !== "STRUCTURAL_PASS" ||
						(body.mode === "POSTGRES_QUESTION_BANK_API" &&
							isRecord(body.validation) &&
							body.validation.passed === true &&
							isRecord(body.artifacts) &&
							typeof body.artifacts.student_exam_html === "string" &&
							typeof body.artifacts.answer_key_html === "string" &&
							typeof body.artifacts.report === "string"));
				const rejectedRequest = !response.ok && httpStatus !== undefined && httpStatus >= 400 && httpStatus < 500;
				const output =
					response.ok && valid && validSuccess && isRecord(body)
						? { ...body, http_status: httpStatus }
						: rejectedRequest
							? {
									status: "INVALID_REQUEST",
									error_code: "INVALID_EXAM_ASSEMBLY_REQUEST",
									http_status: httpStatus,
									detail: isRecord(body) && "detail" in body ? body.detail : body,
									service_response: body,
								}
							: {
									status: "TOOL_ERROR",
									error_code: response.ok ? "INVALID_EXAM_ASSEMBLY_RESPONSE" : "EXAM_ASSEMBLY_UNAVAILABLE",
									http_status: httpStatus,
									detail: isRecord(body) && "detail" in body ? body.detail : body,
									service_response: body,
								};
				return {
					content: [{ type: "text", text: JSON.stringify(output) }],
					details: { result: output },
					isError: output.status === "TOOL_ERROR",
				};
			} catch (error) {
				const output = {
					status: "TOOL_ERROR",
					error_code:
						error instanceof Error && error.name === "TimeoutError"
							? "EXAM_ASSEMBLY_TIMEOUT"
							: signal?.aborted
								? "EXAM_ASSEMBLY_CANCELLED"
								: "EXAM_ASSEMBLY_UNAVAILABLE",
					http_status: httpStatus,
					detail: error instanceof Error ? error.message : "Unknown transport error",
				};
				return {
					content: [{ type: "text", text: JSON.stringify(output) }],
					details: { result: output },
					isError: true,
				};
			}
		},
	});
}
