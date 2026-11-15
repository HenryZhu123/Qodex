import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const compiler = join(root, "node_modules/@typescript/native-preview/bin/tsgo.js");
if (!existsSync(join(root, "packages/ai/src/providers/data/.manifest.json"))) {
	throw new Error("Run npm run hydrate:model-data:release in pi-coding-agent before starting the Web app.");
}
for (const name of ["chord", "tui", "telemetry", "ai", "agent", "session-backends/sqlite-node", "protocol", "client", "server", "coding-agent"]) {
	console.log(`[qodex] Preparing ${name}`);
	execFileSync(process.execPath, [compiler, "-p", join(root, "packages", name, "tsconfig.build.json")], { cwd: root, stdio: "inherit" });
}
cpSync(join(root, "packages/ai/src/providers/data"), join(root, "packages/ai/dist/providers/data"), { recursive: true });
execFileSync(process.execPath, [join(root, "packages/session-backends/sqlite-node/scripts/copy-migrations.mjs")], {
	cwd: join(root, "packages/session-backends/sqlite-node"), stdio: "inherit",
});
const agent = join(root, "packages/coding-agent");
for (const [from, to] of [["src/modes/interactive/theme", "dist/modes/interactive/theme"], ["src/modes/interactive/assets", "dist/modes/interactive/assets"], ["src/core/export-html", "dist/core/export-html"]]) {
	mkdirSync(join(agent, to), { recursive: true });
	cpSync(join(agent, from), join(agent, to), { recursive: true, filter: (source) => !source.endsWith(".ts") });
}
console.log("[qodex] Pi SDK ready; no model API was called.");
