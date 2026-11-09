"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { createPiHttpClient, usePiRuntime } from "@assistant-ui/react-pi";
import { type ReactNode, useMemo } from "react";

export function QodexRuntimeProvider({ children }: Readonly<{ children: ReactNode }>) {
	const client = useMemo(() => createPiHttpClient({ baseUrl: "/api/pi" }), []);
	const runtime = usePiRuntime({ client });

	return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>;
}
