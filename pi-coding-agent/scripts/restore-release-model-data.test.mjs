import assert from "node:assert/strict";
import test from "node:test";
import { prepareCatalog, verifyArchive } from "./restore-release-model-data.mjs";

const baseline = {
	"openai-completions": { old: { id: "old", api: "openai-completions", provider: "test", name: "Original" } },
};
const addition = { id: "new", api: "openai-completions", provider: "test", name: "New" };

test("preserves release IDs and adds an explicit model without replacing metadata", () => {
	const result = prepareCatalog(["test"], () => JSON.stringify(baseline), {
		test: { "openai-completions": { new: addition } },
	});
	assert.deepEqual(JSON.parse(result.contents["test.json"]), {
		"openai-completions": { ...baseline["openai-completions"], new: addition },
	});
	assert.deepEqual(result.structure, { test: { old: "openai-completions", new: "openai-completions" } });
});

test("rejects replacing a release model, including moving it to another API", () => {
	assert.throws(() => prepareCatalog(["test"], () => JSON.stringify(baseline), {
		test: { "anthropic-messages": { old: { ...addition, id: "old", api: "anthropic-messages" } } },
	}), /must not replace/);
});

test("rejects unknown providers and mismatched model identity", () => {
	assert.throws(() => prepareCatalog(["test"], () => "{}", { unknown: {} }), /Unknown added provider/);
	for (const field of ["id", "api", "provider"]) {
		assert.throws(() => prepareCatalog(["test"], () => "{}", {
			test: { "openai-completions": { new: { ...addition, [field]: "wrong" } } },
		}), /Inconsistent added model identity/);
	}
});

test("rejects corrupt archives before reading or replacing local catalogs", () => {
	assert.throws(() => verifyArchive(Buffer.from("invalid archive")), /integrity mismatch/);
});

// Regression for upstream #9209: all Copilot GPT models use Responses.
test("applies source Copilot routing without moving Gemini or keeping completions compat", () => {
	const models = {
		"openai-completions": {
			"gpt-6-astra": { id: "gpt-6-astra", api: "openai-completions", name: "GPT", compat: { supportsStore: false } },
			gemini: { id: "gemini", api: "openai-completions", name: "Gemini" },
		},
	};
	const result = prepareCatalog(["github-copilot"], () => JSON.stringify(models), {});
	const groups = JSON.parse(result.contents["github-copilot.json"]);
	assert.equal(groups["openai-responses"]["gpt-6-astra"].api, "openai-responses");
	assert.equal(groups["openai-responses"]["gpt-6-astra"].compat, undefined);
	assert.equal(groups["openai-completions"]["gpt-6-astra"], undefined);
	assert.equal(groups["openai-completions"].gemini.name, "Gemini");
	assert.equal(result.structure["github-copilot"]["gpt-6-astra"], "openai-responses");
});

// Regression for upstream #9323: source fixes must survive release hydration.
test("preserves Fireworks native tools, unsigned thinking and distinct effort levels", () => {
	const models = {
		"anthropic-messages": {
			"accounts/fireworks/models/deepseek-v4-flash-0731": { compat: { supportsCacheControlOnTools: false } },
			"accounts/fireworks/models/kimi-k2p6": {},
		},
		"openai-completions": {
			"accounts/fireworks/models/glm-5p2": { thinkingLevelMap: { high: "high", max: "max", low: "high" } },
			"accounts/fireworks/models/kimi-k3": { thinkingLevelMap: { low: "low", medium: "medium", high: "high" } },
		},
	};
	const result = prepareCatalog(["fireworks"], () => JSON.stringify(models), {});
	const groups = JSON.parse(result.contents["fireworks.json"]);
	const deepseek = groups["anthropic-messages"]["accounts/fireworks/models/deepseek-v4-flash-0731"];
	assert.equal(deepseek.compat.allowEmptySignature, true);
	assert.equal(deepseek.compat.supportsToolReferences, true);
	assert.equal(deepseek.compat.supportsCacheControlOnTools, false);
	assert.equal(deepseek.compat.forceAdaptiveThinking, true);
	assert.equal(deepseek.thinkingLevelMap.medium, null);
	assert.equal(groups["anthropic-messages"]["accounts/fireworks/models/kimi-k2p6"].compat.forceAdaptiveThinking, undefined);
	assert.equal(groups["openai-completions"]["accounts/fireworks/models/glm-5p2"].thinkingLevelMap.low, null);
	assert.equal(groups["openai-completions"]["accounts/fireworks/models/kimi-k3"].thinkingLevelMap.medium, null);
});
