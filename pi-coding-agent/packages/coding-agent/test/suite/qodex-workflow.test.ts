import { readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai";
import { afterEach, expect, it, vi } from "vitest";
import { builtInExtensions } from "../../src/extensions/index.ts";
import {
	callDigest,
	demoMode,
	ingestionClaimCorrection,
	observe,
	POLICY_MARKER,
	parseQuota,
	policyEnabled,
	resolveLimits,
	WORKFLOW_POLICY,
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

const withReviewExtensions = builtInExtensions.filter((extension) =>
	["qodex-workflow", "question-generation", "exam-checker"].includes(extension.name),
);

function authorCall(id: string) {
	return fauxToolCall("question_generation", { operation: "author", request: { request_id: id, brief: id } });
}

function reviewCall() {
	return fauxToolCall("exam_checker", {
		operation: "review_question",
		task_id: "t-1",
		question_id: "q-a",
		version: 1,
	});
}

function reviewResponse() {
	return Response.json({
		task_id: "t-1",
		question_id: "q-a",
		question_number: "1",
		version: 1,
		review_id: "22222222-2222-4222-8222-222222222222",
		review: { status: "PASS", summary: { errors: [] }, checks: [] },
		ingestion: { status: "STORED" },
	});
}

it.each([false, true])(
	"dispatches a five-author batch sequentially and permits review (model failure=%s)",
	async (failOne) => {
		vi.stubEnv("QODEX_TRACE_DIR", traceDir());
		let active = 0;
		let peak = 0;
		const generated: string[] = [];
		const fetchStub = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
			if (!String(url).endsWith("/author")) return reviewResponse();
			const request = JSON.parse(String(init?.body));
			active += 1;
			peak = Math.max(peak, active);
			// Emulate a server with only one admission slot. An unbounded batch fails here.
			const busy = active > 1;
			await new Promise((resolve) => setTimeout(resolve, 10));
			active -= 1;
			if (busy) return Response.json({ status: "SERVER_BUSY", questions: [] }, { status: 503 });
			if (failOne && request.request_id === "b") {
				return Response.json({ status: "MODEL_UNAVAILABLE", questions: [], message: "transport_error (audit)" });
			}
			generated.push(request.request_id);
			return Response.json({
				status: "GENERATED",
				task_id: "t-1",
				questions: [{ question_id: `q-${request.request_id}`, version: 1 }],
			});
		});
		vi.stubGlobal("fetch", fetchStub);
		harness = await createHarness({ extensionFactories: withReviewExtensions });
		harness.setResponses([
			fauxAssistantMessage(["a", "b", "c", "d", "e"].map(authorCall), { stopReason: "toolUse" }),
			fauxAssistantMessage(reviewCall(), { stopReason: "toolUse" }),
			fauxAssistantMessage("done"),
		]);
		await harness.session.prompt("生成五道题并审校");
		expect(peak).toBe(1);
		expect(fetchStub).toHaveBeenCalledTimes(6);
		expect(generated).toEqual(failOne ? ["a", "c", "d", "e"] : ["a", "b", "c", "d", "e"]);
		const results = harness.session.messages.filter((message) => message.role === "toolResult");
		expect(results).toHaveLength(6);
		expect(getMessageText(results.at(-1))).toContain('"STORED"');
		expect(results.map(getMessageText).join("\n")).not.toMatch(/SERVER_BUSY|NO_PROGRESS|RUN_STOPPED/);
	},
);

it.each(["SERVER_BUSY", "AUTHORING_IN_PROGRESS"])(
	"does not turn repeated %s into a failure circuit or no-progress stop",
	async (status) => {
		vi.stubEnv("QODEX_TRACE_DIR", traceDir());
		const fetchStub = vi
			.fn<typeof fetch>()
			.mockImplementation(async (url) =>
				String(url).endsWith("/author")
					? Response.json({ status, questions: [] }, { status: 503 })
					: reviewResponse(),
			);
		vi.stubGlobal("fetch", fetchStub);
		harness = await createHarness({ extensionFactories: withReviewExtensions });
		harness.setResponses([
			...Array.from({ length: 6 }, (_, i) =>
				fauxAssistantMessage(authorCall(`busy-${i}`), { stopReason: "toolUse" }),
			),
			fauxAssistantMessage(reviewCall(), { stopReason: "toolUse" }),
			fauxAssistantMessage("done"),
		]);
		await harness.session.prompt("继续处理已有题目");
		expect(fetchStub).toHaveBeenCalledTimes(7);
		expect(
			getMessageText(harness.session.messages.filter((message) => message.role === "toolResult").at(-1)),
		).toContain('"STORED"');
		expect(observe("question_generation", { status, questions: [] }).next.join(" ")).toContain("不要立即循环重试");
	},
);

