import { readFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { Type } from "typebox";
import type { ExtensionAPI } from "../../core/extensions/types.ts";

const examCheckerParameters = Type.Object({
	operation: Type.Union(
		[
			Type.Literal("review_file"),
			Type.Literal("review_document"),
			Type.Literal("review_question"),
			Type.Literal("get_question_state"),
		],
		{
			description:
				"Choose review_file for an original PDF/DOC/DOCX, review_document for every question in a parsed document, review_question for one immutable question version, or get_question_state to read its latest version and workflow state.",
		},
	),
	file_path: Type.Optional(
		Type.String({ description: "Original PDF, DOC, or DOCX path. Required only for review_file." }),
	),
	document_id: Type.Optional(
		Type.String({ description: "Parsed exam document ID. Required only for review_document." }),
	),
	task_id: Type.Optional(
		Type.String({ description: "Question task ID returned by question_generation or document parsing." }),
	),
	question_id: Type.Optional(
		Type.String({ description: "Question node ID. Required for review_question and get_question_state." }),
	),
	version: Type.Optional(
		Type.Integer({
			minimum: 1,
			description: "Exact immutable question version; omit to review the current version.",
		}),
	),
});

const questionBankParameters = Type.Object({
	operation: Type.Union([Type.Literal("get_question"), Type.Literal("search_questions")], {
		description:
			"Choose get_question to load one accepted question by record_id, or search_questions to query accepted questions through bounded filters.",
	}),
	record_id: Type.Optional(Type.String({ description: "Question-bank record ID. Required only for get_question." })),
	subject: Type.Optional(Type.String({ description: "Exact subject filter for search_questions." })),
	question_type: Type.Optional(Type.String({ description: "Exact question-type filter for search_questions." })),
	difficulty: Type.Optional(
		Type.Union([Type.Literal("easy"), Type.Literal("medium"), Type.Literal("hard")], {
			description: "Exact difficulty filter for search_questions.",
		}),
	),
	knowledge_point: Type.Optional(Type.String({ description: "Exact knowledge-point filter for search_questions." })),
	keyword: Type.Optional(Type.String({ description: "Case-insensitive substring filter on question_text." })),
	limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100, description: "Maximum results; defaults to 20." })),
});

export type ExamCheckerStatus = "PASS" | "NEEDS_REVISION" | "UNRESOLVED";

export interface CompactReviewError {
	error_type: string;
	position?: string;
	original_text?: string;
	correction?: string;
	description?: string;
	suggestion?: string;
	severity?: string;
}

export interface UnresolvedCheck {
	task_id: string;
	attempts: number;
	error_code: string;
	retryable: boolean;
}

export interface IngestionResult {
	status: "STORED" | "FAILED" | "SKIPPED";
	record_id?: string;
	error_code?: string;
}

export interface CompactExamCheckerResult {
	task_id: string;
	question_id: string;
	question_number: string;
	version: number;
	review_id: string;
	status: ExamCheckerStatus;
	errors: CompactReviewError[];
	unresolved_checks: UnresolvedCheck[];
	ingestion?: IngestionResult;
}

export interface CompactDocumentReviewResult {
	document_id: string;
	status: ExamCheckerStatus;
	questions: CompactExamCheckerResult[];
}

type ExamCheckerErrorCode =
	| "EXAM_CHECKER_UNAVAILABLE"
	| "EXAM_CHECKER_REQUEST_REJECTED"
	| "EXAM_FILE_UNAVAILABLE"
	| "INVALID_EXAM_CHECKER_INPUT"
	| "INVALID_EXAM_CHECKER_RESPONSE";

type QuestionBankErrorCode =
	| "QUESTION_BANK_UNAVAILABLE"
	| "QUESTION_BANK_REQUEST_REJECTED"
	| "INVALID_QUESTION_BANK_INPUT"
	| "INVALID_QUESTION_BANK_RESPONSE";

export interface ExamCheckerToolDetails {
	fullReview?: unknown;
	parsedDocument?: unknown;
	error?: {
		code: ExamCheckerErrorCode;
		status?: number;
		detail?: unknown;
	};
}

export interface QuestionBankToolDetails {
	fullResult?: unknown;
	error?: {
		code: QuestionBankErrorCode;
		status?: number;
	};
}

class ExamCheckerToolError extends Error {
	readonly code: ExamCheckerErrorCode;
	readonly status: number | undefined;
	readonly detail: unknown;

	constructor(code: ExamCheckerErrorCode, status?: number, detail?: unknown) {
		super(code);
		this.code = code;
		this.status = status;
		this.detail = detail;
	}
}

class QuestionBankToolError extends Error {
	readonly code: QuestionBankErrorCode;
	readonly status: number | undefined;

