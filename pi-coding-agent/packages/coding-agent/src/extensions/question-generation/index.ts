import { Type } from "typebox";
import type { ExtensionAPI } from "../../core/extensions/types.ts";

const parameters = Type.Object({
	operation: Type.Union([
		Type.Literal("single"),
		Type.Literal("batch"),
		Type.Literal("comprehensive"),
		Type.Literal("revise"),
	]),
	request: Type.Record(Type.String(), Type.Unknown(), {
		description: "The structured question-generation request for the selected operation.",
	}),
});

export default function questionGenerationExtension(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "question_generation",
		label: "Question generation",
		description:
			"Generate or revise 408 questions and submit the successfully generated versions to the pending review queue.",
		promptSnippet: "Generate or revise 408 questions and submit them for review",
		promptGuidelines: [
			"Use single for one single-choice question, batch for scored slots, comprehensive for one structured problem, and revise for version-specific feedback.",
			"Send the structured request unchanged. Use pre-verified evidence supplied for the topic. Report missing evidence and batch deficits.",
			"Treat queued versions as pending independent review. The student_view is the student-facing content; keep instructor_view separate.",
		],
		parameters,
		async execute(_id, { operation, request }, signal) {
			const base = (process.env.QUESTION_GENERATION_SERVICE_URL || "http://127.0.0.1:8093").replace(/\/+$/, "");
			let response: Response;
			try {
				const timeout = AbortSignal.timeout(15_000);
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
			let result: unknown;
			try {
				result = await response.json();
			} catch (error) {
				if (signal?.aborted) throw error;
				throw new Error("INVALID_QUESTION_GENERATION_RESPONSE");
			}
			if (
				typeof result !== "object" ||
				result === null ||
				!("status" in result) ||
				typeof result.status !== "string" ||
				!("questions" in result) ||
				!Array.isArray(result.questions)
			) {
				throw new Error(`INVALID_QUESTION_GENERATION_RESPONSE (${response.status})`);
			}
			return {
				content: [{ type: "text", text: JSON.stringify(result) }],
				details: result,
			};
		},
	});
}
