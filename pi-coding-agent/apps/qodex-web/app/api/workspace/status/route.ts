import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { rejectUnsafeRequest } from "@/lib/local-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export function GET(request: Request): Response {
	const rejected = rejectUnsafeRequest(request);
	if (rejected) return rejected;
	const root = process.env.PI_WORKSPACE_PATH || resolve(process.cwd(), "../../..");
	const kb = process.env.EXAM_CHECKER_KB_DIR || resolve(root, "pi-coding-agent/services/exam-checker/knowledge-base");
	const available = ["data_structure", "computer_organization", "operating_system", "computer_network"].filter((s) =>
		existsSync(resolve(kb, s, "kb.sqlite")),
	);
	return Response.json(
		{
			model_key_configured: Boolean(process.env.DEEPSEEK_API_KEY || process.env.EXAM_CHECKER_LLM_API_KEY),
			knowledge_base_subjects: available,
		},
		{ headers: { "cache-control": "no-store" } },
	);
}