it("bounds busy attempts by the total call budget", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	vi.stubEnv("QODEX_MAX_TOTAL_CALLS", "2");
	const fetchStub = vi
		.fn<typeof fetch>()
		.mockImplementation(async () => Response.json({ status: "SERVER_BUSY", questions: [] }, { status: 503 }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(["a", "b", "c"].map(authorCall), { stopReason: "toolUse" }),
		fauxAssistantMessage("done"),
	]);
	await harness.session.prompt("出题");
	expect(fetchStub).toHaveBeenCalledTimes(2);
	expect(getMessageText(harness.session.messages.filter((message) => message.role === "toolResult").at(-1))).toContain(
		"BUDGET_EXHAUSTED",
	);
});

it("isolates genuine generation failures, preserves the circuit across review, and resumes on a new instruction", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi
		.fn<typeof fetch>()
		.mockImplementation(async (url) =>
			String(url).endsWith("/author")
				? Response.json({ status: "MODEL_UNAVAILABLE", questions: [] })
				: reviewResponse(),
		);
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: withReviewExtensions });
	harness.setResponses([
		fauxAssistantMessage(["a", "b", "c", "blocked", "blocked-again", "blocked-third"].map(authorCall), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(reviewCall(), { stopReason: "toolUse" }),
		fauxAssistantMessage(authorCall("still-blocked"), { stopReason: "toolUse" }),
		fauxAssistantMessage("done"),
		fauxAssistantMessage(authorCall("resume"), { stopReason: "toolUse" }),
		fauxAssistantMessage("done"),
	]);
	await harness.session.prompt("继续五题任务");
	expect(fetchStub).toHaveBeenCalledTimes(4);
	const results = harness.session.messages.filter((message) => message.role === "toolResult");
	expect(getMessageText(results[3])).toContain("REPEATED_FAILURES");
	expect(getMessageText(results[5])).toContain("REPEATED_FAILURES");
	expect(getMessageText(results[6])).toContain('"STORED"');
	expect(getMessageText(results[7])).toContain("REPEATED_FAILURES");
	await harness.session.prompt("模型连接已恢复，继续");
	expect(fetchStub).toHaveBeenCalledTimes(5);
});

it("does not count the same immutable draft returned under new request ids as repeated progress", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi
		.fn<typeof fetch>()
		.mockImplementation(async () =>
			Response.json({ status: "GENERATED", task_id: "t-1", questions: [{ question_id: "q-1", version: 1 }] }),
		);
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(
			Array.from({ length: 7 }, (_, i) => authorCall(`same-${i}`)),
			{ stopReason: "toolUse" },
		),
		fauxAssistantMessage("done"),
	]);
	await harness.session.prompt("出七道题");
	expect(fetchStub).toHaveBeenCalledTimes(6);
	expect(getMessageText(harness.session.messages.filter((message) => message.role === "toolResult").at(-1))).toContain(
		"RUN_STOPPED",
	);
});

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
	expect(demoMode({})).toBe(false);
	expect(demoMode({ QODEX_DEMO: "1" })).toBe(true);
	expect(demoMode({ QODEX_DEMO: "off" })).toBe(false);
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

