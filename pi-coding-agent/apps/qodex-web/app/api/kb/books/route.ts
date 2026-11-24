import { addBook, deleteBook, KbConflictError, registerExisting } from "@/lib/kb-store";
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

export async function DELETE(request: Request): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	try {
		const body = (await request.json()) as { kbId?: unknown; subjectKeys?: unknown };
		if (
			typeof body.kbId !== "string" ||
			!Array.isArray(body.subjectKeys) ||
			!body.subjectKeys.every((key: unknown) => typeof key === "string")
		) {
			return Response.json({ error: "缺少书目或确认时的关联专业。" }, { status: 400 });
		}
		return Response.json(await deleteBook(body.kbId, body.subjectKeys));
	} catch (error) {
		return Response.json(
			{ error: error instanceof Error ? error.message : "删除书目失败" },
			{ status: error instanceof KbConflictError ? 409 : 400 },
		);
	}
}
