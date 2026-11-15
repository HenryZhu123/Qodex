/** This teacher workspace is intentionally restricted to local development. */
export function rejectUnsafeRequest(request: Request): Response | undefined {
	if (process.env.NODE_ENV !== "development") return new Response(null, { status: 404 });
	const host = request.headers.get("host");
	if (!host) return new Response(null, { status: 403 });
	let url: URL;
	try {
		url = new URL(`${new URL(request.url).protocol}//${host}`);
	} catch {
		return new Response(null, { status: 403 });
	}
	if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) return new Response(null, { status: 403 });
	const origin = request.headers.get("origin");
	const site = request.headers.get("sec-fetch-site");
	if (origin !== null && origin !== url.origin) return new Response(null, { status: 403 });
	if (site !== null && site !== "same-origin" && site !== "none") return new Response(null, { status: 403 });
	if (
		request.method !== "GET" &&
		request.method !== "HEAD" &&
		!origin &&
		!site &&
		request.headers.get("content-type")?.split(";", 1)[0] !== "application/json"
	) {
		return new Response(null, { status: 403 });
	}
	return undefined;
}
