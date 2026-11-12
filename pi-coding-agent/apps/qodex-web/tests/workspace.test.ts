import assert from "node:assert/strict";
import { test } from "node:test";
import { rejectUnsafeRequest } from "../lib/local-access";
import { proxyService, serviceTarget } from "../lib/service-proxy";
import { validateQuotas } from "../lib/workspace-api";

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
