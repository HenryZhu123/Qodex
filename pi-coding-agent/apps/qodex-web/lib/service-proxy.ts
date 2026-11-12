import { rejectUnsafeRequest } from "./local-access";

const services = {
	checker: ["EXAM_CHECKER_SERVICE_URL", "http://127.0.0.1:8091"],
	assembly: ["EXAM_ASSEMBLY_SERVICE_URL", "http://127.0.0.1:8092"],
	generation: ["QUESTION_GENERATION_SERVICE_URL", "http://127.0.0.1:8093"],
} as const;

export function serviceTarget(service: string, parts: string[], method: string): URL | undefined {
	if (!(service in services) || parts.some((p) => !/^[\w.-]+$/.test(p) || p === "..")) return undefined;
	const route = parts.join("/");
	const id = "[\\w-]+";
	const rules: Record<string, Record<string, RegExp>> = {
		assembly: {
			GET: new RegExp(`^(health|v1/exam-assembly/history(?:/${id}(?:/(?:answers|student\\.html|answer\\.html))?)?)$`),
			POST: /^v1\/exam-assembly\/assemble$/,
		},
		checker: {
			GET: new RegExp(
				`^(health|v1/question-bank/(search|${id})|v1/exam-checker/documents/${id}(?:/questions(?:/${id}(?:/(state|checker-payload))?)?)?)$`,
			),
			POST: new RegExp(`^v1/exam-checker/documents/(parse|${id}/review|${id}/questions/${id}/(review|revise|ingest))$`),
		},
		generation: { GET: /^health$/, POST: /^v1\/question-generation\/(single|batch|comprehensive|revise)$/ },
	};
	if (!rules[service]?.[method]?.test(route)) return undefined;
	const [name, fallback] = services[service as keyof typeof services];
	const base = new URL(process.env[name] || fallback);
	if (
		base.protocol !== "http:" ||
		!["127.0.0.1", "localhost", "[::1]"].includes(base.hostname) ||
		base.username ||
		base.password
	) {
		throw new Error("Service URL must be a local HTTP address without credentials");
	}
	return new URL(`/${route}`, base);
}

export async function proxyService(request: Request, service: string, parts: string[]): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	try {
		const target = serviceTarget(service, parts, request.method);
		if (!target) return Response.json({ error: "Unknown service route" }, { status: 404 });
		const search = new URL(request.url).searchParams;
		const download = search.get("download") === "1";
		search.delete("download");
		target.search = search.toString();
		const contentType = request.headers.get("content-type") || "";
		let body: ArrayBuffer | undefined;
		if (request.method === "POST") {
			const isUpload = parts.join("/") === "v1/exam-checker/documents/parse";
			const limit = isUpload ? 11 * 1024 * 1024 : 2 * 1024 * 1024;
			if (
				(isUpload && !contentType.startsWith("multipart/form-data;")) ||
				(!isUpload && !contentType.startsWith("application/json"))
			) {
				return Response.json({ error: "Unsupported content type" }, { status: 415 });
			}
			if (Number(request.headers.get("content-length")) > limit)
				return Response.json({ error: "Request too large" }, { status: 413 });
			body = await request.arrayBuffer();
			if (body.byteLength > limit) return Response.json({ error: "Request too large" }, { status: 413 });
		}
		const response = await fetch(target, {
			method: request.method,
			body,
			headers: body ? { "content-type": contentType } : {},
			cache: "no-store",
			redirect: "error",
			signal: AbortSignal.any([request.signal, AbortSignal.timeout(request.method === "POST" ? 600_000 : 30_000)]),
		});
		const headers = new Headers({ "cache-control": "no-store", "x-content-type-options": "nosniff" });
		headers.set("content-type", response.headers.get("content-type") || "application/json");
		if (headers.get("content-type")?.includes("text/html")) {
			headers.set(
				"content-security-policy",
				"sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'",
			);
			if (download) headers.set("content-disposition", `attachment; filename="${parts.at(-1)}"`);
		}
		return new Response(response.body, { status: response.status, headers });
	} catch {
		return Response.json(
			{ error: "服务不可用或请求超时。请检查服务窗口；操作可能已经执行，请先查询记录，不要重复提交。" },
			{ status: 502 },
		);
	}
}
