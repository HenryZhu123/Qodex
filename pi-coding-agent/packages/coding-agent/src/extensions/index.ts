import type { InlineExtension } from "../core/extensions/types.ts";
import examAssemblyExtension from "./exam-assembly/index.ts";
import examCheckerExtension from "./exam-checker/index.ts";
import llamaExtension from "./llama/index.ts";
import qodexWorkflowExtension from "./qodex-workflow/index.ts";
import questionGenerationExtension from "./question-generation/index.ts";

export const builtInExtensions: InlineExtension[] = [
	{ name: "qodex-workflow", factory: qodexWorkflowExtension },
	{ name: "exam-checker", factory: examCheckerExtension },
	{ name: "exam-assembly", factory: examAssemblyExtension },
	{ name: "question-generation", factory: questionGenerationExtension },
	{ name: "llama.cpp", factory: llamaExtension, hidden: true },
];
