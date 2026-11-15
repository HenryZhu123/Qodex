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
	// The extension injects the task_id that ties every returned question together.
	const submitted = JSON.parse(String(fetchStub.mock.calls[0]?.[1]?.body));
	expect(submitted).toMatchObject(request);
	expect(submitted.task_id).toMatch(/^[0-9a-f-]{36}$/);
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
	const submitted = JSON.parse(String(fetchStub.mock.calls[0]?.[1]?.body));
	expect(submitted).toMatchObject(request);
	expect(submitted.task_id).toMatch(/^[0-9a-f-]{36}$/);
	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(JSON.parse(getMessageText(result))).toEqual(response);
});

it("preserves authoring constraints and allows the configured model timeout", async () => {
	vi.stubEnv("QUESTION_GENERATION_TIMEOUT_MS", "420000");
	const timeout = vi.spyOn(AbortSignal, "timeout");
	const request = {
		schema_version: "0.1",
		request_id: "reasoning-item",
		constraints: { authoring: { objective: "diagnose" } },
	};
	const response = { status: "MODEL_UNAVAILABLE", questions: [], message: "provider timeout" };
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json(response));
	vi.stubGlobal("fetch", fetchStub);
	try {
		harness = await createHarness({
			extensionFactories: builtInExtensions.filter((extension) => extension.name === "question-generation"),
		});
		harness.setResponses([
			fauxAssistantMessage(fauxToolCall("question_generation", { operation: "single", request }), {
				stopReason: "toolUse",
			}),
			fauxAssistantMessage("done"),
		]);
		await harness.session.prompt("Generate a diagnostic question.");
		expect(timeout).toHaveBeenCalledWith(420000);
		// The extension injects the task_id that ties every returned question together.
		const submitted = JSON.parse(String(fetchStub.mock.calls[0]?.[1]?.body));
		expect(submitted).toMatchObject(request);
		expect(submitted.task_id).toMatch(/^[0-9a-f-]{36}$/);
		const result = harness.session.messages.find((message) => message.role === "toolResult");
		expect(JSON.parse(getMessageText(result))).toEqual(response);
	} finally {
		timeout.mockRestore();
	}
});

it("passes a rough request to the author operation for the service to plan", async () => {
	const request = { schema_version: "0.1", request_id: "rough-item", brief: "想练内存这块" };
	const response = { status: "NEEDS_MATERIAL", questions: [] };
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json(response));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({
		extensionFactories: builtInExtensions.filter((extension) => extension.name === "question-generation"),
	});
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("done"),
	]);
	await harness.session.prompt("想练内存这块");
	expect(fetchStub.mock.calls[0]?.[0]).toMatch(/\/v1\/question-generation\/author$/);
	// The extension injects the task_id that ties every returned question together.
	const submitted = JSON.parse(String(fetchStub.mock.calls[0]?.[1]?.body));
	expect(submitted).toMatchObject(request);
	expect(submitted.task_id).toMatch(/^[0-9a-f-]{36}$/);
	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(JSON.parse(getMessageText(result))).toEqual(response);
});
