# Qodex Web — assistant-ui

This local-only Web frontend uses the official `@assistant-ui/react-pi` adapter
with the complete Qodex Pi SDK in this repository. Its package dependency points
to `../../packages/coding-agent`, so the Web process loads the same built-in
extensions as the terminal client: `exam_checker`, `question_bank`,
`exam_assembly`, and `question_generation`.

## Run

Install the root Pi dependencies once, then install and start the Web app:

```bash
cd pi-coding-agent
npm ci --ignore-scripts
cd apps/qodex-web
npm ci --ignore-scripts --workspaces=false --no-audit
npm run dev
```

`npm run dev` first rebuilds the unbundled local coding-agent package. This is
required because the assistant-ui Pi adapter imports the package entry point,
while the terminal development launcher can execute source files directly.

The server binds to `127.0.0.1`. Open <http://127.0.0.1:3000>.

Pi uses `PI_PROVIDER` and `PI_MODEL_ID` when they are set; otherwise it falls back to the model configured in `~/.pi/agent`. The unified root demo exports `deepseek` / `deepseek-flash` and the repository root workspace. To use another configuration directory or a scratch workspace:

```bash
PI_CODING_AGENT_DIR=/absolute/path/to/pi/agent \
PI_WORKSPACE_PATH=/absolute/path/to/scratch/workspace \
npm run dev
```

Start the corresponding local services before calling Qodex tools:

- exam checker and question bank: `http://127.0.0.1:8091`;
- exam assembly: `http://127.0.0.1:8092`;
- question generation: `http://127.0.0.1:8093`.

Override these defaults through `EXAM_CHECKER_SERVICE_URL`,
`EXAM_ASSEMBLY_SERVICE_URL`, and `QUESTION_GENERATION_SERVICE_URL` in
`.env.local`. The browser never receives database credentials or model API keys;
tool execution remains inside the Pi process hosted by Next.js.

The API deliberately returns 404 outside development and rejects non-loopback
or cross-origin requests. The current implementation still uses the Phase 0
in-process Pi node adapter. It is suitable for a local complete-Qodex demo, but
it is not the production multi-user Gateway described in the design plan.

## What this phase proves

- the current Qodex Pi package can be loaded by `@assistant-ui/react-pi/node`;
- thread creation and history work through the official `PiClient` contract;
- streaming text, reasoning and tool calls render through assistant-ui primitives;
- in-flight follow-up/steer messages appear in the Pi queue;
- cancel is routed back to the active Pi run;
- an SSE disconnect releases only the browser subscription and does not cancel the run.

## Current compatibility result

Qodex `0.85.1`, `@assistant-ui/react-pi` `0.0.32`, assistant-ui `0.15.32`, React `19.3.1`, and Next.js `16.4.3` compile and run together. The Pi Node module is loaded at runtime so Next does not bundle Pi's provider-specific dynamic imports.

The local `talkweb` registry now uses `deepseek-flash` as its default model. On 2026-11-03, a browser-driven Phase 0 run verified streaming text, reasoning, a `read` tool call and result, session persistence, and recovery through the complete frontend-to-provider path.
