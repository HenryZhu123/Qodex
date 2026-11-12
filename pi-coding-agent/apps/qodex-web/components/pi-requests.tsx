"use client";
import { type PiHostUiRequest, usePiRuntimeExtras } from "@assistant-ui/react-pi";
import { useState } from "react";

export function PiRequests() {
	const { allHostUiRequests } = usePiRuntimeExtras();
	return (
		<div className="qx-pi-requests">
			{allHostUiRequests.map((request) => (
				<RequestCard key={request.id} request={request} />
			))}
		</div>
	);
}
function RequestCard({ request }: { request: PiHostUiRequest }) {
	const { respondToHostUiRequest } = usePiRuntimeExtras();
	const [value, setValue] = useState(request.kind === "editor" ? request.prefill || "" : "");
	const [busy, setBusy] = useState(false),
		[error, setError] = useState("");
	async function respond(response: Parameters<typeof respondToHostUiRequest>[0]) {
		setBusy(true);
		setError("");
		try {
			await respondToHostUiRequest(response);
		} catch (e) {
			setError(e instanceof Error ? e.message : "回复失败");
			setBusy(false);
		}
	}
	return (
		<div className="qx-pi-request">
			<h3>{request.title}</h3>
			{request.kind === "confirm" && <p>{request.message}</p>}
			{request.kind === "select" && (
				<select aria-label={request.title} value={value} onChange={(e) => setValue(e.target.value)}>
					<option value="">请选择</option>
					{request.options.map((option) => (
						<option key={option}>{option}</option>
					))}
				</select>
			)}
			{(request.kind === "input" || request.kind === "editor") && (
				<textarea
					aria-label={request.title}
					value={value}
					placeholder={request.kind === "input" ? request.placeholder : undefined}
					onChange={(e) => setValue(e.target.value)}
					rows={3}
				/>
			)}
			<div className="qx-actions">
				<button
					type="button"
					className="qx-btn"
					disabled={busy}
					onClick={() => respond({ requestId: request.id, dismissed: true })}
				>
					取消
				</button>
				<button
					type="button"
					className="qx-btn primary"
					disabled={busy || (request.kind !== "confirm" && !value)}
					onClick={() =>
						respond(
							request.kind === "confirm"
								? { requestId: request.id, confirmed: true }
								: { requestId: request.id, value },
						)
					}
				>
					确认
				</button>
			</div>
			{error && <p className="qx-error">{error}</p>}
		</div>
	);
}
