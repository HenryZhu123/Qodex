import type { InlineExtension } from "../core/extensions/types.ts";
import examCheckerExtension from "./exam-checker/index.ts";
import llamaExtension from "./llama/index.ts";
import questionGenerationExtension from "./question-generation/index.ts";

export const builtInExtensions: InlineExtension[] = [
	{ name: "exam-checker", factory: examCheckerExtension },
	{ name: "question-generation", factory: questionGenerationExtension },
	{ name: "llama.cpp", factory: llamaExtension, hidden: true },
];
