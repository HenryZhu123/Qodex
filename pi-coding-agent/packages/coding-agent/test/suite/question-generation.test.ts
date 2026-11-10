import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai";
import { afterEach, expect, it, vi } from "vitest";
import { builtInExtensions } from "../../src/extensions/index.ts";
import { createHarness, getMessageText, type Harness } from "./harness.ts";

let harness: Harness | undefined;

afterEach(() => {
	harness?.cleanup();
	harness = undefined;
	vi.unstubAllGlobals();
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
