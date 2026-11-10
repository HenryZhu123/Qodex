import { expect, expectTypeOf, it } from "vitest";
import { getSupportedThinkingLevels } from "../src/models.ts";
import { getBuiltinModel } from "../src/providers/all.ts";
import { deepseekProvider } from "../src/providers/deepseek.ts";

it("keeps the verified DeepSeek Flash ID available alongside the release baseline", () => {
	const model = getBuiltinModel("deepseek", "deepseek-flash");
	expectTypeOf(model.api).toEqualTypeOf<"openai-completions">();
	expect(model.baseUrl).toBe("https://api.deepseek.com");
	expect(model.compat?.thinkingFormat).toBe("deepseek");
	expect(getSupportedThinkingLevels(model)).toEqual(["off", "low", "high", "max"]);
	expect(
		deepseekProvider()
			.getModels()
			.map((entry) => entry.id),
	).toContain("deepseek-flash");
	expect(getBuiltinModel("deepseek", "deepseek-v4-flash")).toBeDefined();
});
