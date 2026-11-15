import { addBook, registerExisting } from "@/lib/kb-store";
import { rejectUnsafeRequest } from "@/lib/local-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Add a book: either build a knowledge base from a PDF, or register an existing SQLite one. */
export async function POST(request: Request): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	try {
		const body = (await request.json()) as { subjectKey?: unknown; path?: unknown; sqlitePath?: unknown };
		const subjectKey = String(body.subjectKey ?? "").trim();
		if (!subjectKey) throw new Error("请先选择要存放的专业。");
		if (body.sqlitePath) {
			const result = await registerExisting(subjectKey, String(body.sqlitePath));
			return Response.json(result, { status: 201 });
		}
		const result = await addBook(subjectKey, String(body.path ?? ""));
		return Response.json(result, { status: 202 });
	} catch (error) {
		return Response.json({ error: error instanceof Error ? error.message : "添加书籍失败" }, { status: 400 });
	}
}
