import { createSubject, listSubjects } from "@/lib/kb-store";
import { rejectUnsafeRequest } from "@/lib/local-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	try {
		return Response.json(await listSubjects());
	} catch (error) {
		return Response.json({ error: error instanceof Error ? error.message : "读取知识库失败" }, { status: 500 });
	}
}

export async function POST(request: Request): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	try {
		const body = (await request.json()) as { key?: unknown; name?: unknown };
		const created = await createSubject(String(body.key ?? ""), String(body.name ?? ""));
		return Response.json(created, { status: 201 });
	} catch (error) {
		return Response.json({ error: error instanceof Error ? error.message : "创建专业失败" }, { status: 400 });
	}
}
