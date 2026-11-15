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
			"Generate or revise 408 questions and submit the successfully generated versions to the pending review queue. This is the only tool allowed to create a new question version.",
		promptSnippet: "Generate or revise 408 questions and submit them for review",
		promptGuidelines: [
			"Use single for one single-choice question, batch for scored slots, comprehensive for one structured problem, and revise for version-specific feedback.",
			"A new generation call receives one automatically generated task_id shared by every returned question. For revise, pass the existing task_id in request so the new version remains in the same task.",
			"When exam_checker returns NEEDS_REVISION, inspect its structured errors and autonomously decide whether a revision is warranted. If so, call this tool with operation=revise, the same task_id, the exact current_question package, and feedback targeting that version; set feedback.feedback_id to exam_checker's review_id. Then independently decide whether to review the returned version. Do not ask exam_checker to edit a question.",
			"Do not create an unbounded loop. Stop after at most three rejected generated versions for one question and report that the autonomous attempt failed.",
			"Send the structured request unchanged. Use pre-verified evidence supplied for the topic. Report missing evidence and batch deficits.",
			"Treat queued versions as pending independent review. The student_view is the student-facing content; keep instructor_view separate.",
		],
		parameters,
		async execute(_id, { operation, request }, signal) {
			const requestWithTask = {
				...request,
				task_id: typeof request.task_id === "string" ? request.task_id : crypto.randomUUID(),
			};
			const base = (process.env.QUESTION_GENERATION_SERVICE_URL || "http://127.0.0.1:8093").replace(/\/+$/, "");
			let response: Response;
			try {
				const timeout = AbortSignal.timeout(15_000);
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
