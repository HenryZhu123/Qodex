import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai";
import { afterEach, expect, it, vi } from "vitest";
import { builtInExtensions } from "../../src/extensions/index.ts";
import { createHarness, getMessageText, type Harness } from "./harness.ts";

let harness: Harness | undefined;

afterEach(() => {
	harness?.cleanup();
	harness = undefined;
	vi.unstubAllGlobals();
	vi.unstubAllEnvs();
});

const question = {
	document_id: "pending-req-import",
	question_id: "authored-deadbeef-v1",
	question_number: "1",
	question_type: "single_choice",
	question_text: "循环队列的队头到队尾元素序列是什么？",
	options: ["A. a,b", "B. a,b,c", "C. b,c", "D. c"],
	answer_text: "a,b,c",
	points: 2,
	subject: "数据结构",
	paper_title: "Qodex 待审题包 pending-req-import",
	section_titles: ["栈、队列与数组"],
	numbering_path: [],
	numbering_description: "Qodex 生成待审题",
	reference: "",
};

const receipt = {
	document_id: "pending-req-import",
	imported: 1,
	questions: [
		{
			question_id: "authored-deadbeef-v1",
			question_number: "1",
			question_version_id: "3f6c1e0e-6d1a-4c1e-9d57-0f0f0f0f0f0f",
		},
	],
};

it("registers authored question views so the normal review path can run", async () => {
	vi.stubEnv("EXAM_CHECKER_SERVICE_URL", "http://127.0.0.1:8091");
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json(receipt));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({
		extensionFactories: builtInExtensions.filter((extension) => extension.name === "exam-checker"),
	});
	harness.setResponses([
		fauxAssistantMessage(
			fauxToolCall("exam_checker", {
				operation: "import_questions",
				document_id: "pending-req-import",
				paper_title: "Qodex 待审题包 pending-req-import",
				subject_label: "数据结构",
				questions: [question],
			}),
			{ stopReason: "toolUse" },
		),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("Register this authored question for review.");

	expect(fetchStub).toHaveBeenCalledOnce();
	expect(fetchStub.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8091/v1/exam-checker/documents/import");
	const body = JSON.parse(String(fetchStub.mock.calls[0]?.[1]?.body));
	expect(body).toEqual({
		document_id: "pending-req-import",
		paper_title: "Qodex 待审题包 pending-req-import",
		subject: "数据结构",
		questions: [question],
	});
	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(JSON.parse(getMessageText(result))).toEqual(receipt);
});

it("refuses an import that mixes in a review-only parameter", async () => {
	const fetchStub = vi.fn<typeof fetch>();
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({
		extensionFactories: builtInExtensions.filter((extension) => extension.name === "exam-checker"),
	});
	harness.setResponses([
		fauxAssistantMessage(
			fauxToolCall("exam_checker", {
				operation: "import_questions",
				document_id: "pending-req-import",
				question_id: "authored-deadbeef-v1",
				questions: [question],
			}),
			{ stopReason: "toolUse" },
		),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("Register this question.");

	expect(fetchStub).not.toHaveBeenCalled();
	// The extension returns a structured error payload without setting isError; the
	// workflow guardrail is what promotes it to an error observation.
	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(JSON.parse(getMessageText(result))).toMatchObject({ error: "INVALID_EXAM_CHECKER_INPUT" });
});

it("refuses an import without any question views", async () => {
	const fetchStub = vi.fn<typeof fetch>();
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({
		extensionFactories: builtInExtensions.filter((extension) => extension.name === "exam-checker"),
	});
	harness.setResponses([
		fauxAssistantMessage(
			fauxToolCall("exam_checker", { operation: "import_questions", document_id: "pending-req-import" }),
			{ stopReason: "toolUse" },
		),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("Register an empty batch.");

	expect(fetchStub).not.toHaveBeenCalled();
	// The extension returns a structured error payload without setting isError; the
	// workflow guardrail is what promotes it to an error observation.
	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(JSON.parse(getMessageText(result))).toMatchObject({ error: "INVALID_EXAM_CHECKER_INPUT" });
});