	constructor(code: QuestionBankErrorCode, status?: number) {
		super(code);
		this.code = code;
		this.status = status;
	}
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(record: Record<string, unknown>, key: string): string {
	const value = record[key];
	if (typeof value !== "string" || value.length === 0) {
		throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
	}
	return value;
}

function optionalString(record: Record<string, unknown>, key: string): string | undefined {
	const value = record[key];
	return typeof value === "string" && value.length > 0 ? value : undefined;
}

function reviewStatus(record: Record<string, unknown>): ExamCheckerStatus {
	const status = requiredString(record, "status");
	if (status !== "PASS" && status !== "NEEDS_REVISION" && status !== "UNRESOLVED") {
		throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
	}
	return status;
}

function compactError(value: unknown): CompactReviewError {
	if (!isRecord(value)) throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
	return {
		error_type: requiredString(value, "error_type"),
		...(optionalString(value, "position") ? { position: optionalString(value, "position") } : {}),
		...(optionalString(value, "original_text") ? { original_text: optionalString(value, "original_text") } : {}),
		...(optionalString(value, "correction") ? { correction: optionalString(value, "correction") } : {}),
		...(optionalString(value, "description") ? { description: optionalString(value, "description") } : {}),
		...(optionalString(value, "suggestion") ? { suggestion: optionalString(value, "suggestion") } : {}),
		...(optionalString(value, "severity") ? { severity: optionalString(value, "severity") } : {}),
	};
}

function compactUnresolvedCheck(value: unknown): UnresolvedCheck | undefined {
	if (!isRecord(value) || value.execution_status !== "FAILED") return undefined;
	return {
		task_id: requiredString(value, "task_id"),
		attempts: typeof value.attempts === "number" ? value.attempts : 1,
		error_code: optionalString(value, "error_code") ?? "SPECIALIST_FAILED",
		retryable: value.retryable === true,
	};
}

function compactIngestion(value: unknown): IngestionResult | undefined {
	if (!isRecord(value)) return undefined;
	const status = value.status;
	if (status !== "STORED" && status !== "FAILED" && status !== "SKIPPED") return undefined;
	return {
		status,
		...(optionalString(value, "record_id") ? { record_id: optionalString(value, "record_id") } : {}),
		...(optionalString(value, "error_code") ? { error_code: optionalString(value, "error_code") } : {}),
	};
}

export function compactReviewResult(value: unknown): CompactExamCheckerResult {
	if (!isRecord(value) || !isRecord(value.review)) {
		throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
	}
	const review = value.review;
	if (!isRecord(review.summary) || !Array.isArray(review.summary.errors) || !Array.isArray(review.checks)) {
		throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
	}

	const unresolvedChecks = review.checks
		.map(compactUnresolvedCheck)
		.filter((check): check is UnresolvedCheck => check !== undefined);
	const ingestion = compactIngestion(value.ingestion);
	return {
		task_id: requiredString(value, "task_id"),
		question_id: requiredString(value, "question_id"),
		question_number: requiredString(value, "question_number"),
		version:
			typeof value.version === "number"
				? value.version
				: (() => {
						throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
					})(),
		review_id: requiredString(value, "review_id"),
		status: reviewStatus(review),
		errors: review.summary.errors.map(compactError),
		unresolved_checks: unresolvedChecks,
		...(ingestion ? { ingestion } : {}),
	};
}

export function compactDocumentReviewResult(value: unknown): CompactDocumentReviewResult {
	if (!isRecord(value) || !Array.isArray(value.questions)) {
		throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
	}
	return {
		document_id: requiredString(value, "document_id"),
		status: reviewStatus(value),
		questions: value.questions.map(compactReviewResult),
	};
}

function serviceUrl(): string {
	return (process.env.EXAM_CHECKER_SERVICE_URL || "http://127.0.0.1:8091").replace(/\/$/, "");
}

async function responseErrorDetail(response: Response): Promise<unknown> {
	const text = await response.text();
	if (!text) return undefined;
	try {
		const body: unknown = JSON.parse(text);
		return isRecord(body) && "detail" in body ? body.detail : body;
	} catch {
		return text.slice(0, 2000);
	}
}

async function requestJson(url: string, init: RequestInit): Promise<unknown> {
	let response: Response;
	try {
		response = await fetch(url, init);
	} catch {
		throw new ExamCheckerToolError("EXAM_CHECKER_UNAVAILABLE");
	}
	if (!response.ok) {
		const code =
			response.status >= 400 && response.status < 500 ? "EXAM_CHECKER_REQUEST_REJECTED" : "EXAM_CHECKER_UNAVAILABLE";
		throw new ExamCheckerToolError(code, response.status, await responseErrorDetail(response));
	}
	try {
		return await response.json();
	} catch {
		throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
	}
}

async function requestQuestionBankJson(url: string, init: RequestInit): Promise<unknown> {
	let response: Response;
	try {
		response = await fetch(url, init);
	} catch {
		throw new QuestionBankToolError("QUESTION_BANK_UNAVAILABLE");
	}
	if (!response.ok) {
		const code =
			response.status >= 400 && response.status < 500
				? "QUESTION_BANK_REQUEST_REJECTED"
				: "QUESTION_BANK_UNAVAILABLE";
		throw new QuestionBankToolError(code, response.status);
	}
	try {
		return await response.json();
	} catch {
		throw new QuestionBankToolError("INVALID_QUESTION_BANK_RESPONSE");
	}
}

function questionBankEntry(value: unknown): Record<string, unknown> {
	if (!isRecord(value) || !isRecord(value.question_json)) {
		throw new QuestionBankToolError("INVALID_QUESTION_BANK_RESPONSE");
	}
	const recordId = value.record_id;
	const taskId = value.task_id;
	const questionId = value.question_id;
	const version = value.version;
	if (
		typeof recordId !== "string" ||
		recordId.length === 0 ||
		typeof taskId !== "string" ||
		taskId.length === 0 ||
		typeof questionId !== "string" ||
		questionId.length === 0 ||
		typeof version !== "number"
	) {
		throw new QuestionBankToolError("INVALID_QUESTION_BANK_RESPONSE");
	}
	return {
		record_id: recordId,
		task_id: taskId,
		question_id: questionId,
		version,
		question_json: value.question_json,
	};
}

function requireOnly(value: string | undefined, forbidden: unknown[]): string {
	if (!value || forbidden.some((item) => item !== undefined)) {
		throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_INPUT");
	}
	return value;
}

export default function examCheckerExtension(pi: ExtensionAPI): void {
	pi.registerTool<typeof examCheckerParameters, ExamCheckerToolDetails>({
		name: "exam_checker",
		label: "exam checker",
		description:
			"Parse and review exams, review one immutable generated-question version, or read review state. This tool never creates or edits question versions.",
		promptSnippet: "Parse, review, or inspect immutable exam-question versions",
		promptGuidelines: [
			"Use review_file for an original PDF, DOC, or DOCX; review_document for every question in a document_id; use task_id and question_id for review_question and get_question_state. Reuse the task_id returned by question_generation.",
			"This tool has no authority to create or edit a question version. When a generated question returns NEEDS_REVISION, reason over its structured errors and independently decide whether to call question_generation with operation=revise for the same task and exact version; use the returned review_id as feedback.feedback_id.",
			"Treat exam_checker.status as the sole review decision: PASS is eligible for automatic ingestion; NEEDS_REVISION must be returned to the user with the reported errors; UNRESOLVED means review is incomplete.",
			"For UNRESOLVED results, report unresolved_checks and never claim that the question or document passed.",
			"Do not override exam_checker.status or invent errors that are absent from its result.",
		],
		parameters: examCheckerParameters,
		executionMode: "parallel",
		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			try {
				if (params.operation === "get_question_state") {
					const taskId = requireOnly(params.task_id, [params.file_path, params.document_id, params.version]);
					if (!params.question_id) throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_INPUT");
					const fullReview = await requestJson(
						`${serviceUrl()}/v1/exam-checker/tasks/${encodeURIComponent(taskId)}/questions/${encodeURIComponent(params.question_id)}/state`,
						{ method: "GET", signal },
					);
					if (!isRecord(fullReview)) {
						throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
					}
					return {
						content: [{ type: "text", text: JSON.stringify(fullReview) }],
						details: { fullReview },
					};
				}

				if (params.operation === "review_question") {
					const taskId = requireOnly(params.task_id, [params.file_path, params.document_id]);
					if (!params.question_id) throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_INPUT");
					const fullReview = await requestJson(
						`${serviceUrl()}/v1/exam-checker/tasks/${encodeURIComponent(taskId)}/questions/${encodeURIComponent(params.question_id)}/review`,
						{
							method: "POST",
							headers: { "content-type": "application/json" },
							body: JSON.stringify({
								...(params.version ? { version: params.version } : {}),
								idempotency_key: toolCallId,
							}),
							signal,
						},
					);
					return {
						content: [{ type: "text", text: JSON.stringify(compactReviewResult(fullReview)) }],
						details: { fullReview },
					};
				}

				let documentId: string;
				let parsedDocument: unknown;
				if (params.operation === "review_file") {
					const filePath = requireOnly(params.file_path, [
						params.document_id,
						params.question_id,
						params.task_id,
						params.version,
					]);
					const absolutePath = resolve(ctx.cwd, filePath);
					let bytes: Uint8Array;
					try {
						bytes = new Uint8Array(await readFile(absolutePath));
					} catch {
						throw new ExamCheckerToolError("EXAM_FILE_UNAVAILABLE");
					}
					const form = new FormData();
					form.append("file", new Blob([bytes]), basename(absolutePath));
					parsedDocument = await requestJson(`${serviceUrl()}/v1/exam-checker/documents/parse`, {
						method: "POST",
						body: form,
						signal,
					});
					if (!isRecord(parsedDocument)) {
						throw new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
					}
					documentId = requiredString(parsedDocument, "document_id");
				} else {
					documentId = requireOnly(params.document_id, [
						params.file_path,
						params.question_id,
						params.task_id,
						params.version,
					]);
				}

				const fullReview = await requestJson(
					`${serviceUrl()}/v1/exam-checker/documents/${encodeURIComponent(documentId)}/review`,
					{ method: "POST", signal },
				);
				return {
					content: [{ type: "text", text: JSON.stringify(compactDocumentReviewResult(fullReview)) }],
					details: parsedDocument === undefined ? { fullReview } : { fullReview, parsedDocument },
				};
			} catch (error) {
				const known =
					error instanceof ExamCheckerToolError
						? error
						: new ExamCheckerToolError("INVALID_EXAM_CHECKER_RESPONSE");
				return {
					content: [
						{
							type: "text",
							text: JSON.stringify({
								error: known.code,
								...(known.status !== undefined ? { status: known.status } : {}),
								...(known.detail !== undefined ? { detail: known.detail } : {}),
							}),
						},
					],
					details: {
						error: {
							code: known.code,
							...(known.status !== undefined ? { status: known.status } : {}),
							...(known.detail !== undefined ? { detail: known.detail } : {}),
						},
					},
					isError: true,
				};
			}
		},
	});

