import { join, resolve } from "node:path";
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
type PiSdkModule = typeof import("@earendil-works/pi-coding-agent");
const importPiSdkModule = Function("specifier", "return import(specifier)") as (
	specifier: string,
) => Promise<PiSdkModule>;

let clientPromise: Promise<PiClient> | undefined;

export function getPiClient(): Promise<PiClient> {
	clientPromise ??= Promise.all([
		importNodeModule("@assistant-ui/react-pi/node"),
		importPiSdkModule("@earendil-works/pi-coding-agent"),
	]).then(async ([{ createPiNodeClient }, { ModelRuntime }]) => {
		const provider = environmentValue("PI_PROVIDER");
		const modelId = environmentValue("PI_MODEL_ID");
		if (Boolean(provider) !== Boolean(modelId)) {
			throw new Error("PI_PROVIDER and PI_MODEL_ID must be configured together");
		}

		const modelRuntime = await ModelRuntime.create({
			allowModelNetwork: false,
			...(agentDir
				? {
						authPath: join(agentDir, "auth.json"),
						modelsPath: join(agentDir, "models.json"),
					}
				: {}),
		});
		const model = provider && modelId ? modelRuntime.getModel(provider, modelId) : undefined;
		if (provider && modelId && !model) {
			throw new Error(`Configured Pi model ${provider}/${modelId} was not found`);
		}

		return createPiNodeClient({
			workspacePath,
			...(agentDir ? { agentDir } : {}),
			...(model ? { model } : {}),
		});
	});
	return clientPromise;
}
