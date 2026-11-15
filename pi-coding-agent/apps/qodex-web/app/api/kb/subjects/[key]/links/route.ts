import { linkKb, unlinkKb } from "@/lib/kb-store";
import { rejectUnsafeRequest } from "@/lib/local-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ key: string }> };

export async function POST(request: Request, context: Context): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	const { key } = await context.params;
	try {
		const body = (await request.json()) as { kbId?: unknown };
		return Response.json(await linkKb(key, String(body.kbId ?? "")));
	} catch (error) {
		return Response.json({ error: error instanceof Error ? error.message : "链接失败" }, { status: 400 });
	}
}

export async function DELETE(request: Request, context: Context): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	const { key } = await context.params;
	try {
		const kbId = new URL(request.url).searchParams.get("kbId") ?? "";
		return Response.json(await unlinkKb(key, kbId));
	} catch (error) {
		return Response.json({ error: error instanceof Error ? error.message : "取消链接失败" }, { status: 400 });
	}
}
