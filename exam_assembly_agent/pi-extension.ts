import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const workspace = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const parameters = Type.Object({
  bank: Type.Union([Type.Literal("development"), Type.Literal("repair_success"), Type.Literal("repair_failure")],
    { description: "Fixed mock bank. Use development for ordinary tasks; repair banks only for explicit repair demos." }),
  request: Type.Object({
    request_id: Type.String(),
    subject: Type.String(),
    question_type: Type.Literal("single_choice"),
    question_count: Type.Integer({ minimum: 1, maximum: 100 }),
    score_per_question: Type.Integer({ minimum: 1 }),
    total_score: Type.Integer({ minimum: 1 }),
    topic_counts: Type.Record(Type.String(), Type.Integer({ minimum: 0 })),
    difficulty_counts: Type.Record(Type.String(), Type.Integer({ minimum: 0 })),
    max_repair_rounds: Type.Optional(Type.Integer({ minimum: 0, maximum: 10 })),
    allow_mock_reviews: Type.Boolean({ description: "Must be explicitly true for an authorized development demo; never infer actual review acceptance." }),
  }),
});

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "exam_assembly",
    label: "Exam assembly (development)",
    description: "Assemble an exam from fixed local mock-reviewed banks; validate counts, scores, topic/difficulty quotas and identical stems, repair duplicates or report shortages. Writes separate local student, answer and report artifacts. No real database or semantic certification.",
    promptSnippet: "Assemble development exams and return constraint checks or missing-question requirements",
    promptGuidelines: [
      "Call exam_assembly for assembly rather than inventing an exam or tool result. Preserve all explicit user constraints.",
      "Ask for missing quotas or label proposed defaults; do not silently adjust inconsistent requirements.",
      "Only use mock-reviewed banks when the user requests or accepts a development demo. State mock mode in the final response.",
      "STRUCTURAL_PASS is not full quality acceptance. Report NEEDS_QUESTIONS, INVALID_REQUEST, INCOMPLETE or TOOL_ERROR honestly.",
      "On shortage return the missing requirements to the coordinator; generated questions must independently pass review before resuming. This demo cannot actually generate or review questions.",
    ],
    parameters,
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      const encoded = Buffer.from(JSON.stringify(params.request), "utf8").toString("base64");
      const python = process.env.QODEX_PYTHON || "python";
      try {
        const result = await pi.exec(python,
          ["-X", "utf8", "-m", "exam_assembly_agent.pi_bridge", "--bank", params.bank, "--request-base64", encoded],
          { cwd: workspace, signal, timeout: 60000 });
        if (result.killed || result.code !== 0) {
          return { content: [{ type: "text", text: JSON.stringify({ status: "TOOL_ERROR", message: "Python bridge failed, was cancelled or timed out. Check QODEX_PYTHON and the local Python module." }) }],
            details: { code: result.code, killed: result.killed }, isError: true };
        }
        const parsed: unknown = JSON.parse(result.stdout);
        if (typeof parsed !== "object" || parsed === null || !("status" in parsed)) {
          throw new Error("Invalid bridge response");
        }
        return { content: [{ type: "text", text: JSON.stringify(parsed) }], details: { result: parsed } };
      } catch {
        return { content: [{ type: "text", text: JSON.stringify({ status: "TOOL_ERROR", message: "Could not execute or parse the Python bridge result." }) }],
          details: {}, isError: true };
      }
    },
  });
}
