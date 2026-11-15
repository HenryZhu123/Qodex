import { addBookFromFile } from "@/lib/kb-store";
import { rejectUnsafeRequest } from "@/lib/local-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BYTES = 300 * 1024 * 1024;

/** Upload a book file from the browser; the build runs in the background. */
export async function POST(request: Request): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	try {
		const length = Number(request.headers.get("content-length") ?? 0);
		if (length > MAX_BYTES) throw new Error("文件超过 300 MB。");
		const form = await request.formData();
		const subjectKey = String(form.get("subjectKey") ?? "");
		const upload = form.get("file");
		if (!subjectKey) throw new Error("请先选择要存放的专业。");
		if (!(upload instanceof File) || upload.size === 0) throw new Error("请选择要上传的书籍文件。");
		if (upload.size > MAX_BYTES) throw new Error("文件超过 300 MB。");
		const result = await addBookFromFile(subjectKey, upload.name, Buffer.from(await upload.arrayBuffer()));
		return Response.json(result, { status: 202 });
	} catch (error) {
		return Response.json({ error: error instanceof Error ? error.message : "上传失败" }, { status: 400 });
	}
}
