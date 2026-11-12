import { proxyService } from "@/lib/service-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ service: string; path: string[] }> };
async function handle(request: Request, context: Context): Promise<Response> {
	const { service, path } = await context.params;
	return proxyService(request, service, path);
}
export const GET = handle;
export const POST = handle;
