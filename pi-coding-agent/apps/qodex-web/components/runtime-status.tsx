"use client";

import { usePiRuntimeExtras, usePiThreadState } from "@assistant-ui/react-pi";

export function RuntimeStatus() {
	const { status } = usePiRuntimeExtras();
	const readiness = usePiThreadState((state) => state.readiness);
	const ready = readiness?.state === "ready";
	const label =
		status === "running"
			? "Working"
			: readiness && !ready
				? "Setup needed"
				: status === "failed"
					? "Error"
					: "Connected";

	return (
		<div className="flex h-7 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--panel-subtle)] px-2.5 text-[11px]">
			<span
				className={`size-1.5 rounded-full ${
					status === "running"
						? "qodex-pulse bg-amber-500"
						: readiness && !ready
							? "bg-amber-500"
							: status === "failed"
								? "bg-[var(--danger)]"
								: "bg-emerald-500"
				}`}
			/>
			<span className="text-[var(--muted-strong)]">{label}</span>
		</div>
	);
}
