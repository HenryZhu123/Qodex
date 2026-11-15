import { tmpdir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai";
import { afterEach, expect, it, vi } from "vitest";
import { builtInExtensions } from "../../src/extensions/index.ts";
import {
	callDigest,
	observe,
	POLICY_MARKER,
	parseQuota,
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
		generation: 12,
		review: 12,
		assembly: 4,
		wallClockMs: 90 * 60_000,
		failures: 3,
		noProgress: 5,
		total: 40,
	});
	expect(resolveLimits({ QODEX_MAX_GENERATION_CALLS: "2", QODEX_MAX_WALL_CLOCK_MS: "1000" })).toMatchObject({
		generation: 2,
		wallClockMs: 1000,
	});
	expect(resolveLimits({ QODEX_MAX_GENERATION_CALLS: "0" }).generation).toBe(12);
	// A stated goal sizes the budget: a five-question paper gets room to draft and rework.
	expect(resolveLimits({}, 5)).toMatchObject({ generation: 12, review: 17, total: 40 });
	expect(resolveLimits({}, 10)).toMatchObject({ generation: 22, review: 32, total: 58 });
	// Explicit environment values still win over the goal-derived size.
	expect(resolveLimits({ QODEX_MAX_GENERATION_CALLS: "1" }, 10).generation).toBe(1);
	expect(policyEnabled({})).toBe(true);
	expect(policyEnabled({ QODEX_WORKFLOW_POLICY: "off" })).toBe(false);
});

it("reads the requested question count without treating a score as a count", () => {
	expect(parseQuota("数据结构出10题")).toBe(10);
	expect(parseQuota("出三道单选")).toBe(3);
	expect(parseQuota("组十五道题的卷子")).toBe(15);
	expect(parseQuota("各 2 分，出一份卷")).toBeNull();
	expect(parseQuota("帮我出点题")).toBeNull();
	expect(parseQuota("")).toBeNull();
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
	expect(
		observe("exam_checker", {
			status: "PASS",
			task_id: "3f6c1e0e-6d1a-4c1e-9d57-0f0f0f0f0f0f",
			question_id: "authored-1-v1",
			version: 1,
			ingestion: { status: "STORED" },
		}),
	).toMatchObject({ ok: true, artifact: { ingestion: "STORED", version: "1" } });
	expect(observe("exam_assembly", { status: "NEEDS_QUESTIONS", deficits: [{}, {}] })).toMatchObject({
		ok: false,
		artifact: { deficits: "2" },
	});
	expect(observe("question_generation", { error: "INVALID_EXAM_CHECKER_INPUT" })).toMatchObject({
		ok: false,
		code: "INVALID_EXAM_CHECKER_INPUT",
	});
	// Real shape when the review model is misconfigured: HTTP 200, domain-level failure,
	// every check FAILED with CONFIGURATION_ERROR and no ingestion record.
	expect(
		observe("exam_checker", {
			status: "UNRESOLVED",
			review: {
				summary: { has_error: false, errors: [], unresolved_checks: ["typo_check", "logic_check"] },
			},
			ingestion: null,
		}),
	).toMatchObject({ ok: false, status: "UNRESOLVED", detail: "unresolved_checks=2" });
	// Verbatim shapes recorded from a live run (deepseek-flash, 2026-11-15): the Pi tool
	// flattens the review result, so the hook must read the flat form too.
	expect(
		observe("exam_checker", {
			task_id: "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b",
			question_id: "authored-a36e2635f154f385939404cf-v1",
			question_number: "1",
			version: 1,
			status: "PASS",
			errors: [],
			unresolved_checks: [],
			ingestion: { status: "STORED", record_id: "f16e9f77-b813-49bf-a9c6-b49b49ce1797" },
		}),
	).toMatchObject({ ok: true, status: "PASS", artifact: { ingestion: "STORED" } });
	expect(
		observe("exam_checker", {
			task_id: "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b",
			question_id: "authored-a36e2635f154f385939404cf-v1",
			question_number: "1",
			version: 1,
			status: "UNRESOLVED",
			errors: [],
			unresolved_checks: [
				{ task_id: "typo_check", attempts: 1, error_code: "CONFIGURATION_ERROR", retryable: true },
			],
		}),
	).toMatchObject({ ok: false, status: "UNRESOLVED", detail: "unresolved_checks=1" });
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
	// The operator trace must show what the user typed, not only which tools ran.
	const traceDirPath = process.env.QODEX_TRACE_DIR as string;
	const { readdirSync, readFileSync } = await import("node:fs");
	const log = readdirSync(traceDirPath).map((name) => readFileSync(`${traceDirPath}/${name}`, "utf8")).join("");
	expect(log).toContain('"event":"user_prompt"');
	expect(log).toContain("帮我出几道 408 题");
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

it("does not spend the generation budget on a rejected request", async () => {
	vi.stubEnv("QODEX_MAX_GENERATION_CALLS", "1");
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi
		.fn<typeof fetch>()
		.mockResolvedValueOnce(Response.json({ status: "INVALID_REQUEST", questions: [], message: "requirements 须为数组" }))
		.mockResolvedValueOnce(Response.json({ status: "GENERATED", questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: "bad" } }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: "good" } }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("先错一次，再修正后重试");

	expect(fetchStub).toHaveBeenCalledTimes(2);
});

it("stops when calls keep succeeding but nothing advances", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi
		.fn<typeof fetch>()
		.mockImplementation(async () => Response.json({ status: "GENERATED", questions: [{}] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	const calls = ["a", "b", "c", "d", "e", "f"].map((id) =>
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: id } }), {
			stopReason: "toolUse",
		}),
	);
	harness.setResponses([...calls, fauxAssistantMessage("stopped")]);

	await harness.session.prompt("出五道题");

	// Five drafts nobody reviewed is no progress; the sixth call never reaches the service.
	expect(fetchStub).toHaveBeenCalledTimes(5);
	const results = harness.session.messages.filter((message) => message.role === "toolResult");
	expect(getMessageText(results[5])).toContain("NO_PROGRESS");
	const { readdirSync, readFileSync } = await import("node:fs");
	const dir = process.env.QODEX_TRACE_DIR as string;
	const log = readdirSync(dir)
		.map((name) => readFileSync(`${dir}/${name}`, "utf8"))
		.join("");
	expect(log).toContain('"event":"goal_report"');
	expect(log).toContain('"stop":"NO_PROGRESS:5"');
	// "出五道题" sizes the budget, and the report keeps the ledger for the hand-back.
	expect(log).toContain('"quota":5');
});