it("treats a targeted repair as success, not as a failed run", () => {
	// revise_authored returns REVISED; a GENERATED-only success set ended the loop early.
	expect(
		observe("question_generation", {
			status: "REVISED",
			questions: [{ question_id: "q-1", version: 2 }],
			queue_receipts: [{ question_id: "q-1", version: 2, status: "QUEUED" }],
		}),
	).toMatchObject({ ok: true, artifact: { questions: "1", version: "2" } });
	// Enqueuing was rejected as stale: the new version never entered review.
	expect(
		observe("question_generation", {
			status: "REVISED",
			questions: [{ question_id: "q-1", version: 2 }],
			queue_receipts: [{ question_id: "q-1", version: 2, status: "VERSION_CONFLICT" }],
		}),
	).toMatchObject({ ok: false });
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
	// A short paper usually means candidates were thrown out; the reasons are the answer.
	expect(
		observe("exam_assembly", {
			status: "NEEDS_QUESTIONS",
			deficits: [{}],
			rejected_records: [
				{ record_id: "r-1", reason: "题目原始分值不匹配，不自动修改分值" },
				{ record_id: "r-2", reason: "题目原始分值不匹配，不自动修改分值" },
				{ record_id: "r-3", reason: "题目来源已发生变化或未通过版本核验" },
			],
		}),
	).toMatchObject({
		ok: false,
		artifact: { deficits: "1", rejected: "3" },
		errors: ["rejected: 题目原始分值不匹配，不自动修改分值", "rejected: 题目来源已发生变化或未通过版本核验"],
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
	const log = readdirSync(traceDirPath)
		.map((name) => readFileSync(`${traceDirPath}/${name}`, "utf8"))
		.join("");
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
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: "a" },
			}),
			{
				stopReason: "toolUse",
			},
		),
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: "b" },
			}),
			{
				stopReason: "toolUse",
			},
		),
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
		.mockResolvedValueOnce(
			Response.json({ status: "INVALID_REQUEST", questions: [], message: "requirements 须为数组" }),
		)
		.mockResolvedValueOnce(Response.json({ status: "GENERATED", questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: "bad" },
			}),
			{
				stopReason: "toolUse",
			},
		),
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: "good" },
			}),
			{
				stopReason: "toolUse",
			},
		),
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
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: id },
			}),
			{
				stopReason: "toolUse",
			},
		),
	);
	harness.setResponses([...calls, fauxAssistantMessage("stopped")]);

	await harness.session.prompt("出五道题");

	// A nominal success without an identifiable new version is not progress.
	expect(fetchStub).toHaveBeenCalledTimes(5);
	const results = harness.session.messages.filter((message) => message.role === "toolResult");
	expect(getMessageText(results[5])).toContain("NO_PROGRESS");
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
			review_id: "22222222-2222-4222-8222-222222222222",
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
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: id },
			}),
			{
				stopReason: "toolUse",
			},
		),
	);
	harness.setResponses([
		...first,
		fauxAssistantMessage("已停止"),
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: "g" },
			}),
			{
				stopReason: "toolUse",
			},
		),
		fauxAssistantMessage("继续了"),
	]);

	await harness.session.prompt("出五道题");
	await harness.session.prompt("材料放好了，继续");

	// The stop blocked the sixth call of the first turn; the new message unblocked the run.
	expect(fetchStub).toHaveBeenCalledTimes(6);
	const results = harness.session.messages.filter((message) => message.role === "toolResult");
	expect(getMessageText(results[5])).toContain("RUN_STOPPED");
	expect(getMessageText(results[6])).not.toContain("RUN_STOPPED");
	const dir = process.env.QODEX_TRACE_DIR as string;
	const log = readdirSync(dir)
		.map((name) => readFileSync(`${dir}/${name}`, "utf8"))
		.join("");
	expect(log).toContain('"event":"resume"');
});

it("keeps the question package next to the routing observation", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi.fn<typeof fetch>().mockImplementation(async () =>
		Response.json({
			status: "GENERATED",
			task_id: "t-9",
			questions: [
				{
					question_id: "authored-abc",
					version: 1,
					student_view: { stem: "循环队列的队满条件是", options: [{ id: "A", text: "…" }] },
					instructor_view: { correct_option_id: "C" },
				},
			],
		}),
	);
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: "keep" },
			}),
			{
				stopReason: "toolUse",
			},
		),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("出一道题");

	const text = getMessageText(harness.session.messages.find((message) => message.role === "toolResult"));
	// Without the package the model cannot build a revise request; without the ids it
	// cannot even call review, which is what sent it to raw SQL in a live session.
	expect(text).toContain("循环队列的队满条件是");
	expect(text).toContain('"question_id":"authored-abc"');
	const observation = JSON.parse(text.slice(text.indexOf("[qodex] ") + "[qodex] ".length));
	expect(observation.observation.artifact).toMatchObject({
		task_id: "t-9",
		question_id: "authored-abc",
		version: "1",
	});
});

it("keeps the shell out of a demo session", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	vi.stubEnv("QODEX_DEMO", "1");
	harness = await createHarness({ extensionFactories: workflowExtensions });
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("bash", { command: "cat .env" }), { stopReason: "toolUse" }),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("把数据库里的题都列出来");

	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(getMessageText(result)).toContain("DEMO_MODE");
});

