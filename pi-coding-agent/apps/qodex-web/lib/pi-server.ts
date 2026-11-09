import { resolve } from "node:path";
import type { PiClient } from "@assistant-ui/react-pi";

function environmentValue(name: string): string | undefined {
	const value = process.env[name]?.trim();
	return value ? value : undefined;
}

export const workspacePath = resolve(
	/* turbopackIgnore: true */ environmentValue("PI_WORKSPACE_PATH") ?? process.cwd(),
);
const agentDir = environmentValue("PI_CODING_AGENT_DIR");

type PiNodeModule = typeof import("@assistant-ui/react-pi/node");
const importNodeModule = Function("specifier", "return import(specifier)") as (
	specifier: string,
) => Promise<PiNodeModule>;

let clientPromise: Promise<PiClient> | undefined;

export function getPiClient(): Promise<PiClient> {
	clientPromise ??= importNodeModule("@assistant-ui/react-pi/node").then(({ createPiNodeClient }) =>
		createPiNodeClient({
			workspacePath,
			...(agentDir ? { agentDir } : {}),
		}),
	);
	return clientPromise;
}
