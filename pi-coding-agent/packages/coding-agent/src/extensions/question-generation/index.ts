import { Type } from "typebox";
import type { ExtensionAPI } from "../../core/extensions/types.ts";

const parameters = Type.Object({
	operation: Type.Union([
		Type.Literal("single"),
		Type.Literal("batch"),
		Type.Literal("replenishment"),
		Type.Literal("comprehensive"),
		Type.Literal("revise"),
		Type.Literal("author"),
	]),
	request: Type.Record(Type.String(), Type.Unknown(), {
		description: "The structured question-generation request for the selected operation.",
	}),
});

const DETAIL_LIMIT = 500;

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

export default function questionGenerationExtension(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "question_generation",
		label: "Question generation",
		description:
			"Generate or revise 408 questions, including exam assembly supplements, and queue successful versions for review.",
		promptSnippet: "Generate or revise 408 questions and submit them for review",
		promptGuidelines: [
			"Use single for one single-choice question, batch for scored slots, comprehensive for one structured problem, and revise for version-specific feedback.",
			"Use author for one reasoning question when the user gives a rough topic, materials, or asks for any 408 question. Send schema_version: '0.1', request_id, and the user's brief when provided. Omit brief for an unrestricted 408 question. Preserve explicitly requested subject, syllabus_areas, question_type, total_score, and requirements. Put supplied material in evidence entries with id, source, version, anchor, summary, rules: [], and excerpt when available. The service chooses the specific topic, learning objective, and question type when unspecified.",
			"Keep the supplied material's wording in excerpt. Label material with no known provenance as user-provided, and split long material into excerpts of at most 12,000 characters.",
			"Use replenishment for an exam assembly v1.0 joint shortage plan. Send it unchanged as request.replenishment_request with a seed and slot_profiles keyed by assembly-1, assembly-2, and so on. Use only supplied topic mappings.",
			"Use supplied evidence or omit evidence for configured knowledge-base lookup. Report remaining deficits and queue receipts, including partial success.",
			"Treat queued versions as pending independent review. The student_view is the student-facing content; keep instructor_view, pedagogy, self_check, generator, and authoring_report separate.",
			"For evidence-grounded reasoning questions, set request.constraints.authoring to {objective: analyze|diagnose|transfer|design, focus?: string}. This uses the configured model; batches support at most two authored items. Omit authoring for the deterministic generator.",
		],
		parameters,
		async execute(_id, { operation, request }, signal) {
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
					body: JSON.stringify(request),
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