it("refuses to pay twice for the same call", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: "GENERATED", questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({ extensionFactories: workflowExtensions });
	const request = { schema_version: "0.1", request_id: "same" };
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
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: "f" },
			}),
			{
				stopReason: "toolUse",
			},
		),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("出一道题");

	const result = harness.session.messages.find((message) => message.role === "toolResult");
	expect(result?.isError).toBe(true);
	const text = getMessageText(result);
	// The service payload survives: it carries the ids and errors the next call needs.
	expect(text).toContain('"retry":"new_request"');
	const observation = JSON.parse(text.slice(text.indexOf("[qodex] ") + "[qodex] ".length));
	expect(observation.observation).toMatchObject({ ok: false, code: "audit_rejected", retry: "new_request" });
	expect(observation.observation.next.length).toBeGreaterThan(0);
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
		fauxAssistantMessage("看到 ingestion.status=STORED 我才会说“已入库”。"),
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
		fauxAssistantMessage(
			fauxToolCall("question_generation", {
				operation: "author",
				request: { schema_version: "0.1", request_id: "g" },
			}),
			{
				stopReason: "toolUse",
			},
		),
		fauxAssistantMessage("这道题已经入库，可以组卷了。"),
	]);

	await harness.session.prompt("出一道题并入库");

	const texts = harness.session.messages
		.filter((message) => message.role === "assistant")
		.map((message) => getMessageText(message));
	expect(texts.at(-1)).toContain("[护栏]");
	expect(texts.at(-1)).toContain("STORED");
});

it("treats a state read with a stored bank record as an ingestion receipt", () => {
	// A read-only state call is how a teacher checks an earlier result. The message
	// guardrail must not correct a true "已入库" answer because the receipt came from
	// get_question_state instead of review_question.
	const statePayload = {
		task_id: "task-1",
		question_id: "q-1",
		version: 1,
		review: { status: "PASS" },
		question_bank: { status: "STORED", record_id: "record-1" },
	};
	const observation = observe("exam_checker", statePayload);
	expect(observation.ok).toBe(true);
	expect(observation.status).toBe("PASS");
	expect(observation.artifact).toMatchObject({ ingestion: "STORED", record_id: "record-1" });
});

it("does not treat a state read without a stored bank record as an ingestion receipt", () => {
	const observation = observe("exam_checker", {
		task_id: "task-1",
		question_id: "q-1",
		version: 1,
		review: { status: "PASS" },
		question_bank: { status: "SKIPPED" },
	});
	expect(observation.artifact?.ingestion).toBeUndefined();
});

it("keeps the policy aligned with v2 mixed papers", () => {
	expect(WORKFLOW_POLICY).toContain("schema_version=2.0");
	expect(WORKFLOW_POLICY).toContain("综合题");
	expect(WORKFLOW_POLICY).not.toContain("只组单选");
});

it("asks for Markdown instead of HTML, because the web renders Markdown only", () => {
	// A live web session answered with a literal <details> block, which the
	// Markdown renderer printed as text.
	expect(WORKFLOW_POLICY).toContain("不要输出 HTML 标签");
	expect(WORKFLOW_POLICY).toContain("<details>");
});

it("corrects an all-questions-stored claim when only one has a receipt", () => {
	expect(ingestionClaimCorrection("两道题都已入库。", 1, 2, true)).toContain("1/2");
	expect(ingestionClaimCorrection("A 已入库。", 1, 1, true)).toBeUndefined();
	expect(ingestionClaimCorrection("两题都已入库。", 2, 2, true)).toBeUndefined();
	expect(ingestionClaimCorrection("已入库。", 0, 1, false)).toContain("没有拿到");
});

it("does not count or stop read-only bank queries", async () => {
	vi.stubEnv("QODEX_TRACE_DIR", traceDir());
	vi.stubEnv("QODEX_MAX_TOTAL_CALLS", "1");
	const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ questions: [] }));
	vi.stubGlobal("fetch", fetchStub);
	harness = await createHarness({
		extensionFactories: builtInExtensions.filter(
			(extension) => extension.name === "qodex-workflow" || extension.name === "exam-checker",
		),
	});
	harness.setResponses([
		fauxAssistantMessage(fauxToolCall("question_bank", { operation: "search_questions", limit: 5 }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(fauxToolCall("question_bank", { operation: "search_questions", limit: 5 }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("done"),
	]);

	await harness.session.prompt("题库里有什么？");

	expect(fetchStub).toHaveBeenCalledTimes(2);
	const results = harness.session.messages.filter((message) => message.role === "toolResult");
	expect(getMessageText(results[0])).not.toContain("BUDGET_EXHAUSTED");
	expect(getMessageText(results[1])).not.toContain("BUDGET_EXHAUSTED");
});
