import type { NextRequest } from "next/server";
import type {
	PiClient,
	PiHostUiResponse,
	PiSendMessageInput,
	PiThinkingLevel,
} from "@assistant-ui/react-pi";
import { getPiClient, workspacePath } from "@/lib/pi-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

const loopbackHostnames = new Set(["localhost", "127.0.0.1", "[::1]"]);

function rejectUnsafeRequest(request: Request): Response | undefined {
	if (process.env.NODE_ENV !== "development") return new Response(null, { status: 404 });

	const host = request.headers.get("host");
	if (!host) return new Response(null, { status: 403 });
	let requestOrigin: URL;
	try {
		requestOrigin = new URL(`${new URL(request.url).protocol}//${host}`);
	} catch {
		return new Response(null, { status: 403 });
	}
	if (!loopbackHostnames.has(requestOrigin.hostname)) return new Response(null, { status: 403 });

	const fetchSite = request.headers.get("sec-fetch-site");
	const origin = request.headers.get("origin");
	if (origin !== null && origin !== requestOrigin.origin) return new Response(null, { status: 403 });
	if (fetchSite !== null && fetchSite !== "same-origin" && fetchSite !== "none") {
		return new Response(null, { status: 403 });
	}
	if (
		request.method !== "GET" &&
		request.method !== "HEAD" &&
		origin === null &&
		fetchSite === null &&
		request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() !== "application/json"
	) {
		return new Response(null, { status: 403 });
	}
	return undefined;
}

function noContent(): Response {
	return new Response(null, { status: 204 });
}

function jsonError(error: unknown): Response {
	return Response.json({ error: error instanceof Error ? error.message : String(error) }, { status: 500 });
}

function notFound(): Response {
	return Response.json({ error: "Unknown Pi API route" }, { status: 404 });
}

async function guarded(
	request: NextRequest,
	context: RouteContext,
	handler: (path: string[]) => Promise<Response>,
): Promise<Response> {
	const rejection = rejectUnsafeRequest(request);
	if (rejection) return rejection;
	try {
		const { path } = await context.params;
		return await handler(path);
	} catch (error) {
		return jsonError(error);
	}
}

export function GET(request: NextRequest, context: RouteContext): Promise<Response> {
	return guarded(request, context, async (path) => {
		if (path.length === 1 && path[0] === "handshake") {
			return Response.json({ workspacePath, phase: "phase-0" as const });
		}
		const piClient = await getPiClient();
		if (path.length === 1 && path[0] === "models") {
			return Response.json(await piClient.getAvailableModels());
		}
		if (path.length === 1 && path[0] === "threads") {
			const search = request.nextUrl.searchParams;
			return Response.json(
				await piClient.listThreads({
					workspacePath: search.get("workspacePath") ?? workspacePath,
					includeArchived: search.get("includeArchived") === "true",
				}),
			);
		}
		if (path.length === 2 && path[0] === "threads") {
			return Response.json(await piClient.getThread(path[1]));
		}
		if (path.length === 3 && path[0] === "threads" && path[2] === "events") {
			return createEventStream(request, path[1], piClient);
		}
		return notFound();
	});
}

export function POST(request: NextRequest, context: RouteContext): Promise<Response> {
	return guarded(request, context, async (path) => {
		const piClient = await getPiClient();
		if (path.length === 1 && path[0] === "threads") {
			const body = (await request.json().catch(() => ({}))) as NonNullable<
				Parameters<PiClient["createThread"]>[0]
			>;
			return Response.json(await piClient.createThread({ ...body, workspacePath: body.workspacePath ?? workspacePath }));
		}
		if (path.length < 3 || path[0] !== "threads") return notFound();

		const threadId = path[1];
		const action = path.slice(2).join("/");
		switch (action) {
			case "messages": {
				const { input } = (await request.json()) as { input: PiSendMessageInput };
				await piClient.sendMessage(threadId, input);
				return noContent();
			}
			case "cancel":
				await piClient.cancelRun(threadId);
				return noContent();
			case "queue/clear":
				return Response.json(await piClient.clearQueue(threadId));
			case "model": {
				const input = (await request.json()) as { provider: string; modelId: string };
				await piClient.setModel(threadId, input);
				return noContent();
			}
			case "thinking": {
				const { level } = (await request.json()) as { level: PiThinkingLevel };
				await piClient.setThinkingLevel(threadId, level);
				return noContent();
			}
			case "archive":
				await piClient.archiveThread(threadId);
				return noContent();
			case "unarchive":
				await piClient.unarchiveThread(threadId);
				return noContent();
			case "host-ui": {
				const { response } = (await request.json()) as { response: PiHostUiResponse };
				await piClient.respondToHostUiRequest(threadId, response);
				return noContent();
			}
			default:
				return notFound();
		}
	});
}

export function PATCH(request: NextRequest, context: RouteContext): Promise<Response> {
	return guarded(request, context, async (path) => {
		const piClient = await getPiClient();
		if (path.length !== 2 || path[0] !== "threads") return notFound();
		const { title } = (await request.json()) as { title?: unknown };
		if (typeof title !== "string" || title.trim() === "") {
			return Response.json({ error: "title must be a non-empty string" }, { status: 400 });
		}
		await piClient.renameThread(path[1], title);
		return noContent();
	});
}

export function DELETE(request: NextRequest, context: RouteContext): Promise<Response> {
	return guarded(request, context, async (path) => {
		const piClient = await getPiClient();
		if (path.length !== 2 || path[0] !== "threads") return notFound();
		await piClient.deleteThread(path[1]);
		return noContent();
	});
}

function createEventStream(request: NextRequest, threadId: string, piClient: PiClient): Response {
	const encoder = new TextEncoder();
	const stream = new TransformStream<Uint8Array, Uint8Array>();
	const writer = stream.writable.getWriter();
	let unsubscribe: (() => void) | undefined;
	let heartbeat: ReturnType<typeof setInterval> | undefined;
	let closed = false;

	const write = (value: string) => {
		if (closed) return;
		void writer.write(encoder.encode(value)).catch(() => close());
	};
	const close = () => {
		if (closed) return;
		closed = true;
		unsubscribe?.();
		if (heartbeat) clearInterval(heartbeat);
		void writer.close().catch(() => {});
	};

	write(": connected\n\n");
	heartbeat = setInterval(() => write(": ping\n\n"), 20_000);
	heartbeat.unref?.();
	unsubscribe = piClient.subscribe(
		threadId,
		(event) => write(`data: ${JSON.stringify(event)}\n\n`),
		{ includeSnapshot: request.nextUrl.searchParams.get("snapshot") !== "false" },
	);
	request.signal.addEventListener("abort", close, { once: true });
	if (request.signal.aborted) close();

	return new Response(stream.readable, {
		headers: {
			"cache-control": "no-cache, no-transform",
			connection: "keep-alive",
			"content-type": "text/event-stream; charset=utf-8",
		},
	});
}