it("counts a stored question as progress and records it in the ledger", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	// Shape the real service returns: the tool compacts it, so the hook sees the flat form.
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(
		Response.json({
			task_id: "t-1",
			question_id: "q-1",
			question_number: "1",
			version: 1,
			review: { status: "PASS", summary: { errors: [] }, checks: [] },
			ingestion: { status: "STORED" },
		}),
	);
	vi.stubGlobal("fetch", fetchStub);
	// The review tool lives in another extension, so load both for this case.
	const withReview = builtInExtensions.filter(
		(extension) => extension.name === "qodex-workflow" || extension.name === "exam-checker",
	);
	harness = await createHarness({ extensionFactories: withReview });
	harness.setResponses([
		fauxAssistantMessage(
			fauxToolCall("exam_checker", { operation: "review_question", task_id: "t-1", question_id: "q-1", version: 1 }),
			{ stopReason: "toolUse" },
		),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("审校一下这道题");

	const { readdirSync, readFileSync } = await import("node:fs");
	const dir = process.env.QODEX_TRACE_DIR as string;
	const log = readdirSync(dir)
		.map((name) => readFileSync(`${dir}/${name}`, "utf8"))
		.join("");
	expect(log).toContain('"progress":true');
	expect(log).toContain('"stored":1');
});

it("lets the run continue once the user answers the hand-back", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi
		.fn<typeof fetch>()
		.mockImplementation(async () => Response.json({ status: "GENERATED", questions: [{}] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	const first = ["a", "b", "c", "d", "e", "blocked"].map((id) =>
		fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: id } }), {
			stopReason: "toolUse",
		}),
	);
	harness.setResponses([...first, fauxAssistantMessage("已停止"), fauxAssistantMessage(fauxToolCall("question_generation", { operation: "author", request: { request_id: "g" } }), { stopReason: "toolUse" }), fauxAssistantMessage("继续了")]);

	await harness.session.prompt("出五道题");
	await harness.session.prompt("材料放好了，继续");

	// The stop blocked the sixth call of the first turn; the new message unblocked the run.
	expect(fetchStub).toHaveBeenCalledTimes(6);
	const results = harness.session.messages.filter((message) => message.role === "toolResult");
	expect(getMessageText(results[5])).toContain("RUN_STOPPED");
	expect(getMessageText(results[6])).not.toContain("RUN_STOPPED");
	const { readdirSync, readFileSync } = await import("node:fs");
	const dir = process.env.QODEX_TRACE_DIR as string;
	const log = readdirSync(dir)
		.map((name) => readFileSync(`${dir}/${name}`, "utf8"))
		.join("");
	expect(log).toContain('"event":"resume"');
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

it("passes a read-only bank answer through untouched", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const records = {
		questions: [
			{
				record_id: "r-1",
				task_id: "t-1",
				question_id: "q-1",
				version: 1,
				question_json: { question: { subject: "数据结构", stem: "循环队列", options: ["A", "B", "C", "D"] } },
			},
		],
	};
	const fetchStub = vi.fn<typeof fetch>().mockImplementation(async () => Response.json(records));
	vi.stubGlobal("fetch", fetchStub);
	// question_bank is registered by the exam-checker extension.
	const withBank = builtInExtensions.filter(
		(extension) => extension.name === "qodex-workflow" || extension.name === "exam-checker",
	);
	harness = await createHarness({ extensionFactories: withBank });
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_bank", { operation: "search_questions", request: { limit: 5 } }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("题库里有哪些题");

	const result = harness.session.messages.find((message) => message.role === "toolResult");
	const body = getMessageText(result);
	// The records must survive: a hit count would send the model off to call the API itself.
	expect(body).toContain("循环队列");
	expect(body).not.toContain('"observation"');
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

it("leaves a quoted policy rule alone even after a read-only tool call", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_bank", { operation: "search_questions", limit: 5 }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage('看到 ingestion.status=STORED 我才会说“已入库”。'),
	]);

	await harness.session.prompt("题库里有什么？");

	const texts = harness.session.messages
		.filter((message) => message.role === "assistant")
		.map((message) => getMessageText(message));
	expect(texts.at(-1)).not.toContain("[护栏]");
});

it("leaves a capability sentence alone when no tool ran", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([fauxAssistantMessage("我可以从已入库题目组卷，也可以出题送审。")]);

	await harness.session.prompt("你能做什么？");

	const texts = harness.session.messages
		.filter((message) => message.role === "assistant")
		.map((message) => getMessageText(message));
	expect(texts.at(-1)).not.toContain("[护栏]");
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