	pi.registerTool<typeof questionBankParameters, QuestionBankToolDetails>({
		name: "question_bank",
		label: "question bank",
		description:
			"Read accepted questions from the shared question bank by record ID or bounded metadata and text filters.",
		promptSnippet: "Read or search accepted questions in the shared question bank",
		promptGuidelines: [
			"Use get_question when a question-bank record_id is known; use search_questions to find accepted questions by subject, question type, difficulty, knowledge point, or question-text keyword.",
			"Treat returned question_json as the complete stored question record. Do not invent fields or assume that omitted search results exist.",
			"This tool is read-only. Use exam_checker for review and workflow state; only question_generation may create a revised question version.",
		],
		parameters: questionBankParameters,
		executionMode: "parallel",
		async execute(_toolCallId, params, signal) {
			try {
				let fullResult: unknown;
				if (params.operation === "get_question") {
					if (
						!params.record_id ||
						params.subject !== undefined ||
						params.question_type !== undefined ||
						params.difficulty !== undefined ||
						params.knowledge_point !== undefined ||
						params.keyword !== undefined ||
						params.limit !== undefined
					) {
						throw new QuestionBankToolError("INVALID_QUESTION_BANK_INPUT");
					}
					fullResult = await requestQuestionBankJson(
						`${serviceUrl()}/v1/question-bank/${encodeURIComponent(params.record_id)}`,
						{ method: "GET", signal },
					);
					fullResult = questionBankEntry(fullResult);
				} else {
					if (params.record_id !== undefined) {
						throw new QuestionBankToolError("INVALID_QUESTION_BANK_INPUT");
					}
					const query = new URLSearchParams();
					if (params.subject) query.set("subject", params.subject);
					if (params.question_type) query.set("question_type", params.question_type);
					if (params.difficulty) query.set("difficulty", params.difficulty);
					if (params.knowledge_point) query.set("knowledge_point", params.knowledge_point);
					if (params.keyword) query.set("keyword", params.keyword);
					if (params.limit !== undefined) query.set("limit", String(params.limit));
					const response = await requestQuestionBankJson(
						`${serviceUrl()}/v1/question-bank/search${query.size > 0 ? `?${query}` : ""}`,
						{ method: "GET", signal },
					);
					if (!isRecord(response) || !Array.isArray(response.questions)) {
						throw new QuestionBankToolError("INVALID_QUESTION_BANK_RESPONSE");
					}
					fullResult = { questions: response.questions.map(questionBankEntry) };
				}
				return {
					content: [{ type: "text", text: JSON.stringify(fullResult) }],
					details: { fullResult },
				};
			} catch (error) {
				const known =
					error instanceof QuestionBankToolError
						? error
						: new QuestionBankToolError("INVALID_QUESTION_BANK_RESPONSE");
				return {
					content: [{ type: "text", text: JSON.stringify({ error: known.code }) }],
					details: { error: { code: known.code, ...(known.status ? { status: known.status } : {}) } },
					isError: true,
				};
			}
		},
	});
}
