import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExtensionAPI } from "../src/core/extensions/types.ts";
import examAssemblyExtension, { assemblyParameters } from "../src/extensions/exam-assembly/index.ts";
import { builtInExtensions } from "../src/extensions/index.ts";

interface Tool {
	execute: (
		id: string,
		params: typeof request,
		signal?: AbortSignal,
	) => Promise<{ content: { text?: string }[]; isError?: boolean }>;
}
const request = {
	request_id: "test",
	subject: "数据结构",
	question_count: 1,
	total_score: 2,
	question_type_counts: { single_choice: 1 },
	question_type_scores: { single_choice: 2 },
	knowledge_point_counts: { 栈: 1 },
	difficulty_counts: { easy: 1, medium: 0, hard: 0 },
};
function tool(): Tool {
	let registered: unknown;
	examAssemblyExtension({
		registerTool: (definition: unknown) => {
			registered = definition;
		},
	} as unknown as ExtensionAPI);
	return registered as Tool;
}
afterEach(() => {
	vi.unstubAllGlobals();
	vi.unstubAllEnvs();
	vi.restoreAllMocks();
});

describe("built-in exam assembly", () => {
	it("matches the shared public example and excludes old development fields", () => {
		const example = JSON.parse(
			readFileSync(new URL("../../../services/exam-assembly/examples/request.json", import.meta.url), "utf8"),
		) as Record<string, unknown>;
		for (const key of Object.keys(example)) expect(assemblyParameters.properties).toHaveProperty(key);
		for (const key of ["bank", "allow_mock_reviews", "question_type", "score_per_question", "topic_counts"]) {
			expect(assemblyParameters.properties).not.toHaveProperty(key);
		}
	});
	it("registers on ordinary startup", () => {
		const assembly = builtInExtensions.find((e) => typeof e !== "function" && e.name === "exam-assembly");
		expect(typeof assembly !== "function" && assembly?.factory).toBe(examAssemblyExtension);
		const registered: string[] = [];
		for (const extension of builtInExtensions) {
			if (typeof extension === "function" || extension.hidden) continue;
			extension.factory({
				registerTool: (definition: { name: string }) => registered.push(definition.name),
			} as unknown as ExtensionAPI);
		}
		expect(registered).toContain("question_bank");
		expect(registered.filter((name) => name === "exam_assembly")).toHaveLength(1);
	});
	it("forwards quotas and retains shortage", async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response(
				JSON.stringify({
					status: "NEEDS_QUESTIONS",
					deficits: [{ knowledge_point: "栈", difficulty: "easy", missing_count: 1 }],
					replenishment_request: { minimum_count_proven: false },
				}),
			),
		);
		vi.stubGlobal("fetch", fetchMock);
		const result = await tool().execute("test", request);
		expect(JSON.parse(result.content[0].text ?? "")).toMatchObject({ status: "NEEDS_QUESTIONS", http_status: 200 });
		expect(JSON.parse(result.content[0].text ?? "").deficits[0].missing_count).toBe(1);
		expect(JSON.parse(result.content[0].text ?? "").replenishment_request.minimum_count_proven).toBe(false);
		expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(request);
		expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8092/v1/exam-assembly/assemble");
	});
	it("retains upstream status and detail", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "bank offline" }), { status: 502 })),
		);
		const result = await tool().execute("test", request);
		expect(result.isError).toBe(true);
		expect(JSON.parse(result.content[0].text ?? "")).toMatchObject({
			status: "TOOL_ERROR",
			http_status: 502,
			detail: "bank offline",
		});
	});
	it("preserves pending review and forwards only the supplied decision", async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response(
				JSON.stringify({
					status: "UNRESOLVED",
					similarity_review: { status: "NEEDS_REVIEW" },
					artifacts: { similarity_review_packet: "teacher.json", similarity_decisions_template: "template.json" },
				}),
			),
		);
		vi.stubGlobal("fetch", fetchMock);
		const supplied = {
			...request,
			similarity_decisions: [
				{
					pair_id: "a".repeat(24),
					question_ids: ["one", "two"],
					content_hashes: ["a".repeat(64), "b".repeat(64)],
					source: "human",
					reviewer: "TEST_ONLY_supplied_reviewer",
					verdict: "UNRESOLVED",
					reason: "TEST_ONLY_reason",
				},
			],
		};
		const result = JSON.parse((await tool().execute("review-test", supplied)).content[0].text ?? "");
		expect(result.status).toBe("UNRESOLVED");
		expect(result.similarity_review.status).toBe("NEEDS_REVIEW");
		expect(JSON.parse(fetchMock.mock.calls[0][1].body).similarity_decisions).toEqual(supplied.similarity_decisions);
	});
	it.each(["not-json", JSON.stringify({ status: "STRUCTURAL_PASS" })])("rejects invalid response %s", async (body) => {
		vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
		expect((await tool().execute("test", request)).isError).toBe(true);
	});
	it("handles unreachable service", async () => {
		vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("connection refused")));
		expect(JSON.parse((await tool().execute("test", request)).content[0].text ?? "").error_code).toBe(
			"EXAM_ASSEMBLY_UNAVAILABLE",
		);
	});
	it("bounds service wait", async () => {
		vi.stubEnv("EXAM_ASSEMBLY_TIMEOUT_SECONDS", "0.01");
		vi.stubGlobal(
			"fetch",
			vi.fn(
				(_url: string, init: RequestInit) =>
					new Promise((_resolve, reject) => {
						init.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
					}),
			),
		);
		expect(JSON.parse((await tool().execute("test", request)).content[0].text ?? "").error_code).toBe(
			"EXAM_ASSEMBLY_TIMEOUT",
		);
	});
});

import { readFileSync } from "node:fs";
