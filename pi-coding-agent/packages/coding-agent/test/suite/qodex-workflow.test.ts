import { tmpdir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai";
import { afterEach, expect, it, vi } from "vitest";
import { builtInExtensions } from "../../src/extensions/index.ts";
import {
	callDigest,
	observe,
	POLICY_MARKER,
	policyEnabled,
	resolveLimits,
} from "../../src/extensions/qodex-workflow/index.ts";
import { createHarness, getMessageText, type Harness } from "./harness.ts";

let harness: Harness | undefined;

afterEach(() => {
	harness?.cleanup();
	harness = undefined;
	vi.unstubAllGlobals();
	vi.unstubAllEnvs();
});

const workflowExtensions = builtInExtensions.filter(
	(extension) => extension.name === "qodex-workflow" || extension.name === "question-generation",
);

function traceDir(): string {
	return join(tmpdir(), `qodex-trace-${Math.trunc(performance.now())}-${process.pid}`);
}

it("parses limits and keeps the policy switch explicit", () => {
	expect(resolveLimits({})).toEqual({
		generation: 6,
		review: 6,
		assembly: 3,
		wallClockMs: 45 * 60_000,
	});
	expect(resolveLimits({ QODEX_MAX_GENERATION_CALLS: "2", QODEX_MAX_WALL_CLOCK_MS: "1000" })).toMatchObject({
		generation: 2,
		wallClockMs: 1000,
	});
	expect(resolveLimits({ QODEX_MAX_GENERATION_CALLS: "0" }).generation).toBe(6);
	expect(policyEnabled({})).toBe(true);
	expect(policyEnabled({ QODEX_WORKFLOW_POLICY: "off" })).toBe(false);
});

it("digests identical calls the same regardless of key order", () => {
	expect(callDigest("t", { a: 1, b: [2, 3] })).toBe(callDigest("t", { b: [2, 3], a: 1 }));
	expect(callDigest("t", { a: 1 })).not.toBe(callDigest("t", { a: 2 }));
});

it("turns each service payload into a routing observation", () => {
	expect(observe("question_generation", { status: "GENERATED", questions: [{}, {}] })).toMatchObject({
		ok: true,
		artifact: { questions: "2" },
	});
	expect(
		observe("question_generation", {
			status: "SELF_CHECK_FAILED",
			message: "通用命题未交付：反例与解析审计",
			failure: { code: "audit_rejected", retry: "new_request", needs: "human" },
		}),
	).toMatchObject({ ok: false, code: "audit_rejected", retry: "new_request", needs: "human" });
	expect(
		observe("exam_checker", {
			status: "NEEDS_REVISION",
			review: { summary: { errors: [{ error_type: "ambiguity" }, { error_type: "grading" }] } },
		}),
	).toMatchObject({ ok: false, status: "NEEDS_REVISION", errors: ["ambiguity", "grading"] });
	expect(observe("exam_checker", { document_id: "d1", imported: 2 })).toMatchObject({
		ok: true,
		artifact: { document_id: "d1", imported: "2" },
	});
	expect(
		observe("exam_checker", {
			status: "PASS",
			document_id: "d1",
			question_id: "q1",
			ingestion: { status: "STORED" },
		}),
	).toMatchObject({ ok: true, artifact: { ingestion: "STORED" } });
	expect(observe("exam_assembly", { status: "NEEDS_QUESTIONS", deficits: [{}, {}] })).toMatchObject({
		ok: false,
		artifact: { deficits: "2" },
	});
	expect(observe("question_generation", { error: "INVALID_EXAM_CHECKER_INPUT" })).toMatchObject({
		ok: false,
		code: "INVALID_EXAM_CHECKER_INPUT",
	});
});

it("appends the policy without replacing the assembled system prompt", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: "GENERATED", questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	const before = harness.session.systemPrompt;
	harness.setResponses([fauxAssistantMessage("done")]);

	await harness.session.prompt("帮我出几道 408 题");

	expect(harness.session.systemPrompt).toContain(POLICY_MARKER);
	expect(harness.session.systemPrompt.length).toBeGreaterThan(before.length);
});

it("stays out of the way when the policy switch is off", async () => {
	vi.stubEnv("QODEX_WORKFLOW_POLICY", "off");
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([fauxAssistantMessage("done")]);

	await harness.session.prompt("帮我出几道 408 题");

	expect(harness.session.systemPrompt).not.toContain(POLICY_MARKER);
});

it("stops spending when the generation budget is exhausted", async () => {
	vi.stubEnv("QODEX_MAX_GENERATION_CALLS", "1");
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: "GENERATED", questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: "a" } }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: "b" } }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("stopped"),
	]);

	await harness.session.prompt("出两道题");

	expect(fetchStub).toHaveBeenCalledOnce();
	const results = harness.session.messages.filter((message) => message.role === "toolResult");
	expect(getMessageText(results[1])).toContain("BUDGET_EXHAUSTED");
});

it("refuses to pay twice for the same call", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: "GENERATED", questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	const request = { request_id: "same" };
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("出题，然后重试同一请求");

	expect(fetchStub).toHaveBeenCalledOnce();
	const results = harness.session.messages.filter((message) => message.role === "toolResult");
	expect(getMessageText(results[1])).toContain("DUPLICATE_CALL");
});

it("reports a domain failure as an error observation instead of a success", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(
		Response.json({
			status: "SELF_CHECK_FAILED",
			message: "通用命题未交付：反例与解析审计",
			questions: [],
			failure: { code: "audit_rejected", status: "SELF_CHECK_FAILED", retry: "new_request", needs: "human" },
		}),
	);
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: "f" } }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("出一道题");

	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(result?.isError).toBe(true);
	const body = JSON.parse(getMessageText(result));
	expect(body.observation).toMatchObject({ ok: false, code: "audit_rejected", retry: "new_request" });
	expect(body.observation.next.length).toBeGreaterThan(0);
});

it("corrects an ingestion claim that the ledger cannot support", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: "GENERATED", questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: "g" } }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("这道题已经入库，可以组卷了。"),
	]);

	await harness.session.prompt("出一道题并入库");

	const texts = harness.session.messages
		.filter((message) => message.role === "assistant")
		.map((message) => getMessageText(message));
	expect(texts.at(-1)).toContain("[护栏]");
	expect(texts.at(-1)).toContain("STORED");
});
