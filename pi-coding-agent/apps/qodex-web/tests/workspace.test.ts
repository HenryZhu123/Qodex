import assert from "node:assert/strict";
import { test } from "node:test";
import { rejectUnsafeRequest } from "../lib/local-access";
import { proxyService, serviceTarget } from "../lib/service-proxy";
import { parseModelSelection, validateQuotas } from "../lib/workspace-api";

test("local teacher API rejects hostile origins and non-local hosts", () => {
	Object.assign(process.env, { NODE_ENV: "development" });
	assert.equal(
		rejectUnsafeRequest(
			new Request("http://127.0.0.1:3000/api", { headers: { host: "127.0.0.1:3000", origin: "https://evil.example" } }),
		)?.status,
		403,
	);
	assert.equal(
		rejectUnsafeRequest(new Request("http://evil.example/api", { headers: { host: "evil.example" } }))?.status,
		403,
	);
	assert.equal(
		rejectUnsafeRequest(
			new Request("http://127.0.0.1:3000/api", { headers: { host: "127.0.0.1:3000", "sec-fetch-site": "cross-site" } }),
		)?.status,
		403,
	);
	Object.assign(process.env, { NODE_ENV: "production" });
	assert.equal(rejectUnsafeRequest(new Request("http://localhost/api"))?.status, 404);
	Object.assign(process.env, { NODE_ENV: "development" });
});

test("proxy restricts service paths; traversal and external targets are unavailable", () => {
	assert.equal(
		serviceTarget("assembly", ["v1", "exam-assembly", "history"], "GET")?.pathname,
		"/v1/exam-assembly/history",
	);
	assert.equal(serviceTarget("assembly", ["..", "private"], "GET"), undefined);
	assert.equal(serviceTarget("checker", ["v1", "question-bank", "search"], "POST"), undefined);
	assert.equal(serviceTarget("unknown", ["health"], "GET"), undefined);
	process.env.EXAM_ASSEMBLY_SERVICE_URL = "https://external.example";
	assert.throws(() => serviceTarget("assembly", ["health"], "GET"), /local HTTP/);
	delete process.env.EXAM_ASSEMBLY_SERVICE_URL;
});

test("proxy exposes the six generation operations and the read-only queue listing", () => {
	for (const operation of ["single", "batch", "replenishment", "comprehensive", "revise", "author"]) {
		assert.equal(
			serviceTarget("generation", ["v1", "question-generation", operation], "POST")?.pathname,
			`/v1/question-generation/${operation}`,
		);
	}
	assert.equal(
		serviceTarget("generation", ["v1", "question-generation", "pending"], "GET")?.pathname,
		"/v1/question-generation/pending",
	);
	// The queue listing is read-only, and an unknown operation stays unavailable.
	assert.equal(serviceTarget("generation", ["v1", "question-generation", "pending"], "POST"), undefined);
	assert.equal(serviceTarget("generation", ["v1", "question-generation", "unknown"], "POST"), undefined);
	assert.equal(serviceTarget("generation", ["v1", "question-generation", "author", "extra"], "POST"), undefined);
});

test("proxy exposes review state and review for one generated version, and nothing else", () => {
	const taskId = "cfe4a758-f990-4fdf-8ea7-7d484456deeb";
	const questionId = "authored-964e468069b9e33438f3c8d0";
	const route = ["v1", "exam-checker", "tasks", taskId, "questions", questionId];
	const path = `/v1/exam-checker/tasks/${taskId}/questions/${questionId}`;
	assert.equal(serviceTarget("checker", [...route, "state"], "GET")?.pathname, `${path}/state`);
	assert.equal(serviceTarget("checker", route, "GET")?.pathname, path);
	assert.equal(serviceTarget("checker", [...route, "review"], "POST")?.pathname, `${path}/review`);
	// Reading with POST, or ingesting from this route, is not a supported shape.
	assert.equal(serviceTarget("checker", route, "POST"), undefined);
	assert.equal(serviceTarget("checker", [...route, "ingest"], "POST"), undefined);
	assert.equal(serviceTarget("checker", [...route, "state"], "POST"), undefined);
	// A task route must still name exactly one question.
	assert.equal(serviceTarget("checker", ["v1", "exam-checker", "tasks", taskId], "GET"), undefined);
});

test("HTML downloads use isolated snapshots; no credentials or browser headers go upstream", async () => {
	const original = globalThis.fetch;
	globalThis.fetch = async (input, init) => {
		assert.equal(new URL(String(input)).search, "");
		assert.deepEqual(init?.headers, {});
		return new Response("<html>saved snapshot</html>", { headers: { "content-type": "text/html" } });
	};
	try {
		const request = new Request("http://localhost:3000/api?download=1", {
			headers: { host: "localhost:3000", cookie: "private=secret", authorization: "Bearer private" },
		});
		const response = await proxyService(request, "assembly", ["v1", "exam-assembly", "history", "abc", "student.html"]);
		assert.equal(response.status, 200);
		assert.equal(response.headers.get("cache-control"), "no-store");
		assert.match(response.headers.get("content-security-policy") || "", /sandbox/);
		assert.match(response.headers.get("content-disposition") || "", /student\.html/);
	} finally {
		globalThis.fetch = original;
	}
});

test("upstream business errors retain their status; mutations are not retried", async () => {
	const original = globalThis.fetch;
	let count = 0;
	globalThis.fetch = async () => {
		count++;
		return Response.json({ detail: "not ready" }, { status: 409 });
	};
	try {
		const request = new Request("http://localhost:3000/api", {
			method: "POST",
			headers: { host: "localhost:3000", origin: "http://localhost:3000", "content-type": "application/json" },
			body: "{}",
		});
		const response = await proxyService(request, "assembly", ["v1", "exam-assembly", "assemble"]);
		assert.equal(response.status, 409);
		assert.equal(count, 1);
		assert.deepEqual(await response.json(), { detail: "not ready" });
	} finally {
		globalThis.fetch = original;
	}
});

test("quota validation rejects silent rebalancing, duplicate topics, fractional and mismatched counts", () => {
	assert.equal(validateQuotas(3, 2, [{ name: "树", count: 3 }], [1, 2, 0]), "");
	assert.notEqual(validateQuotas(3, 2, [{ name: "树", count: 2 }], [1, 2, 0]), "");
	assert.notEqual(
		validateQuotas(
			3,
			2,
			[
				{ name: "树", count: 1 },
				{ name: "树", count: 2 },
			],
			[1, 2, 0],
		),
		"",
	);
	assert.notEqual(validateQuotas(3, 1.5, [{ name: "树", count: 3 }], [1, 2, 0]), "");
	assert.notEqual(validateQuotas(3, 2, [{ name: "树", count: 3 }], [0, 1, 0]), "");
});

test("model selections preserve model IDs containing slashes", () => {
	assert.deepEqual(parseModelSelection("openrouter/anthropic/claude-sonnet-4"), {
		provider: "openrouter",
		modelId: "anthropic/claude-sonnet-4",
	});
	assert.equal(parseModelSelection("missing-separator"), undefined);
	assert.equal(parseModelSelection("provider/"), undefined);
});
