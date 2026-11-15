import { subjectDetail } from "@/lib/kb-store";
import { rejectUnsafeRequest } from "@/lib/local-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ key: string }> };

export async function GET(request: Request, context: Context): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	const { key } = await context.params;
	try {
		return Response.json(await subjectDetail(key));
	} catch (error) {
		return Response.json({ error: error instanceof Error ? error.message : "读取专业失败" }, { status: 404 });
	}
}
