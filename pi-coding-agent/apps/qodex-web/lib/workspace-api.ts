export type JsonObject = Record<string, unknown>;
export function object(value: unknown): JsonObject {
	return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as JsonObject) : {};
}
export function array(value: unknown): unknown[] {
	return Array.isArray(value) ? value : [];
}
export function text(value: unknown): string {
	return typeof value === "string" ? value : value == null ? "" : String(value);
}
export function pretty(value: unknown): string {
	return JSON.stringify(value, null, 2);
}
export async function api(path: string, options?: RequestInit): Promise<JsonObject> {
	const response = await fetch(`/api/services/${path}`, { ...options, cache: "no-store" });
	const data: unknown = await response.json();
	if (!response.ok)
		throw new Error(`${response.status} · ${pretty(object(data).detail ?? object(data).error ?? data)}`);
	return object(data);
}
export function post(path: string, body: unknown): Promise<JsonObject> {
	return api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}
export function statusLabel(status: unknown): string {
	const labels: Record<string, string> = {
		STRUCTURAL_PASS: "已生成",
		NEEDS_QUESTIONS: "题量不足",
		UNRESOLVED: "待复核",
		INVALID_REQUEST: "需求有误",
		TOOL_ERROR: "服务异常",
		PASS: "审校通过",
		NEEDS_REVISION: "需要修订",
	};
	return labels[text(status)] || text(status);
}
export function badgeClass(status: unknown): string {
	return status === "STRUCTURAL_PASS" || status === "PASS"
		? "green"
		: status === "NEEDS_QUESTIONS" || status === "INVALID_REQUEST"
			? "amber"
			: "gray";
}
export function historyUrl(id: string, suffix = ""): string {
	return `assembly/v1/exam-assembly/history/${encodeURIComponent(id)}${suffix}`;
}
export function validateQuotas(
	count: number,
	points: number,
	topics: { name: string; count: number }[],
	difficulties: number[],
): string {
	if (!Number.isInteger(count) || count < 1 || count > 100 || !Number.isInteger(points) || points < 1)
		return "题数须为 1–100 的整数，每题分值须为正整数。";
	if (
		!topics.length ||
		topics.some((t) => !t.name.trim() || !Number.isInteger(t.count) || t.count < 0) ||
		new Set(topics.map((t) => t.name.trim())).size !== topics.length
	)
		return "知识点名称须非空且不重复，配额须为非负整数。";
	if (
		difficulties.some((n) => !Number.isInteger(n) || n < 0) ||
		difficulties.reduce((a, b) => a + b, 0) !== count ||
		topics.reduce((a, b) => a + b.count, 0) !== count
	)
		return "知识点配额与难度配额都必须分别等于题目总数。";
	return "";
}
