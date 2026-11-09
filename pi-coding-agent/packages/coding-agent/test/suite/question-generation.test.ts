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

it("sends the joint shortage plan unchanged and preserves partial replenishment results", async () => {
	vi.stubEnv("QUESTION_GENERATION_SERVICE_URL", "http://127.0.0.1:8093");
	const request = {
		seed: 42,
		replenishment_request: {
			schema_version: "1.0",
			request_id: "joint-gap",
			plan_status: "PROPOSED_NOT_EXECUTED",
			scope: "CURRENT_VERIFIED_CANDIDATE_POOL",
			suggested_additional_count: 2,
			deficits: [
				{
					subject: "数据结构",
					knowledge_point: "栈",
					question_type: "single_choice",
					difficulty: "hard",
					score_per_question: 2,
					missing_count: 1,
				},
				{
					subject: "数据结构",
					knowledge_point: "队列",
					question_type: "single_choice",
					difficulty: "hard",
					score_per_question: 2,
					missing_count: 1,
				},
			],
			avoid_stems: ["已保留的题干"],
		},
		slot_profiles: { "assembly-1": { topic: "stack_pop_sequence" } },
	};
	const response = {
		status: "PARTIAL",
		assembly_request_id: "joint-gap",
		questions: [{ question_id: "stack-demo", version: 1, review_status: "PENDING" }],
		queue_receipts: [{ question_id: "stack-demo", version: 1, status: "QUEUED" }],
		deficits: [{ slot_id: "assembly-2", missing_count: 1, reason: { code: "UNSUPPORTED_REQUEST" } }],
	};
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json(response));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({
		extensionFactories: builtInExtensions.filter((extension) => extension.name === "question-generation"),
	});
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "replenishment", request }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("Generate supplements for this joint shortage plan.");

	expect(fetchStub).toHaveBeenCalledOnce();
	expect(fetchStub.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8093/v1/question-generation/replenishment");
	expect(fetchStub.mock.calls[0]?.[1]?.body).toBe(JSON.stringify(request));
	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(JSON.parse(getMessageText(result))).toEqual(response);
});

it("runs the built-in question-generation tool and preserves the service receipt", async () => {
	vi.stubEnv("QUESTION_GENERATION_SERVICE_URL", "http://127.0.0.1:8093/");
	const response = {
		status: "PARTIAL",
		questions: [{ question_id: "paging-demo", version: 1, review_status: "PENDING" }],
		queue_receipts: [{ question_id: "paging-demo", version: 1, status: "QUEUED" }],
		deficits: [{ slot_id: "stack", missing_count: 1 }],
	};
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json(response));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({
		extensionFactories: builtInExtensions.filter((extension) => extension.name === "question-generation"),
	});
	const request = { schema_version: "0.1", request_id: "mixed", slots: [] };
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "batch", request }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("Generate a 408 batch.");

	expect(fetchStub).toHaveBeenCalledOnce();
	expect(fetchStub.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8093/v1/question-generation/batch");
	expect(fetchStub.mock.calls[0]?.[1]?.body).toBe(JSON.stringify(request));
	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(JSON.parse(getMessageText(result))).toEqual(response);
});
