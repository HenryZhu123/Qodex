import { addBookFromFile, getBuildJob } from "@/lib/kb-store";
import { rejectUnsafeRequest } from "@/lib/local-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BYTES = 300 * 1024 * 1024;
const MAX_MULTIPART_BYTES = MAX_BYTES + 64 * 1024;

export async function GET(request: Request): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	const params = new URL(request.url).searchParams;
	const job = await getBuildJob(params.get("kbId") ?? "", params.get("jobId") ?? "");
	return job ? Response.json(job) : Response.json({ error: "未找到构建任务。" }, { status: 404 });
}

/** Upload a book file from the browser; the build runs in the background. */
export async function POST(request: Request): Promise<Response> {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	try {
		const length = Number(request.headers.get("content-length") ?? 0);
		if (length > MAX_MULTIPART_BYTES) throw new Error("文件超过 300 MB。");
		const form = await request.formData();
		const subjectKey = String(form.get("subjectKey") ?? "");
		const upload = form.get("file");
		if (!(upload instanceof File) || upload.size === 0) throw new Error("请选择要上传的书籍文件。");
		if (upload.size > MAX_BYTES) throw new Error("文件超过 300 MB。");
		const result = await addBookFromFile(subjectKey, upload.name, Buffer.from(await upload.arrayBuffer()));
		return Response.json(result, { status: 202 });
	} catch (error) {
		return Response.json({ error: error instanceof Error ? error.message : "上传失败" }, { status: 400 });
	}
}
