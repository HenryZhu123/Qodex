import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
	createModelDataManifest,
	readModelDataProviderIds,
	validateModelDataDirectory,
} from "../packages/ai/scripts/model-data.ts";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packageRoot = join(repoRoot, "packages/ai");
// The archive is a release baseline, not today's live provider availability list.
export const RELEASE = {
	version: "0.85.1",
	archive: "earendil-works-pi-ai-0.85.1.tgz",
	integrity: "sha512-+VgVIJDkDO2efYJKEEqvPTH4zmnIaXdAppGbO+vKFA9qy5PdhFiAenuFAkU+oiCSfOC4dMHDyrjdQeL4ZoC5CQ==",
};

// Verified effort fallbacks already declared in generate-models.ts (#9323).
const fireworksAdaptiveIds = new Set([
	"accounts/fireworks/models/deepseek-v4-flash-0731",
	"accounts/fireworks/models/deepseek-v4-flash-vision-exp",
	"accounts/fireworks/models/deepseek-v4-pro-0813",
	"accounts/fireworks/models/qwen3p8-max",
	"accounts/fireworks/models/qwen3p8-2p4t-a95b",
]);

export function verifyArchive(bytes) {
	const integrity = `sha512-${createHash("sha512").update(bytes).digest("base64")}`;
	if (integrity !== RELEASE.integrity) throw new Error("Pi release archive integrity mismatch; model data was not changed");
}

export function prepareCatalog(providerIds, readProvider, additions) {
	for (const provider of Object.keys(additions)) {
		if (!providerIds.includes(provider)) throw new Error(`Unknown added provider: ${provider}`);
	}
	const structure = {};
	const contents = {};
	for (const provider of providerIds) {
		const groups = JSON.parse(readProvider(provider));
		// Match the source generator's Copilot routing fix for #9209. The release
		// archive predates it for gpt-6-astra; completions compat is not Responses compat.
		if (provider === "github-copilot") {
			for (const [id, model] of Object.entries(groups["openai-completions"] ?? {})) {
				if (!["gpt-", "grok-", "oswe", "mai-"].some((prefix) => id.startsWith(prefix))) continue;
				const { compat: _completionsCompat, ...metadata } = model;
				groups["openai-responses"] ??= {};
				groups["openai-responses"][id] = { ...metadata, api: "openai-responses" };
				delete groups["openai-completions"][id];
			}
		}
		if (provider === "fireworks") {
			for (const [id, model] of Object.entries(groups["anthropic-messages"] ?? {})) {
				model.compat = { ...model.compat, allowEmptySignature: true, supportsToolReferences: true };
				if (fireworksAdaptiveIds.has(id)) {
					model.compat.forceAdaptiveThinking = true;
					model.thinkingLevelMap = id.includes("deepseek-")
						? { minimal: null, low: "low", medium: null, high: "high", xhigh: null, max: "max" }
						: { minimal: null, low: "low", medium: "medium", high: null, xhigh: "xhigh", max: null };
				}
			}
			for (const [id, model] of Object.entries(groups["openai-completions"] ?? {})) {
				if (id.includes("glm-5p2")) {
					model.thinkingLevelMap = { ...model.thinkingLevelMap, low: null, medium: null };
				} else if (id.includes("kimi-k3")) {
					model.thinkingLevelMap = { ...model.thinkingLevelMap, medium: null };
				}
			}
		}
		const modelIds = new Set(Object.values(groups).flatMap((group) => Object.keys(group)));
		for (const [api, models] of Object.entries(additions[provider] ?? {})) {
			for (const [id, model] of Object.entries(models)) {
				if (modelIds.has(id)) throw new Error(`Addition must not replace release model: ${provider}/${id}`);
				if (model.id !== id || model.provider !== provider || model.api !== api) {
					throw new Error(`Inconsistent added model identity: ${provider}/${id}`);
				}
				groups[api] ??= {};
				groups[api][id] = model;
				modelIds.add(id);
			}
		}
		structure[provider] = Object.fromEntries(
			Object.entries(groups).flatMap(([api, models]) => Object.keys(models).map((id) => [id, api])),
		);
		contents[`${provider}.json`] = JSON.stringify(groups);
	}
	return { structure, contents };
}

export function restoreReleaseModelData(archive) {
	const sourceVersion = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8")).version;
	if (sourceVersion !== RELEASE.version) throw new Error(`Release baseline does not match source version ${sourceVersion}`);
	verifyArchive(readFileSync(archive));
	const extract = (name) => execFileSync("tar", ["-xOf", archive, `package/${name}`], { encoding: "utf8", maxBuffer: 8_000_000 });
	const published = JSON.parse(extract("package.json"));
	if (published.name !== "@earendil-works/pi-ai" || published.version !== sourceVersion) {
		throw new Error("Unexpected Pi release package");
	}
	const providerIds = readModelDataProviderIds(packageRoot);
	const additions = JSON.parse(readFileSync(join(repoRoot, "scripts/release-model-additions.json"), "utf8"));
	const { structure, contents } = prepareCatalog(providerIds, (provider) => extract(`dist/providers/data/${provider}.json`), additions);
	const manifest = createModelDataManifest(structure, contents, new Date().toISOString());
	const providersDir = join(packageRoot, "src/providers");
	const staging = mkdtempSync(join(providersDir, ".model-generation-release-"));
	for (const [name, content] of Object.entries(contents)) writeFileSync(join(staging, name), content);
	writeFileSync(join(staging, ".manifest.json"), JSON.stringify(manifest));
	validateModelDataDirectory(structure, staging);
	const cache = join(repoRoot, "../outputs/model-baseline");
	mkdirSync(cache, { recursive: true });
	const dataDir = join(providersDir, "data");
	let backup;
	if (existsSync(dataDir)) {
		backup = join(mkdtempSync(join(cache, "previous-")), "data");
		renameSync(dataDir, backup);
	}
	try {
		renameSync(staging, dataDir);
	} catch (error) {
		if (backup) renameSync(backup, dataDir);
		throw error;
	}
	return { sourceVersion, providers: providerIds.length, backup, dataDir };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	try {
		const args = process.argv.slice(2);
		if (args.length && (args.length !== 2 || args[0] !== "--archive")) {
			throw new Error("Usage: node scripts/restore-release-model-data.mjs [--archive path]");
		}
		const cache = join(repoRoot, "../outputs/model-baseline");
		mkdirSync(cache, { recursive: true });
		const archive = args.length ? resolve(args[1]) : join(cache, RELEASE.archive);
		if (!existsSync(archive) && !args.length) {
			const npmArgs = ["pack", `@earendil-works/pi-ai@${RELEASE.version}`, "--ignore-scripts", "--registry=https://registry.npmjs.org", "--pack-destination", cache, "--json"];
			if (process.platform === "win32") {
				execFileSync(process.execPath, [join(dirname(process.execPath), "node_modules/npm/bin/npm-cli.js"), ...npmArgs], { stdio: "pipe" });
			} else {
				execFileSync("npm", npmArgs, { stdio: "pipe" });
			}
		}
		console.log(JSON.stringify(restoreReleaseModelData(archive), null, 2));
	} catch (error) {
		console.error(error instanceof Error ? error.message : String(error));
		process.exitCode = 1;
	}
}
